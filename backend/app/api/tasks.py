"""Фоновые задачи: статус, прогресс, отмена (Фаза 8).

UI не должен висеть спиннером минутами — он спрашивает здесь статус и может
отменить операцию.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.security import get_current_user, require_researcher
from app.db.models import User
from app.db.session import get_db
from app.services.tasks import Task, TaskStatus, tasks

router = APIRouter(prefix="/api/tasks", tags=["tasks"],
                   dependencies=[Depends(require_researcher)])


def _own(task: Task, user: User) -> Task:
    """Задача видна автору и админу; остальным — как несуществующая."""
    if task.user_id and task.user_id != user.id and user.role.value != "admin":
        raise NotFoundError("Задача не найдена")
    return task


@router.get("")
def list_tasks(user: User = Depends(get_current_user),
               limit: int = 20, session_id: str | None = None,
               active_only: bool = False) -> dict[str, Any]:
    found = tasks.list(user_id=None if user.role.value == "admin" else user.id,
                       session_id=session_id, limit=max(1, min(limit, 100)))
    if active_only:
        found = [t for t in found if not t.finished]
    return {"tasks": [t.to_dict() for t in found],
            "active": sum(1 for t in found if not t.finished)}


@router.get("/{task_id}")
def get_task(task_id: str, user: User = Depends(get_current_user)) -> dict[str, Any]:
    task = tasks.get(task_id)
    if task is None:
        raise NotFoundError("Задача не найдена")
    return _own(task, user).to_dict()


@router.post("/{task_id}/cancel")
def cancel_task(task_id: str, request: Request,
                user: User = Depends(get_current_user),
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
def clear_finished(user: User = Depends(get_current_user)) -> None:
    if user.role.value != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Доступно только администратору")
    tasks.clear_finished()


@router.get("/health")
def tasks_health() -> dict[str, Any]:
    return {"active": tasks.active_count(),
            "total": len(tasks.list(limit=1000)),
            "statuses": [s.value for s in TaskStatus]}