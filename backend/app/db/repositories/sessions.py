"""Жизненный цикл исследовательской сессии (Фаза 5).

Содержит операции состояния, которых нет в `users.py` (создание и касание
сессии живут там, потому что на них завязаны существующие тесты):

  * автосохранение состояния — «точка возврата»;
  * пауза / архивирование / реактивация;
  * «только чтение» для архивных сессий;
  * purge архивов по retention-политике (N дней после архивации);
  * сводка сессии для дашборда.
"""

from __future__ import annotations

from datetime import timedelta
from math import ceil
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.errors import ConflictError
from app.db.models import (
    Document,
    DocumentLink,
    Message,
    ResearchSession,
    SessionStatus,
    utcnow,
)
from app.db.repositories.users import touch_session

STATE_META_KEY = "saved_at"

WRITABLE_STATUSES = (SessionStatus.active, SessionStatus.paused)


# --------------------------------------------------------------------------- статус
def ensure_writable(session: ResearchSession) -> ResearchSession:
    """Архивная сессия — только чтение (ТЗ: reaper архивирует и закрывает)."""
    if session.status not in WRITABLE_STATUSES:
        raise ConflictError(
            f"Сессия в статусе «{session.status.value}» — доступно только чтение",
            meta={"session_id": session.id, "status": session.status.value},
        )
    return session


def pause_session(db: Session, session: ResearchSession,
                  note: str | None = None) -> ResearchSession:
    """Пауза с заметкой: сессия остаётся открытой, но закреплена пользователем."""
    ensure_writable(session)
    session.status = SessionStatus.paused
    db.commit()
    return touch_session(db, session, action_type="session.paused",
                         action_label="Пауза с заметкой", note=note)


def archive_session(db: Session, session: ResearchSession,
                    note: str | None = None) -> ResearchSession:
    """Ручная архивация — то же состояние, что ставит reaper по TTL."""
    session.status = SessionStatus.archived
    session.archived_at = utcnow()
    session.resume_note = note if note is not None else session.resume_note
    db.commit()
    return session


def reactivate_session(db: Session, session: ResearchSession) -> ResearchSession:
    if session.status is SessionStatus.archived:
        raise ConflictError(
            "Сессия архивирована по TTL и восстановлению не подлежит. "
            "Начните новую сессию — документы и заметки остаются в архиве.",
            meta={"session_id": session.id, "status": SessionStatus.archived.value},
        )
    if session.status is SessionStatus.paused:
        session.status = SessionStatus.active
        db.commit()
    return touch_session(db, session, action_type="session.resumed",
                         action_label="Возврат к работе")


# --------------------------------------------------------------------------- состояние
def save_state(
    db: Session,
    session: ResearchSession,
    *,
    snapshot: dict[str, Any] | None = None,
    note: str | None = None,
    action_type: str | None = None,
    action_label: str | None = None,
    force: bool = False,
) -> tuple[ResearchSession, bool]:
    """Автосохранение «точки возврата».

    Снапшот merges-ится в `session.state_snapshot`. Если содержимое не изменилось
    — запись не делается (дебаунс на стороне клиента плюс дедупликация здесь),
    и возвращается ``False``.
    """
    if snapshot is None and note is None and action_type is None:
        return session, False

    if snapshot is not None:
        current = {k: v for k, v in (session.state_snapshot or {}).items()
                   if k != STATE_META_KEY}
        if current == snapshot and not force:
            # состояние не изменилось — продлеваем TTL, но не пишем снапшот
            touch_session(db, session, action_type=action_type,
                          action_label=action_label, note=note)
            return session, False
        merged = dict(snapshot)
        merged[STATE_META_KEY] = utcnow().isoformat()
        session.state_snapshot = merged

    touch_session(db, session, action_type=action_type, action_label=action_label,
                  note=note)
    return session, True


def state_snapshot(session: ResearchSession) -> dict[str, Any]:
    """Снапшот без служебного поля `saved_at`."""
    return {k: v for k, v in (session.state_snapshot or {}).items()
            if k != STATE_META_KEY}


def state_saved_at(session: ResearchSession) -> str | None:
    return (session.state_snapshot or {}).get(STATE_META_KEY)


# --------------------------------------------------------------------------- purge
def purge_expired_archives(db: Session, *, retention_days: int | None = None
                           ) -> list[dict[str, Any]]:
    """Очистить архивы старше retention-политики.

    Строка сессии остаётся как tombstone (`purged_at` — «снесено, в выдаче нет»),
    но пользовательские данные удаляются: документы (каскадом и связи),
    сообщения и файлы. Файлы и чанки чистит вызывающий — здесь отдаём пути.
    """
    from app.db.repositories.documents import session_document_paths

    days = retention_days if retention_days is not None else get_settings().archive_retention_days
    cutoff = utcnow() - timedelta(days=days)
    due = list(db.scalars(
        select(ResearchSession).where(
            ResearchSession.status == SessionStatus.archived,
            ResearchSession.archived_at.is_not(None),
            ResearchSession.archived_at <= cutoff,
            ResearchSession.purged_at.is_(None),
        )))
    purged: list[dict[str, Any]] = []
    now = utcnow()
    for session in due:
        paths = session_document_paths(db, session.id)
        documents = list(db.scalars(
            select(Document).where(Document.session_id == session.id)))
        for document in documents:
            db.delete(document)  # document_links уйдут каскадом
        for message in db.scalars(
                select(Message).where(Message.session_id == session.id)):
            db.delete(message)
        session.purged_at = now
        purged.append({
            "session_id": session.id,
            "user_id": session.user_id,
            "title": session.title,
            "paths": paths,
            "documents": len(documents),
        })
    db.commit()
    return purged


def hard_delete_session(db: Session, session: ResearchSession) -> dict[str, Any]:
    """Полное удаление сессии (владелец явно нажал «удалить»)."""
    from app.db.repositories.documents import session_document_paths

    info = {
        "session_id": session.id,
        "paths": session_document_paths(db, session.id),
    }
    db.delete(session)
    db.commit()
    return info


# --------------------------------------------------------------------------- сводка
def session_summary(db: Session, session: ResearchSession) -> dict[str, Any]:
    """Счётчики для карточки сессии на дашборде."""
    from app.db.repositories import documents as docs_repo

    session_id = session.id
    messages = int(db.scalar(
        select(func.count()).select_from(Message)
        .where(Message.session_id == session_id))) or 0
    links = int(db.scalar(
        select(func.count()).select_from(DocumentLink)
        .where(DocumentLink.session_id == session_id))) or 0
    document_stats = docs_repo.documents_summary(db, session_id)
    settings = get_settings()
    return {
        "documents": document_stats["total"],
        "documents_by_category": document_stats["by_category"],
        "storage_bytes": document_stats["storage_bytes"],
        "storage_limit_bytes": settings.max_session_storage_mb * 1024 * 1024,
        "documents_limit": settings.max_documents_per_session,
        "projects": docs_repo.count_projects(db, session_id),
        "projects_limit": settings.max_projects_per_session,
        "messages": messages,
        "links": links,
        "read_only": session.status not in WRITABLE_STATUSES,
    }


def days_left(session: ResearchSession) -> int:
    """Сколько дней осталось до истечения TTL (для индикатора в UI).

    Округление вверх: пока не прошёл весь день, «остался ещё день» — так
    индикатор не показывает 0 на последних сутках.
    """
    delta = session.expires_at - utcnow()
    return max(0, ceil(delta.total_seconds() / 86400))