"""Фаза 8 — реестр фоновых задач: прогресс, отмена, видимость по владельцу.

Ключевое требование UI: запрос дольше минуты должен показывать прогресс и
оставаться отменяемым. Здесь это проверяется без Streamlit — на самом реестре.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.errors import NotFoundError
from app.db.models import Role
from app.services.tasks import ProgressReporter, TaskRegistry, TaskStatus, reset_registry, tasks


@pytest.fixture(autouse=True)
def clean_registry():
    reset_registry()
    yield
    reset_registry()


async def _wait_finished(task, limit_seconds: float = 3.0) -> None:
    """Дождаться завершения задачи, чтобы статус был определённым."""
    deadline = asyncio.get_running_loop().time() + limit_seconds
    while not task.finished:
        assert asyncio.get_running_loop().time() < deadline, "задача зависла"
        await asyncio.sleep(0.01)


async def test_task_runs_and_completes() -> None:
    async def body(task):
        tasks.report(task, 50, "половина")
        return {"items": 3}

    task = tasks.submit(body, kind="indexing", title="Индексация")
    await _wait_finished(task)

    assert task.status is TaskStatus.done
    assert task.progress == 100
    assert task.step == "готово"
    assert task.result == {"items": 3}
    assert task.seconds is not None
    assert task.started_at is not None and task.finished_at is not None


async def test_task_reports_progress_while_running() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def body(task):
        tasks.report(task, 10, "файл 1/10")
        started.set()
        await release.wait()
        tasks.report(task, 90, "файл 9/10")
        return "ok"

    task = tasks.submit(body, kind="indexing", title="Пачка")
    await started.wait()

    assert task.status is TaskStatus.running
    assert task.progress == 10
    assert task.step == "файл 1/10"

    release.set()
    await _wait_finished(task)
    assert task.status is TaskStatus.done


async def test_task_failure_is_recorded() -> None:
    async def body(task):
        raise ValueError("файл битый")

    task = tasks.submit(body, kind="indexing", title="Ошибка")
    await _wait_finished(task)

    assert task.status is TaskStatus.error
    assert "ValueError" in task.error
    assert "битый" in task.error
    assert task.step == "ошибка"


async def test_cancel_stops_running_task() -> None:
    """Главное для UI: долгий запрос должен останавливаться по кнопке."""
    started = asyncio.Event()
    warmed_up = asyncio.Event()
    processed: list[int] = []

    async def body(task):
        started.set()
        for index in range(1000):
            tasks.report(task, index // 10, f"шаг {index}")
            processed.append(index)
            if len(processed) >= 5:
                warmed_up.set()
            await asyncio.sleep(0.005)
        return "не дойдём"

    task = tasks.submit(body, kind="chat", title="Долгий вопрос")
    await started.wait()
    await warmed_up.wait()

    assert tasks.request_cancel(task.id) is True
    await _wait_finished(task)

    assert task.status is TaskStatus.cancelled
    assert task.cancel_requested is True
    assert "отменено" in task.step
    assert len(processed) < 1000, "отмена должна остановить работу"


async def test_cancel_prevents_result_from_being_saved() -> None:
    started = asyncio.Event()

    async def body(task):
        started.set()
        await asyncio.sleep(1)
        return "готово"

    task = tasks.submit(body, kind="chat", title="t")
    await started.wait()
    tasks.request_cancel(task.id)
    await _wait_finished(task)

    assert task.result is None


async def test_cancel_of_finished_task_returns_false() -> None:
    async def body(task):
        return "ok"

    task = tasks.submit(body, kind="chat", title="Быстрая")
    await _wait_finished(task)

    assert tasks.request_cancel(task.id) is False


def test_cancel_of_unknown_task_returns_false() -> None:
    assert tasks.request_cancel("нет-такой") is False


async def test_report_raises_inside_body_when_cancel_requested() -> None:
    """Отмена кооперативная: тело задачи узнаёт о ней через report()."""
    registry = TaskRegistry()
    started = asyncio.Event()

    async def body(task):
        started.set()
        await asyncio.sleep(1)
        registry.report(task, 50, "шаг")
        return "ok"

    task = registry.submit(body, kind="chat", title="t")
    await started.wait()
    task.cancel_requested = True

    with pytest.raises(asyncio.CancelledError):
        registry.report(task, 50, "шаг")


def test_progress_reporter_calculates_percent() -> None:
    registry = TaskRegistry()
    seen: list[tuple[int, str]] = []

    class _FakeTask:
        cancel_requested = False

    task = _FakeTask()
    reporter = ProgressReporter(task, registry)  # type: ignore[arg-type]

    for index in range(1, 5):
        reporter.step(index, 4, f"файл {index}")
        seen.append((task.progress, task.step))  # type: ignore[attr-defined]

    assert [pct for pct, _ in seen] == [25, 50, 75, 100]
    assert seen[-1][1] == "файл 4"


async def test_registry_lists_tasks_newest_first() -> None:
    registry = TaskRegistry()

    async def body(task):
        return "ok"

    first = registry.submit(body, kind="chat", title="первая")
    await _wait_finished(first)
    second = registry.submit(body, kind="chat", title="вторая")
    await _wait_finished(second)

    listed = registry.list()
    assert [t.title for t in listed][:2] == ["вторая", "первая"]
    assert registry.list(user_id="никто") == []


async def test_registry_trims_finished_tasks() -> None:
    registry = TaskRegistry(keep_finished=2)

    async def body(task):
        return "ok"

    for _ in range(5):
        task = registry.submit(body, kind="chat", title="t")
        await _wait_finished(task)

    assert len(registry.list()) == 2


def test_task_dict_shape_for_api() -> None:
    """Контракт, который читает UI: эти поля обязаны быть в to_dict()."""
    payload = {
        "id": "1", "kind": "indexing", "title": "t", "status": "queued",
        "progress": 0, "step": "в очереди", "error": None,
        "cancel_requested": False, "session_id": None, "project_id": None,
        "seconds": None, "result": None,
    }
    assert set(payload) >= {"id", "kind", "status", "progress", "step",
                            "cancel_requested", "seconds"}


# --------------------------------------------------------------------------- видимость
class _FakeUser:
    def __init__(self, user_id: str, role: Role) -> None:
        self.id = user_id
        self.role = role


class _FakeTask:
    def __init__(self, user_id: str | None) -> None:
        self.user_id = user_id


def test_foreign_task_looks_absent() -> None:
    """Чужая задача должна выглядеть как несуществующая, а не как 403."""
    from app.api.tasks import _own

    with pytest.raises(NotFoundError):
        _own(_FakeTask("someone-else"), _FakeUser("me", Role.researcher))


def test_admin_sees_foreign_task() -> None:
    from app.api.tasks import _own

    task = _FakeTask("someone-else")
    assert _own(task, _FakeUser("admin", Role.admin)) is task


def test_owner_sees_own_task() -> None:
    from app.api.tasks import _own

    task = _FakeTask("me")
    assert _own(task, _FakeUser("me", Role.researcher)) is task


def test_anonymous_task_visible_to_anyone() -> None:
    from app.api.tasks import _own

    task = _FakeTask(None)
    assert _own(task, _FakeUser("me", Role.researcher)) is task