# -*- coding: utf-8 -*-
"""FastAPI 鉴权依赖：优先从 HttpOnly Cookie 读取 JWT，回退到 Authorization Header。"""
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.backend.db.models import User
from app.backend.db.session import SessionLocal
from app.backend.service.auth_service import JWTError, decode_access_token

_bearer = HTTPBearer(auto_error=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _resolve_token(request: Request, creds: HTTPAuthorizationCredentials | None) -> str | None:
    cookie_token = request.cookies.get("access_token")
    if cookie_token:
        return cookie_token
    if creds and creds.credentials:
        return creds.credentials
    return None


def get_optional_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """从 Cookie 或 Authorization Header 解析 JWT，无 token 或校验失败返回 None。"""
    token = _resolve_token(request, creds)
    if not token:
        return None
    try:
        payload = decode_access_token(token)
    except JWTError:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    user = db.get(User, int(user_id))
    if user is None or not user.is_active:
        return None
    token_ver = payload.get("ver")
    if token_ver is not None and token_ver != user.token_version:
        return None
    return user


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """从 Cookie 或 Authorization Header 解析 JWT。未带 token / token 失效 → 401。"""
    user = get_optional_user(request=request, creds=creds, db=db)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未携带认证凭据")
    return user


def require_role(*roles: str):
    def _check(current: User = Depends(get_current_user)) -> User:
        if current.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"权限不足，需要角色：{', '.join(roles)}",
            )
        return current

    return _check
