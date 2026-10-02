"""Фаза 5 — API сессий и документов: RBAC, лимиты, точка возврата, read-only.

Реестр PaperQA подменён заглушкой (`stub_registry`), LLM не используется:
эндпоинты документов индексируют файлы локальными эмбеддингами.
"""

from __future__ import annotations

import pytest

from tests.conftest import login_headers


# --------------------------------------------------------------------------- фикстуры
@pytest.fixture
async def researcher(client, researcher_user):
    return await login_headers(client, "ivanov", "researcher-pass-123")


@pytest.fixture
async def admin(client, admin_user):
    return await login_headers(client, "admin", "admin-pass-123")


@pytest.fixture
async def session_id(client, researcher):
    response = await client.post("/api/sessions", json={"title": "Биомасса Баренцева моря"},
                                 headers=researcher)
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.fixture
def paper(tmp_path):
    path = tmp_path / "biomass.md"
    path.write_text(
        "# Биомасса водорослей\n\n"
        "Биомасса измеряется методом GF/F — отношением сухого вещества к сырому.\n"
        "Хлорофилл-а определяют экстракционным методом в ацетоне.\n",
        encoding="utf-8")
    return path


# --------------------------------------------------------------------------- CRUD
async def test_create_session_sets_ttl_90_days(client, researcher) -> None:
    response = await client.post("/api/sessions", json={"title": "Проект"}, headers=researcher)
    body = response.json()

    assert response.status_code == 201
    assert body["status"] == "active"
    assert body["title"] == "Проект"
    delta = body["expires_at"]
    assert delta  # 90 дней проставляются на сервере


async def test_session_limit_returns_409(client, researcher, monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_sessions_per_user", 2, raising=False)
    for i in range(2):
        assert (await client.post("/api/sessions", json={"title": f"S{i}"},
                                  headers=researcher)).status_code == 201

    response = await client.post("/api/sessions", json={"title": "Лишняя"}, headers=researcher)

    assert response.status_code == 409
    assert response.json()["error"] == "limit_exceeded"
    assert response.json()["meta"]["limit"] == 2


async def test_list_sessions_isolated_between_users(client, researcher, db_engine) -> None:
    from sqlalchemy.orm import sessionmaker

    from app.core.security import hash_password
    from app.db.models import Role
    from app.db.repositories.users import create_research_session, create_user

    with sessionmaker(bind=db_engine, expire_on_commit=False)() as db:
        petrov = create_user(db, username="petrov", password="petrov-pass-123",
                             role=Role.researcher,
                             hashed_password=hash_password("petrov-pass-123"))
        create_research_session(db, petrov, "Чужая сессия")
        db.commit()
    petrov_headers = await login_headers(client, "petrov", "petrov-pass-123")

    mine = await client.get("/api/sessions", headers=researcher)
    theirs = await client.get("/api/sessions", headers=petrov_headers)

    assert [s["title"] for s in mine.json()] == []
    assert [s["title"] for s in theirs.json()] == ["Чужая сессия"]


async def test_admin_sees_all_sessions(client, admin, researcher, session_id) -> None:
    response = await client.get("/api/sessions", headers=admin)
    assert session_id in {s["id"] for s in response.json()}


async def test_cannot_read_foreign_session(client, researcher, db_engine) -> None:
    """Сессия Иванова недоступна Петрову: 404, а не 403 (не раскрываем факт)."""
    from sqlalchemy.orm import sessionmaker

    from app.core.security import hash_password
    from app.db.models import Role
    from app.db.repositories.users import create_user

    session_id = (await client.post("/api/sessions", json={"title": "Личное"},
                                    headers=researcher)).json()["id"]
    with sessionmaker(bind=db_engine, expire_on_commit=False)() as db:
        create_user(db, username="petrov", password="petrov-pass-123",
                    role=Role.researcher,
                    hashed_password=hash_password("petrov-pass-123"))
        db.commit()
    petrov_headers = await login_headers(client, "petrov", "petrov-pass-123")

    for method, url in (("GET", f"/api/sessions/{session_id}"),
                        ("GET", f"/api/sessions/{session_id}/documents"),
                        ("POST", f"/api/sessions/{session_id}/resume"),
                        ("DELETE", f"/api/sessions/{session_id}")):
        response = await client.request(method, url, headers=petrov_headers)
        assert response.status_code == 404, f"{method} {url} -> {response.status_code}"


async def test_session_detail_has_summary(client, researcher, session_id) -> None:
    response = await client.get(f"/api/sessions/{session_id}", headers=researcher)

    body = response.json()
    assert response.status_code == 200
    assert body["writable"] is True
    assert body["days_left"] in (89, 90)
    assert body["summary"]["documents"] == 0
    assert body["summary"]["documents_limit"] == 50
    assert body["summary"]["storage_limit_bytes"] == 500 * 1024 * 1024


async def test_patch_session_updates_note(client, researcher, session_id) -> None:
    response = await client.patch(
        f"/api/sessions/{session_id}",
        json={"title": "Новое имя", "resume_note": "найти Smith 2023"},
        headers=researcher)

    body = response.json()
    assert body["title"] == "Новое имя"
    assert body["resume_note"] == "найти Smith 2023"


async def test_state_autosave_and_dedup(client, researcher, session_id) -> None:
    payload = {"snapshot": {"tab": "chat", "chat_scroll": 120},
               "action_label": "Вкладка чата"}

    first = await client.put(f"/api/sessions/{session_id}/state", json=payload, headers=researcher)
    assert first.status_code == 200
    saved_at = first.json()["state_snapshot"]["saved_at"]

    second = await client.put(f"/api/sessions/{session_id}/state", json=payload, headers=researcher)
    assert second.json()["state_snapshot"]["saved_at"] == saved_at  # без изменений

    third = await client.put(f"/api/sessions/{session_id}/state",
                             json={"snapshot": {"tab": "projects"}}, headers=researcher)
    snapshot = third.json()["state_snapshot"]
    assert snapshot["tab"] == "projects"
    assert "chat_scroll" not in snapshot  # снапшот заменяется целиком


async def test_resume_returns_point_of_return(client, researcher, session_id) -> None:
    await client.put(f"/api/sessions/{session_id}/state",
                     json={"snapshot": {"tab": "documents"}, "resume_note": "продолжить разбор"},
                     headers=researcher)

    response = await client.post(f"/api/sessions/{session_id}/resume", headers=researcher)

    body = response.json()
    assert response.status_code == 200
    assert body["state"]["tab"] == "documents"
    assert body["session"]["resume_note"] == "продолжить разбор"
    assert body["restored_documents"] == 0
    assert body["summary"]["read_only"] is False


# --------------------------------------------------------------------------- TTL
async def test_heartbeat_extends_ttl(client, researcher, session_id) -> None:
    from app.db.models import utcnow

    before = (await client.get(f"/api/sessions/{session_id}",
                               headers=researcher)).json()["expires_at"]

    response = await client.post(f"/api/sessions/{session_id}/heartbeat", headers=researcher)

    assert response.status_code == 200
    assert response.json()["last_action_type"] == "session.heartbeat"
    assert (await client.get(f"/api/sessions/{session_id}",
                             headers=researcher)).json()["expires_at"] >= before
    assert utcnow() is not None


async def test_pause_and_archive_flow(client, researcher, session_id) -> None:
    paused = await client.post(f"/api/sessions/{session_id}/pause?note=до%20пятницы",
                               headers=researcher)
    assert paused.json()["status"] == "paused"
    assert paused.json()["resume_note"] == "до пятницы"

    resumed = await client.post(f"/api/sessions/{session_id}/resume", headers=researcher)
    assert resumed.json()["session"]["status"] == "active"

    archived = await client.post(f"/api/sessions/{session_id}/archive", headers=researcher)
    assert archived.json()["status"] == "archived"

    # архив — только чтение: реактивировать и менять нельзя
    assert (await client.post(f"/api/sessions/{session_id}/resume",
                              headers=researcher)).status_code == 409
    assert (await client.patch(f"/api/sessions/{session_id}", json={"title": "X"},
                               headers=researcher)).status_code == 409
    detail = await client.get(f"/api/sessions/{session_id}", headers=researcher)
    assert detail.json()["writable"] is False
    assert detail.json()["summary"]["read_only"] is True


async def test_delete_session_removes_it(client, researcher, session_id) -> None:
    assert (await client.delete(f"/api/sessions/{session_id}",
                                headers=researcher)).status_code == 204
    assert (await client.get(f"/api/sessions/{session_id}",
                             headers=researcher)).status_code == 404


# --------------------------------------------------------------------------- документы
async def test_add_document_from_path_and_list(client, researcher, session_id,
                                               stub_registry, paper) -> None:
    response = await client.post(
        f"/api/sessions/{session_id}/documents/path",
        json={"path": str(paper), "category": "project_data", "tags": [" биомасса ", "Баренцево"]},
        headers=researcher)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["category"] == "project_data"
    assert body["tags"] == ["биомасса", "Баренцево"]
    assert body["chunk_count"] >= 1
    assert body["session_id"] == session_id

    listed = await client.get(f"/api/sessions/{session_id}/documents", headers=researcher)
    assert [d["dockey"] for d in listed.json()] == [body["dockey"]]


async def test_add_document_missing_path_404(client, researcher, session_id, stub_registry) -> None:
    response = await client.post(f"/api/sessions/{session_id}/documents/path",
                                 json={"path": "/tmp/нет-такого.md"}, headers=researcher)
    assert response.status_code == 404


async def test_add_document_unknown_category_422(client, researcher, session_id,
                                                 stub_registry, paper) -> None:
    response = await client.post(f"/api/sessions/{session_id}/documents/path",
                                 json={"path": str(paper), "category": "выдумка"},
                                 headers=researcher)
    assert response.status_code == 422


async def test_document_count_limit_409(client, researcher, session_id, stub_registry,
                                        paper, monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_documents_per_session", 1, raising=False)
    assert (await client.post(f"/api/sessions/{session_id}/documents/path",
                              json={"path": str(paper)}, headers=researcher)).status_code == 200

    response = await client.post(f"/api/sessions/{session_id}/documents/path",
                                 json={"path": str(paper)}, headers=researcher)

    assert response.status_code == 409
    assert response.json()["meta"]["resource"] == "documents"


async def test_storage_limit_409(client, researcher, session_id, stub_registry,
                                 paper, monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_session_storage_mb", 0, raising=False)
    response = await client.post(f"/api/sessions/{session_id}/documents/path",
                                 json={"path": str(paper)}, headers=researcher)
    assert response.status_code == 409
    assert response.json()["meta"]["resource"] == "storage"


async def test_archived_session_documents_are_read_only(client, researcher, session_id,
                                                        stub_registry, paper) -> None:
    await client.post(f"/api/sessions/{session_id}/archive", headers=researcher)
    response = await client.post(f"/api/sessions/{session_id}/documents/path",
                                 json={"path": str(paper)}, headers=researcher)
    assert response.status_code == 409
    assert "только чтение" in response.json()["detail"]


async def test_patch_and_delete_document(client, researcher, session_id,
                                         stub_registry, paper) -> None:
    created = (await client.post(f"/api/sessions/{session_id}/documents/path",
                                 json={"path": str(paper)}, headers=researcher)).json()
    document_id = created["id"]

    patched = await client.patch(f"/api/sessions/{session_id}/documents/{document_id}",
                                 json={"category": "project_draft", "title": "Черновик",
                                       "tags": ["черновик"]},
                                 headers=researcher)
    assert patched.json()["category"] == "project_draft"
    assert patched.json()["title"] == "Черновик"

    # категория влияет на индексацию: документ уходит в отчёт сессии
    detail = (await client.get(f"/api/sessions/{session_id}", headers=researcher)).json()
    assert detail["summary"]["documents_by_category"]["project_draft"] == 1

    assert (await client.delete(f"/api/sessions/{session_id}/documents/{document_id}",
                                headers=researcher)).status_code == 204
    assert (await client.get(f"/api/sessions/{session_id}/documents",
                             headers=researcher)).json() == []


async def test_delete_document_removes_it_from_index(client, researcher, session_id,
                                                     stub_registry, paper) -> None:
    created = (await client.post(f"/api/sessions/{session_id}/documents/path",
                                 json={"path": str(paper)}, headers=researcher)).json()
    await client.delete(f"/api/sessions/{session_id}/documents/{created['id']}",
                        headers=researcher)

    service = stub_registry.session_service(session_id)
    assert service.list_documents() == []


async def test_upload_document(client, researcher, session_id, stub_registry) -> None:
    response = await client.post(
        f"/api/sessions/{session_id}/documents/upload",
        files=[("files", ("upload.md", b"# Zaglavlenie\n\nHlorofill-a 1.85 mg/m3.\n",
                          "text/markdown"))],
        data={"category": "temp_literature", "tags": "загрузка"},
        headers=researcher)

    body = response.json()
    assert response.status_code == 200, response.text
    assert body["total"] == 1
    assert body["added"][0]["category"] == "temp_literature"
    assert body["added"][0]["tags"] == ["загрузка"]


async def test_upload_goes_to_session_directory(client, researcher, session_id,
                                                stub_registry, tmp_path) -> None:
    await client.post(
        f"/api/sessions/{session_id}/documents/upload",
        files=[("files", ("a.md", b"# A\n\nHlorofill.\n", "text/markdown"))],
        headers=researcher)

    stored = list((stub_registry.app.sessions_dir / session_id / "uploads").glob("*"))
    assert stored, "файл должен лежать в каталоге своей сессии"


async def test_document_links_crud(client, researcher, session_id, stub_registry,
                                   paper, db_engine) -> None:
    from sqlalchemy.orm import sessionmaker

    from app.db.models import Project

    created = (await client.post(f"/api/sessions/{session_id}/documents/path",
                                 json={"path": str(paper)}, headers=researcher)).json()
    with sessionmaker(bind=db_engine, expire_on_commit=False)() as db:
        project = Project(session_id=session_id, title="Статья")
        db.add(project)
        db.commit()
        project_id = project.id

    link = await client.post(
        f"/api/sessions/{session_id}/documents/{created['id']}/links",
        json={"project_id": project_id, "role": "reference", "relation": "supports",
              "note": "данные согласуются"},
        headers=researcher)

    assert link.status_code == 201, link.text
    body = link.json()
    assert body["relation"] == "supports"
    assert body["role"] == "reference"

    listed = await client.get(f"/api/sessions/{session_id}/documents/links", headers=researcher)
    assert [link["id"] for link in listed.json()] == [body["id"]]

    detail = (await client.get(f"/api/sessions/{session_id}", headers=researcher)).json()
    assert detail["summary"]["links"] == 1

    assert (await client.delete(
        f"/api/sessions/{session_id}/documents/links/{body['id']}",
        headers=researcher)).status_code == 204
    assert (await client.get(f"/api/sessions/{session_id}/documents/links",
                             headers=researcher)).json() == []


async def test_restore_index_endpoint(client, researcher, session_id, stub_registry, paper) -> None:
    await client.post(f"/api/sessions/{session_id}/documents/path",
                      json={"path": str(paper)}, headers=researcher)

    response = await client.post(f"/api/sessions/{session_id}/documents/restore",
                                 headers=researcher)

    assert response.status_code == 200
    assert response.json()["restored"] == 1
    assert len(stub_registry.session_service(session_id).list_documents()) == 1


# --------------------------------------------------------------------------- RBAC
async def test_researcher_cannot_open_admin_routes(client, researcher) -> None:
    assert (await client.get("/api/admin/documents",
                             headers=researcher)).status_code == 403
    assert (await client.get("/api/admin/users",
                             headers=researcher)).status_code == 403


async def test_global_documents_are_admin_only(client, admin, researcher) -> None:
    assert (await client.get("/api/admin/documents", headers=admin)).status_code == 200
    assert (await client.get("/api/admin/documents", headers=researcher)).status_code == 403