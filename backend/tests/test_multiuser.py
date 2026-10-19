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

def _seed_global_document(db, owner_id: str, **kwargs) -> None:
    """Документ в глобальной базе напрямую в БД — индексация тут ни при чём."""
    from app.db.models import (
        DocumentCategory,
        DocumentStatus,
        DocumentVisibility,
    )
    from app.db.repositories import documents as docs_repo

    params = {
        "dockey": "dockey-1",
        "docname": "docname-1",
        "title": "Хлорофилл и фотосинтез",
        "filename": "chlorophyll.pdf",
        "size_bytes": 2048,
        "chunk_count": 7,
        "category": DocumentCategory.global_knowledge,
        "visibility": DocumentVisibility.global_,
        "session_id": None,
        "owner_user_id": owner_id,
        "added_by": owner_id,
        "status": DocumentStatus.ready,
    }
    params.update(kwargs)
    docs_repo.upsert_document(db, **params)


async def test_researcher_reads_global_base_list(client, db, admin, researcher,
                                                 admin_user) -> None:
    """Исследователь, который не может наполнять базу, должен её видеть.

    Иначе он получает в ответе ссылку на источник, которого никогда не видел
    в списке, и не может понять, доступен ли нужный документ вообще.
    """
    _seed_global_document(db, admin_user.id)

    as_admin = await client.get("/api/admin/documents", headers=admin)
    assert as_admin.status_code == 200
    assert len(as_admin.json()) == 1

    # исследователь видит тот же список...
    response = await client.get("/api/documents", headers=researcher)
    assert response.status_code == 200
    listed = response.json()
    assert len(listed) == 1
    assert listed[0]["title"] == "Хлорофилл и фотосинтез"

    # ...но ответ не отдаёт служебные поля админского DTO: путь на диске,
    # текст ошибки и хэш содержимого читателю списка не нужны
    assert "path" not in listed[0]
    assert "error" not in listed[0]
    assert "content_hash" not in listed[0]


async def test_global_base_list_needs_authentication(client) -> None:
    """Анонимный посетитель не видит глобальную базу."""
    assert (await client.get("/api/documents")).status_code == 401


async def test_global_base_list_filters(client, db, admin_user, researcher) -> None:
    """Поиск по названию, имени файла и меткам; фильтр по категории."""
    from app.db.models import DocumentCategory

    _seed_global_document(db, admin_user.id, dockey="a", docname="a",
                          title="Хлорофилл и фотосинтез", filename="a.pdf")
    _seed_global_document(db, admin_user.id, dockey="b", docname="b",
                          title="CTD-зонды", filename="b.pdf",
                          category=DocumentCategory.temp_literature,
                          tags=["океан"])

    async def titles(**params) -> list[str]:
        response = await client.get("/api/documents", headers=researcher, params=params)
        assert response.status_code == 200
        return sorted(item["title"] for item in response.json())

    assert len(await titles()) == 2
    assert await titles(q="хлорофилл") == ["Хлорофилл и фотосинтез"]
    assert await titles(q="CTD") == ["CTD-зонды"]          # регистр не важен
    assert await titles(q="океан") == ["CTD-зонды"]          # по меткам
    assert await titles(q="нетакого") == []
    # категория отсекает второй документ
    assert await titles(category="global_knowledge") == ["Хлорофилл и фотосинтез"]


async def test_global_base_stats(client, db, admin_user, researcher) -> None:
    """Сводка по базе доступна вместе со списком."""
    _seed_global_document(db, admin_user.id, dockey="a", docname="a", size_bytes=1000)
    _seed_global_document(db, admin_user.id, dockey="b", docname="b", size_bytes=500)

    response = await client.get("/api/documents/stats", headers=researcher)
    assert response.status_code == 200
    summary = response.json()
    assert summary["total"] == 2
    assert summary["storage_bytes"] == 1500
