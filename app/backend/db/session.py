from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backend.config import settings
from app.backend.db.models import Base, User
from app.backend.logger import logger

# SQLite 支持多线程访问，关闭同线程检查
engine = create_engine(
    f"sqlite:///{settings.database_file_path}",
    connect_args={"check_same_thread": False},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """应用启动时创建所有继承 Base 的表结构，并种入默认管理员账号。"""
    Base.metadata.create_all(bind=engine)
    _seed_default_admin()


def _seed_default_admin() -> None:
    """users 表为空时，按配置种入默认管理员，方便首次登录。"""
    # 延迟导入，避免循环依赖
    from app.backend.service.auth_service import hash_password

    with SessionLocal() as session:
        if session.query(User).count() > 0:
            return
        admin = User(
            username=settings.default_admin_username,
            password_hash=hash_password(settings.default_admin_password),
            role="admin",
            is_active=True,
        )
        session.add(admin)
        session.commit()
        logger.info(
            f"已种入默认管理员账号：{settings.default_admin_username}（请尽快修改密码）"
        )
