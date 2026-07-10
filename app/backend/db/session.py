from sqlalchemy import create_engine
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
    _seed_default_users()


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
