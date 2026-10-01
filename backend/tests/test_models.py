"""Модели, ограничения и миграции."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.core.errors import ConflictError, NotFoundError
from app.core.security import hash_password
from app.db.models import (
    AuditLog,
    Document,
    DocumentCategory,
    DocumentVisibility,
    Message,
    Project,
    Role,
    SearchMode,
    SessionStatus,
    new_id,
    utcnow,
)
from app.db.repositories.users import (
    create_research_session,
    create_user,
    expire_due_sessions,
    get_owned_session,
    list_user_sessions,
    session_storage_bytes,
    touch_session,
)


def _user(db, username="u1", role=Role.researcher):
    return create_user(db, username=username, password="password-1234", role=role,
                       hashed_password=hash_password("password-1234"))


def test_unique_username(db) -> None:
    _user(db, "dup")
    with pytest.raises(ConflictError):
        _user(db, "dup")


def test_cascade_delete_session_documents(db) -> None:
    user = _user(db)
    session = create_research_session(db, user, "Проект")
    db.add(Document(session_id=session.id, owner_user_id=user.id, added_by=user.id,
                    category=DocumentCategory.project_data,
                    visibility=DocumentVisibility.session,
                    title="Данные", filename="data.csv", path="/tmp/data.csv",
                    size_bytes=1024))
    db.commit()
    assert len(session.documents) == 1

    db.delete(session)
    db.commit()
    assert db.scalars(select(Document)).all() == []


def test_foreign_keys_enforced(db) -> None:
    with pytest.raises(IntegrityError):
        db.add(Project(session_id="nonexistent", title="X"))
        db.commit()


def test_session_limits_from_spec(db, monkeypatch) -> None:
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "max_sessions_per_user", 3, raising=False)
    user = _user(db)
    for i in range(3):
        create_research_session(db, user, f"Сессия {i}")
    with pytest.raises(ConflictError) as exc:
        create_research_session(db, user, "Лишняя")
    assert exc.value.meta["limit"] == 3


def test_touch_session_extends_ttl(db) -> None:
    from app.config import get_settings

    user = _user(db)
    session = create_research_session(db, user, "TTL")

    session.expires_at = utcnow() - timedelta(days=1)  # искусственно «истёкшая»
    db.commit()

    touch_session(db, session, action_type="chat", action_label="Анализ введения",
                  note="найти Smith 2023")
    assert session.expires_at > utcnow() + timedelta(days=89)  # TTL продлён на 90 дней
    assert session.last_action_type == "chat"
    assert session.resume_note == "найти Smith 2023"
    assert (session.expires_at - session.last_activity_at).days == get_settings().session_ttl_days


def test_expire_due_sessions_archives(db) -> None:
    user = _user(db)
    fresh = create_research_session(db, user, "Свежая")
    stale = create_research_session(db, user, "Протухшая")
    stale.expires_at = utcnow() - timedelta(days=1)
    db.commit()

    archived = expire_due_sessions(db)
    assert archived == [stale.id]
    assert stale.status is SessionStatus.archived
    assert stale.archived_at is not None
    assert fresh.status is SessionStatus.active


def test_session_ownership_isolation(db) -> None:
    alice = _user(db, "alice")
    bob = _user(db, "bob")
    admins = _user(db, "root", Role.admin)
    session = create_research_session(db, alice, "Личное")

    assert get_owned_session(db, session.id, alice).id == session.id
    with pytest.raises(NotFoundError):
        get_owned_session(db, session.id, bob)
    assert get_owned_session(db, session.id, admins).id == session.id  # админ видит все


def test_list_user_sessions_sorted_by_activity(db) -> None:
    user = _user(db)
    first = create_research_session(db, user, "Первая")
    second = create_research_session(db, user, "Вторая")
    first.last_activity_at = utcnow() - timedelta(days=2)
    db.commit()

    titles = [s.title for s in list_user_sessions(db, user.id)]
    assert titles[0] == "Вторая"
    assert set(titles) == {"Первая", "Вторая"}
    assert second.id in {s.id for s in list_user_sessions(db, user.id)}


def test_document_storage_sum(db) -> None:
    user = _user(db)
    session = create_research_session(db, user, "Данные")
    for size in (100, 250):
        db.add(Document(session_id=session.id, owner_user_id=user.id, added_by=user.id,
                        title=f"f{size}", filename=f"f{size}.csv", path=f"/tmp/{size}",
                        size_bytes=size))
    db.commit()
    assert session_storage_bytes(db, session.id) == 350


def test_message_supports_quick_chat_without_session(db) -> None:
    user = _user(db)
    db.add(Message(user_id=user.id, session_id=None, role="user", content="Что такое CTD-зонд?",
                   mode=SearchMode.global_only))
    db.commit()
    stored = db.scalars(select(Message)).one()
    assert stored.session_id is None
    assert stored.mode is SearchMode.global_only


def test_audit_log_fields(db) -> None:
    from app.db.repositories.users import audit

    user = _user(db)
    entry = audit(db, action="admin.documents.upload", actor=user, target_type="document",
                  target_id=new_id(), ip="127.0.0.1", files=3)
    assert isinstance(entry, AuditLog)
    assert entry.actor_username == "u1"
    assert entry.meta["files"] == 3


def test_research_session_defaults(db) -> None:
    user = _user(db)
    session = create_research_session(db, user, "  Название  ")
    assert session.title == "Название"
    assert session.status is SessionStatus.active
    assert session.state_snapshot == {}
    assert session.archived_at is None


def test_alembic_migration_is_head_for_metadata() -> None:
    """Миграция из Фазы 1 покрывает всю текущую схему моделей."""
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from app.db.models import Base

    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(cfg)
    head = scripts.get_current_head()
    assert head is not None, "нет ни одной миграции"

    versions_dir = Path(scripts.versions)
    migration_files = list(versions_dir.glob("*.py"))
    assert migration_files, "каталог миграций пуст"

    created_tables: set[str] = set()
    for file in migration_files:
        text = file.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "op.create_table(" in line:
                created_tables.add(line.split("op.create_table(")[1].strip().strip("',"))

    assert set(Base.metadata.tables) - {"alembic_version"} <= created_tables


def test_engine_tables_created(db_engine) -> None:
    inspector = inspect(db_engine)
    tables = set(inspector.get_table_names())
    assert {"users", "research_sessions", "documents", "projects", "document_links",
            "messages", "audit_log", "refresh_tokens"} <= tables