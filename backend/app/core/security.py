"""Пароли, JWT, RBAC-зависимости."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlalchemy.orm import Session
from starlette.status import HTTP_403_FORBIDDEN

from app.config import get_settings
from app.db.models import Role, User
from app.db.session import get_db

_password_hash = PasswordHash.recommended()
_bearer = HTTPBearer(auto_error=False)


# --------------------------------------------------------------------------- пароли
def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("Пароль должен быть не короче 8 символов")
    return _password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _password_hash.verify(password, hashed)
    except Exception:
        return False


# --------------------------------------------------------------------------- JWT
def create_access_token(user: User, *, extra: dict[str, Any] | None = None) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": user.id,
        "username": user.username,
        "role": user.role.value,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_ttl_minutes),
        **(extra or {}),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(user: User) -> tuple[str, datetime]:
    settings = get_settings()
    token = secrets.token_urlsafe(48)
    expires_at = datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days)
    return token, expires_at


def hash_token(token: str) -> str:
    """Храним только хэш refresh-токена."""
    return hashlib.sha256(token.encode()).hexdigest()


def decode_token(token: str, *, expected_type: str = "access") -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Токен истёк") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Некорректный токен") from exc
    if payload.get("type") != expected_type:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный тип токена")
    return payload


# --------------------------------------------------------------------------- deps
def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется авторизация")
    payload = decode_token(credentials.credentials, expected_type="access")
    user = db.get(User, payload.get("sub"))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Пользователь не найден или отключён")
    request.state.user = user
    return user


def require_role(*roles: Role) -> Any:
    """Зависимость FastAPI: пускает только пользователей с указанными ролями."""

    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                HTTP_403_FORBIDDEN,
                detail=f"Недостаточно прав: требуется {', '.join(r.value for r in roles)}",
            )
        return user

    return dependency


require_admin = require_role(Role.admin)
require_researcher = require_role(Role.researcher, Role.admin)


def verify_secret(provided: str, expected: str) -> bool:
    return hmac.compare_digest(provided, expected)