"""SSE-канал задач: авторизация EventSource и порядок статических маршрутов.

EventSource не умеет задавать HTTP-заголовки, поэтому `/api/tasks/events`
принимает access-токен в query. Здесь же фиксируем регрессию, из-за которой
поток не открывался вообще: `GET /{task_id}` регистрировался раньше `/events`
и перехватывал его (404 «Задача не найдена») даже с валидным Bearer.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.api.tasks import _task_event_stream
from app.services.tasks import Task, TaskRegistry, TaskStatus, event_manager
from tests.conftest import login_headers

SSE_URL = "/api/tasks/events"


@pytest.fixture(autouse=True)
def clean_subscribers():
    """Глобальный pub/sub не должен протекать между тестами."""
    yield
    event_manager._subscribers.clear()


@pytest.fixture
def finite_stream(monkeypatch):
    """Для HTTP-тестов авторизации поток должен завершиться сам.

    Бесконечный SSE нельзя прочитать через ASGITransport: транспорт
    буферизует тело до конца. Авторизацию и роутинг проверяем на конечной
    заглушке, а бесконечность — прямой проверкой генератора ниже.
    """
    async def stream(user_id: str):
        yield 'data: {"id": "t-sse"}\n\n'

    monkeypatch.setattr("app.api.tasks._task_event_stream", stream)


async def _read_stream(client, url: str, user_id: str,
                       headers: dict[str, str] | None = None):
    """Прочитать конечный поток (см. `finite_stream`)."""
    response = await client.get(url, headers=headers or {}, timeout=10.0)
    return response, response.content


async def _collect_events(user_id: str, tasks: list[Task],
                          count: int) -> list[str]:
    """Прямой проход по генератору: поток не должен закрыться на `finished`."""
    stream = _task_event_stream(user_id)

    async def publish_when_subscribed() -> None:
        for _ in range(200):
            if await event_manager.get_queue(user_id) is not None:
                break
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.02)
        for task in tasks:
            await event_manager.publish(task)
            await asyncio.sleep(0.02)

    pump = asyncio.create_task(publish_when_subscribed())
    events: list[str] = []
    try:
        async for event in stream:
            if not event.startswith("data: "):
                continue
            events.append(event)
            if len(events) >= count:
                break
        return events
    finally:
        await stream.aclose()
        pump.cancel()


async def _login(client, username: str, password: str) -> tuple[str, str]:
    """(user_id, access_token) — подписке нужно знать id пользователя."""
    response = await client.post("/api/auth/login",
                                 json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    body = response.json()
    return body["user"]["id"], body["tokens"]["access_token"]


# ------------------------------------------------------------------ авторизация
async def test_sse_requires_token(client, researcher_user) -> None:
    response = await client.get(SSE_URL)
    assert response.status_code == 401
    assert response.json()["detail"] == "Требуется авторизация"


async def test_sse_rejects_garbage_query_token(client, researcher_user) -> None:
    response = await client.get(SSE_URL, params={"access_token": "не-токен"})
    assert response.status_code == 401


async def test_sse_accepts_query_token(client, researcher_user, finite_stream) -> None:
    """Главный сценарий: EventSource шлёт токен в query и получает поток."""
    user_id, token = await _login(client, "ivanov", "researcher-pass-123")

    response, body = await _read_stream(client, f"{SSE_URL}?access_token={token}", user_id)

    assert response.status_code == 200, body
    assert response.headers["content-type"].startswith("text/event-stream")
    assert b'data: {"id": "t-sse"' in body


async def test_sse_accepts_bearer_header(client, researcher_user, finite_stream) -> None:
    """Заголовок тоже работает: curl и серверные клиенты не сломаны."""
    user_id, _ = await _login(client, "ivanov", "researcher-pass-123")
    headers = await login_headers(client, "ivanov", "researcher-pass-123")

    response, body = await _read_stream(client, SSE_URL, user_id, headers=headers)

    assert response.status_code == 200, body
    assert b'data: {"id": "t-sse"' in body


async def test_sse_does_not_stop_after_first_finished_task(client, researcher_user) -> None:
    """Регрессия: break после `finished` терял события второй задачи."""
    user_id, _ = await _login(client, "ivanov", "researcher-pass-123")

    def task(task_id: str, status: TaskStatus) -> Task:
        return Task(id=task_id, kind="chat", title=task_id,
                    status=status, user_id=user_id)

    tasks = [
        task("t-first", TaskStatus.running),
        task("t-first", TaskStatus.done),
        task("t-second", TaskStatus.running),
        task("t-second", TaskStatus.done),
    ]

    events = await _collect_events(user_id, tasks, len(tasks))
    body = "\n".join(events).encode()
    assert body.count(b"data: ") == 4
    assert b'"id": "t-first"' in body
    assert b'"id": "t-second"' in body
    assert b'"status": "done"' in body
    # После завершения первой задачи поток продолжил отдавать вторую.
    assert body.index(b'"id": "t-second"') > body.index(b'"id": "t-first"')


async def test_registry_publishes_progress_events(client, researcher_user) -> None:
    """Регрессия: `publish` не вызывался из жизни задачи — SSE молчал.

    Раньше тесты зеленели, потому что события публиковались вручную; в
    приложении прогресс ехал только поллингом. Здесь задача идёт через
    настоящий `TaskRegistry.submit` и публикует сама через `set_stage`.
    """
    user_id, _ = await _login(client, "ivanov", "researcher-pass-123")

    async def body(task: Task) -> None:
        for progress in (10, 50, 100):
            task.set_stage(progress, f"шаг {progress}")
            await asyncio.sleep(0.02)

    registry = TaskRegistry()
    stream = _task_event_stream(user_id)

    async def pump() -> None:
        # Ждём, пока генератор подпишется, и только потом запускаем задачу.
        for _ in range(200):
            if await event_manager.get_queue(user_id) is not None:
                break
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.02)
        registry.submit(body, kind="chat", title="прогресс", user_id=user_id)

    pump_task = asyncio.create_task(pump())
    events: list[str] = []
    try:
        async for event in stream:
            if not event.startswith("data: "):
                continue
            events.append(event)
            if '"progress": 50' in event:
                break
    finally:
        await stream.aclose()
        pump_task.cancel()

    # `json.dumps` экранирует кириллицу, поэтому разбираем, а не ищем строку.
    payloads = [json.loads(event[len("data: "):]) for event in events]
    assert any(p["progress"] == 50 for p in payloads)
    assert any(p["step"] == "шаг 50" for p in payloads)


async def test_query_token_works_only_for_sse(client, researcher_user) -> None:
    """Токен в query не ослабляет остальные маршруты — им нужен заголовок."""
    _, token = await _login(client, "ivanov", "researcher-pass-123")

    response = await client.get("/api/tasks", params={"access_token": token})

    assert response.status_code == 401


# ------------------------------------------------------------------- роутинг
async def test_health_route_not_shadowed_by_task_id(client, researcher_user) -> None:
    """`/health` тоже стоял после `/{task_id}` — вернулся из 404."""
    headers = await login_headers(client, "ivanov", "researcher-pass-123")

    response = await client.get("/api/tasks/health", headers=headers)

    assert response.status_code == 200
    assert "statuses" in response.json()
