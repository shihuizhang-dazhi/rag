# SecKB - 企业网络安全助手

基于 RAG（检索增强生成）的企业网络安全知识库问答系统。上传安全文档后，通过自然语言提问检索知识库，结合大模型生成专业回答。

## 功能

- **智能问答**：SSE 流式对话，Markdown 渲染，多轮对话记忆
- **权限系统**：admin（全部权限）、auditor（聊天+审计）、user/guest（仅聊天）
- **多会话管理**：创建/切换/删除/重命名，每用户上限 5 个，匿名会话 30 分钟自动清理
- **文档管理**：上传 / 搜索 / 分页 / 删除，支持 .md .txt .pdf .csv
- **向量化**：MD 按标题层级切分（保留 h2/h3 元数据），非 MD 递归字符切
- **审计日志**：记录用户操作，支持多选批量删除和清空
- **安全防护**：PoW 登录验证 + 签名盐值防重放 + 速率限制 + XSS 过滤 + 文件魔数校验

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
│   ├── main.py                   # FastAPI 路由（含认证、审计、用户管理）
│   ├── config.py                 # Pydantic 配置（.env 驱动）
│   ├── logger.py                 # loguru 日志（按天轮转）
│   ├── deps.py                   # 依赖注入（JWT 认证、角色校验）
│   ├── db/
│   │   ├── models.py             # Document / User / ConversationMeta / AuditLog
│   │   └── session.py            # SQLite 引擎与会话
│   └── service/
│       ├── document_service.py   # 文档管理（上传/列表/删除+魔数校验）
│       ├── vectorization_service.py # 解析→切分→Embedding→Chroma
│       └── chat_service.py       # RAG 检索 + SSE 流式对话 + 会话管理
└── web/
    ├── index.html                # Vue SPA
    ├── css/style.css             # 青色暗色主题
    └── js/
        ├── app.js                # 前端逻辑（含 PoW、签名验证）
        ├── marked.min.js         # Markdown 渲染
        ├── purify.min.js         # XSS 过滤
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
| POST | `/auth/login` | 用户登录（PoW + 签名验证） |
| GET | `/auth/login-salt` | 获取一次性登录盐值 |
| GET/PUT | `/conversations` | 会话列表 / 重命名会话 |
| DELETE | `/conversations/{tid}` | 删除会话 |
| GET | `/documents` | 文档列表 `?page&page_size&keyword` |
| POST | `/documents/upload` | 上传文档（multipart `files`） |
| DELETE | `/documents/{id}` | 删除文档（含向量清理） |
| GET | `/audit` | 审计日志列表 `?page&page_size` |
| DELETE | `/audit` | 批量删除审计记录 |
| DELETE | `/audit/all` | 清空所有审计记录 |
| GET | `/users` | 用户列表（admin） |
| PUT/DELETE | `/users/{id}` | 编辑/删除用户（admin） |

### 默认账户

| 角色 | 用户名 | 密码 |
|------|--------|------|
| admin | admin | 88888888 |
| auditor | auditor | auditor123 |
| user | guest | guest123 |

## 安全特性

- **登录安全**：PoW（工作量证明）→ 签名盐值（防重放）→ 速率限制（5 次/5 分钟）三层防护
- **XSS 防护**：DOMPurify + marked 标签白名单
- **文件安全**：PDF 魔数校验，UUID 重命名存储
- **敏感信息**：API Key / JWT Secret 存于 `.env`，启动时校验默认值
- **HTTP 安全头**：CORS、X-Content-Type-Options、X-Frame-Options、X-XSS-Protection

## 文档处理流程

### 切分策略

RAG 系统最核心的环节是文档切分。切得太碎丢失上下文，切得太粗检索精度下降。本项目采用**格式感知的分层切分策略**：

```
上传文档 → 魔数校验（PDF 防伪造）→ 解析加载 → route → 向量入库
                                                    │
                            ┌───────────────────────┤
                            ▼                       ▼
                       Markdown 文档           非 Markdown 文档
                   （.md / .markdown）     （.txt / .pdf / .csv）
                            │                       │
                            ▼                       ▼
              MarkdownHeaderTextSplitter   RecursiveCharacterTextSplitter
                 按 ## / ### 切分            chunk_size=800
                            │               chunk_overlap=100
                            ▼               separators=["\n\n","\n","。","，"," "]
              每个 section ≤ 800 字符?
                    │           │
                   是          否
                    │           │
                    ▼           ▼
              直接作为 chunk  递归字符切后继承父级标题元数据
```

### 关键参数

| 参数 | 值 | 说明 |
|------|-----|------|
| `chunk_size` | 800 | 每个分块最大字符数，平衡上下文完整性和检索精度 |
| `chunk_overlap` | 100 | 相邻分块重叠字符数，防止关键信息落在边界被切断 |
| `top_k` | 5 | 每次检索返回最相似的 5 个分块 |
| `score_threshold` | 0.3 | 相似度阈值，低于此值的分块丢弃（cosine 距离转换） |

### 为什么这样切？

**Markdown 文档**用 `MarkdownHeaderTextSplitter` 按 `##`/`###` 标题边界切分。好处：
- 每个 chunk 自带 `h2`/`h3` 元数据，回答时可以溯源到具体章节
- 标题层级天然形成文档结构，切分边界符合人类阅读逻辑
- 如果某个 section 超过 800 字符，用 `RecursiveCharacterTextSplitter` 补切但保留父级标题元数据，避免"孤儿段落"
- 如果文档根本没有标题（纯文本存成 `.md`），自动回退到字符切

**非 Markdown 文档**（PDF、TXT、CSV）用 `RecursiveCharacterTextSplitter`：
- 分离器优先级：`\n\n`（段落）→ `\n`（行）→ `。`（句号）→ `，`（逗号）→ ` `（空格），逐级降级直到切分成功
- 800 字符约等于 2-3 个段落，刚好覆盖一个完整的安全知识点
- 100 字符重叠确保"SQL 注入的防护措施是..."这类跨越边界的句子不会丢失

### 检索流程

```
用户问题 → DashScope Embedding（text-embedding-v3）
         → Chroma 向量检索（cosine 距离，top_k=5）
         → 相似度过滤（score ≥ 0.3）
         → 拼接上下文 → 注入 system prompt → 流式生成回答
```

`Document` 模型仅存储原始文件元和状态（`original_filename`, `file_size`, `mime_type`, `storage_path`, `is_vectorized`），不保存分块文本。分块后的文本内容全部存储在 Chroma 向量库中，检索时通过 `doc_id` 元数据关联回源文档，删除文档时同步清理向量。

## 许可证

MIT
