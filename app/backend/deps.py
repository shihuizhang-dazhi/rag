# -*- coding: utf-8 -*-
"""FastAPI 鉴权依赖：从请求中解析 JWT，返回当前用户。"""
from typing import Iterable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.backend.db.models import User
from app.backend.db.session import SessionLocal
from app.backend.service.auth_service import JWTError, decode_access_token

# auto_error=False 让我们在 401 时返回统一格式，而不是让 FastAPI 直接弹 WWW-Authenticate
_bearer = HTTPBearer(auto_error=False)


def get_db():
    """请求级 DB Session：路由结束时自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """解析 Bearer token，返回当前登录用户。未带 token / token 失效 / 用户不存在 → 401。"""
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未携带认证凭据")
    try:
        payload = decode_access_token(creds.credentials)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="凭据已失效或非法")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="凭据内容非法")

    user = db.get(User, int(user_id))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已禁用")
    return user


def require_role(*roles: str):
    """工厂：返回一个依赖，校验当前用户角色是否在允许列表内，否则 403。

    用法：
        @router.post("/documents/upload", dependencies=[Depends(require_role("admin"))])
    """

    def _check(current: User = Depends(get_current_user)) -> User:
        if current.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"权限不足，需要角色：{', '.join(roles)}",
            )
        return current

    return _check
