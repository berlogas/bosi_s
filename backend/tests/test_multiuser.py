"""Совместная работа нескольких пользователей: изоляция чужих данных.

Замысел: каждый исследователь работает в своих сессиях, но администратор
видит всё. Поэтому проверяем две вещи:

  1. исследователь не достаёт до сессий, документов, проектов, истории чата
     и фоновых задач другого (404, а не 403 — сам факт существования не
     раскрывается);
  2. списки исследователя не содержат чужих записей (не только по прямому
     запросу чужого id, но и в выдаче).

Глобальная база документов общая для всех намеренно: она и называется
глобальной, и загружает её администратор.
"""

from __future__ import annotations

import pytest

from tests.conftest import login_headers


@pytest.fixture
async def researcher(client, researcher_user):
    return await login_headers(client, "ivanov", "researcher-pass-123")


@pytest.fixture
async def admin(client, admin_user):
    return await login_headers(client, "admin", "admin-pass-123")


@pytest.fixture
async def petrov(client, db_engine):
    """Второй исследователь со своей сессией."""
    from sqlalchemy.orm import sessionmaker

    from app.core.security import hash_password
    from app.db.models import Role
    from app.db.repositories.users import create_research_session, create_user

    with sessionmaker(bind=db_engine, expire_on_commit=False)() as db:
        user = create_user(db, username="petrov", password="petrov-pass-123",
                           role=Role.researcher,
                           hashed_password=hash_password("petrov-pass-123"))
        session = create_research_session(db, user, "Сессия Петрова")
        db.commit()
        petrov_session_id = session.id
    return {"headers": await login_headers(client, "petrov", "petrov-pass-123"),
            "session_id": petrov_session_id}


@pytest.fixture
async def ivanov_assets(client, researcher, stub_registry):
    """Сессия Иванова с документом и проектом."""
    directory = stub_registry.app.documents_dir / "incoming"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "biomass.md"
    path.write_text(
        "# Биомасса\n\nБиомасса измеряется методом GF/F.\n", encoding="utf-8")

    session_id = (await client.post("/api/sessions", json={"title": "Личное"},
                                    headers=researcher)).json()["id"]
    document = (await client.post(
        f"/api/sessions/{session_id}/documents/path",
        json={"path": str(path), "category": "temp_literature"},
        headers=researcher)).json()
    project = (await client.post(f"/api/sessions/{session_id}/projects",
                                 json={"title": "Статья"}, headers=researcher)).json()
    return {"session_id": session_id, "document_id": document["id"],
            "project_id": project["id"]}


async def test_foreign_session_resources_are_404(client, petrov, ivanov_assets) -> None:
    """Ни один ресурс сессии Иванова не отдаётся Петрову — даже по прямому id."""
    headers = petrov["headers"]
    session_id = ivanov_assets["session_id"]
    document_id = ivanov_assets["document_id"]
    project_id = ivanov_assets["project_id"]

    forbidden = [
        ("GET", f"/api/sessions/{session_id}"),
        ("PATCH", f"/api/sessions/{session_id}"),
        ("DELETE", f"/api/sessions/{session_id}"),
        ("POST", f"/api/sessions/{session_id}/resume"),
        ("POST", f"/api/sessions/{session_id}/archive"),
        ("POST", f"/api/sessions/{session_id}/pause"),
        ("POST", f"/api/sessions/{session_id}/heartbeat"),
        ("PUT", f"/api/sessions/{session_id}/state"),
        ("GET", f"/api/sessions/{session_id}/documents"),
        ("POST", f"/api/sessions/{session_id}/documents/path"),
        ("POST", f"/api/sessions/{session_id}/documents/restore"),
        ("PATCH", f"/api/sessions/{session_id}/documents/{document_id}"),
        ("DELETE", f"/api/sessions/{session_id}/documents/{document_id}"),
        ("GET", f"/api/sessions/{session_id}/projects"),
        ("POST", f"/api/sessions/{session_id}/projects"),
        ("GET", f"/api/sessions/{session_id}/projects/{project_id}"),
        ("PATCH", f"/api/sessions/{session_id}/projects/{project_id}"),
        ("DELETE", f"/api/sessions/{session_id}/projects/{project_id}"),
        ("GET", f"/api/sessions/{session_id}/projects/{project_id}/sections"),
        ("GET", f"/api/sessions/{session_id}/projects/{project_id}/documents"),
        ("GET", f"/api/sessions/{session_id}/projects/{project_id}/versions"),
        ("GET", f"/api/sessions/{session_id}/projects/{project_id}/export"),
        ("GET", f"/api/chat/messages?session_id={session_id}"),
        ("DELETE", f"/api/chat/messages?session_id={session_id}"),
    ]
    for method, url in forbidden:
        response = await client.request(method, url, headers=headers,
                                        json={"title": "взлом", "query": "чужое"})
        assert response.status_code == 404, (
            f"{method} {url} -> {response.status_code}, ожидался 404")


async def test_lists_do_not_leak_foreign_sessions(client, researcher, petrov,
                                                  ivanov_assets) -> None:
    """Выдача исследователя содержит только его сессии."""
    mine = await client.get("/api/sessions", headers=researcher)
    titles = {s["title"] for s in mine.json()}
    assert titles == {"Личное"}, titles

    petrov_sessions = await client.get("/api/sessions", headers=petrov["headers"])
    assert {s["id"] for s in petrov_sessions.json()} == {petrov["session_id"]}


async def test_chat_history_is_isolated(client, researcher, petrov,
                                       ivanov_assets) -> None:
    """История переписки Иванова не попадает в выдачу Петрова."""
    session_id = ivanov_assets["session_id"]

    # вопрос Иванова: синхронный путь не требует LLM-генерации при кэше,
    # поэтому пишем историю напрямую через быстрый чат-механизм сессии
    written = await client.post("/api/chat/quick-message",
                                json={"query": "секретный вопрос"}, headers=researcher)
    assert written.status_code == 201

    # у сессии своя история пуста
    own = await client.get(f"/api/chat/messages?session_id={session_id}",
                           headers=researcher)
    assert own.status_code == 200

    # а быстрые запросы у каждого свои
    quick_ivanov = await client.get("/api/chat/quick-history", headers=researcher)
    quick_petrov = await client.get("/api/chat/quick-history",
                                    headers=petrov["headers"])
    ivanov_texts = {m["content"] for m in quick_ivanov.json()["messages"]}
    petrov_texts = {m["content"] for m in quick_petrov.json()["messages"]}
    assert "секретный вопрос" in ivanov_texts
    assert "секретный вопрос" not in petrov_texts


async def test_admin_sees_foreign_session_but_researcher_does_not(
    client, admin, petrov, ivanov_assets) -> None:
    """Админ видит чужую сессию (для аудита), исследователь — нет."""
    session_id = ivanov_assets["session_id"]

    as_admin = await client.get(f"/api/sessions/{session_id}", headers=admin)
    assert as_admin.status_code == 200
    assert as_admin.json()["owner_username"] == "ivanov"

    as_petrov = await client.get(f"/api/sessions/{session_id}",
                                 headers=petrov["headers"])
    assert as_petrov.status_code == 404


async def test_global_base_is_managed_by_admin_only(client, admin, researcher,
                                                   petrov) -> None:
    """Глобальная база — общая для всех, но управляет ею администратор.

    Исследователь её читает через поиск по сессии, а вот список и загрузка
    (/api/admin/documents) закрыты require_admin. Проверка фиксирует это
    решение, чтобы случайная смена не прошла молча.
    """
    as_admin = await client.get("/api/admin/documents", headers=admin)
    assert as_admin.status_code == 200

    for headers in (researcher, petrov["headers"]):
        response = await client.get("/api/admin/documents", headers=headers)
        assert response.status_code == 403, response.status_code