"""Админ-панель: управление пользователями, аудит, системные операции."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, UpstreamError
from app.core.security import hash_password, require_admin
from app.db.models import User
from app.db.repositories.users import audit, get_user, get_user_by_username
from app.db.session import get_db
from app.schemas.api import (
    AuditLogOut,
    BackupCreateRequest,
    BackupListOut,
    BackupResultOut,
    CreateUserRequest,
    ResetPlanOut,
    ResetRequest,
    ResetResultOut,
    UserOut,
    UserUpdateRequest,
    UserWithPasswordOut,
)
from app.services import backup as backup_service
from app.services.backup import plan_backup
from app.services.reset import (
    CONFIRM_PHRASES,
    plan_reset,
    run_reset,
)

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _client_meta(request: Request) -> dict[str, str | None]:
    return {
        "ip": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
    }


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)) -> list[User]:
    return list(db.scalars(select(User).order_by(User.created_at)))


@router.post(
    "/users",
    response_model=UserWithPasswordOut,
    status_code=status.HTTP_201_CREATED,
)
def create_user(
    payload: CreateUserRequest,
    request: Request,
    actor: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> User:
    if get_user_by_username(db, payload.username):
        raise ConflictError(f"Пользователь «{payload.username}» уже существует")
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
    audit(
        db,
        action="admin.user.create",
        actor=actor,
        target_type="user",
        target_id=user.id,
        **_client_meta(request),
        username=user.username,
        role=user.role.value,
    )
    return user


@router.get("/users/{user_id}", response_model=UserOut)
def get_user_detail(user_id: str, db: Session = Depends(get_db)) -> User:
    user = get_user(db, user_id)
    if not user:
        raise NotFoundError("Пользователь не найден")
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: str,
    payload: UserUpdateRequest,
    request: Request,
    actor: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> User:
    user = get_user(db, user_id)
    if not user:
        raise NotFoundError("Пользователь не найден")
    changes: dict[str, Any] = {}
    if payload.email is not None:
        user.email = payload.email
        changes["email"] = payload.email
    if payload.full_name is not None:
        user.full_name = payload.full_name
        changes["full_name"] = payload.full_name
    if payload.role is not None:
        user.role = payload.role
        changes["role"] = payload.role.value
    if payload.is_active is not None:
        user.is_active = payload.is_active
        changes["is_active"] = payload.is_active
    if payload.password is not None:
        user.hashed_password = hash_password(payload.password)
        changes["password_changed"] = True
    db.commit()
    db.refresh(user)
    audit(
        db,
        action="admin.user.update",
        actor=actor,
        target_type="user",
        target_id=user.id,
        **_client_meta(request),
        changes=changes,
    )
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: str,
    request: Request,
    actor: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    user = get_user(db, user_id)
    if not user:
        raise NotFoundError("Пользователь не найден")
    if user.id == actor.id:
        raise ConflictError("Нельзя удалить самого себя")
    username = user.username
    db.delete(user)
    db.commit()
    audit(
        db,
        action="admin.user.delete",
        actor=actor,
        target_type="user",
        target_id=user_id,
        **_client_meta(request),
        username=username,
    )


@router.get("/audit", response_model=list[AuditLogOut])
def list_audit(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    action: str | None = Query(default=None),
    target_type: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[Any]:
    from app.db.models import AuditLog

    q = select(AuditLog).order_by(AuditLog.created_at.desc())
    if action:
        q = q.where(AuditLog.action.ilike(f"%{action}%"))
    if target_type:
        q = q.where(AuditLog.target_type == target_type)
    if since:
        q = q.where(AuditLog.created_at >= since)
    q = q.offset(offset).limit(limit)
    return list(db.scalars(q))


# --------------------------------------------------------------- сброс состояния
@router.get("/reset/preview", response_model=ResetPlanOut)
def reset_preview(
    scope: str = Query(default="data"),
    include_models: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Что будет удалено при сбросе. Ничего не меняет — безопасно вызывать."""
    try:
        return plan_reset(scope, include_models=include_models, db=db).as_dict()
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc


@router.post("/reset", response_model=ResetResultOut)
def reset_state(
    payload: ResetRequest,
    request: Request,
    actor: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Сбросить состояние платформы.

    Требует точного совпадения `confirm` с фразой из `/reset/preview`:
    одного клика недостаточно. В prod дополнительно нужен
    ALLOW_DESTRUCTIVE_RESET=true в .env.
    """
    expected = CONFIRM_PHRASES.get(payload.scope)
    if expected is None:
        raise ConflictError(f"Неизвестный scope: {payload.scope}")
    if payload.confirm.strip() != expected:
        raise ConflictError(
            f"Неверная фраза подтверждения. Для scope={payload.scope} нужно: "
            f"{expected!r}")
    result = run_reset(
        payload.scope,
        dry_run=False,
        include_models=payload.include_models,
        db=db,
        actor=actor,
        meta={"source": "api", **_client_meta(request)},
    )
    return result.as_dict()


# ------------------------------------------------------------ резервные копии
# Бэкап снимается изнутри процесса backend, поэтому одинаково работает
# и в контейнере (данные в томе /data), и на Windows (каталог data/).
# Восстановления здесь нет намеренно: оно требует остановки платформы и
# остаётся скриптом scripts/restore.sh.
@router.get("/backup", response_model=BackupListOut)
def list_backups(
    request: Request,
    actor: User = Depends(require_admin),
) -> dict[str, Any]:
    """Список копий и план следующей (что и сколько займёт)."""
    plan = plan_backup()
    return {
        "backups": [entry.as_dict() for entry in backup_service.list_backups()],
        "plan": plan.as_dict(),
    }


@router.post("/backup", response_model=BackupResultOut)
def create_backup(
    payload: BackupCreateRequest,
    request: Request,
    actor: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Снять копию.

    Фразы подтверждения здесь нет намеренно: операция неразрушающая, её
    платный исход — свободное место (оценка видна в плане), и всё, что может
    пойти не так, проверяется до записи.
    """
    plan = plan_backup()
    if not plan.db_exists:
        raise ConflictError(
            "База данных не найдена — копия получится без данных. "
            "Проверьте, что платформа видит свой каталог данных.")
    if plan.free_bytes is not None and plan.free_bytes < plan.estimated_bytes:
        raise ConflictError(
            f"Не хватает места: свободно {plan.free_human}, "
            f"копия займёт около {plan.estimated_human}")
    try:
        result = backup_service.run_backup(
            keep=payload.keep, actor=actor)
    except OSError as exc:
        raise UpstreamError(f"Не удалось создать копию: {exc}") from exc
    audit(
        db,
        action="admin.backup.create",
        actor=actor,
        target_type="backup",
        target_id=result.entry.name,
        **_client_meta(request),
        bytes=result.entry.bytes,
        deleted_old=result.deleted_old,
        data_dir=plan.data_dir,
    )
    return result.as_dict()


@router.delete("/backup/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_backup(
    name: str,
    request: Request,
    actor: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    """Удалить копию. Восстановиться из неё после удаления уже нельзя."""
    try:
        removed = backup_service.delete_backup(name)
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc
    if not removed:
        raise NotFoundError(f"Копия не найдена: {name}")
    audit(db, action="admin.backup.delete", actor=actor, target_type="backup",
          target_id=name, **_client_meta(request))
