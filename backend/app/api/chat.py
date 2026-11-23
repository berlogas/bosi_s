"""Чат: RAG-fusion по сессии и быстрый запрос по глобальной базе (Фаза 6).

  POST /api/chat/query          — синхронный ответ с источниками 📚 (скрипты, тесты)
  POST /api/chat/query-async    — фоновый вопрос по сессии: task_id + опрос
  POST /api/chat/quick-query   — быстрый вопрос по глобальной базе, тоже фоном
  GET  /api/chat/suggest-queries — уточняющие вопросы

Маршруты `/api/chat/messages`, `/quick-history`, `/quick-message` живут в
`app/api/history.py`.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
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
    SuggestionsResponse,
)
from app.services.pqa_registry import get_registry
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
            token_counts=result.answer.token_counts,
            checks=result.checks)

    touch_session(db, session, action_type="chat",
                  action_label=f"Вопрос: {payload.query[:60]}",
                  snapshot={"tab": "chat"})
    audit(db, action="chat.query", actor=user, target_type="session",
          target_id=session.id, ip=_ip(request), mode=payload.mode.value,
          sources=len(result.sources), from_cache=result.from_cache,
          seconds=result.answer.seconds)
    leases.touch(session.id, 600)

    # Сохранить отчёт о цитировании для эндпоинта /api/citation-report
    citations = result.stats.get("citations") if result.stats else None
    if citations:
        get_registry().set_citation_report(citations)

    return ChatQueryResponse(
        answer=result.answer.formatted_answer,
        sources=result.sources, references=result.references,
        mode=payload.mode, query=payload.query,
        from_cache=result.from_cache, stats=result.stats,
        base_empty=result.answer.base_empty)


@router.post("/stream")
async def chat_stream(
    payload: ChatQueryRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Стриминг ответа по токенам через SSE.

    Отправляет текст ответа фрагментами по мере генерации LLM.
    Формат: `data: {"token": "..."}\n\n`, в конце `data: [DONE]\n\n`.

    Любая ошибка (включая до первого байта потока) возвращается как
    SSE-сообщение `data: {"error": ...}`, а не как HTTP 500, чтобы браузер
    мог прочитать её через EventSource / fetch + читатель потока.
    """
    sse_headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }

    async def error_stream(message: str) -> AsyncIterator[str]:
        yield f'data: {json.dumps({"error": message})}\n\n'
        yield 'data: [DONE]\n\n'

    try:
        if not payload.session_id:
            return StreamingResponse(
                error_stream("session_id обязателен для chat/stream"),
                media_type="text/event-stream",
                headers=sse_headers,
            )
        session = get_owned_session(db, payload.session_id, user)
        ensure_writable(session)

        service = get_registry().global_service()

        async def token_generator() -> AsyncIterator[str]:
            # 1. Ищем контекст (чанки) без генерации ответа
            try:
                chunks, _ = await service.get_evidence(
                    payload.query,
                    k=payload.k or 10,
                )
            except Exception as exc:
                yield f'data: {json.dumps({"error": str(exc)})}\n\n'
                yield 'data: [DONE]\n\n'
                return
            if not chunks:
                message = json.dumps(
                    {"token": "Не найдено подходящих источников в базе знаний."})
                yield f"data: {message}\n\n"
                yield 'data: [DONE]\n\n'
                return

            # 2. Формируем промпт с контекстом
            context_parts = []
            for i, chunk in enumerate(chunks[:payload.max_sources or 5], start=1):
                context_parts.append(f"[{i}] {chunk.text}")
            context_text = "\n\n".join(context_parts)

            prompt = (
                "Ответь на вопрос пользователя, используя ТОЛЬКО информацию из "
                "контекста ниже. Каждое утверждение снабжай ссылкой на источник "
                "в формате [n], где n — номер источника из контекста. "
                "Если информации недостаточно, скажи об этом честно.\n\n"
                f"КОНТЕКСТ:\n{context_text}\n\n"
                f"ВОПРОС: {payload.query}\n\n"
                "ОТВЕТ:"
            )

            # 3. Стримим ответ по токенам
            try:
                async for token in service.stream_complete(prompt, name="chat_stream"):
                    yield f'data: {json.dumps({"token": token})}\n\n'
            except Exception as exc:  # нетокенная ошибка — передаём как SSE-ошибку
                yield f'data: {json.dumps({"error": str(exc)})}\n\n'
            finally:
                yield 'data: [DONE]\n\n'

        return StreamingResponse(
            token_generator(),
            media_type="text/event-stream",
            headers=sse_headers,
        )
    except Exception as exc:
        log.exception("Ошибка при создании стрима чата")
        return StreamingResponse(
            error_stream(str(exc)),
            media_type="text/event-stream",
            headers=sse_headers,
        )

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
        # прогресс по этапам: поиск -> rerank -> LLM -> проверки -> сохранение.
        # Этапы внутри fusion передаются колбэком on_stage=task.set_stage:
        # без них строка прогресса замирает на 20%, пока LLM считает ответ.
        task.set_stage(20, "поиск по глобальной базе и сессии")
        fusion = RagFusionService()
        result = await fusion.answer(
            db, query=payload.query, session_id=session.id, mode=payload.mode,
            k=payload.k or 10, max_sources=payload.max_sources or 5,
            use_cache=not payload.no_cache, on_stage=task.set_stage)
        task.set_stage(95, "сохранение ответа")
        messages_repo.save_exchange(
            db, user=user, question=payload.query,
            answer=result.answer.formatted_answer, session_id=session.id,
            mode=payload.mode, sources=result.sources,
            cost=result.answer.cost, duration_seconds=result.answer.seconds,
            token_counts=result.answer.token_counts,
            checks=result.checks)
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


@router.post("/quick-query")
async def quick_query(payload: QuickQueryRequest, request: Request,
                      user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)) -> dict[str, Any]:
    """Быстрый вопрос по глобальной базе — фоновой задачей, без сессии.

    Отдаёт task_id, UI опрашивает `/api/tasks/{id}`. Ответ лежит в
    `Task.result`: answer, sources, references, query, from_cache, stats,
    base_empty — и дописывается в историю быстрых запросов.
    """
    from app.services.tasks import Task, tasks

    # Маршрут был синхронным, и на CPU-инференсе это выглядело как зависание:
    # ответ считается минуты, а UI показывал только спиннер — без этапов, без
    # отмены и без возможности уйти со вкладки и вернуться. Теперь путь тот
    # же, что у вопроса по сессии (`POST /query-async`).
    async def body(task: Task) -> dict[str, Any]:
        # Этапы приходят колбэком on_stage: без них строка прогресса замирает
        # на 20%, пока LLM считает ответ.
        task.set_stage(20, "поиск по глобальной базе")
        fusion = RagFusionService()
        result = await fusion.answer(
            db, query=payload.query, session_id=None,
            mode=SearchMode.global_only, k=payload.k or 10,
            max_sources=payload.max_sources or 5,
            use_cache=not payload.no_cache, on_stage=task.set_stage)

        if not result.from_cache:
            task.set_stage(95, "сохранение в историю")
            messages_repo.save_exchange(
                db, user=user, question=payload.query,
                answer=result.answer.formatted_answer, session_id=None,
                mode=SearchMode.global_only, sources=result.sources,
                cost=result.answer.cost, duration_seconds=result.answer.seconds,
                token_counts=result.answer.token_counts,
                checks=result.checks)
            messages_repo.trim_quick_history(db, user.id)

        audit(db, action="chat.quick_query", actor=user, target_type="collection",
              target_id="global", ip=_ip(request), sources=len(result.sources),
              from_cache=result.from_cache, seconds=result.answer.seconds)

        return {
            "answer": result.answer.formatted_answer,
            "sources": result.sources,
            "references": result.references,
            "query": payload.query,
            "from_cache": result.from_cache,
            "stats": result.stats,
            "base_empty": result.answer.base_empty,
        }

    task = tasks.submit(body, kind="chat",
                        title=f"Быстрый вопрос: {payload.query[:50]}",
                        user_id=user.id)
    audit(db, action="chat.quick_query_async", actor=user,
          target_type="collection", target_id="global", ip=_ip(request),
          task=task.id)
    return {"task_id": task.id}


@router.get("/suggest-queries", response_model=SuggestionsResponse)
async def suggest_queries(query: str,
                          user: User = Depends(get_current_user)) -> SuggestionsResponse:
    """3–5 уточняющих вопросов (генерация LLM; при отказе — пустой список)."""
    suggestions = await RagFusionService().suggest_queries(query)
    return SuggestionsResponse(suggestions=suggestions, query=query)


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None