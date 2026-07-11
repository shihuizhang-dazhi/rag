from pathlib import Path

from langchain_chroma import Chroma
from langchain_community.document_loaders import CSVLoader, PyPDFLoader, TextLoader
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from app.backend.config import settings
from app.backend.logger import logger

# ---- 文本切分器 ----
# 通用：按段落→句子→字符递归切，所有非 MD 文件走这个
CHAR_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=settings.chunk_size,
    chunk_overlap=settings.chunk_overlap,
)

# MD 专用：先按 ## / ### 标题边界切，保留标题层级到 metadata
MARKDOWN_HEADER_SPLITTER = MarkdownHeaderTextSplitter(
    headers_to_split_on=[
        ("##", "h2"),
        ("###", "h3"),
    ],
    strip_headers=False,
)


def _get_embeddings():
    return OpenAIEmbeddings(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        model=settings.embedding_model,
        check_embedding_ctx_length=False,
        chunk_size=10,
    )


def _get_vector_store():
    return Chroma(
        persist_directory=settings.chroma_path,
        embedding_function=_get_embeddings(),
        collection_name=settings.chroma_collection_name,
    )


def _load_document(file_path: str, mime_type: str | None = None):
    """根据扩展名选择合适的文档加载器。"""
    path = Path(file_path)
    ext = path.suffix.lower()

    if ext == ".pdf":
        return PyPDFLoader(file_path)
    if ext == ".csv":
        return CSVLoader(file_path)
    if ext in {".txt", ".md", ".markdown"}:
        return TextLoader(file_path, encoding="utf-8")

    logger.warning(f"未配置专用加载器，按文本处理：{file_path}")
    return TextLoader(file_path, encoding="utf-8")


# ---- Markdown 智能切分 ----
def _split_markdown(raw_docs: list) -> list:
    """Markdown 文档的混合切分策略：

    1. 先按 ## / ### 标题边界切 → 每个 section 自带标题层级 metadata（h2, h3）；
    2. 如果某个 section 超过 chunk_size，再补一刀字符切，但保留父 section 的标题元数据；
    3. 如果文档根本没标题（如纯文本存成 .md），回退到通用字符切。
    """
    final_chunks = []
    for doc in raw_docs:
        sections = MARKDOWN_HEADER_SPLITTER.split_text(doc.page_content)

        # 没有切出任何分段（文档无标题）→ 回退字符切
        if not sections:
            logger.info("MD 文档未检测到 ##/### 标题，回退到通用字符切")
            return CHAR_SPLITTER.split_documents(raw_docs)

        for section in sections:
            if len(section.page_content) <= settings.chunk_size:
                final_chunks.append(section)
            else:
                # 长 section 二次切分，但 header metadata 继承到每个子片段
                sub_chunks = CHAR_SPLITTER.split_documents([section])
                for sub in sub_chunks:
                    for key, value in section.metadata.items():
                        if key not in sub.metadata:
                            sub.metadata[key] = value
                final_chunks.extend(sub_chunks)

    return final_chunks


def process_document(
    doc_id: int, file_path: str, mime_type: str | None = None,
    original_filename: str | None = None,
) -> bool:
    """对单个文档进行解析、分块、Embedding 并向量入库。

    - .md/.markdown → 标题边界切（保留 h2/h3 元数据）+ 长段补字符切
    - .txt/.pdf/.csv  → 通用递归字符切
    """
    try:
        loader = _load_document(file_path, mime_type)
        raw_docs = loader.load()
        if not raw_docs:
            logger.warning(f"文档解析为空，跳过向量化：{file_path}")
            return True

        path = Path(file_path)
        ext = path.suffix.lower()

        if ext in {".md", ".markdown"}:
            chunks = _split_markdown(raw_docs)
        else:
            chunks = CHAR_SPLITTER.split_documents(raw_docs)

        if not chunks:
            logger.warning(f"文档分块为空，跳过向量化：{file_path}")
            return True

        for chunk in chunks:
            chunk.metadata["doc_id"] = doc_id
            if "source" not in chunk.metadata:
                chunk.metadata["source"] = original_filename or path.name

        vector_store = _get_vector_store()
        vector_store.add_documents(chunks)
        logger.info(
            f"文档向量化完成：id={doc_id}, chunks={len(chunks)}, "
            f"strategy={'markdown-header' if ext in {'.md', '.markdown'} else 'char-recursive'}"
        )
        return True
    except Exception as e:
        logger.error(f"文档向量化失败：id={doc_id}, path={file_path}, error={e}")
        return False


def delete_document_vectors(doc_id: int) -> bool:
    """从向量库中删除指定文档的所有分块。"""
    try:
        vector_store = _get_vector_store()
        vector_store.delete(where={"doc_id": doc_id})
        logger.info(f"已删除文档向量：id={doc_id}")
        return True
    except Exception as e:
        logger.error(f"删除文档向量失败：id={doc_id}, error={e}")
        return False
