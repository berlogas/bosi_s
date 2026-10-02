"""Репозиторий истории чата (`messages`).

`session_id = NULL` — быстрый запрос по глобальной базе (без сессии),
`session_id = <id>` — диалог внутри сессии. История нужна для «точки возврата»:
после рестарта диалог должен восстановиться вместе с документами и заметками.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, literal_column, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Message, SearchMode, utcnow

# Порядок диалога: `created_at` в SQLite имеет микросекундное разрешение, и
# несколько сообщений часто получают одинаковую метку. Вторичный ключ по UUID
# был бы произвольным, поэтому опираемся на `rowid` — это порядок вставки
# (проект работает на SQLite, см. docs/DECISIONS.md).
_INSERT_ORDER = literal_column("rowid")


def _oldest_first() -> tuple[Any, Any]:
    return Message.created_at, _INSERT_ORDER


def _newest_first() -> tuple[Any, Any]:
    return Message.created_at.desc(), _INSERT_ORDER.desc()


def add_message(
    db: Session,
    *,
    user_id: str,
    content: str,
    role: str = "user",
    session_id: str | None = None,
    mode: SearchMode | None = None,
    sources: list[dict[str, Any]] | None = None,
    project_id: str | None = None,
    cost: float = 0.0,
    duration_seconds: float | None = None,
    token_counts: dict[str, Any] | None = None,
) -> Message:
    """Дописать сообщение в историю (user | assistant | system)."""
    message = Message(
        user_id=user_id,
        session_id=session_id,
        role=role,
        content=content,
        mode=mode,
        sources=sources or [],
        project_id=project_id,
        cost=cost,
        duration_seconds=duration_seconds,
        token_counts=token_counts or {},
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def save_exchange(
    db: Session,
    *,
    user: Any,
    question: str,
    answer: str,
    session_id: str | None = None,
    mode: SearchMode | None = None,
    sources: list[dict[str, Any]] | None = None,
    cost: float = 0.0,
    duration_seconds: float | None = None,
    token_counts: dict[str, Any] | None = None,
) -> tuple[Message, Message]:
    """Сохранить вопрос и ответ одной транзакцией."""
    ask = Message(user_id=user.id, session_id=session_id, role="user",
                  content=question, mode=mode)
    reply = Message(user_id=user.id, session_id=session_id, role="assistant",
                    content=answer, sources=sources or [], mode=mode, cost=cost,
                    duration_seconds=duration_seconds, token_counts=token_counts or {})
    db.add_all([ask, reply])
    db.commit()
    db.refresh(ask)
    db.refresh(reply)
    return ask, reply


def list_messages(
    db: Session,
    session_id: str,
    *,
    limit: int = 200,
    offset: int = 0,
) -> list[Message]:
    return list(db.scalars(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(*_oldest_first())
        .offset(offset)
        .limit(limit)
    ))


def list_quick_messages(db: Session, user_id: str, *, limit: int = 50) -> list[Message]:
    """История быстрых запросов пользователя (session_id IS NULL)."""
    return list(db.scalars(
        select(Message)
        .where(Message.user_id == user_id, Message.session_id.is_(None))
        .order_by(*_newest_first())
        .limit(limit)
    ))


def count_messages(db: Session, session_id: str) -> int:
    return int(db.scalar(
        select(func.count()).select_from(Message)
        .where(Message.session_id == session_id))) or 0


def trim_quick_history(db: Session, user_id: str) -> int:
    """Оставить последние `max_quick_history` записей быстрых запросов."""
    limit = get_settings().max_quick_history
    total = int(db.scalar(
        select(func.count()).select_from(Message)
        .where(Message.user_id == user_id, Message.session_id.is_(None)))) or 0
    if total <= limit:
        return 0

    keep_ids = list(db.scalars(
        select(Message.id)
        .where(Message.user_id == user_id, Message.session_id.is_(None))
        .order_by(*_newest_first())
        .offset(limit)
    ))
    if not keep_ids:
        return 0
    result = db.execute(delete(Message).where(Message.id.in_(keep_ids)))
    db.commit()
    return int(result.rowcount or 0)


def delete_messages(db: Session, session_id: str) -> int:
    result = db.execute(delete(Message).where(Message.session_id == session_id))
    db.commit()
    return int(result.rowcount or 0)


def last_exchange(db: Session, session_id: str) -> tuple[str, str] | None:
    """Последние вопрос и ответ — для восстановления диалога при resume."""
    messages = list(db.scalars(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(*_newest_first())
        .limit(2)
    ))
    if len(messages) < 2:
        return None
    reply, question = messages[0], messages[1]
    if reply.role != "assistant" or question.role != "user":
        return None
    return question.content, reply.content


def touch(db: Session, message: Message) -> Message:
    message.created_at = utcnow()
    db.commit()
    return message


__all__ = [
    "add_message",
    "count_messages",
    "delete_messages",
    "last_exchange",
    "list_messages",
    "list_quick_messages",
    "save_exchange",
    "trim_quick_history",
]