"""Фондовые задачи с прогрессом и отменой (Фаза 8).

На dev-машине ответ занимает минуты (сеть проекта это не оптимизирует), а
Streamlit живёт в HTTP-запросе. Поэтому долгие операции — индексация пачки
документов, вопрос по контексту, генерация раздела — запускаются как фоновые
задачи: UI получает `task_id` и опрашивает статус, вместо того чтобы висеть
спиннером без возможности отмены.

Отмена кооперативная и настоящая: работа идёт как `asyncio.Task`, и
`cancel()` прерывает её на ближайшем await — то есть файлы, уже отданные
индексатору, доезжают, а недобранные не начинаются.

Реестр живёт в памяти процесса: после рестарта незавершённые задачи теряются,
что корректно — их можно поставить заново.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from app.db.models import utcnow

log = logging.getLogger("boasi.services.tasks")

# Долгую задачу без heartbeat считаем упавшей при чтении статуса.
STALE_AFTER_SECONDS = 3600


class TaskStatus(str, Enum):
    queued = "queued"
    running = "running"
    done = "done"
    error = "error"
    cancelled = "cancelled"


@dataclass
class Task:
    id: str
    kind: str
    title: str
    user_id: str | None = None
    session_id: str | None = None
    project_id: str | None = None
    status: TaskStatus = TaskStatus.queued
    progress: int = 0
    step: str = "в очереди"
    # Секундомер текущего этапа: UI показывает «3:12» рядом с процентами,
    # иначе при долгой LLM строка прогресса замирает на одних и тех же
    # числах и выглядит как зависшая.
    stage_started_at: float = field(default_factory=time.monotonic,
                                    repr=False, compare=False)
    result: Any = None
    error: str | None = None
    cancel_requested: bool = False
    created_at: datetime = field(default_factory=utcnow)
    # Монотонный номер: метки времени совпадают в пределах микросекунды,
    # а порядок задач в UI должен быть однозначным.
    seq: int = field(default=0, repr=False, compare=False)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    _handle: asyncio.Task | None = field(default=None, repr=False, compare=False)
    _stage_ended_at: float | None = field(default=None, repr=False,
                                          compare=False)

    @property
    def finished(self) -> bool:
        return self.status in (TaskStatus.done, TaskStatus.error,
                               TaskStatus.cancelled)

    @property
    def seconds(self) -> float | None:
        if self.started_at is None:
            return None
        end = self.finished_at or utcnow()
        return round((end - self.started_at).total_seconds(), 1)

    def set_stage(self, progress: int, step: str) -> None:
        """Перейти на новый этап: процент (с зажимом 0..100), подпись,
        сброс секундомера этапа."""
        self.progress = max(0, min(100, int(progress)))
        self.step = step
        self.stage_started_at = time.monotonic()

    @property
    def stage_seconds(self) -> float:
        """Сколько идёт текущий этап (после завершения — заморожено)."""
        end = self._stage_ended_at or time.monotonic()
        return round(max(0.0, end - self.stage_started_at), 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "kind": self.kind, "title": self.title,
            "status": self.status.value, "progress": self.progress,
            "step": self.step, "error": self.error,
            "cancel_requested": self.cancel_requested,
            # user_id нужен админу для фильтра «задачи пользователя»: раньше
            # в списке автор задачи не был виден вовсе.
            "user_id": self.user_id,
            "session_id": self.session_id, "project_id": self.project_id,
            "created_at": self.created_at, "started_at": self.started_at,
            "finished_at": self.finished_at, "seconds": self.seconds,
            "stage_seconds": self.stage_seconds, "result": self.result,
        }


TaskBody = Callable[["Task"], Awaitable[Any]]


class TaskRegistry:
    def __init__(self, *, keep_finished: int = 50) -> None:
        self._tasks: dict[str, Task] = {}
        self._keep = keep_finished
        self._counter = itertools.count(1)

    # ------------------------------------------------------------------ доступ
    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def list(self, *, user_id: str | None = None,
             session_id: str | None = None,
             status: TaskStatus | None = None,
             limit: int = 20) -> list[Task]:
        tasks = list(self._tasks.values())
        if user_id is not None:
            tasks = [t for t in tasks if t.user_id == user_id]
        if session_id is not None:
            tasks = [t for t in tasks if t.session_id == session_id]
        if status is not None:
            tasks = [t for t in tasks if t.status is status]
        tasks.sort(key=lambda t: (t.created_at, t.seq), reverse=True)
        return tasks[:limit]

    def active_count(self) -> int:
        return sum(1 for t in self._tasks.values() if not t.finished)

    # ------------------------------------------------------------------ запуск
    def submit(self, body: TaskBody, *, kind: str, title: str,
               user_id: str | None = None, session_id: str | None = None,
               project_id: str | None = None) -> Task:
        """Поставить задачу в фон и вернуть её сразу (не дожидаясь)."""
        task = Task(id=str(uuid.uuid4()), kind=kind, title=title, user_id=user_id,
                    session_id=session_id, project_id=project_id,
                    seq=next(self._counter))
        self._tasks[task.id] = task
        task._handle = asyncio.create_task(self._run(task, body), name=f"task:{task.id}")
        self._trim()
        return task

    async def _run(self, task: Task, body: TaskBody) -> None:
        task.status = TaskStatus.running
        task.started_at = utcnow()
        task.set_stage(0, "начало")
        try:
            task.result = await body(task)
        except asyncio.CancelledError:
            task.status = TaskStatus.cancelled
            task.set_stage(task.progress, "отменено пользователем")
            task.finished_at = utcnow()
            log.info("task %s (%s) отменена", task.id[:8], task.kind)
            raise
        except Exception as exc:
            task.status = TaskStatus.error
            task.error = f"{type(exc).__name__}: {exc}"
            task.set_stage(task.progress, "ошибка")
            task.finished_at = utcnow()
            log.exception("task %s (%s) упала", task.id[:8], task.kind)
        else:
            task.status = TaskStatus.done
            task.set_stage(100, "готово")
            task.finished_at = utcnow()
            log.info("task %s (%s) выполнена за %sс", task.id[:8], task.kind,
                     task.seconds)
        finally:
            # секундомер этапа замораживаем: payload завершённой задачи
            # обязан отдавать одно и то же значение
            task._stage_ended_at = time.monotonic()
            self._trim()

    # ------------------------------------------------------------------ прогресс
    def report(self, task: Task, progress: int, step: str) -> None:
        """Обновить прогресс из тела задачи (и перезапустить этап)."""
        if task.cancel_requested:
            raise asyncio.CancelledError
        task.set_stage(progress, step)

    def request_cancel(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task is None or task.finished:
            return False
        task.cancel_requested = True
        task.set_stage(task.progress, "отмена запрошена")
        if task._handle is not None and not task._handle.done():
            task._handle.cancel()
        return True

    def _trim(self) -> None:
        finished = [t for t in self._tasks.values() if t.finished]
        if len(finished) <= self._keep:
            return
        finished.sort(key=lambda t: (t.finished_at or t.created_at, t.seq))
        for task in finished[: len(finished) - self._keep]:
            self._tasks.pop(task.id, None)

    def clear_finished(self) -> int:
        done = [t.id for t in self._tasks.values() if t.finished]
        for task_id in done:
            self._tasks.pop(task_id, None)
        return len(done)


tasks = TaskRegistry()


def get_registry() -> TaskRegistry:
    return tasks


def reset_registry() -> None:
    global tasks
    tasks = TaskRegistry()


class ProgressReporter:
    """Хелпер для тела задачи: считает прогресс по номеру шага."""

    def __init__(self, task: Task, registry: TaskRegistry | None = None) -> None:
        self.task = task
        self.registry = registry or tasks

    def step(self, index: int, total: int, label: str) -> None:
        percent = int(100 * index / max(1, total))
        self.registry.report(self.task, percent, label)


__all__ = ["ProgressReporter", "Task", "TaskRegistry", "TaskStatus",
           "get_registry", "reset_registry", "tasks"]