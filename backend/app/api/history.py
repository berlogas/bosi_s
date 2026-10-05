"""История чата: диалог сессии и быстрые запросы."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_researcher
from app.db.models import User
from app.db.repositories import messages as messages_repo
from app.db.repositories.sessions import ensure_writable
from app.db.repositories.users import audit, get_owned_session, touch_session
from app.db.session import get_db
from app.schemas.api import MessageOut, MessagePage, QuickQueryRequest

router = APIRouter(prefix="/api/chat", tags=["chat"],
                   dependencies=[Depends(require_researcher)])


@router.get("/quick-history", response_model=MessagePage)
def quick_history(user: User = Depends(get_current_user),
                  db: Session = Depends(get_db),
                  limit: int = 50) -> MessagePage:
    """История быстрых запросов пользователя (без создания сессии)."""
    limit = max(1, min(limit, 200))
    items = list(reversed(messages_repo.list_quick_messages(db, user.id, limit=limit)))
    return MessagePage(messages=[_out(m) for m in items], total=len(items))


@router.get("/messages", response_model=MessagePage)
def session_history(session_id: str, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db),
                    limit: int = 200, offset: int = 0) -> MessagePage:
    """История диалога сессии — часть «точки возврата»."""
    session = get_owned_session(db, session_id, user)
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    items = messages_repo.list_messages(db, session.id, limit=limit, offset=offset)
    return MessagePage(
        messages=[_out(m) for m in items],
        total=messages_repo.count_messages(db, session.id),
        offset=offset,
    )


@router.delete("/messages", status_code=status.HTTP_204_NO_CONTENT)
def clear_history(session_id: str, request: Request,
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)) -> None:
    """Очистить историю диалога сессии (документы и заметки не трогаем)."""
    session = get_owned_session(db, session_id, user)
    ensure_writable(session)
    removed = messages_repo.delete_messages(db, session.id)
    touch_session(db, session, action_type="chat.cleared",
                  action_label=f"История очищена ({removed})")
    audit(db, action="chat.history_clear", actor=user, target_type="session",
          target_id=session.id, removed=removed)


@router.delete("/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_history_message(message_id: str, request: Request,
                           user: User = Depends(get_current_user),
                           db: Session = Depends(get_db)) -> None:
    """Удалить сообщение переписки вместе с парой.

    Кнопка в интерфейсе одна на пару: удаляет вопрос и ответ целиком,
    независимо от того, у какого из них нажали. Вопрос без ответа и
    ответ без вопроса бесполезны, поэтому «половинки» не оставляем.
    Остальную историю и документы не трогаем.
    """
    removed = messages_repo.delete_message(db, message_id, user_id=user.id)
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Сообщение не найдено")
    audit(db, action="chat.message_delete", actor=user, target_type="message",
          target_id=message_id, ip=_ip(request), removed=removed)


@router.post("/quick-message", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
def save_quick_message(payload: QuickQueryRequest,
                       user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)) -> MessageOut:
    """Дописать заметку в историю быстрых запросов (без генерации)."""
    message = messages_repo.add_message(
        db, user_id=user.id, content=payload.query, role="user")
    messages_repo.trim_quick_history(db, user.id)
    return _out(message)


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _out(message: Any) -> MessageOut:
    return MessageOut(
        id=message.id,
        session_id=message.session_id,
        role=message.role,
        content=message.content,
        mode=getattr(message.mode, "value", None),
        sources=list(message.sources or []),
        duration_seconds=message.duration_seconds,
        created_at=message.created_at,
    )