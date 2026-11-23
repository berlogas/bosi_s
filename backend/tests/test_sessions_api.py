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
def paper(stub_registry):
    """Файл в РАЗРЕШЁННОМ каталоге: с Фазы 9 путь снаружи data_dir отклоняется (403)."""
    directory = stub_registry.app.documents_dir / "incoming"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "biomass.md"
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


async def test_session_list_carries_owner(client, admin, researcher, session_id) -> None:
    """Админ раскладывает чужие сессии по владельцам — нужен логин в DTO."""
    response = await client.get("/api/sessions", headers=admin)
    body = next(s for s in response.json() if s["id"] == session_id)
    assert body["owner_username"] == "ivanov"
    assert body["user_id"]


async def test_session_list_carries_owner_full_name(client, admin, researcher,
                                                    session_id, researcher_user,
                                                    db) -> None:
    researcher_user.full_name = "Иванов Иван"
    db.commit()  # иначе клиент открывает другую сессию и не увидит ФИО

    response = await client.get("/api/sessions", headers=admin)
    body = next(s for s in response.json() if s["id"] == session_id)
    assert body["owner_full_name"] == "Иванов Иван"


async def test_own_session_list_also_has_owner(client, researcher, session_id) -> None:
    """Поле заполняется и для исследователя — карточка не должна падать."""
    response = await client.get("/api/sessions", headers=researcher)
    body = next(s for s in response.json() if s["id"] == session_id)
    assert body["owner_username"] == "ivanov"


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


async def test_список_документов_отдаёт_число_чанков(client, researcher, session_id,
                                                    stub_registry, paper) -> None:
    """Список показывает настоящий счётчик чанков.

    Раньше эндпоинт отдавал ORM-объекты напрямую, а в DTO поле называется
    `chunk_count`, в модели — `chunks_count`. FastAPI брал второе имя, не
    находил и молча ставил 0: интерфейс писал «0 чанков» у документов,
    которые были проиндексированы.
    """
    added = await client.post(
        f"/api/sessions/{session_id}/documents/path",
        json={"path": str(paper), "category": "project_data"},
        headers=researcher)
    assert added.status_code == 200, added.text
    assert added.json()["chunk_count"] >= 1

    listed = await client.get(f"/api/sessions/{session_id}/documents", headers=researcher)
    assert listed.json()[0]["chunk_count"] >= 1


async def test_add_document_missing_path_404(client, researcher, session_id,
                                             stub_registry) -> None:
    """Разрешённый каталог, но файла нет -> 404 (а не 403)."""
    missing = stub_registry.app.documents_dir / "incoming" / "нет-такого.md"
    response = await client.post(f"/api/sessions/{session_id}/documents/path",
                                 json={"path": str(missing)}, headers=researcher)
    assert response.status_code == 404


async def test_add_document_outside_data_dir_403(client, researcher, session_id,
                                                 stub_registry, tmp_path) -> None:
    """Фаза 9: путь вне каталога данных отклоняется, даже если файл существует."""
    outside = tmp_path / "secret.md"
    outside.write_text("секрет", encoding="utf-8")

    response = await client.post(f"/api/sessions/{session_id}/documents/path",
                                 json={"path": str(outside)}, headers=researcher)

    assert response.status_code == 403
    assert "вне разрешённых" in response.json()["detail"]


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


async def test_upload_rejects_global_knowledge_category(client, researcher, session_id) -> None:
    """D11: `global_knowledge` — категория только глобальной базы, не сессии."""
    response = await client.post(
        f"/api/sessions/{session_id}/documents/upload",
        files=[("files", ("otchet.md", b"# Otchet\n\nHlorofill-a 1.85 mg/m3.\n",
                          "text/markdown"))],
        data={"category": "global_knowledge"},
        headers=researcher)
    assert response.status_code == 422
    assert "global_knowledge" in response.json()["detail"]


async def test_delete_document_removes_temp_file(client, researcher, session_id,
                                                stub_registry) -> None:
    """D12: удаление документа из сессии чистит временный файл загрузки."""
    response = await client.post(
        f"/api/sessions/{session_id}/documents/upload",
        files=[("files", ("otchet.md", b"# Otchet\n\nHlorofill-a 1.85 mg/m3.\n",
                          "text/markdown"))],
        headers=researcher)
    assert response.status_code == 200, response.text

    stored = list((stub_registry.app.sessions_dir / session_id / "uploads").glob("*"))
    assert stored, "файл должен быть на диске до удаления"

    listed = await client.get(f"/api/sessions/{session_id}/documents", headers=researcher)
    document_id = listed.json()[0]["id"]
    assert (await client.delete(f"/api/sessions/{session_id}/documents/{document_id}",
                                headers=researcher)).status_code == 204

    assert list((stub_registry.app.sessions_dir / session_id / "uploads").glob("*")) == []


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
        files=[("files", ("a.md", b"# Zaglavlenie\n\nHlorofill-a 1.85 mg/m3.\n",
                          "text/markdown"))],
        headers=researcher)

    stored = list((stub_registry.app.sessions_dir / session_id / "uploads").glob("*"))
    assert stored, "файл должен лежать в каталоге своей сессии"


async def test_upload_async_returns_task_and_indexes_in_background(
        client, researcher, session_id, stub_registry) -> None:
    """Фоновая загрузка: ответ с task_id, индексация идёт в задаче.

    Требование ТЗ (приёмка Фазы 10): «индексация запускается асинхронно,
    progress visible в UI» — держать HTTP-запрос открытым на минуты нельзя.
    """
    from app.services.tasks import tasks

    response = await client.post(
        f"/api/sessions/{session_id}/documents/upload-async",
        files=[("files", ("a.md", b"# A\n\nHlorofill-a 1.85 mg/m3 v more.\n",
                          "text/markdown"))],
        data={"category": "temp_literature"},
        headers=researcher)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["task_id"]
    assert body["total"] == 1

    # Ждём завершения задачи: индексация идёт в фоне.
    task = await _wait_task(tasks, body["task_id"])
    assert task.status.value == "done", task.error
    assert task.result["total"] == 1
    assert len(task.result["added"]) == 1

    # Документ попал в реестр сессии.
    listed = await client.get(f"/api/sessions/{session_id}/documents", headers=researcher)
    assert [d["title"] for d in listed.json()] == ["a"]


async def test_upload_async_reports_failures_per_file(client, researcher,
                                                       session_id,
                                                       stub_registry) -> None:
    """Плохой файл не роняет пачку: его причина попадает в результат задачи."""
    from app.services.tasks import tasks

    response = await client.post(
        f"/api/sessions/{session_id}/documents/upload-async",
        files=[("files", ("bad.unknownext", b"\x00\x01", "application/octet-stream"))],
        headers=researcher)

    # Неподдерживаемое расширение отсекается на сохранении — ответ с ошибкой.
    assert response.status_code in (200, 422)
    if response.status_code == 200:
        task = await _wait_task(tasks, response.json()["task_id"])
        assert task.result["failed"] or task.result["added"]


async def _wait_task(tasks, task_id: str, wait_seconds: float = 30.0):
    """Дождаться завершения фоновой задачи."""
    import asyncio

    deadline = asyncio.get_running_loop().time() + wait_seconds
    while asyncio.get_running_loop().time() < deadline:
        task = tasks.get(task_id)
        if task is not None and task.finished:
            return task
        await asyncio.sleep(0.05)
    raise AssertionError(f"задача {task_id} не завершилась за {wait_seconds}с")


async def test_add_document_by_path_can_force_reindex(client, researcher,
                                                      session_id, stub_registry,
                                                      paper) -> None:
    """Повторное добавление того же файла — с переиндексацией.

    Без `force_reindex` сервер отвечает 409 (дедуп по содержимому); с ним
    документ переиндексируется — это нужно после смены настроек индексации.
    """
    first = await client.post(
        f"/api/sessions/{session_id}/documents/path",
        json={"path": str(paper)}, headers=researcher)
    assert first.status_code == 200, first.text

    duplicate = await client.post(
        f"/api/sessions/{session_id}/documents/path",
        json={"path": str(paper)}, headers=researcher)
    assert duplicate.status_code == 409
    assert "force_reindex" in duplicate.json()["detail"]

    forced = await client.post(
        f"/api/sessions/{session_id}/documents/path",
        json={"path": str(paper), "force_reindex": True}, headers=researcher)
    assert forced.status_code == 200, forced.text
    assert forced.json()["dockey"] == first.json()["dockey"]

    # Документ по-прежнему один: версия обновилась, а не добавилась вторая.
    listed = await client.get(f"/api/sessions/{session_id}/documents", headers=researcher)
    assert [d["dockey"] for d in listed.json()] == [first.json()["dockey"]]


async def test_upload_with_replace_swaps_older_version(client, researcher,
                                                        session_id,
                                                        stub_registry) -> None:
    """Файл с тем же именем заменяет прежнюю версию, а не ложится рядом.

    Дедуп PaperQA идёт по содержимому: изменённый файл получил бы новый
    dockey и стал бы вторым документом, а старая версия осталась бы в индексе.
    """
    first = await client.post(
        f"/api/sessions/{session_id}/documents/upload-async",
        files=[("files", ("otchet.md", b"# Otchet\n\nHlorofill-a 1.85 mg/m3.\n",
                          "text/markdown"))],
        headers=researcher)
    assert first.status_code == 200, first.text
    task = await _wait_task(tasks_registry(), first.json()["task_id"])
    assert task.result["added"]

    # Тот же файл, но с другим содержимым, и с replace.
    second = await client.post(
        f"/api/sessions/{session_id}/documents/upload-async",
        files=[("files", ("otchet.md", b"# Otchet\n\nHlorofill-a 2.10 mg/m3 v more.\n",
                          "text/markdown"))],
        data={"replace": "true"},
        headers=researcher)
    assert second.status_code == 200, second.text
    task = await _wait_task(tasks_registry(), second.json()["task_id"])
    assert task.result["added"], task.result

    listed = await client.get(f"/api/sessions/{session_id}/documents", headers=researcher)
    titles = [d["title"] for d in listed.json()]
    assert titles == ["otchet"], "прежняя версия должна исчезнуть, а не остаться рядом"
    # Имя файла — исходное, без технического префикса временного файла.
    assert listed.json()[0]["filename"] == "otchet.md"


def tasks_registry():
    from app.services.tasks import tasks

    return tasks


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
# --------------------------------------------------------------------------- админ: правка профиля
async def test_admin_changes_username_and_full_name(client, admin, researcher) -> None:
    users = (await client.get("/api/admin/users", headers=admin)).json()
    target = next(u for u in users if u["username"] == "ivanov")

    response = await client.patch(
        f"/api/admin/users/{target['id']}",
        json={"username": "ivanov.i", "full_name": "Иванов Иван Иванович"},
        headers=admin,
    )

    assert response.status_code == 200, response.text
    assert response.json()["username"] == "ivanov.i"
    assert response.json()["full_name"] == "Иванов Иван Иванович"


async def test_admin_cannot_take_existing_username(client, admin, researcher) -> None:
    users = (await client.get("/api/admin/users", headers=admin)).json()
    target = next(u for u in users if u["username"] == "ivanov")

    response = await client.patch(
        f"/api/admin/users/{target['id']}",
        json={"username": "admin"},
        headers=admin,
    )

    assert response.status_code == 409
    assert "уже существует" in response.json()["detail"]


async def test_admin_can_clear_full_name(client, admin, researcher) -> None:
    users = (await client.get("/api/admin/users", headers=admin)).json()
    target = next(u for u in users if u["username"] == "ivanov")

    response = await client.patch(
        f"/api/admin/users/{target['id']}",
        json={"full_name": ""},
        headers=admin,
    )

    assert response.status_code == 200, response.text
    assert response.json()["full_name"] == ""


async def test_username_too_short_rejected(client, admin, researcher) -> None:
    users = (await client.get("/api/admin/users", headers=admin)).json()
    target = next(u for u in users if u["username"] == "ivanov")

    response = await client.patch(
        f"/api/admin/users/{target['id']}",
        json={"username": "x"},
        headers=admin,
    )

    assert response.status_code == 422


async def test_new_username_works_in_login(client, admin, researcher) -> None:
    users = (await client.get("/api/admin/users", headers=admin)).json()
    target = next(u for u in users if u["username"] == "ivanov")
    await client.patch(f"/api/admin/users/{target['id']}",
                       json={"username": "ivanov.i"}, headers=admin)

    ok = await client.post("/api/auth/login",
                           json={"username": "ivanov.i",
                                 "password": "researcher-pass-123"})
    old = await client.post("/api/auth/login",
                            json={"username": "ivanov",
                                  "password": "researcher-pass-123"})
    assert ok.status_code == 200, ok.text
    assert old.status_code == 403  # старый логин больше не существует


async def test_researcher_cannot_open_admin_routes(client, researcher) -> None:
    assert (await client.get("/api/admin/documents",
                             headers=researcher)).status_code == 403
    assert (await client.get("/api/admin/users",
                             headers=researcher)).status_code == 403


async def test_global_documents_are_admin_only(client, admin, researcher) -> None:
    assert (await client.get("/api/admin/documents", headers=admin)).status_code == 200
    assert (await client.get("/api/admin/documents", headers=researcher)).status_code == 403


async def test_bulk_async_indexes_in_background_and_registers_documents(
        client, admin, stub_registry) -> None:
    """Фоновая индексация пачки: task_id сразу, документы в глобальной базе.

    Фоновая задача работает в своей сессии БД: сессия запроса к моменту её
    старта уже закрыта.
    """
    from app.services.tasks import tasks

    directory = stub_registry.app.documents_dir / "incoming"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "paper.md"
    path.write_text("# Статья\n\nХлорофилл-а 1.85 мг/м3 в Баренцевом море.\n",
                    encoding="utf-8")

    response = await client.post("/api/admin/documents/bulk-async",
                                 json={"paths": [str(path)]}, headers=admin)
    assert response.status_code == 200, response.text
    task_id = response.json()["task_id"]

    task = await _wait_task(tasks, task_id)
    assert task.status.value == "done", task.error
    assert len(task.result["added"]) == 1

    listed = await client.get("/api/admin/documents", headers=admin)
    assert [d["filename"] for d in listed.json()] == ["paper.md"]


async def test_bulk_async_rejects_paths_outside_allowed_dirs(client, admin,
                                                              stub_registry,
                                                              tmp_path) -> None:
    """Путь проверяется как в `bulk_add`: мимо каталога данных — нельзя.

    Без проверки админ проиндексировал бы любой файл на диске, обойдя
    `ALLOW_EXTERNAL_IMPORT_PATHS`.
    """
    outside = tmp_path / "секрет.md"
    outside.write_text("# Секрет\n\nВнутренний документ компании.\n", encoding="utf-8")

    response = await client.post("/api/admin/documents/bulk-async",
                                 json={"paths": [str(outside)]}, headers=admin)

    assert response.status_code in (403, 404)
    assert response.json().get("error") in ("forbidden", "not_found")