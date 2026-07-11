# SecKB - 企业网络安全助手

基于 RAG（检索增强生成）的企业网络安全知识库问答系统。上传安全文档后，通过自然语言提问检索知识库，结合大模型生成专业回答。支持知识图谱实体关系自动提取与可视化。

## 功能

- **智能问答**：SSE 流式对话（8 字缓冲合并，防卡顿），Markdown 渲染，多轮对话记忆
- **知识图谱**：LLM 自动提取安全实体（漏洞、攻击手法、防御措施等）和关系，vis-network 力导向图可视化，支持搜索和双击展开邻接节点
- **对话记忆优化**：保留最近 5 轮原文，更早对话通过 LLM 压缩为摘要，节省 token
- **来源引用持久化**：每次回答的检索来源（向量 + 图谱）随对话历史保存，切换会话后仍可回溯
- **文档预览/下载**：文档列表支持在线预览（文本弹窗 / PDF 新标签页）、一键下载
- **权限系统**：admin（全部权限）、auditor（聊天+审计）、user/guest（仅聊天）
- **多会话管理**：创建/切换/删除/重命名，每用户上限 5 个，匿名会话 30 分钟自动清理
- **文档管理**：上传 / 搜索 / 分页 / 删除，支持 .md .txt .pdf .csv，上传后自动向量化 + 图谱提取
- **向量化**：MD 按标题层级切分（保留 h2/h3 元数据），非 MD 递归字符切
- **审计日志**：记录用户操作，支持多选批量删除和清空
- **安全防护**：PoW 登录验证 + 签名盐值防重放 + 速率限制 + XSS 过滤 + 文件魔数校验

## 技术栈

| 层 | 技术 |
|---|------|
| 后端 | Python 3.12 + FastAPI + Uvicorn |
| 前端 | Vue 3（CDN，无构建步骤） |
| 大模型 | 阿里云百炼 MaaS（qwen3.7-plus） |
| 向量模型 | text-embedding-v3（通过 MaaS OpenAI 兼容接口） |
| 向量库 | ChromaDB |
| 嵌入 SDK | langchain-openai（check_embedding_ctx_length=False，chunk_size=10） |
| 数据库 | SQLite + SQLAlchemy |
| 知识图谱 | LLM 驱动实体关系提取 + vis-network 力导向图 |
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
# 编辑 .env，填入你的 MaaS API Key
```

关键配置项：

```env
# 聊天模型
OPENAI_API_KEY=sk-ws-H.xxx
OPENAI_BASE_URL=https://xxx.maas.aliyuncs.com/compatible-mode/v1
OPENAI_MODEL_NAME=qwen3.7-plus

# 向量模型（可与聊天模型使用不同 API Key，如聊天 API 不含嵌入能力）
EMBEDDING_API_KEY=sk-ws-H.yyy
EMBEDDING_BASE_URL=https://yyy.maas.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=text-embedding-v3

# 知识图谱
kg_enabled=True
```

> 如果聊天和嵌入使用同一个 API Key，`EMBEDDING_API_KEY` / `EMBEDDING_BASE_URL` 可留空，系统自动回退到 `OPENAI_API_KEY` / `OPENAI_BASE_URL`。

### 3. 启动

```bash
# 推荐方式：自动处理 API Key 环境变量冲突
python start_fixed.py

# 或者直接启动
uvicorn app.backend.main:app --host 0.0.0.0 --port 8000 --reload
```

> `start_fixed.py` 会从 `.env` 读取正确的 API Key 并写入环境变量，确保 uvicorn reload 子进程也能使用正确的 Key。如果环境中已存在同名的过期 Key，直接 `uvicorn` 启动会导致子进程继承过期值。

访问 http://127.0.0.1:8000

## 项目结构

```
app/
├── backend/
│   ├── main.py                   # FastAPI 路由（含认证、审计、用户管理、图谱）
│   ├── config.py                 # Pydantic 配置（.env 驱动）
│   ├── logger.py                 # loguru 日志（按天轮转）
│   ├── deps.py                   # 依赖注入（JWT 认证、角色校验）
│   ├── db/
│   │   ├── models.py             # Document / User / ConversationMeta / AuditLog / GraphEntity / GraphRelation
│   │   └── session.py            # SQLite 引擎与会话
│   └── service/
│       ├── document_service.py   # 文档管理（上传/列表/删除+魔数校验+图谱抽取钩子）
│       ├── vectorization_service.py # 解析→切分→Embedding→Chroma
│       ├── chat_service.py       # RAG 检索（向量+图谱双路）+ SSE 流式对话 + 会话管理
│       └── knowledge_graph_service.py  # LLM 实体关系提取、BFS 图搜索、统计、重建
└── web/
    ├── index.html                # Vue SPA（含知识图谱页面）
    ├── css/style.css             # 青色暗色主题
    └── js/
        ├── app.js                # 前端逻辑（含 PoW、图谱渲染、vis-network 交互）
        ├── marked.min.js         # Markdown 渲染
        ├── purify.min.js         # XSS 过滤
        └── vue.global.prod.js    # Vue 3 运行时
data/                             # 运行时目录（已 gitignore，启动自动创建）
├── docs.db                       # SQLite 文档元信息 + 图谱数据
├── chroma/                       # Chroma 向量库持久化
├── documents/                    # 上传文件的 UUID 重命名存储
logs/                             # loguru 日志（按天轮转）
```

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 前端页面 |
| POST | `/chat` | SSE 流式问答 `{message, thread_id}`（返回 sources + graph_sources） |
| POST | `/auth/login` | 用户登录（PoW + 签名验证） |
| GET | `/auth/login-salt` | 获取一次性登录盐值 |
| GET/PUT | `/conversations` | 会话列表 / 重命名会话 |
| DELETE | `/conversations/{tid}` | 删除会话 |
| GET | `/documents` | 文档列表 `?page&page_size&keyword` |
| POST | `/documents/upload` | 上传文档（multipart `files`，自动向量化+图谱提取） |
| GET | `/documents/{id}/preview` | 预览文档内容（文本 JSON / PDF 内联） |
| GET | `/documents/{id}/download` | 下载文档（Content-Disposition: attachment） |
| DELETE | `/documents/{id}` | 删除文档（含向量+图谱清理） |
| GET | `/graph/stats` | 图谱统计（实体/关系数量，按标签分布） |
| GET | `/graph/entities` | 实体列表 `?page&page_size&label` |
| GET | `/graph/entities/{id}` | 实体详情（含邻接关系和邻居节点） |
| GET | `/graph/search` | 图谱搜索 `?q&depth`，支持自然语言问句 |
| POST | `/graph/rebuild` | 重新提取指定文档的图谱 `{doc_id}`（admin） |
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

## 知识图谱

上传文档后，系统自动调用大模型逐文档提取安全实体及实体间关系，整个过程在向量化完成后同步触发，无需手动干预。实体和关系持久化到 SQLite，与向量检索引擎完全解耦。

系统定义 7 类实体和 8 类关系，大模型按预置 Schema 输出结构化 JSON，后端做去重与批量入库，单文档提取耗时约 2-3 分钟。

**实体类型**：漏洞、攻击手法、安全工具、网络协议、防御措施、合规标准、威胁组织

**关系类型**：利用、缓解、依赖、属于、检测、变种、参考、影响

### 可视化

前端基于 vis-network 构建力导向图。节点按实体类型着色，连线标注关系名称。支持关键字搜索、双击节点展开邻接关系和邻居实体。图谱容器始终可见，加载和错误态以遮罩覆盖，避免 0×0 画布导致的布局异常。

### 双路检索

聊天时向量检索与图谱检索并行执行，分别返回 `sources` 和 `graph_sources`，随对话历史一起持久化。图搜索采用 BFS 子图扩展，对自然语言问句自动去除提问词并反向匹配实体名，深度可在 `.env` 中配置（`KG_GRAPH_SEARCH_DEPTH`）。

### 抽取统计（51 篇安全文档）

| 实体类型 | 数量 | 说明 |
|---------|------|------|
| 防御措施 | 365 | WAF、IDS/IPS、访问控制、加固策略等 |
| 安全工具 | 315 | Nmap、Metasploit、BurpSuite、Nessus 等 |
| 攻击手法 | 255 | SQL 注入、XSS、CSRF、反序列化等 |
| 漏洞 | 95 | CVE、OWASP Top 10、0-day 等 |
| 网络协议 | 91 | HTTP/HTTPS、DNS、TCP/IP、TLS 等 |
| 合规标准 | 50 | 等保2.0、GDPR、ISO 27001 等 |
| 威胁组织 | 2 | APT 组织关联 |
| **合计** | **1173 实体 / 1203 关系** | |

## 安全特性

- **登录安全**：PoW（工作量证明）→ 签名盐值（防重放）→ 速率限制（5 次/5 分钟）三层防护
- **XSS 防护**：DOMPurify + marked 标签白名单
- **文件安全**：PDF 魔数校验，UUID 重命名存储
- **敏感信息**：API Key / JWT Secret 存于 `.env`，启动时校验默认值
- **HTTP 安全头**：CORS、X-Content-Type-Options、X-Frame-Options、X-XSS-Protection
- **防 FOUC**：v-cloak 指令防止未授权元素闪现

## 文档处理流程

### 切分策略

RAG 系统最核心的环节是文档切分。切得太碎丢失上下文，切得太粗检索精度下降。本项目采用**格式感知的分层切分策略**：

```
上传文档 → 魔数校验（PDF 防伪造）→ 解析加载 → route → 向量入库 → 图谱提取
                                                     │              │
                             ┌───────────────────────┤              │
                             ▼                       ▼              │
                        Markdown 文档           非 Markdown 文档      │
                    （.md / .markdown）     （.txt / .pdf / .csv）    │
                             │                       │              │
                             ▼                       ▼              │
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
用户问题 → 向量检索（text-embedding-v3, MaaS OpenAI 兼容接口）
         → 图谱检索（BFS 子图扩展，深度可配）
         → 双路并行
         → Chroma 向量检索（cosine 距离，top_k=5）
         → 相似度过滤（score ≥ 0.3）
         → 拼接上下文 → 注入 system prompt → SSE 缓冲流式生成（8 字合并）
```

> 嵌入层使用 `langchain-openai` 的 `OpenAIEmbeddings`。MaaS 接口 Key 格式（`sk-ws-H...`）仅支持 OpenAI 兼容端点。需设置 `check_embedding_ctx_length=False` 绕过 tiktoken 分词（MaaS embedding API 只接收原始字符串），`chunk_size=10` 限制每批最多 10 条（MaaS API 强制约束）。

## 性能优化

- **SSE 缓冲合并**：百炼 `qwen3.7-plus` 流式返回 token 粒度极小（1-3 字/帧）导致前端渲染卡顿。服务端增加 8 字符缓冲区合并后发送，SSE 帧数减少 60-80%
- **对话摘要压缩**：长对话保留最近 5 轮原文，更早内容通过 LLM 压缩为 2-3 句摘要，显著降低 token 消耗
- **来源持久化**：检索来源随对话历史存入 `conversations.sources` 字段，切换会话后无需重新检索即可回溯
- **向量库单例缓存**：模块级 `_vector_store_cache` 避免重复初始化 Chroma 连接
- **会话列表 N+1 优化**：LEFT JOIN 元信息 + 批量首消息子查询，从 N+1 降至 2 次查询
- **图谱搜索优化**：提问词自动去除（"有哪些"、"怎么" 等）+ 反向实体名匹配，支持自然语言问句查询

## 许可证

MIT
