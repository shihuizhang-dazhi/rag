from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.backend.config import settings
from app.backend.db.models import Base, ConversationMeta, User
from app.backend.logger import logger

engine = create_engine(
    f"sqlite:///{settings.database_file_path}",
    connect_args={"check_same_thread": False},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """应用启动时创建所有继承 Base 的表结构，并种入默认账号。"""
    Base.metadata.create_all(bind=engine)
    _migrate_add_token_version()
    _migrate_add_conversation_sources()
    _migrate_add_conversation_meta_summary()
    _migrate_add_composite_indexes()
    _migrate_add_graph_extraction_flag()
    _seed_default_users()


def _migrate_add_composite_indexes() -> None:
    with engine.connect() as conn:
        indexes = {row[1] for row in conn.execute(text("PRAGMA index_list(conversations)")).fetchall()}
        if "idx_conv_user_thread" not in indexes:
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_conv_user_thread ON conversations(user_id, thread_id)"))
            conn.commit()
            logger.info("数据库迁移：已添加 conversations(user_id, thread_id) 复合索引")
        if "idx_conv_user_role_thread" not in indexes:
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_conv_user_role_thread ON conversations(user_id, role, thread_id)"))
            conn.commit()
            logger.info("数据库迁移：已添加 conversations(user_id, role, thread_id) 复合索引")
        meta_indexes = {row[1] for row in conn.execute(text("PRAGMA index_list(conversation_meta)")).fetchall()}
        if "idx_meta_user_thread" not in meta_indexes:
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_meta_user_thread ON conversation_meta(user_id, thread_id)"))
            conn.commit()
            logger.info("数据库迁移：已添加 conversation_meta(user_id, thread_id) 复合索引")


def _migrate_add_token_version() -> None:
    """对旧数据库迁移：添加 token_version 列（单点登录所需）。"""
    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(users)")).fetchall()}
        if "token_version" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0"))
            conn.commit()
            logger.info("数据库迁移：已为 users 表添加 token_version 列")


def _migrate_add_conversation_sources() -> None:
    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(conversations)")).fetchall()}
        if "sources" not in cols:
            conn.execute(text("ALTER TABLE conversations ADD COLUMN sources TEXT"))
            conn.commit()
            logger.info("数据库迁移：已为 conversations 表添加 sources 列")


def _migrate_add_conversation_meta_summary() -> None:
    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(conversation_meta)")).fetchall()}
        if "summary" not in cols:
            conn.execute(text("ALTER TABLE conversation_meta ADD COLUMN summary TEXT"))
            conn.commit()
            logger.info("数据库迁移：已为 conversation_meta 表添加 summary 列")


def _migrate_add_graph_extraction_flag() -> None:
    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(documents)")).fetchall()}
        if "is_graph_extracted" not in cols:
            conn.execute(text("ALTER TABLE documents ADD COLUMN is_graph_extracted BOOLEAN NOT NULL DEFAULT 0"))
            conn.commit()
            logger.info("数据库迁移：已为 documents 表添加 is_graph_extracted 列")


def _seed_default_users() -> None:
    """users 表为空时，种入默认管理员、游客、审计员账号。"""
    from app.backend.service.auth_service import hash_password

    with SessionLocal() as session:
        if session.query(User).count() > 0:
            return
        defaults = [
            User(
                username="admin",
                password_hash=hash_password("88888888"),
                role="admin",
                is_active=True,
            ),
            User(
                username="guest",
                password_hash=hash_password("guest123"),
                role="user",
                is_active=True,
            ),
            User(
                username="auditor",
                password_hash=hash_password("auditor123"),
                role="auditor",
                is_active=True,
            ),
        ]
        session.add_all(defaults)
        session.commit()
        logger.info("已种入默认账号：admin / guest / auditor（请尽快修改密码）")
