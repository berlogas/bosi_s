"""Фаза 5 — жизненный цикл сессий: лимиты, точка возврата, архив, purge.

Тесты идут на репозитории (без HTTP и без LLM), чтобы быстро фиксировать
поведение, на которое опирается API.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.errors import ConflictError, NotFoundError
from app.db.models import (
    DocumentCategory,
    DocumentLink,
    DocumentVisibility,
    Message,
    Project,
    ProjectDocRole,
    RelationType,
    SessionStatus,
    utcnow,
)
from app.db.repositories import documents as docs_repo
from app.db.repositories import sessions as sessions_repo
from app.db.repositories.users import (
    create_research_session,
    create_user,
    get_owned_session,
    list_user_sessions,
)


# --------------------------------------------------------------------------- фикстуры
@pytest.fixture
def user(db):
    from app.core.security import hash_password

    return create_user(db, username="ivanov", password="password-1234",
                       hashed_password=hash_password("password-1234"))


@pytest.fixture
def research_session(db, user):
    return create_research_session(db, user, "Биомасса Баренцева моря")


def _doc(db, session, dockey: str, size: int = 1024,
         category: DocumentCategory = DocumentCategory.temp_literature):
    return docs_repo.upsert_document(
        db, dockey=dockey, docname=dockey[:8], title=f"Документ {dockey[:6]}",
        filename=f"{dockey[:8]}.pdf", path=f"/data/{dockey[:8]}.pdf",
        size_bytes=size, category=category, visibility=DocumentVisibility.session,
        session_id=session.id, owner_user_id=session.user_id, added_by=session.user_id,
    )


# --------------------------------------------------------------------------- лимиты
def test_document_count_limit(db, research_session, monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_documents_per_session", 2, raising=False)
    _doc(db, research_session, "a1")
    _doc(db, research_session, "b2")

    with pytest.raises(ConflictError) as exc:
        docs_repo.check_document_limits(db, research_session.id)
    assert exc.value.meta["limit"] == 2
    assert exc.value.meta["current"] == 2
    assert exc.value.meta["resource"] == "documents"


def test_document_count_limit_ignores_duplicates(db, research_session, monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_documents_per_session", 2, raising=False)
    _doc(db, research_session, "a1")
    _doc(db, research_session, "b2")
    docs_repo.check_document_limits(db, research_session.id, incoming_count=0)  # ок


def test_storage_limit(db, research_session, monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_session_storage_mb", 1, raising=False)
    _doc(db, research_session, "a1", size=900 * 1024)

    with pytest.raises(ConflictError) as exc:
        docs_repo.check_document_limits(db, research_session.id,
                                        incoming_count=1,
                                        incoming_bytes=500 * 1024)
    assert exc.value.meta["resource"] == "storage"
    assert exc.value.meta["current"] == 900 * 1024


def test_project_limit(db, research_session, monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_projects_per_session", 2, raising=False)
    for i in range(2):
        db.add(Project(session_id=research_session.id, title=f"Проект {i}"))
    db.commit()

    with pytest.raises(ConflictError) as exc:
        docs_repo.check_project_limit(db, research_session.id)
    assert exc.value.meta["resource"] == "projects"


# --------------------------------------------------------------------------- реестр
def test_upsert_document_is_idempotent_by_dockey(db, research_session) -> None:
    first = _doc(db, research_session, "dockey-1")
    second = _doc(db, research_session, "dockey-1")

    assert first.id == second.id
    assert docs_repo.count_documents(db, research_session.id) == 1


def test_documents_of_other_session_are_not_seen(db, research_session, user) -> None:
    other = create_research_session(db, user, "Другая")
    _doc(db, research_session, "dockey-1")
    _doc(db, other, "dockey-2")

    mine = {d.dockey for d in docs_repo.list_documents(db, session_id=research_session.id)}
    theirs = {d.dockey for d in docs_repo.list_documents(db, session_id=other.id)}
    assert mine == {"dockey-1"}
    assert theirs == {"dockey-2"}


def test_list_documents_filtered_by_category(db, research_session) -> None:
    _doc(db, research_session, "d1", category=DocumentCategory.project_data)
    _doc(db, research_session, "d2", category=DocumentCategory.notes)

    only_data = docs_repo.list_documents(
        db, session_id=research_session.id, category=DocumentCategory.project_data)
    assert [d.dockey for d in only_data] == ["d1"]


def test_document_tags_and_category_update(db, research_session) -> None:
    document = _doc(db, research_session, "d1")

    updated = docs_repo.update_document(
        db, document.id, category=DocumentCategory.project_draft,
        tags=[" биомасса ", "Баренцево"], title="Черновик раздела")

    assert updated.category is DocumentCategory.project_draft
    assert updated.tags == ["биомасса", "Баренцево"]
    assert updated.title == "Черновик раздела"


def test_delete_document_row_returns_bool(db, research_session) -> None:
    document = _doc(db, research_session, "d1")
    assert docs_repo.delete_document_row(db, document.id) is True
    assert docs_repo.delete_document_row(db, document.id) is False
    assert docs_repo.find_document(db, session_id=research_session.id,
                                   dockey="d1") is None


def test_documents_summary_by_category(db, research_session) -> None:
    _doc(db, research_session, "d1", size=100, category=DocumentCategory.notes)
    _doc(db, research_session, "d2", size=250, category=DocumentCategory.notes)
    _doc(db, research_session, "d3", size=50, category=DocumentCategory.project_data)

    summary = docs_repo.documents_summary(db, research_session.id)
    assert summary["total"] == 3
    assert summary["storage_bytes"] == 400
    assert summary["by_category"]["notes"] == 2
    assert summary["by_category"]["project_data"] == 1


# --------------------------------------------------------------------------- связи
def test_document_links_lifecycle(db, research_session) -> None:
    document = _doc(db, research_session, "d1")
    project = Project(session_id=research_session.id, title="Статья")
    db.add(project)
    db.commit()

    link = docs_repo.link_document(
        db, document_id=document.id, session_id=research_session.id,
        project_id=project.id, role=ProjectDocRole.reference,
        relation=RelationType.supports, note="данные согласуются")

    assert link.id in {i.id for i in docs_repo.list_links(db, session_id=research_session.id)}
    assert link.relation is RelationType.supports
    assert link.role is ProjectDocRole.reference

    # повторный вызов с теми же ключами обновляет, а не дублирует
    again = docs_repo.link_document(
        db, document_id=document.id, session_id=research_session.id,
        project_id=project.id, note="уточнено")
    assert again.id == link.id
    assert len(docs_repo.list_links(db, session_id=research_session.id)) == 1
    assert again.note == "уточнено"

    assert docs_repo.unlink_document(db, link.id) is True
    assert docs_repo.unlink_document(db, link.id) is False


def test_links_are_removed_with_document(db, research_session) -> None:
    document = _doc(db, research_session, "d1")
    docs_repo.link_document(db, document_id=document.id,
                            session_id=research_session.id)
    db.commit()

    docs_repo.delete_document_row(db, document.id)
    assert db.query(DocumentLink).count() == 0


# --------------------------------------------------------------------------- точка возврата
def test_save_state_merges_snapshot_and_extends_ttl(db, research_session) -> None:
    research_session.expires_at = utcnow() + timedelta(days=1)
    db.commit()

    sessions_repo.save_state(
        db, research_session,
        snapshot={"tab": "documents", "chat_scroll": 42},
        action_type="session.state", action_label="Вкладка документов")

    assert research_session.state_snapshot["tab"] == "documents"
    assert research_session.state_snapshot["chat_scroll"] == 42
    assert research_session.state_snapshot["saved_at"]  # служебное поле
    assert research_session.expires_at > utcnow() + timedelta(days=89)


def test_save_state_skips_identical_snapshot(db, research_session) -> None:
    sessions_repo.save_state(db, research_session, snapshot={"tab": "chat"})
    first_saved_at = research_session.state_snapshot["saved_at"]

    _, written = sessions_repo.save_state(db, research_session, snapshot={"tab": "chat"})

    assert written is False
    assert research_session.state_snapshot["saved_at"] == first_saved_at


def test_save_state_without_payload_does_nothing(db, research_session) -> None:
    """Пустое сохранение — не пишем в БД (TTL продлечает отдельный heartbeat)."""
    research_session.expires_at = utcnow() + timedelta(days=1)
    db.commit()

    _, written = sessions_repo.save_state(db, research_session)

    assert written is False
    assert research_session.expires_at == utcnow() + timedelta(days=1)
    assert research_session.state_snapshot == {}


def test_state_snapshot_hides_meta_field(db, research_session) -> None:
    sessions_repo.save_state(db, research_session,
                             snapshot={"active_project": "p1"})
    assert sessions_repo.state_snapshot(research_session) == {"active_project": "p1"}
    assert sessions_repo.state_saved_at(research_session)


# --------------------------------------------------------------------------- статусы
def test_pause_and_reactivate(db, research_session) -> None:
    sessions_repo.pause_session(db, research_session, note="до пятницы")
    assert research_session.status is SessionStatus.paused
    assert research_session.resume_note == "до пятницы"

    sessions_repo.reactivate_session(db, research_session)
    assert research_session.status is SessionStatus.active


def test_archive_is_manual_and_marked(db, research_session) -> None:
    sessions_repo.archive_session(db, research_session, note="завершено")

    assert research_session.status is SessionStatus.archived
    assert research_session.archived_at is not None
    with pytest.raises(ConflictError):
        sessions_repo.ensure_writable(research_session)


def test_archived_session_cannot_be_reactivated(db, research_session) -> None:
    sessions_repo.archive_session(db, research_session)
    with pytest.raises(ConflictError) as exc:
        sessions_repo.reactivate_session(db, research_session)
    assert exc.value.meta["status"] == "archived"


def test_ensure_writable_allows_paused(db, research_session) -> None:
    sessions_repo.pause_session(db, research_session)
    assert sessions_repo.ensure_writable(research_session) is research_session


def test_days_left_never_negative(db, research_session) -> None:
    assert sessions_repo.days_left(research_session) == 90
    research_session.expires_at = utcnow() - timedelta(days=5)
    db.commit()
    assert sessions_repo.days_left(research_session) == 0


# --------------------------------------------------------------------------- purge
def _archive_long_ago(db, session, days: int) -> None:
    session.status = SessionStatus.archived
    session.archived_at = utcnow() - timedelta(days=days)
    db.commit()


def test_purge_expired_archives_marks_purged(db, research_session, user) -> None:
    _archive_long_ago(db, research_session, days=45)

    purged = sessions_repo.purge_expired_archives(db, retention_days=30)

    assert [p["session_id"] for p in purged] == [research_session.id]
    assert research_session.purged_at is not None
    assert research_session.purged_at >= utcnow() - timedelta(seconds=1)
    # purged-сессия исчезает из выдачи и больше не доступна
    assert all(s.id != research_session.id
               for s in list_user_sessions(db, research_session.user_id))
    with pytest.raises(NotFoundError):
        get_owned_session(db, research_session.id, user)


def test_purge_keeps_fresh_archive(db, research_session) -> None:
    _archive_long_ago(db, research_session, days=5)

    assert sessions_repo.purge_expired_archives(db, retention_days=30) == []
    assert research_session.purged_at is None


def test_purge_reports_file_paths(db, research_session) -> None:
    _doc(db, research_session, "d1")
    _archive_long_ago(db, research_session, days=100)

    purged = sessions_repo.purge_expired_archives(db, retention_days=30)
    assert purged[0]["paths"] == ["/data/d1.pdf"]
    assert purged[0]["title"] == research_session.title


def test_hard_delete_removes_session_and_children(db, research_session) -> None:
    _doc(db, research_session, "d1")
    db.add(Message(user_id=research_session.user_id, session_id=research_session.id,
                   role="user", content="Вопрос про биомассу"))
    db.commit()

    info = sessions_repo.hard_delete_session(db, research_session)

    assert info["paths"] == ["/data/d1.pdf"]
    assert db.get(type(research_session), research_session.id) is None
    assert db.query(Message).count() == 0


def test_purged_session_frees_slot_for_new_one(db, user) -> None:

    old = create_research_session(db, user, "Старая")
    _archive_long_ago(db, old, days=90)
    sessions_repo.purge_expired_archives(db, retention_days=30)

    # освободившийся слот можно занять (лимит считается без purged)
    fresh = create_research_session(db, user, "Новая")
    assert fresh.status is SessionStatus.active


# --------------------------------------------------------------------------- сводка
def test_session_summary_counts_everything(db, research_session, monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_projects_per_session", 5, raising=False)
    _doc(db, research_session, "d1", size=100)
    _doc(db, research_session, "d2", size=200, category=DocumentCategory.project_data)
    db.add(Project(session_id=research_session.id, title="P"))
    db.add(Message(user_id=research_session.user_id, session_id=research_session.id,
                   role="user", content="Q"))
    docs_repo.link_document(db, document_id=docs_repo.find_document(
        db, session_id=research_session.id, dockey="d1").id,
        session_id=research_session.id)
    db.commit()

    summary = sessions_repo.session_summary(db, research_session)

    assert summary["documents"] == 2
    assert summary["storage_bytes"] == 300
    assert summary["documents_limit"] == 50
    assert summary["projects"] == 1
    assert summary["messages"] == 1
    assert summary["links"] == 1
    assert summary["read_only"] is False


def test_session_summary_reports_read_only(db, research_session) -> None:
    sessions_repo.archive_session(db, research_session)
    summary = sessions_repo.session_summary(db, research_session)
    assert summary["read_only"] is True