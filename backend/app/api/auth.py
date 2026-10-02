"""Аутентификация (тонкий вертикальный срез; полный RBAC — Фаза 3)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.errors import ForbiddenError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    hash_password,
    hash_token,
    require_admin,
    verify_password,
)
from app.db.models import User, utcnow
from app.db.repositories.users import (
    audit,
    get_user_by_username,
    revoke_refresh_token,
    rotate_refresh_token,
    save_refresh_token,
)
from app.db.session import get_db
from app.schemas.api import (
    CreateUserRequest,
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    TokenPair,
    UserOut,
    UserWithPasswordOut,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _client_meta(request: Request) -> dict[str, str | None]:
    return {"ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent")}


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, request: Request,
                db: Session = Depends(get_db)) -> LoginResponse:
    settings = get_settings()
    user = get_user_by_username(db, payload.username)

    if user is None or not verify_password(payload.password, user.hashed_password):
        audit(db, action="auth.login", actor=user, ok=False,
              reason="bad_credentials", **_client_meta(request))
        raise ForbiddenError("Неверный логин или пароль")

    if not user.is_active:
        raise ForbiddenError("Пользователь отключён")

    access = create_access_token(user)
    refresh, refresh_expires = create_refresh_token(user)
    save_refresh_token(db, user.id, hash_token(refresh), refresh_expires)
    user.last_login_at = utcnow()
    db.commit()
    db.refresh(user)
    audit(db, action="auth.login", actor=user, **_client_meta(request))

    return LoginResponse(
        user=UserOut.model_validate(user),
        tokens=TokenPair(
            access_token=access,
            refresh_token=refresh,
            expires_in=settings.access_token_ttl_minutes * 60,
        ),
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh_tokens(payload: RefreshRequest, request: Request,
                         db: Session = Depends(get_db)) -> TokenPair:
    settings = get_settings()
    token_hash = hash_token(payload.refresh_token)
    record = rotate_refresh_token(db, token_hash)
    user = db.get(User, record.user_id)
    if user is None or not user.is_active:
        raise ForbiddenError("Пользователь недоступен")

    access = create_access_token(user)
    refresh, refresh_expires = create_refresh_token(user)
    save_refresh_token(db, user.id, hash_token(refresh), refresh_expires)
    audit(db, action="auth.refresh", actor=user, **_client_meta(request))
    return TokenPair(access_token=access, refresh_token=refresh,
                     expires_in=settings.access_token_ttl_minutes * 60)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: RefreshRequest, request: Request,
                 db: Session = Depends(get_db)) -> None:
    revoke_refresh_token(db, hash_token(payload.refresh_token))
    audit(db, action="auth.logout", **_client_meta(request))




@router.post("/register", response_model=UserWithPasswordOut, status_code=status.HTTP_201_CREATED)
async def register(
    payload: CreateUserRequest,
    request: Request,
    actor: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> User:
    from app.db.repositories.users import get_user_by_username

    if get_user_by_username(db, payload.username):
        from app.core.errors import ConflictError

        raise ConflictError(f"������������ �{payload.username}� ��� ����������")
    user = User(
        username=payload.username,
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    from app.db.repositories.users import audit

    audit(
        db,
        action="auth.register",
        actor=actor,
        target_type="user",
        target_id=user.id,
        **_client_meta(request),
        username=user.username,
    )
    return user


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)
