"""Уборка артефактов сессии: файлы и коллекция чанков.

Проверяем главное — purge сессии не имеет права удалять чужие файлы.
Исследователь вправе добавить в сессию файл из общей библиотеки
(`documents_dir`): такой документ лежит в каталоге сессии, а его файл — в
каталоге глобальной базы. Если purge съест и его, файл глобальной базы
исчезнет с диска, а запись в реестре и индекс останутся.
"""

from __future__ import annotations

import pytest

from app.db.models import DocumentCategory, DocumentVisibility
from app.db.repositories.documents import upsert_document
from app.db.repositories.users import create_research_session
from app.services.session_cleanup import (
    owned_paths,
    purge_session_artifacts,
    remove_session_files,
)
from tests.conftest import login_headers


@pytest.fixture
async def researcher(client, researcher_user):
    return await login_headers(client, "ivanov", "researcher-pass-123")


@pytest.fixture
async def session_id(client, researcher):
    response = await client.post("/api/sessions", json={"title": "Сессия"},
                                 headers=researcher)
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.fixture
def paper(stub_registry):
    """Файл в разрешённом каталоге (внутри data_dir)."""
    directory = stub_registry.app.documents_dir / "incoming"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "biomass.md"
    path.write_text(
        "# Биомасса водорослей\n\n"
        "Биомасса измеряется методом GF/F — отношением сухого вещества к сырому.\n",
        encoding="utf-8")
    return path


@pytest.fixture
def user(db):
    from app.core.security import hash_password

    from app.db.repositories.users import create_user

    return create_user(db, username="ivanov", password="password-1234",
                       hashed_password=hash_password("password-1234"))


@pytest.fixture
def session(db, user):
    return create_research_session(db, user, "Сессия для уборки")


# --------------------------------------------------------------------------- owned_paths
def test_owned_paths_keeps_only_session_files(stub_registry, session) -> None:
    """Файл сессии — наш; файл общей библиотеки — чужой."""
    session_dir = stub_registry.app.sessions_dir / session.id / "uploads"
    session_dir.mkdir(parents=True, exist_ok=True)
    mine = session_dir / "paper.md"
    mine.write_text("свой", encoding="utf-8")

    library = stub_registry.app.documents_dir / "library"
    library.mkdir(parents=True, exist_ok=True)
    foreign = library / "global.md"
    foreign.write_text("чужой", encoding="utf-8")

    owned = owned_paths(session.id, [str(mine), str(foreign)])

    assert owned == [mine.resolve()]


def test_owned_paths_ignores_missing_and_empty(stub_registry, session) -> None:
    assert owned_paths(session.id, ["", None]) == []  # type: ignore[list-item]


def test_remove_session_files_spares_foreign_files(stub_registry, session) -> None:
    """Главная гарантия: файл глобальной базы остаётся на месте."""
    session_dir = stub_registry.app.sessions_dir / session.id / "uploads"
    session_dir.mkdir(parents=True, exist_ok=True)
    mine = session_dir / "paper.md"
    mine.write_text("свой", encoding="utf-8")

    library = stub_registry.app.documents_dir / "library"
    library.mkdir(parents=True, exist_ok=True)
    foreign = library / "global.md"
    foreign.write_text("чужой", encoding="utf-8")

    removed = remove_session_files(session.id, [str(mine), str(foreign)])

    assert removed == 1
    assert not mine.exists()
    assert foreign.exists(), "файл глобальной базы нельзя удалять вместе с сессией"


# --------------------------------------------------------------------------- purge
async def test_purge_session_artifacts_clears_files_and_chunks(stub_registry,
                                                               db, user,
                                                               session) -> None:
    session_dir = stub_registry.app.sessions_dir / session.id / "uploads"
    session_dir.mkdir(parents=True, exist_ok=True)
    stored = session_dir / "paper.md"
    stored.write_text("# Статья\n\nХлорофилл 1.85.\n", encoding="utf-8")

    upsert_document(db, dockey="d1", docname="paper", title="Статья",
                    filename="paper.md", path=str(stored), size_bytes=10,
                    category=DocumentCategory.temp_literature,
                    visibility=DocumentVisibility.session, session_id=session.id,
                    owner_user_id=user.id, added_by=user.id)
    await stub_registry.session_service(session.id).add_file(stored,
                                                             session_id=session.id)

    cleaned = await purge_session_artifacts(session.id, [str(stored)])

    assert cleaned["files_removed"] == 1
    assert cleaned["chunks_removed"] >= 1
    assert not stored.exists()

    # Коллекция чанков очищена — иначе persist_state при остановке вернул бы
    # удалённые документы обратно в хранилище.
    from app.services.pqa_registry import session_collection

    collection = session_collection(session.id)
    assert await stub_registry.store.list_documents(collection) == []


async def test_purge_session_artifacts_keeps_foreign_files(stub_registry,
                                                            db, user,
                                                            session) -> None:
    """Полный сценарий: файл общей базы в сессии → purge → файл уцелел.

    Идём через репозиторий (`session_document_paths`), а не напрямую: именно
    он отдаёт reaper'у пути для удаления.
    """
    from app.db.repositories.documents import session_document_paths

    library = stub_registry.app.documents_dir / "library"
    library.mkdir(parents=True, exist_ok=True)
    foreign = library / "global.md"
    foreign.write_text("общая база", encoding="utf-8")

    upsert_document(db, dockey="g1", docname="global", title="Общий",
                    filename="global.md", path=str(foreign), size_bytes=10,
                    category=DocumentCategory.temp_literature,
                    visibility=DocumentVisibility.session, session_id=session.id,
                    owner_user_id=user.id, added_by=user.id)

    # Репозиторий отдаёт для удаления только файлы сессии.
    assert session_document_paths(db, session.id) == []

    cleaned = await purge_session_artifacts(
        session.id, session_document_paths(db, session.id))

    assert cleaned["files_removed"] == 0
    assert foreign.exists(), "файл глобальной базы нельзя удалять вместе с сессией"


# --------------------------------------------------------------------------- API
async def test_delete_session_removes_files_and_chunks(client, stub_registry,
                                                        researcher, session_id,
                                                        paper) -> None:
    """Явное удаление сессии чистит файлы и чанки, а не только записи БД."""
    response = await client.post(
        f"/api/sessions/{session_id}/documents/path",
        json={"path": str(paper), "category": "project_data"},
        headers=researcher)
    assert response.status_code == 200, response.text

    stored = stub_registry.app.sessions_dir / session_id / "uploads"
    owned = list(stored.rglob("*")) if stored.exists() else []
    owned = [p for p in owned if p.is_file()]

    deleted = await client.delete(f"/api/sessions/{session_id}", headers=researcher)
    assert deleted.status_code == 204

    for path in owned:
        assert not path.exists(), f"файл сессии не удалён: {path}"

    from app.services.pqa_registry import session_collection

    collection = session_collection(session_id)
    assert await stub_registry.store.list_documents(collection) == []
