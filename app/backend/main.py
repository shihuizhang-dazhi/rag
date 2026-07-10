import sys
from pathlib import Path
from typing import List

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles

# Ensure the project root is on sys.path so `from app...` works when running this file directly
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.backend.config import settings
from app.backend.db.session import init_db
from app.backend.logger import logger
from app.backend.service import chat_service
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


@app.post("/chat")
async def chat(request: Request):
    body = await request.json()
    question = (body.get("message") or body.get("question") or "").strip()
    thread_id = body.get("thread_id") or ""
    logger.info(f"用户问题：{question}, thread_id={thread_id}")
    return chat_service._stream_chat(question, thread_id, request)


@app.get("/documents")
def get_documents(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(10, ge=1, le=100, description="每页条数"),
    keyword: str | None = Query(None, description="文件名关键词"),
):
    logger.info(f"查询文档列表：page={page}, page_size={page_size}, keyword={keyword}")
    return document_service.list_documents(keyword=keyword, page=page, page_size=page_size)


@app.post("/documents/upload")
async def upload_documents(
    files: List[UploadFile] = File(..., description="待上传的文档文件"),
):
    if not files:
        raise HTTPException(status_code=400, detail="未选择上传文件")
    logger.info(f"上传文档：{[f.filename for f in files]}")
    results = []
    for file in files:
        content = await file.read()
        try:
            info = document_service.upload(file.filename, content, file.content_type)
        except ValueError as e:
            msg = str(e)
            # 大小超限单独映射 413，其余（类型不支持）映射 400
            status = 413 if "大小" in msg else 400
            raise HTTPException(status_code=status, detail=msg)
        results.append(info)
    return {"documents": results}


@app.delete("/documents/{doc_id}")
def delete_document(doc_id: int):
    logger.info(f"删除文档：id={doc_id}")
    ok = document_service.delete(doc_id)
    if not ok:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"detail": "删除成功"}


@app.get("/")
def index():
    logger.info("访问首页")
    return FileResponse(WEB_DIR / "index.html")


# 托管前端静态资源，访问路径：/static/css/style.css
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.backend.main:app", host="127.0.0.1", port=8000, reload=True)
