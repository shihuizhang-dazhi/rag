# SecKB - 企业网络安全助手

基于 RAG（检索增强生成）的企业网络安全知识库问答系统。上传安全文档后，通过自然语言提问检索知识库，结合大模型生成专业回答。

## 功能

- **智能问答**：SSE 流式对话，Markdown 渲染，多轮对话记忆（localStorage 持久化）
- **文档管理**：上传 / 搜索 / 分页 / 删除，支持 .md .txt .pdf .csv
- **智能切分**：MD 文档按标题层级切分（保留 h2/h3 元数据），非 MD 文档递归字符切
- **检索增强**：Chroma 向量检索 + DashScope Embedding，检索结果带相关度分数和来源标注
- **混合回答**：知识库有资料优先参考，资料不足时 LLM 基于自身知识补充

## 技术栈

| 层 | 技术 |
|---|------|
| 后端 | Python 3.12 + FastAPI + Uvicorn |
| 前端 | Vue 3（CDN，无构建步骤） |
| 大模型 | 阿里云百炼 DashScope（qwen3.7-plus） |
| 向量模型 | text-embedding-v3 |
| 向量库 | ChromaDB |
| 数据库 | SQLite + SQLAlchemy |
| 文档切分 | MarkdownHeaderTextSplitter + RecursiveCharacterTextSplitter |

## 快速开始

### 1. 安装依赖

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置

```bash
cp .env.example .env
# 编辑 .env，填入你的 DashScope API Key
```

### 3. 启动

```bash
uvicorn app.backend.main:app --host 127.0.0.1 --port 8000 --reload
```

访问 http://127.0.0.1:8000

## 项目结构

```
app/
├── backend/
│   ├── main.py                   # FastAPI 路由
│   ├── config.py                 # Pydantic 配置（.env 驱动）
│   ├── logger.py                 # loguru 日志（按天轮转）
│   ├── db/
│   │   ├── models.py             # Document 模型
│   │   └── session.py            # SQLite 引擎与会话
│   └── service/
│       ├── document_service.py   # 文档管理（上传/列表/删除）
│       ├── vectorization_service.py # 解析→切分→Embedding→Chroma
│       └── chat_service.py       # RAG 检索 + SSE 流式对话
└── web/
    ├── index.html                # Vue SPA
    ├── css/style.css             # 青色暗色主题
    └── js/
        ├── app.js                # 前端逻辑
        ├── marked.min.js         # Markdown 渲染
        └── vue.global.prod.js    # Vue 3 运行时
data/                             # 运行时目录（已 gitignore，启动自动创建）
├── docs.db                       # SQLite 文档元信息
├── chroma/                       # Chroma 向量库持久化
├── documents/                    # 上传文件的 UUID 重命名存储
logs/                             # loguru 日志（按天轮转）
```

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 前端页面 |
| POST | `/chat` | SSE 流式问答 `{message, thread_id}` |
| GET | `/documents` | 文档列表 `?page&page_size&keyword` |
| POST | `/documents/upload` | 上传文档（multipart `files`） |
| DELETE | `/documents/{id}` | 删除文档（含向量清理） |

## 切分策略

| 格式 | 策略 | 说明 |
|------|------|------|
| .md | MarkdownHeaderTextSplitter（## / ###） | 标题边界切，元数据保留 h2/h3；长 section 补 RecursiveCharacterTextSplitter |
| .txt / .pdf / .csv | RecursiveCharacterTextSplitter | 按段落→行→字符降级切，chunk_size=800, overlap=100 |

## 许可证

MIT
