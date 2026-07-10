# CLAUDE.md

本文件为 Claude Code 在本仓库中工作时提供指引。

## 项目简介

**SecKB - 企业网络安全助手**，一款基于 RAG 的企业网络安全知识库问答系统。FastAPI 后端服务于 Vue 3 前端，从上传的安全文档中检索答案（LangChain + Chroma + DashScope Qwen）。

- Python 3.12，虚拟环境位于 `.venv/`。
- 所有界面文案、日志、git 提交信息均为中文 - 编辑时请保持一致。

## 常用命令

**在项目根目录下**启动开发服务器：
```bash
.venv/bin/uvicorn app.backend.main:app --reload --port 8000
```
然后访问 http://127.0.0.1:8000/（界面）或 http://127.0.0.1:8000/docs（OpenAPI 文档）。

> 注意：也可以用 `python app/backend/main.py`（`__name__ == "__main__"` 块），但上面的 uvicorn CLI 是推荐方式。

## 架构说明

**后端 - `app/backend/`**

- `main.py`：FastAPI 应用，包含全部路由（`POST /chat`、`GET/POST /documents`、`DELETE /documents/{id}`）。
- `config.py`：Pydantic Settings，从 `.env` 加载全部配置（API Key、模型名、切分参数、路径等）。`system_prompt` 也在此定义。
- `logger.py`：loguru 封装，写入 `logs/app_YYYYMMDD.log`，按天轮转。通过 `.patch(fix_log_position)` 遍历调用栈，显示真正的业务调用方。
- `db/models.py`：`Document` ORM 模型（original_filename, file_size, mime_type, storage_path, is_vectorized, created_at）。
- `db/session.py`：SQLite 引擎、`SessionLocal` 工厂、`init_db()`。
- `service/document_service.py`：文档管理（upload 去重/落盘/入库/向量化，list 分页+搜索，delete 清磁盘+DB+向量）。类式设计，使用 `SessionLocal()` 上下文管理器。
- `service/vectorization_service.py`：MD 文档用 `MarkdownHeaderTextSplitter`（##/### 边界切，h2/h3 元数据保留）；非 MD 用 `RecursiveCharacterTextSplitter`。Embedding 用 DashScopeEmbeddings，Chroma 持久化。
- `service/chat_service.py`：Chroma 检索 → 构建 messages（含对话历史）→ DashScope 流式 SSE 输出。多轮记忆用内存字典（thread_id → messages），保留最近 10 轮。

**前端 - `app/web/`**

- Vue 3 CDN（`vue.global.prod.js`），无构建步骤，无 npm。直接编辑 `index.html` + `js/app.js` + `css/style.css`。
- 对话记忆通过 `localStorage` 持久化（thread_id + messages），清空会话时清理。
- Markdown 渲染用 `marked.js`（`marked.min.js` 本地文件）。
- 默认深色主题（cyan 色调），`html.dark` 类名切换。

**大模型对接**：阿里云百炼 DashScope 通过 OpenAI 兼容端点访问。对话模型 `qwen3.7-plus`，Embedding 模型 `text-embedding-v3`。

## API 契约

- `POST /chat`，请求体 JSON `{message, thread_id}` → SSE 流 `data:` 帧（`content`、`sources`、`error`），`data: [DONE]` 结束。
- `GET /documents?page=&page_size=&keyword=` → `{documents:[{id,original_filename,file_size,created_at,is_vectorized}], total, page, page_size, total_pages}`
- `POST /documents/upload`（multipart `files`）→ `{documents:[{...,deduplicated}]}`
- `DELETE /documents/{id}` → `{detail:"删除成功"}` 或 404
- 支持格式：`.txt .pdf .csv .md`（前端校验，后端二次校验）

## 安全

- API Key 存于 `.env`（已 gitignore），不硬编码。
- 文件上传用 UUID 重命名存储，防止路径遍历。
- 暂无鉴权和速率限制（本地课程项目不考虑生产部署）。
