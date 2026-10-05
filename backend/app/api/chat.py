"""Чат: RAG-fusion по сессии и быстрый запрос по глобальной базе (Фаза 6).

  POST /api/chat/query         — ответ с источниками 📚 (глобальная) / 📁 (сессия)
  POST /api/chat/quick-query   — только глобальная база, без создания сессии
  GET  /api/chat/suggest-queries — уточняющие вопросы

Маршруты `/api/chat/messages`, `/quick-history`, `/quick-message` живут в
`app/api/history.py`.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.leases import leases
from app.core.security import get_current_user, require_researcher
from app.db.models import SearchMode, User
from app.db.repositories import messages as messages_repo
from app.db.repositories.sessions import ensure_writable
from app.db.repositories.users import audit, get_owned_session, touch_session
from app.db.session import get_db
from app.schemas.api import (
    ChatQueryRequest,
    ChatQueryResponse,
    QuickQueryRequest,
    QuickQueryResponse,
    SuggestionsResponse,
)
from app.services.rag_service import RagFusionService

log = logging.getLogger("boasi.api.chat")

router = APIRouter(prefix="/api/chat", tags=["chat"],
                   dependencies=[Depends(require_researcher)])


@router.post("/query", response_model=ChatQueryResponse)
async def chat_query(payload: ChatQueryRequest, request: Request,
                     user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)) -> ChatQueryResponse:
    if not payload.session_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "session_id обязателен для chat/query")
    session = get_owned_session(db, payload.session_id, user)
    ensure_writable(session)  # архивная сессия — только чтение

    fusion = RagFusionService()
    result = await fusion.answer(
        db, query=payload.query, session_id=session.id, mode=payload.mode,
        k=payload.k or 10, max_sources=payload.max_sources or 5,
        use_cache=not payload.no_cache)

    if not result.from_cache:
        messages_repo.save_exchange(
            db, user=user, question=payload.query,
            answer=result.answer.formatted_answer,
            session_id=session.id, mode=payload.mode, sources=result.sources,
            cost=result.answer.cost, duration_seconds=result.answer.seconds,
            token_counts=result.answer.token_counts)

    touch_session(db, session, action_type="chat",
                  action_label=f"Вопрос: {payload.query[:60]}",
                  snapshot={"tab": "chat"})
    audit(db, action="chat.query", actor=user, target_type="session",
          target_id=session.id, ip=_ip(request), mode=payload.mode.value,
          sources=len(result.sources), from_cache=result.from_cache,
          seconds=result.answer.seconds)
    leases.touch(session.id, 600)

    return ChatQueryResponse(
        answer=result.answer.formatted_answer,
        sources=result.sources, references=result.references,
        mode=payload.mode, query=payload.query,
        from_cache=result.from_cache, stats=result.stats,
        base_empty=result.answer.base_empty)


@router.post("/query-async")
async def chat_query_async(payload: ChatQueryRequest, request: Request,
                           user: User = Depends(get_current_user),
                           db: Session = Depends(get_db)) -> dict[str, Any]:
    """Фоновый вопрос: отдаём task_id, UI опрашивает /api/tasks/{id}.

    На dev-машине ответ занимает минуты, поэтому синхронный POST /query
    (он остаётся для скриптов и тестов) дополняется фоновым режимом.
    """
    from app.services.tasks import Task, tasks

    if not payload.session_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "session_id обязателен для chat/query")
    session = get_owned_session(db, payload.session_id, user)
    ensure_writable(session)

    async def body(task: Task) -> dict[str, Any]:
        # прогресс по этапам: поиск по коллекциям -> rerank -> генерация
        task.step = "поиск по глобальной базе и сессии"
        task.progress = 20
        fusion = RagFusionService()
        result = await fusion.answer(
            db, query=payload.query, session_id=session.id, mode=payload.mode,
            k=payload.k or 10, max_sources=payload.max_sources or 5,
            use_cache=not payload.no_cache)
        task.progress = 100
        task.step = "готово"
        messages_repo.save_exchange(
            db, user=user, question=payload.query,
            answer=result.answer.formatted_answer, session_id=session.id,
            mode=payload.mode, sources=result.sources,
            cost=result.answer.cost, duration_seconds=result.answer.seconds,
            token_counts=result.answer.token_counts)
        touch_session(db, session, action_type="chat",
                      action_label=f"Вопрос: {payload.query[:60]}",
                      snapshot={"tab": "chat"})
        leases.touch(session.id, 600)
        return {
            "answer": result.answer.formatted_answer,
            "sources": result.sources,
            "references": result.references,
            "from_cache": result.from_cache,
            "stats": result.stats,
            "base_empty": result.answer.base_empty,
        }

    task = tasks.submit(body, kind="chat",
                        title=f"Вопрос: {payload.query[:50]}",
                        user_id=user.id, session_id=session.id)
    audit(db, action="chat.query_async", actor=user, target_type="session",
          target_id=session.id, ip=_ip(request), task=task.id,
          mode=payload.mode.value)
    return {"task_id": task.id}


@router.post("/quick-query", response_model=QuickQueryResponse)
async def quick_query(payload: QuickQueryRequest, request: Request,
                      user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)) -> QuickQueryResponse:
    """Быстрый вопрос по глобальной базе — без создания сессии."""
    fusion = RagFusionService()
    result = await fusion.answer(
        db, query=payload.query, session_id=None,
        mode=SearchMode.global_only, k=payload.k or 10,
        max_sources=payload.max_sources or 5, use_cache=not payload.no_cache)

    if not result.from_cache:
        messages_repo.save_exchange(
            db, user=user, question=payload.query,
            answer=result.answer.formatted_answer, session_id=None,
            mode=SearchMode.global_only, sources=result.sources,
            cost=result.answer.cost, duration_seconds=result.answer.seconds,
            token_counts=result.answer.token_counts)
        messages_repo.trim_quick_history(db, user.id)

    audit(db, action="chat.quick_query", actor=user, target_type="collection",
          target_id="global", ip=_ip(request), sources=len(result.sources),
          from_cache=result.from_cache, seconds=result.answer.seconds)

    return QuickQueryResponse(
        answer=result.answer.formatted_answer, sources=result.sources,
        references=result.references, query=payload.query,
        from_cache=result.from_cache, stats=result.stats,
        base_empty=result.answer.base_empty)


@router.get("/suggest-queries", response_model=SuggestionsResponse)
async def suggest_queries(query: str,
                          user: User = Depends(get_current_user)) -> SuggestionsResponse:
    """3–5 уточняющих вопросов (генерация LLM; при отказе — пустой список)."""
    suggestions = await RagFusionService().suggest_queries(query)
    return SuggestionsResponse(suggestions=suggestions, query=query)


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None