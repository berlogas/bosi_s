"""Репозитории: пользователи, аудит, сессии."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.errors import ConflictError, NotFoundError
from app.db.models import (
    AuditLog,
    Document,
    RefreshToken,
    ResearchSession,
    Role,
    SessionStatus,
    User,
    new_id,
    utcnow,
)


# --------------------------------------------------------------------------- users
def get_user_by_username(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == username))


def get_user(db: Session, user_id: str) -> User | None:
    return db.get(User, user_id)


def create_user(
    db: Session,
    *,
    username: str,
    password: str,
    role: Role = Role.researcher,
    email: str | None = None,
    full_name: str | None = None,
    hashed_password: str,
) -> User:
    if get_user_by_username(db, username):
        raise ConflictError(f"Пользователь «{username}» уже существует")
    user = User(
        username=username,
        email=email,
        full_name=full_name,
        hashed_password=hashed_password,
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def save_refresh_token(db: Session, user_id: str, token_hash: str,
                       expires_at: datetime) -> RefreshToken:
    record = RefreshToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
    db.add(record)
    db.commit()
    return record


def rotate_refresh_token(db: Session, token_hash: str) -> RefreshToken:
    record = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if record is None or record.revoked_at is not None:
        raise NotFoundError("Refresh-токен не найден или отозван")
    if record.expires_at < datetime.now(UTC):
        raise NotFoundError("Срок действия refresh-токена истёк")
    record.revoked_at = utcnow()
    db.commit()
    return record


def revoke_refresh_token(db: Session, token_hash: str) -> None:
    record = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if record and record.revoked_at is None:
        record.revoked_at = utcnow()
        db.commit()


# --------------------------------------------------------------------------- sessions
def create_research_session(db: Session, user: User, title: str) -> ResearchSession:
    settings = get_settings()
    active = db.scalar(
        select(func.count())
        .select_from(ResearchSession)
        .where(
            ResearchSession.user_id == user.id,
            ResearchSession.status != SessionStatus.archived,
            ResearchSession.purged_at.is_(None),
        )
    )
    if (active or 0) >= settings.max_sessions_per_user:
        raise ConflictError(
            f"Достигнут лимит: не более {settings.max_sessions_per_user} сессий",
            meta={"limit": settings.max_sessions_per_user},
        )
    now = utcnow()
    session = ResearchSession(
        user_id=user.id,
        title=title.strip()[:255] or "Без названия",
        status=SessionStatus.active,
        last_activity_at=now,
        expires_at=now + timedelta(days=settings.session_ttl_days),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def touch_session(db: Session, session: ResearchSession, *, action_type: str | None = None,
                  action_label: str | None = None, note: str | None = None,
                  snapshot: dict[str, Any] | None = None) -> ResearchSession:
    """Продлевает TTL и обновляет точку возврата (вызывается heartbeat-ом)."""
    settings = get_settings()
    now = utcnow()
    session.last_activity_at = now
    session.expires_at = now + timedelta(days=settings.session_ttl_days)
    if action_type:
        session.last_action_type = action_type
        session.last_action_label = action_label or action_type
        session.last_action_at = now
    if note is not None:
        session.resume_note = note
    if snapshot is not None:
        session.state_snapshot = snapshot
    db.commit()
    return session


def list_user_sessions(db: Session, user_id: str) -> list[ResearchSession]:
    return list(
        db.scalars(
            select(ResearchSession)
            .where(ResearchSession.user_id == user_id,
                   ResearchSession.purged_at.is_(None))
            .order_by(ResearchSession.last_activity_at.desc())
        )
    )


def get_owned_session(db: Session, session_id: str, user: User) -> ResearchSession:
    """Доступ только к собственной сессии; админ видит все (аудит)."""
    session = db.get(ResearchSession, session_id)
    if session is None or session.purged_at is not None:
        raise NotFoundError("Сессия не найдена")
    if session.user_id != user.id and user.role != Role.admin:
        raise NotFoundError("Сессия не найдена")
    return session


def expire_due_sessions(db: Session) -> list[str]:
    """Архивирует сессии, у которых истёк TTL (Фаза 5: reaper)."""
    now = utcnow()
    due = list(
        db.scalars(
            select(ResearchSession).where(
                ResearchSession.expires_at < now,
                ResearchSession.status != SessionStatus.archived,
                ResearchSession.purged_at.is_(None),
            )
        )
    )
    for session in due:
        session.status = SessionStatus.archived
        session.archived_at = now
    db.commit()
    return [s.id for s in due]


# --------------------------------------------------------------------------- documents
def count_session_documents(db: Session, session_id: str) -> int:
    return len(list(db.scalars(select(Document).where(Document.session_id == session_id))))


def session_storage_bytes(db: Session, session_id: str) -> int:
    docs = db.scalars(select(Document).where(Document.session_id == session_id))
    return sum(d.size_bytes or 0 for d in docs)


def audit(
    db: Session,
    *,
    action: str,
    actor: User | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    ok: bool = True,
    **meta: Any,
) -> AuditLog:
    entry = AuditLog(
        id=new_id(),
        actor_user_id=actor.id if actor else None,
        actor_username=actor.username if actor else None,
        action=action,
        target_type=target_type,
        target_id=target_id,
        ip=ip,
        user_agent=user_agent,
        ok=ok,
        meta=meta,
    )
    db.add(entry)
    db.commit()
    return entry