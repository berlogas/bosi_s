"""Админ-панель: управление пользователями, аудит, системные операции."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ConflictError, NotFoundError, UpstreamError
from app.core.security import hash_password, require_admin
from app.db.models import User
from app.db.repositories.users import audit, get_user, get_user_by_username
from app.db.repositories.users import audit_stats as audit_stats_db
from app.db.session import get_db
from app.schemas.api import (
    AuditLogOut,
    BackupCreateRequest,
    BackupListOut,
    BackupResultOut,
    CreateUserRequest,
    InboxFileOut,
    InboxRunOut,
    InboxScanResultOut,
    InboxStatusOut,
    ResetPlanOut,
    ResetRequest,
    ResetResultOut,
    UserOut,
    UserUpdateRequest,
    UserWithPasswordOut,
)
from app.services import backup as backup_service
from app.services.backup import plan_backup
from app.services.inbox import InboxService
from app.services.reset import (
    CONFIRM_PHRASES,
    plan_reset,
    run_reset,
)

# BOM в начале CSV: без него Excel открывает кириллицу как mojibake.
BOM = chr(0xFEFF)
NEWLINE = chr(10)



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
    if payload.username is not None:
        new_username = payload.username.strip()
        if not new_username:
            raise AppError("Логин не может быть пустым")
        if new_username != user.username:
            taken = get_user_by_username(db, new_username)
            if taken and taken.id != user.id:
                raise ConflictError(f"Пользователь «{new_username}» уже существует")
            user.username = new_username
            changes["username"] = new_username
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


# --------------------------------------------------------------------- inbox
def _run_out(service: InboxService, db: Session, run: Any) -> InboxRunOut:
    from app.db.models import InboxFile

    files = db.scalars(
        select(InboxFile).where(InboxFile.run_id == run.id)
        .order_by(InboxFile.rel_path)
    )
    return InboxRunOut(
        id=run.id, trigger=run.trigger, status=run.status.value,
        inbox_dir=run.inbox_dir, scanned=run.scanned, indexed=run.indexed,
        archived=run.archived, rejected=run.rejected, replaced=run.replaced,
        failed=run.failed, error=run.error, started_at=run.started_at,
        finished_at=run.finished_at,
        files=[InboxFileOut.model_validate(f) for f in files],
    )


@router.get("/inbox/status", response_model=InboxStatusOut)
def inbox_status(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Что лежит в папке-приёмнике. Быстрый и безопасный вызов для UI."""
    return InboxService().peek(db)


@router.get("/inbox/runs", response_model=list[InboxRunOut])
def inbox_runs(
    limit: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[InboxRunOut]:
    """История прогонов: что добавляли и чем закончилось (журнал, не лог)."""
    service = InboxService()
    return [_run_out(service, db, run) for run in service.runs(db, limit=limit)]


@router.get("/inbox/runs/{run_id}", response_model=InboxRunOut)
def inbox_run_detail(run_id: str, db: Session = Depends(get_db)) -> InboxRunOut:
    service = InboxService()
    return _run_out(service, db, service.get_run(db, run_id))


@router.get("/audit/stats", response_model=dict)
def audit_stats(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Сколько записей в журнале и какая самая старая.

    Без этого не видно, работает ли ретрация: список в UI всегда
    ограничен страницей, а растёт или уменьшается хвост — неизвестно.
    """
    stats = audit_stats_db(db)
    return {
        "total": stats["total"],
        "oldest_at": stats["oldest_at"].isoformat() if stats["oldest_at"] else None,
        "newest_at": stats["newest_at"].isoformat() if stats["newest_at"] else None,
    }


@router.get("/audit/export")
def audit_export(
    limit: int = Query(default=10_000, ge=1, le=100_000),
    action: str | None = Query(default=None),
    target_type: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
) -> Any:
    """Выгрузка журнала в CSV.

    Отдельный эндпоинт, а не флаг у списка: файл отдаётся вложением, и
    интерфейсу не нужно уметь разбирать чужой формат.
    """
    from app.db.models import AuditLog

    q = select(AuditLog).order_by(AuditLog.created_at.desc())
    if action:
        q = q.where(AuditLog.action.ilike(f"%{action}%"))
    if target_type:
        q = q.where(AuditLog.target_type == target_type)
    if since:
        q = q.where(AuditLog.created_at >= since)
    rows = db.scalars(q.limit(limit))

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator=NEWLINE)
    writer.writerow(["created_at", "actor_username", "action", "target_type",
                     "target_id", "ip", "ok", "meta"])
    for row in rows:
        writer.writerow([
            row.created_at.isoformat() if row.created_at else "",
            row.actor_username or "", row.action, row.target_type or "",
            row.target_id or "", row.ip or "", "1" if row.ok else "0",
            json.dumps(row.meta or {}, ensure_ascii=False),
        ])
    payload = BOM + buffer.getvalue()
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return Response(
        content=payload,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="audit-{stamp}.csv"'},
    )


@router.post("/inbox/scan", response_model=InboxScanResultOut)
async def inbox_scan(
    request: Request,
    actor: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Обработать содержимое папки-приёмника.

    Синхронный вызов: индексация больших PDF занимает минуты, поэтому UI
    показывает «идёт обработка» и не должен получить таймаут. Повторный
    клик во время прогона получает 409 — два скана одновременно запускать
    нельзя.
    """
    from app.services.paperqa_service import get_registry

    service = InboxService()
    status = service.peek(db)
    if status["busy"]:
        raise ConflictError("Обработка inbox уже идёт — дождитесь окончания.")
    if not status["exists"]:
        raise NotFoundError(
            f"Папка-приёмник не найдена: {status['inbox_dir']}. "
            "Проверьте INBOX_DIR и монтирование в docker-compose.yml.")

    run = await service.scan(db, get_registry().global_service(), actor)
    audit(db, action="admin.inbox.scan", actor=actor, target_type="inbox_run",
          target_id=run.id, **_client_meta(request),
          scanned=run.scanned, indexed=run.indexed, archived=run.archived,
          rejected=run.rejected, replaced=run.replaced, failed=run.failed)
    return {"run": _run_out(service, db, run).model_dump(),
            "inbox_dir": status["inbox_dir"]}


@router.delete("/inbox/rejected", response_model=dict[str, int])
def inbox_clear_rejected(
    request: Request,
    actor: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    """Очистить каталог `rejected` (причины остаются в журнале прогонов)."""
    removed = InboxService().clear_rejected(db)
    audit(db, action="admin.inbox.rejected.clear", actor=actor, target_type="inbox",
          target_id="rejected", **_client_meta(request), removed=removed)
    return {"removed": removed}
