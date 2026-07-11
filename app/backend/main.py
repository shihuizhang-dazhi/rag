import hashlib
import json
import os
import secrets
import sys
import time
from pathlib import Path
from typing import List

from fastapi import Body, Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func
from sqlalchemy.orm import Session
from starlette.responses import FileResponse, JSONResponse
from starlette.staticfiles import StaticFiles

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.backend.config import settings
from app.backend.db.models import AuditLog as AuditLogModel, User, Conversation, ConversationMeta
from app.backend.db.session import SessionLocal, init_db
from app.backend.deps import get_current_user, get_db, get_optional_user, require_role
from app.backend.logger import logger
from app.backend.service import chat_service
from app.backend.service.auth_service import create_access_token, hash_password, verify_password
from app.backend.service.document_service import document_service

app = FastAPI(
    title="企业网络安全助手",
    version="2.0.0",
    docs_url="/docs" if settings.enable_docs else None,
    redoc_url="/redoc" if settings.enable_docs else None,
    openapi_url="/openapi.json" if settings.enable_docs else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

# 登录速率限制：ip/username -> [fail_timestamps]
_login_failures: dict[str, list[float]] = {}
LOGIN_MAX_FAILURES = 5
LOGIN_BLOCK_SECONDS = 300

# 登录签名盐：salt -> timestamp（120 秒过期，一次性使用）
_login_salts: dict[str, float] = {}
LOGIN_SALT_TTL = 120
POW_DIFFICULTY = 5


def _check_login_rate(key: str) -> int:
    """检查登录失败次数，返回剩余尝试次数。超过限制返回 -1。"""
    now = time.time()
    failures = [t for t in _login_failures.get(key, []) if now - t < LOGIN_BLOCK_SECONDS]
    _login_failures[key] = failures
    if len(failures) >= LOGIN_MAX_FAILURES:
        return -1
    return LOGIN_MAX_FAILURES - len(failures)

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"


@app.on_event("startup")
def on_startup():
    Path(settings.documents_save_path).mkdir(parents=True, exist_ok=True)
    Path(settings.chroma_path).mkdir(parents=True, exist_ok=True)
    Path(settings.database_file_path).parent.mkdir(parents=True, exist_ok=True)
    init_db()
    logger.info("数据目录与数据库表结构初始化完成")


def _client_ip(request: Request | None) -> str:
    if request is None:
        return "-"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "-"


def _audit(db: Session, user_id: int | None, username: str | None, action: str, detail: str = "", ip: str = ""):
    try:
        full_detail = f"{username} {detail}" if detail else f"{username or '匿名'} 执行了 {action}"
        db.add(AuditLogModel(user_id=user_id, username=username, action=action, detail=full_detail, ip=ip))
        db.commit()
    except Exception:
        db.rollback()


# ============ 认证 ============
@app.get("/auth/login-salt")
def get_login_salt():
    """返回一次性签名盐、PoW 挑战和时间戳。"""
    salt = secrets.token_hex(32)
    challenge = secrets.token_hex(16)
    _login_salts[salt] = time.time()
    _login_salts[salt + ":challenge"] = challenge
    return {
        "salt": salt,
        "challenge": challenge,
        "difficulty": POW_DIFFICULTY,
        "timestamp": int(time.time()),
        "ttl": LOGIN_SALT_TTL,
    }


@app.post("/auth/login")
def login(request: Request, payload: dict = Body(...), db: Session = Depends(get_db)):
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    ip = _client_ip(request)
    client_salt = payload.get("salt") or ""
    client_sign = payload.get("sign") or ""

    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")

    # 签名校验：防重放和自动化攻击
    salt_ts = _login_salts.pop(client_salt, None)
    if not salt_ts or time.time() - salt_ts > LOGIN_SALT_TTL:
        raise HTTPException(status_code=400, detail="登录令牌已过期，请刷新页面重试")
    challenge = _login_salts.pop(client_salt + ":challenge", "")
    expected = hashlib.sha256(f"{username}:{password}:{client_salt}".encode()).hexdigest()
    if not client_sign or not secrets.compare_digest(expected, client_sign):
        raise HTTPException(status_code=400, detail="请求签名无效，请刷新页面重试")

    # PoW 工作量证明校验
    pow_nonce = payload.get("pow_nonce", "")
    if not pow_nonce:
        raise HTTPException(status_code=400, detail="缺少工作量证明")
    pow_hash = hashlib.sha256(f"{challenge}:{pow_nonce}".encode()).hexdigest()
    if not pow_hash.startswith("0" * POW_DIFFICULTY):
        raise HTTPException(status_code=400, detail="工作量证明校验失败，请刷新页面重试")

    # 速率限制检查
    for key in (ip, username):
        remaining = _check_login_rate(key)
        if remaining <= 0:
            raise HTTPException(status_code=429, detail="登录尝试过于频繁，请 5 分钟后再试")

    user = db.query(User).filter(User.username == username).first()
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        for key in (ip, username):
            _login_failures.setdefault(key, []).append(time.time())
        logger.warning(f"登录失败：username={username}, ip={ip}")
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    user.token_version += 1
    db.commit()
    token = create_access_token(
        user.id,
        extra={
            "role": user.role,
            "username": user.username,
            "ver": user.token_version,
        },
    )
    for key in (ip, username):
        _login_failures.pop(key, None)
    _audit(db, user.id, user.username, "login", f"{user.username} 登录成功", ip)
    logger.info(f"登录成功：username={username}, role={user.role}, ip={ip}")
    resp: JSONResponse = JSONResponse({"user": user.to_dict()})
    resp.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        max_age=settings.token_expire_minutes * 60,
        path="/",
    )
    return resp


@app.get("/auth/me")
def me(current: User = Depends(get_current_user)):
    return current.to_dict()


@app.post("/auth/logout")
def logout():
    resp = JSONResponse({"detail": "已退出登录"})
    resp.delete_cookie(key="access_token", path="/")
    return resp


# ============ 对话（匿名 + 登录均可） ============
@app.post("/chat")
async def chat(request: Request, current: User | None = Depends(get_optional_user)):
    body = await request.json()
    question = (body.get("message") or body.get("question") or "").strip()
    thread_id = body.get("thread_id") or ""
    user_name = current.username if current else "匿名"
    user_id = current.id if current else 0
    logger.info(f"用户问题：{question}, thread_id={thread_id}, user={user_name}")
    return chat_service._stream_chat(question, thread_id, request, user_id=user_id)


@app.get("/conversations")
def list_conversations(
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    threads = (
        db.query(
            Conversation.thread_id,
            func.min(Conversation.created_at).label("created_at"),
            func.count(Conversation.id).label("msg_count"),
            ConversationMeta.title,
        )
        .outerjoin(
            ConversationMeta,
            (ConversationMeta.user_id == Conversation.user_id)
            & (ConversationMeta.thread_id == Conversation.thread_id),
        )
        .filter(Conversation.user_id == current.id)
        .group_by(Conversation.thread_id)
        .order_by(func.min(Conversation.created_at).desc())
        .all()
    )

    threads_without_title = [t for t in threads if not t.title]
    first_msg_map = {}
    if threads_without_title:
        tids = [t.thread_id for t in threads_without_title]
        subq = (
            db.query(
                Conversation.thread_id,
                func.min(Conversation.id).label("min_id"),
            )
            .filter(
                Conversation.user_id == current.id,
                Conversation.role == "user",
                Conversation.thread_id.in_(tids),
            )
            .group_by(Conversation.thread_id)
            .subquery()
        )
        rows = (
            db.query(Conversation.thread_id, Conversation.content)
            .join(subq, Conversation.id == subq.c.min_id)
            .all()
        )
        first_msg_map = {row.thread_id: row.content for row in rows}

    result = []
    for t in threads:
        title = t.title or (first_msg_map.get(t.thread_id, "新会话")[:50])
        result.append({
            "thread_id": t.thread_id,
            "title": title,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "msg_count": t.msg_count,
        })
    return {"conversations": result}


@app.get("/conversations/{thread_id}/messages")
def get_conversation_messages(
    thread_id: str,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Conversation)
        .filter(
            Conversation.user_id == current.id,
            Conversation.thread_id == thread_id,
        )
        .order_by(Conversation.id.asc())
        .all()
    )
    messages = []
    for r in rows:
        msg = {"role": r.role, "content": r.content}
        if r.sources:
            try:
                msg["sources"] = json.loads(r.sources)
            except (json.JSONDecodeError, TypeError):
                pass
        messages.append(msg)
    return {"messages": messages}


@app.put("/conversations/{thread_id}")
def rename_conversation(
    thread_id: str,
    payload: dict = Body(...),
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    title = (payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")
    if len(title) > 200:
        raise HTTPException(status_code=400, detail="标题不能超过 200 个字符")
    meta = (
        db.query(ConversationMeta)
        .filter(
            ConversationMeta.user_id == current.id,
            ConversationMeta.thread_id == thread_id,
        )
        .first()
    )
    if meta:
        meta.title = title
    else:
        db.add(ConversationMeta(user_id=current.id, thread_id=thread_id, title=title))
    db.commit()
    return {"detail": "重命名成功", "title": title}


@app.delete("/conversations/{thread_id}")
def clear_conversation(
    thread_id: str,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.query(Conversation).filter(
        Conversation.user_id == current.id,
        Conversation.thread_id == thread_id,
    ).delete()
    db.query(ConversationMeta).filter(
        ConversationMeta.user_id == current.id,
        ConversationMeta.thread_id == thread_id,
    ).delete()
    db.commit()
    logger.info(f"用户 {current.username} 清空会话：{thread_id}")
    return {"detail": "会话已清空"}


# ============ 文档列表（需登录） ============
@app.get("/documents")
def get_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    keyword: str | None = Query(None),
    current: User = Depends(get_current_user),
):
    user_name = current.username if current else "匿名"
    logger.info(f"查询文档列表：page={page}, page_size={page_size}, keyword={keyword}, user={user_name}")
    return document_service.list_documents(keyword=keyword, page=page, page_size=page_size)


@app.post("/documents/upload")
async def upload_documents(
    request: Request,
    files: List[UploadFile] = File(...),
    current: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    if not files:
        raise HTTPException(status_code=400, detail="未选择上传文件")
    logger.info(f"上传文档：{[f.filename for f in files]}, user={current.username}")
    results = []
    for file in files:
        content = await file.read()
        try:
            info = document_service.upload(file.filename, content, file.content_type)
        except ValueError as e:
            msg = str(e)
            status_code = 413 if "大小" in msg else 400
            raise HTTPException(status_code=status_code, detail=msg)
        results.append(info)
    filenames = ", ".join(r.get("original_filename", "") for r in results)
    _audit(db, current.id, current.username, "upload", f"上传文档：{filenames}", _client_ip(request))
    return {"documents": results}


@app.delete("/documents/{doc_id}")
def delete_document(
    request: Request,
    doc_id: int,
    current: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    logger.info(f"删除文档：id={doc_id}, user={current.username}")
    ok = document_service.delete(doc_id)
    if not ok:
        raise HTTPException(status_code=404, detail="文档不存在")
    _audit(db, current.id, current.username, "delete", f"删除文档 ID={doc_id}", _client_ip(request))
    return {"detail": "删除成功"}


@app.get("/documents/{doc_id}/preview")
def preview_document(
    doc_id: int,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.backend.db.models import Document as DocModel

    doc = db.query(DocModel).filter(DocModel.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    if not doc.storage_path or not os.path.exists(doc.storage_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    ext = os.path.splitext(doc.original_filename)[-1].lower()
    if ext == ".pdf":
        return FileResponse(
            doc.storage_path,
            media_type="application/pdf",
            headers={"Content-Disposition": f"inline; filename={doc.original_filename}"},
        )
    content = Path(doc.storage_path).read_text(encoding="utf-8", errors="replace")
    return JSONResponse({
        "id": doc.id,
        "filename": doc.original_filename,
        "content": content,
        "mime_type": doc.mime_type,
    })


@app.get("/documents/{doc_id}/download")
def download_document(
    doc_id: int,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.backend.db.models import Document as DocModel

    doc = db.query(DocModel).filter(DocModel.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    if not doc.storage_path or not os.path.exists(doc.storage_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    return FileResponse(
        doc.storage_path,
        media_type=doc.mime_type or "application/octet-stream",
        filename=doc.original_filename,
    )


# ============ 用户管理（管理员） ============
@app.get("/users")
def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    current: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    total = db.query(User).count()
    users = (
        db.query(User)
        .order_by(User.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "users": [u.to_dict() for u in users],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
    }


@app.post("/users")
def create_user(
    request: Request,
    payload: dict = Body(...),
    current: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    role = payload.get("role", "user")
    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")
    if role not in ("admin", "user", "auditor"):
        raise HTTPException(status_code=400, detail="角色无效，可选：admin/user/auditor")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=409, detail="用户名已存在")

    user = User(
        username=username,
        password_hash=hash_password(password),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    _audit(db, current.id, current.username, "user_create", f"创建用户 {username}（{role}）", _client_ip(request))
    db.refresh(user)
    logger.info(f"管理员 {current.username} 创建用户：{username}（{role}）")
    return user.to_dict()


@app.put("/users/{user_id}")
def update_user(
    request: Request,
    user_id: int,
    payload: dict = Body(...),
    current: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    if "password" in payload and payload["password"]:
        target.password_hash = hash_password(payload["password"])
    if "role" in payload:
        role = payload["role"]
        if role not in ("admin", "user", "auditor"):
            raise HTTPException(status_code=400, detail="角色无效")
        target.role = role
    if "is_active" in payload:
        target.is_active = bool(payload["is_active"])
    db.commit()
    _audit(db, current.id, current.username, "user_update", f"修改用户 {target.username}", _client_ip(request))
    logger.info(f"管理员 {current.username} 修改用户：{target.username}")
    return target.to_dict()


@app.delete("/users/{user_id}")
def delete_user(
    request: Request,
    user_id: int,
    current: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    if user_id == current.id:
        raise HTTPException(status_code=400, detail="不能删除自己的账号")
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    username = target.username
    db.delete(target)
    db.commit()
    _audit(db, current.id, current.username, "user_delete", f"删除用户 {username}", _client_ip(request))
    logger.info(f"管理员 {current.username} 删除用户：{username}")
    return {"detail": f"用户 {username} 已删除"}


# ============ 审计日志（审计员/管理员） ============
@app.get("/audit")
def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current: User = Depends(require_role("admin", "auditor")),
    db: Session = Depends(get_db),
):
    total = db.query(AuditLogModel).count()
    logs = (
        db.query(AuditLogModel)
        .order_by(AuditLogModel.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "logs": [lg.to_dict() for lg in logs],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
    }


@app.delete("/audit")
def delete_audit_logs(
    request: Request,
    ids: list[int] = Body(..., embed=True),
    current: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    if not ids:
        raise HTTPException(status_code=400, detail="请选择要删除的日志")
    deleted = (
        db.query(AuditLogModel)
        .filter(AuditLogModel.id.in_(ids))
        .delete(synchronize_session=False)
    )
    db.commit()
    _audit(db, current.id, current.username, "audit_delete", f"删除 {deleted} 条审计日志", _client_ip(request))
    logger.info(f"管理员 {current.username} 删除 {deleted} 条审计日志")
    return {"detail": f"已删除 {deleted} 条日志", "deleted": deleted}


@app.delete("/audit/all")
def clear_all_audit_logs(
    request: Request,
    current: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    total = db.query(AuditLogModel).count()
    db.query(AuditLogModel).delete()
    db.commit()
    _audit(db, current.id, current.username, "audit_clear_all", f"清空全部 {total} 条审计日志", _client_ip(request))
    logger.info(f"管理员 {current.username} 清空全部审计日志（{total} 条）")
    return {"detail": f"已清空全部 {total} 条日志", "deleted": total}


# ============ 知识图谱 ============
@app.get("/graph/stats")
def graph_stats(current: User = Depends(get_current_user)):
    from app.backend.service.knowledge_graph_service import kg_service
    return kg_service.get_stats()


@app.get("/graph/entities")
def list_graph_entities(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    label: str | None = Query(None),
    keyword: str | None = Query(None),
    current: User = Depends(get_current_user),
):
    from app.backend.service.knowledge_graph_service import kg_service
    return kg_service.query_entities(page=page, page_size=page_size, label=label, keyword=keyword)


@app.get("/graph/entities/{entity_id}")
def get_graph_entity(entity_id: int, current: User = Depends(get_current_user)):
    from app.backend.service.knowledge_graph_service import kg_service
    result = kg_service.get_entity(entity_id)
    if not result:
        raise HTTPException(status_code=404, detail="实体不存在")
    return result


@app.get("/graph/search")
def search_graph(
    q: str = Query(..., min_length=1),
    depth: int = Query(1, ge=1, le=3),
    current: User = Depends(get_current_user),
):
    from app.backend.service.knowledge_graph_service import kg_service
    return kg_service.search_graph(q, depth=depth)


@app.post("/graph/rebuild")
def rebuild_graph(
    doc_id: int = Body(..., embed=True),
    current: User = Depends(require_role("admin")),
):
    from app.backend.service.knowledge_graph_service import kg_service
    ok = kg_service.rebuild(doc_id)
    if not ok:
        raise HTTPException(status_code=404, detail="文档不存在或文件已丢失")
    return {"detail": "图谱重建成功"}


# ============ 前端入口 & 静态资源 ============
@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.backend.main:app", host="127.0.0.1", port=8000, reload=True)
