import sys
from pathlib import Path
from typing import List

from fastapi import Body, Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from sqlalchemy.orm import Session
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles

# Ensure the project root is on sys.path so `from app...` works when running this file directly
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.backend.config import settings
from app.backend.db.models import User
from app.backend.db.session import init_db
from app.backend.deps import get_current_user, get_db, require_role
from app.backend.logger import logger
from app.backend.service import chat_service
from app.backend.service.auth_service import create_access_token, verify_password
from app.backend.service.document_service import document_service

app = FastAPI(title="企业网络安全助手", version="1.0.0")

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"


@app.on_event("startup")
def on_startup():
    """应用启动时创建数据目录并初始化数据库表结构。"""
    Path(settings.documents_save_path).mkdir(parents=True, exist_ok=True)
    Path(settings.chroma_path).mkdir(parents=True, exist_ok=True)
    Path(settings.database_file_path).parent.mkdir(parents=True, exist_ok=True)
    init_db()
    logger.info("数据目录与数据库表结构初始化完成")


# ============ 认证 ============
@app.post("/auth/login")
def login(request: Request, payload: dict = Body(...), db: Session = Depends(get_db)):
    """账号密码登录，校验通过后签发 JWT。"""
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")

    user = db.query(User).filter(User.username == username).first()
    # 统一返回"用户名或密码错误"，避免泄露用户是否存在
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        logger.warning(f"登录失败：username={username}, ip={_client_ip(request)}")
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = create_access_token(user.id, extra={"role": user.role, "username": user.username})
    logger.info(f"登录成功：username={username}, role={user.role}, ip={_client_ip(request)}")
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user.to_dict(),
    }


@app.get("/auth/me")
def me(current: User = Depends(get_current_user)):
    """返回当前登录用户信息，前端用于刷新页面后恢复会话。"""
    return current.to_dict()


# ============ 业务路由（需登录） ============
@app.post("/chat")
async def chat(request: Request, current: User = Depends(get_current_user)):
    body = await request.json()
    question = (body.get("message") or body.get("question") or "").strip()
    thread_id = body.get("thread_id") or ""
    logger.info(f"用户问题：{question}, thread_id={thread_id}, user={current.username}({current.role})")
    return chat_service._stream_chat(question, thread_id, request)


@app.get("/documents")
def get_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    keyword: str | None = Query(None),
    current: User = Depends(get_current_user),
):
    # 普通用户也能看文档列表（用于了解知识库内容），但只有 admin 能增删
    logger.info(f"查询文档列表：page={page}, page_size={page_size}, keyword={keyword}, user={current.username}")
    return document_service.list_documents(keyword=keyword, page=page, page_size=page_size)


@app.post("/documents/upload")
async def upload_documents(
    files: List[UploadFile] = File(...),
    current: User = Depends(require_role("admin")),
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
    return {"documents": results}


@app.delete("/documents/{doc_id}")
def delete_document(
    doc_id: int,
    current: User = Depends(require_role("admin")),
):
    logger.info(f"删除文档：id={doc_id}, user={current.username}")
    ok = document_service.delete(doc_id)
    if not ok:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"detail": "删除成功"}


# ============ 前端入口 & 静态资源（公开） ============
@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


def _client_ip(request: Request | None) -> str:
    if request is None:
        return "-"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "-"


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.backend.main:app", host="127.0.0.1", port=8000, reload=True)
