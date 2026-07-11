from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Document(Base):
    """文档元信息表。"""

    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    original_filename = Column(String(255), nullable=False, comment="原始文件名")
    file_size = Column(Integer, nullable=False, comment="文件大小（字节）")
    mime_type = Column(String(128), nullable=True, comment="MIME 类型")
    storage_path = Column(String(512), nullable=False, comment="服务器存储路径")
    is_vectorized = Column(Boolean, default=False, comment="是否已完成向量化")
    is_graph_extracted = Column(Boolean, default=False, comment="是否已完成知识图谱抽取")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "original_filename": self.original_filename,
            "file_size": self.file_size,
            "mime_type": self.mime_type,
            "is_vectorized": self.is_vectorized,
            "is_graph_extracted": self.is_graph_extracted,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class User(Base):
    """用户表：账号密码登录 + RBAC 角色。

    role 取值：admin（管理员）/ user（游客，只能问答）/ auditor（审计员，问答+看日志）
    """

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), nullable=False, unique=True, index=True, comment="登录用户名")
    password_hash = Column(String(255), nullable=False, comment="bcrypt 哈希后的密码")
    role = Column(String(32), nullable=False, default="user", comment="角色：admin/user/auditor")
    is_active = Column(Boolean, default=True, comment="是否启用，禁用后无法登录")
    token_version = Column(Integer, default=0, comment="令牌版本号，每次登录自增，用于实现单点登录")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Conversation(Base):
    """对话历史表：按 user_id + thread_id 隔离不同用户的会话。"""

    __tablename__ = "conversations"
    __table_args__ = (
        Index("idx_conv_user_thread", "user_id", "thread_id"),
        Index("idx_conv_user_role_thread", "user_id", "role", "thread_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True, comment="所属用户 ID")
    thread_id = Column(String(128), nullable=False, index=True, comment="会话标识")
    role = Column(String(16), nullable=False, comment="角色：user / assistant")
    content = Column(Text, nullable=False, comment="消息内容")
    sources = Column(Text, nullable=True, comment="引用来源 JSON")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "thread_id": self.thread_id,
            "role": self.role,
            "content": self.content,
            "sources": self.sources,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ConversationMeta(Base):
    """会话元数据：存储用户自定义的会话标题。"""

    __tablename__ = "conversation_meta"
    __table_args__ = (
        Index("idx_meta_user_thread", "user_id", "thread_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True, comment="所属用户 ID")
    thread_id = Column(String(128), nullable=False, index=True, comment="会话标识")
    title = Column(String(200), nullable=False, default="新会话", comment="自定义标题")
    summary = Column(Text, nullable=True, comment="历史对话摘要")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "thread_id": self.thread_id,
            "title": self.title,
        }


class AuditLog(Base):
    """审计日志表：记录用户操作行为。"""

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=True, index=True, comment="操作用户 ID（未登录为 NULL）")
    username = Column(String(64), nullable=True, comment="操作用户名")
    action = Column(String(64), nullable=False, comment="操作类型：login/chat/upload/delete/user_create/...")
    detail = Column(String(512), nullable=True, comment="操作详情")
    ip = Column(String(64), nullable=True, comment="客户端 IP")
    created_at = Column(DateTime, default=func.now(), comment="操作时间")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "username": self.username,
            "action": self.action,
            "detail": self.detail,
            "ip": self.ip,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class GraphEntity(Base):
    """知识图谱：实体节点。"""

    __tablename__ = "graph_entities"
    __table_args__ = (
        Index("idx_ge_name", "name"),
        Index("idx_ge_label", "label"),
        Index("idx_ge_doc", "doc_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, comment="实体名称")
    label = Column(String(64), nullable=False, comment="实体类型")
    doc_id = Column(Integer, nullable=False, comment="来源文档 ID")
    metadata_json = Column(Text, nullable=True, comment="额外元数据 JSON")
    created_at = Column(DateTime, default=func.now())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "label": self.label,
            "doc_id": self.doc_id,
            "metadata_json": self.metadata_json,
        }


class GraphRelation(Base):
    """知识图谱：关系边。"""

    __tablename__ = "graph_relations"
    __table_args__ = (
        Index("idx_gr_src", "source_entity_id"),
        Index("idx_gr_tgt", "target_entity_id"),
        Index("idx_gr_doc", "doc_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_entity_id = Column(Integer, nullable=False, comment="起始实体 ID")
    target_entity_id = Column(Integer, nullable=False, comment="目标实体 ID")
    relation = Column(String(128), nullable=False, comment="关系类型")
    doc_id = Column(Integer, nullable=False, comment="来源文档 ID")
    metadata_json = Column(Text, nullable=True, comment="额外元数据 JSON")
    created_at = Column(DateTime, default=func.now())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source_entity_id": self.source_entity_id,
            "target_entity_id": self.target_entity_id,
            "relation": self.relation,
            "doc_id": self.doc_id,
            "metadata_json": self.metadata_json,
        }
