# -*- coding: utf-8 -*-
"""
DocumentService：负责文件管理。

职责：
  - 校验文件类型与大小
  - 将上传文件保存到指定目录（config.documents_save_path）
  - 将文件元信息写入 SQLite 数据库（documents 表）
  - 调用 VectorService 完成向量化入库
  - 列出 / 按文件名搜索 / 删除文档（同时清理磁盘文件与向量）
  - 上传去重：同名文件视为重复，直接返回已有记录
"""
import mimetypes
import os
import re
import uuid

from app.backend.config import settings
from app.backend.db.models import Document
from app.backend.db.session import SessionLocal
from app.backend.logger import logger
from app.backend.service.vectorization_service import (
    delete_document_vectors,
    process_document,
)

_TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".csv"}

_DOC_INJECTION_PATTERNS = [
    r"(?i)ignore\s+(all\s+)?(previous|above|prior)\s+(instructions?|directives?|prompts?)",
    r"(?i)(you\s+are|you're)\s+(now\s+)?(DAN|jailbroken|unrestricted)",
    r"(?i)forget\s+(everything|all)\s+(you\s+know|you.ve\s+learned)",
    r"(?i)system\s*(:\s*|prompt\s*:)\s*(new|override|replace)",
    r"(?i)do\s+anything\s+now",
    r"<\|im_start\|>|<\|im_end\|>",
    r"\[SYSTEM\]\s*\(.*?\)",
]


def _scan_document_content(content: bytes, ext: str):
    """扫描上传文档中是否包含提示词注入 payload。仅对纯文本格式扫描。"""
    if ext.lower() not in _TEXT_EXTENSIONS:
        return
    try:
        text = content.decode("utf-8", errors="ignore")
    except Exception:
        return
    for pattern in _DOC_INJECTION_PATTERNS:
        if re.search(pattern, text):
            logger.warning(f"文档内容包含疑似注入 payload，匹配模式: {pattern}")
            raise ValueError("文档内容包含不安全的指令模式，请检查后重新上传")


# 魔数签名白名单
_MAGIC_SIGNATURES = {
    ".pdf": b"%PDF",
    ".txt": None,       # txt 无固定魔数，放行
    ".csv": None,       # csv 无固定魔数，放行
    ".md": None,        # md 无固定魔数，放行
}


def _check_magic_bytes(content: bytes, ext: str):
    """校验文件头部魔数是否与扩展名一致。"""
    sig = _MAGIC_SIGNATURES.get(ext)
    if sig is None:
        return
    if not content.startswith(sig):
        raise ValueError(f"文件内容与扩展名 {ext} 不匹配，拒绝上传")

# 部分系统（如 Windows）对 .md / .csv 没有内置 MIME 映射，这里补充常用类型
_EXT_MIME = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".pdf": "application/pdf",
}


class DocumentService:
    def __init__(self):
        os.makedirs(settings.documents_save_path, exist_ok=True)

    # ---------- 上传 ----------
    def upload(self, filename, content: bytes, content_type=None):
        """保存单个文件并入库。同名文件视为重复，直接返回已有记录。

        参数:
            filename:     原始文件名
            content:      文件二进制内容
            content_type: 浏览器提供的 MIME 类型（可选）
        返回: 文档信息字典；命中已有记录时额外带 deduplicated=True
        """
        ext = os.path.splitext(filename)[-1].lower()
        if ext not in settings.supported_extensions:
            raise ValueError(
                f"不支持的文件类型: {ext}（支持 {', '.join(settings.supported_extensions)}）"
            )

        # 魔数校验：防止伪造扩展名
        _check_magic_bytes(content, ext)

        # 扫描文档内容中的注入 payload
        _scan_document_content(content, ext)

        size = len(content)
        max_bytes = settings.max_file_size_mb * 1024 * 1024
        if size > max_bytes:
            raise ValueError(f"文件大小超过限制（最大 {settings.max_file_size_mb} MB）")

        # MIME 类型：优先用浏览器提供的，否则按扩展名推断（含自定义补充映射）
        mime_type = (
            content_type
            or mimetypes.guess_type(filename)[0]
            or _EXT_MIME.get(ext)
            or "application/octet-stream"
        )

        # SQLAlchemy 的 Session 支持上下文管理器。with 退出时会：
        # 1. 若发生未捕获异常 → 自动 rollback()
        # 2. 始终 close()
        # 不需要写繁琐的 try/except
        with SessionLocal() as session:
            # 同名文件已存在 → 视为重复上传，直接返回已有记录，不再落盘/入库/向量化
            existing = (
                session.query(Document)
                .filter(Document.original_filename == filename)
                .first()
            )
            if existing is not None:
                return {**existing.to_dict(), "deduplicated": True}

            # 以唯一名称落盘，避免重名覆盖；保留原始名记录在数据库
            stored_name = f"{uuid.uuid4().hex}{ext}"
            storage_path = os.path.join(settings.documents_save_path, stored_name)
            with open(storage_path, "wb") as f:
                f.write(content)

            doc = Document(
                original_filename=filename,
                file_size=size,
                mime_type=mime_type,
                storage_path=storage_path,
            )
            session.add(doc)
            session.commit()
            session.refresh(doc)

            # ---- 向量化入库（补上 docstring 承诺但原代码遗漏的步骤）----
            # 文件已落盘入库，向量化失败不阻断上传，仅标记 is_vectorized=False 并由日志告警
            try:
                ok = process_document(doc.id, storage_path, mime_type, original_filename=filename)
                doc.is_vectorized = ok
                session.commit()
                session.refresh(doc)
            except Exception as e:
                logger.error(f"向量化失败（文件已落盘入库）：id={doc.id}, error={e}")

            return {**doc.to_dict(), "deduplicated": False}

    # ---------- 列表 / 搜索 ----------
    def list_documents(self, keyword=None, page=1, page_size=10):
        """列出文档，支持按原始文件名模糊搜索 + 分页。

        返回 dict：{"documents": [...], "total": N, "page": P,
                  "page_size": S, "total_pages": M}
        """
        with SessionLocal() as session:
            query = session.query(Document)
            if keyword:
                safe_kw = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                query = query.filter(Document.original_filename.like(f"%{safe_kw}%", escape="\\"))

            total = query.count()

            docs = (
                query.order_by(Document.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            total_pages = (total + page_size - 1) // page_size if total else 0
            return {
                "documents": [d.to_dict() for d in docs],
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
            }

    # ---------- 删除 ----------
    def delete(self, doc_id):
        """删除文档：数据库记录 + 磁盘文件 + 向量。返回是否删除成功。"""
        with SessionLocal() as session:
            doc = session.query(Document).filter(Document.id == doc_id).first()
            if not doc:
                return False

            # 先清向量，避免元数据已删但向量残留
            try:
                delete_document_vectors(doc.id)
            except Exception as e:
                logger.error(f"删除向量失败：id={doc.id}, error={e}")

            # 删除磁盘文件
            if doc.storage_path and os.path.exists(doc.storage_path):
                try:
                    os.remove(doc.storage_path)
                except OSError:
                    pass
            # 删除数据库记录
            session.delete(doc)
            session.commit()
            return True


# 模块级单例，供路由层直接调用（类内部已自行管理 Session）
document_service = DocumentService()
