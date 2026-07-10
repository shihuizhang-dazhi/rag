import ast
from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, NoDecode

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve_path(value: str) -> str:
    """将相对路径解析为项目根目录下的绝对路径字符串。"""
    if not value:
        return value
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return str(path.resolve())


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ============ 大模型 / 向量模型 ============
    openai_api_key: str
    openai_base_url: str
    openai_model_name: str
    embedding_model: str

    # ============ 文档解析 / 检索参数 ============
    supported_extensions: Annotated[list[str], NoDecode]
    chunk_size: int
    chunk_overlap: int
    top_k: int
    score_threshold: float

    # ============ 文档存储 / 数据库 / 向量库路径 ============
    max_file_size_mb: int
    documents_save_path: str
    database_file_path: str
    chroma_path: str
    chroma_collection_name: str = "documents"

    # ============ 认证鉴权 ============
    jwt_secret: str = "change-me-in-production-please"
    jwt_algorithm: str = "HS256"
    token_expire_minutes: int = 60 * 24  # access token 有效期，默认 24 小时
    # 启动时若 users 表为空，自动种入的默认管理员账号
    default_admin_username: str = "admin"
    default_admin_password: str = "admin123"

    # ============ 应用文案 ============
    system_prompt: str = (
        "你是一名企业网络安全助手，专注于信息安全领域。"
        "你擅长回答网络安全相关问题，包括但不限于：应急响应、渗透测试、"
        "安全分析、漏洞研究、安全运维、入侵检测、日志分析、恶意软件分析等。"
        "回答问题时，优先参考提供的知识库资料；"
        "如果资料不充分或与问题不相关，你可以基于自己的安全知识直接回答，"
        "无需刻意区分资料来源。"
    )

    @field_validator("supported_extensions", mode="before")
    @classmethod
    def parse_supported_extensions(cls, value):
        if isinstance(value, str):
            return ast.literal_eval(value)
        return value

    @field_validator("documents_save_path", "database_file_path", "chroma_path")
    @classmethod
    def resolve_paths(cls, value):
        return _resolve_path(value)


# 创建全局配置对象
settings = AppSettings()

if __name__ == "__main__":
    print(settings.supported_extensions)
    print(settings.chroma_path)
