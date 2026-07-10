from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backend.config import settings
from app.backend.db.models import Base

# SQLite 支持多线程访问，关闭同线程检查
engine = create_engine(
    f"sqlite:///{settings.database_file_path}",
    connect_args={"check_same_thread": False},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """应用启动时创建所有继承 Base 的表结构。"""
    Base.metadata.create_all(bind=engine)
