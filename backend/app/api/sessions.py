"""Сессии исследователя: CRUD, точка возврата, жизненный цикл (Фаза 5).

Маршруты:
  GET    /api/sessions                     — свои сессии (админ видит все)
  POST   /api/sessions                     — создать (лимит 10 активных)
  GET    /api/sessions/{id}                — карточка с лимитами и TTL
  PATCH  /api/sessions/{id}                — переименовать, заметка, проект
  PUT    /api/sessions/{id}/state          — автосохранение точки возврата
  POST   /api/sessions/{id}/pause          — пауза с заметкой
  POST   /api/sessions/{id}/archive        — ручная архивация
  POST   /api/sessions/{id}/resume         — вернуться (реконструкция Docs)
  POST   /api/sessions/{id}/heartbeat      — продление TTL открытой сессии
  DELETE /api/sessions/{id}                — удалить вместе с файлами
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.serializers import session_detail, session_resume
from app.core.leases import leases
from app.core.security import get_current_user, require_researcher
from app.db.models import ResearchSession, Role, SessionStatus, User
from app.db.repositories import messages as messages_repo
from app.db.repositories.sessions import (
    WRITABLE_STATUSES,
    archive_session,
    days_left,
    ensure_writable,
    hard_delete_session,
    pause_session,
    reactivate_session,
    save_state,
    session_summary,
    state_snapshot,
)
from app.db.repositories.users import (
    audit,
    create_research_session,
    get_owned_session,
    list_user_sessions,
    touch_session,
)
from app.db.session import get_db
from app.schemas.api import (
    SessionCreate,
    SessionDetailOut,
    SessionOut,
    SessionPatch,
    SessionResumeOut,
    SessionStateUpdate,
)

log = logging.getLogger("boasi.api.sessions")

router = APIRouter(prefix="/api/sessions", tags=["sessions"],
                   dependencies=[Depends(require_researcher)])


def _meta(request: Request) -> dict[str, str | None]:
    return {"ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent")}


def _keepalive(session_id: str) -> None:
    """Клиент держит сессию открытой — продлеваем аренду для heartbeat-воркера."""
    from app.config import get_settings

    settings = get_settings()
    leases.touch(session_id, settings.heartbeat_interval_minutes * 120)


@router.get("", response_model=list[SessionOut])
def list_sessions(user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)) -> list[ResearchSession]:
    if user.role is Role.admin:
        return list(db.scalars(
            select(ResearchSession)
            .where(ResearchSession.purged_at.is_(None))
            .order_by(ResearchSession.last_activity_at.desc())))
    return list_user_sessions(db, user.id)


@router.post("", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
def create_session(payload: SessionCreate, request: Request,
                   user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)) -> ResearchSession:
    session = create_research_session(db, user, payload.title)
    audit(db, action="session.create", actor=user, target_type="session",
          target_id=session.id, **_meta(request), title=session.title,
          expires_at=session.expires_at.isoformat())
    return session


@router.get("/{session_id}", response_model=SessionDetailOut)
def get_session(session_id: str, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)) -> SessionDetailOut:
    session = get_owned_session(db, session_id, user)
    _keepalive(session.id)
    return session_detail(
        session,
        session_summary(db, session),
        days_left(session),
        session.status in WRITABLE_STATUSES,
    )


@router.patch("/{session_id}", response_model=SessionOut)
def update_session(session_id: str, payload: SessionPatch, request: Request,
                   user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)) -> ResearchSession:
    session = get_owned_session(db, session_id, user)
    ensure_writable(session)

    changed: list[str] = []
    if payload.title is not None:
        session.title = payload.title.strip()[:255] or session.title
        changed.append("title")
    if payload.active_project_id is not None:
        session.active_project_id = payload.active_project_id
        changed.append("active_project_id")
    if payload.resume_note is not None:
        session.resume_note = payload.resume_note
        changed.append("resume_note")
    if payload.state_snapshot is not None:
        save_state(db, session, snapshot=payload.state_snapshot, force=True)
        changed.append("state_snapshot")
    else:
        touch_session(db, session, action_type="session.updated",
                      action_label="Обновление сессии")
    db.commit()

    _keepalive(session.id)
    if changed:
        audit(db, action="session.update", actor=user, target_type="session",
              target_id=session.id, **_meta(request), fields=changed)
    return session


@router.put("/{session_id}/state", response_model=SessionOut)
def save_session_state(session_id: str, payload: SessionStateUpdate,
                       request: Request, user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)) -> ResearchSession:
    """Автосохранение «точки возврата» (дебаунс 5 мин делает клиент).

    Снапшот не изменился — запись не делается, но TTL продлевается.
    """
    session = get_owned_session(db, session_id, user)
    ensure_writable(session)
    _, written = save_state(
        db, session,
        snapshot=payload.snapshot or None,
        note=payload.resume_note,
        action_type=payload.action_type or "session.state",
        action_label=payload.action_label or "Сохранение состояния",
        force=payload.force,
    )
    if written:
        audit(db, action="session.state_saved", actor=user, target_type="session",
              target_id=session.id, **_meta(request))
    _keepalive(session.id)
    return session


@router.post("/{session_id}/pause", response_model=SessionOut)
def pause(session_id: str, request: Request, note: str | None = None,
          user: User = Depends(get_current_user),
          db: Session = Depends(get_db)) -> ResearchSession:
    session = get_owned_session(db, session_id, user)
    pause_session(db, session, note=note)
    leases.drop(session.id)
    audit(db, action="session.pause", actor=user, target_type="session",
          target_id=session.id, **_meta(request))
    return session


@router.post("/{session_id}/archive", response_model=SessionOut)
def archive(session_id: str, request: Request, note: str | None = None,
            user: User = Depends(get_current_user),
            db: Session = Depends(get_db)) -> ResearchSession:
    session = get_owned_session(db, session_id, user)
    archive_session(db, session, note=note)
    leases.drop(session.id)
    audit(db, action="session.archive", actor=user, target_type="session",
          target_id=session.id, **_meta(request))
    return session


@router.post("/{session_id}/resume", response_model=SessionResumeOut)
async def resume(session_id: str, request: Request,
                 user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)) -> SessionResumeOut:
    """Возврат к работе: реактивация + реконструкция `Docs` из БД + точка возврата."""
    session = get_owned_session(db, session_id, user)
    reactivate_session(db, session)

    from app.services.paperqa_service import get_registry

    service = get_registry().session_service(session.id)
    restored = await service.restore_state()

    audit(db, action="session.resume", actor=user, target_type="session",
          target_id=session.id, **_meta(request), restored=restored)
    _keepalive(session.id)
    return session_resume(
        session, session_summary(db, session), state_snapshot(session),
        restored, days_left(session),
        last_exchange=list(messages_repo.last_exchange(db, session.id) or []) or None,
    )


@router.post("/{session_id}/heartbeat", response_model=SessionOut)
def heartbeat(session_id: str, user: User = Depends(get_current_user),
              db: Session = Depends(get_db)) -> ResearchSession:
    """Клиент сообщает, что сессия открыта: продлеваем TTL и аренду."""
    session = get_owned_session(db, session_id, user)
    if session.status is SessionStatus.archived:
        return session
    _keepalive(session.id)
    return touch_session(db, session, action_type="session.heartbeat",
                         action_label="Сессия открыта")


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: str, request: Request,
                   user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)) -> None:
    session = get_owned_session(db, session_id, user)
    info = hard_delete_session(db, session)
    leases.drop(session.id)
    audit(db, action="session.delete", actor=user, target_type="session",
          target_id=session_id, **_meta(request), files=len(info["paths"]))