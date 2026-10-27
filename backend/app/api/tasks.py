"""Фоновые задачи: статус, прогресс, отмена (Фаза 8).

UI не должен висеть спиннером минутами — он спрашивает здесь статус и может
отменить операцию.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.security import require_researcher, require_researcher_sse
from app.db.models import User
from app.db.session import get_db
from app.services.tasks import Task, TaskStatus, event_manager, tasks

# Роутер БЕЗ общего require_researcher: у /events свой барьер
# (require_researcher_sse — авторизация query-токеном для EventSource),
# остальные маршруты декларируют роль явно в сигнатуре.
router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _own(task: Task, user: User) -> Task:
    """Задача видна автору и админу; остальным — как несуществующая."""
    if task.user_id and task.user_id != user.id and user.role.value != "admin":
        raise NotFoundError("Задача не найдена")
    return task


@router.get("")
def list_tasks(user: User = Depends(require_researcher),
               limit: int = 20, session_id: str | None = None,
               active_only: bool = False) -> dict[str, Any]:
    found = tasks.list(user_id=None if user.role.value == "admin" else user.id,
                       session_id=session_id, limit=max(1, min(limit, 100)))
    if active_only:
        found = [t for t in found if not t.finished]
    return {"tasks": [t.to_dict() for t in found],
            "active": sum(1 for t in found if not t.finished)}


# Статические пути — строго ДО /{task_id}: Starlette матчит по порядку
# регистрации, иначе /events и /health пожирает get_task (404 «Задача не
# найдена» вместо потока).


@router.get("/health")
def tasks_health(user: User = Depends(require_researcher)) -> dict[str, Any]:
    return {"active": tasks.active_count(),
            "total": len(tasks.list(limit=1000)),
            "statuses": [s.value for s in TaskStatus]}


async def _task_event_stream(user_id: str, last_seq: int | None = None) -> AsyncIterator[str]:
    """Бесконечный поток событий задач одного пользователя.

    Завершение одной задачи не повод закрывать канал: при двух параллельных
    задачах события по второй терялись — EventSource на клиенте закрывался
    после первого `finished`, а сервер обрывал поток тем же break.
    Keep-alive раз в 15 с не даёт прокси принять молчание за обрыв.

    `last_seq` — seq последнего полученного события (из заголовка
    `Last-Event-ID`). Если задан, сначала отсылаем пропущенные события
    из буфера, а потом переходим к реальному времени.
    """
    queue = await event_manager.subscribe(user_id)
    # При переподключении после обрыва отсылаем пропущенные события из буфера.
    if last_seq is not None:
        missed = await event_manager.get_events_since(user_id, last_seq)
        for task in missed:
            data = task.to_dict()
            yield f"id: {task.seq}\ndata: {json.dumps(data, default=str)}\n\n"
    try:
        while True:
            try:
                task = await asyncio.wait_for(queue.get(), timeout=15.0)
            except TimeoutError:
                yield ": keep-alive\n\n"
                continue
            data = task.to_dict()
            yield f"id: {task.seq}\ndata: {json.dumps(data, default=str)}\n\n"
    except asyncio.CancelledError:
        pass
    finally:
        # Только своя очередь: при переподключении EventSource старая
        # генератор не должна снимать новую подписку.
        await event_manager.unsubscribe(user_id, queue)


@router.get("/events")
async def task_events(user: User = Depends(require_researcher_sse),
                      request: Request = None) -> StreamingResponse:
    """SSE-канал для live-прогресса задач вместо поллинга.

    Подключение: `GET /api/tasks/events` с заголовком `Accept: text/event-stream`.
    События приходят в реальном времени при изменении статуса задач.

    Браузерный EventSource не умеет задавать HTTP-заголовки, поэтому токен
    разрешено передавать в query: `?access_token=...`. Это единственный
    маршрут, принимающий токен из query, — заголовок тоже поддерживается.

    `Last-Event-ID` — seq последнего полученного события. При переподключении
    сервер пришлёт пропущенные события из буфера.
    """
    last_seq = None
    if request is not None:
        last_event_id = request.headers.get("last-event-id")
        if last_event_id:
            try:
                last_seq = int(last_event_id)
            except ValueError:
                last_seq = None

    return StreamingResponse(
        _task_event_stream(user.id, last_seq),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{task_id}")
def get_task(task_id: str, user: User = Depends(require_researcher)) -> dict[str, Any]:
    task = tasks.get(task_id)
    if task is None:
        raise NotFoundError("Задача не найдена")
    return _own(task, user).to_dict()


@router.post("/{task_id}/cancel")
def cancel_task(task_id: str, request: Request,
                user: User = Depends(require_researcher),
                db: Session = Depends(get_db)) -> dict[str, Any]:
    """Попросить отменить задачу. Отмена кооперативная, на ближайшем await."""
    task = tasks.get(task_id)
    if task is None:
        raise NotFoundError("Задача не найдена")
    _own(task, user)

    cancelled = tasks.request_cancel(task_id)
    from app.db.repositories.users import audit

    audit(db, action="task.cancel", actor=user, target_type="task",
          target_id=task_id,
          ip=request.client.host if request.client else None,
          kind=task.kind, cancelled=cancelled)
    return {"cancelled": cancelled, "task": task.to_dict()}


@router.post("/clear", status_code=status.HTTP_204_NO_CONTENT)
def clear_finished(user: User = Depends(require_researcher)) -> None:
    if user.role.value != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Доступно только администратору")
    tasks.clear_finished()
