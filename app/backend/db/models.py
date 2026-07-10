from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, func
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
    created_at = Column(DateTime, default=func.now(), comment="创建时间")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "original_filename": self.original_filename,
            "file_size": self.file_size,
            "mime_type": self.mime_type,
            "storage_path": self.storage_path,
            "is_vectorized": self.is_vectorized,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
