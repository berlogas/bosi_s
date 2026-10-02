"""Фаза 5 — воркеры: heartbeat по арендам и reaper (архив + purge)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.errors import NotFoundError
from app.core.leases import LeaseRegistry
from app.db.models import SessionStatus, utcnow
from app.db.repositories.users import create_research_session, create_user, get_owned_session


@pytest.fixture
def factory(db_engine, monkeypatch):
    """Фабрика сессий, направленная на тестовую БД (для воркеров)."""
    import app.db.session as session_module

    monkeypatch.setattr(
        session_module, "_session_factory",
        sessionmaker(bind=db_engine, expire_on_commit=False, future=True))
    return session_module.get_session_factory


@pytest.fixture
def leases():
    """Глобальный реестр аренд (его же использует heartbeat-воркер)."""
    from app.core.leases import leases as global_leases

    global_leases.clear()
    yield global_leases
    global_leases.clear()


@pytest.fixture
def user(db):
    from app.core.security import hash_password

    return create_user(db, username="ivanov", password="password-1234",
                       hashed_password=hash_password("password-1234"))


# --------------------------------------------------------------------------- аренды
def test_lease_registry_lifecycle() -> None:
    registry = LeaseRegistry()
    assert registry.live() == []

    registry.touch("s1", ttl_seconds=60)
    assert registry.is_live("s1") and registry.live() == ["s1"]

    registry.touch("s1", ttl_seconds=0)  # истёкшая аренда
    assert not registry.is_live("s1")
    assert registry.live() == []

    registry.touch("s2", 60)
    registry.drop("s2")
    assert registry.live() == []


def test_lease_registry_stats() -> None:
    registry = LeaseRegistry()
    registry.touch("s1", 60)
    assert registry.stats() == {"live": 1}


# --------------------------------------------------------------------------- heartbeat
async def test_heartbeat_touches_only_leased_sessions(factory, db, leases, user) -> None:
    from app.workers.heartbeat import heartbeat_once

    open_session = create_research_session(db, user, "Открыта")
    idle_session = create_research_session(db, user, "Забыта")
    open_before = open_session.expires_at
    idle_before = idle_session.expires_at
    db.commit()

    leases.touch(open_session.id, 300)

    assert await heartbeat_once() == 1

    db.expire_all()
    assert db.get(type(open_session), open_session.id).expires_at >= open_before
    assert db.get(type(idle_session), idle_session.id).expires_at == idle_before


async def test_heartbeat_drops_archived_session(factory, db, leases, user) -> None:
    from app.workers.heartbeat import heartbeat_once

    session = create_research_session(db, user, "Архив")
    session.status = SessionStatus.archived
    session.archived_at = utcnow()
    before = session.expires_at
    db.commit()
    leases.touch(session.id, 300)

    assert await heartbeat_once() == 0

    db.expire_all()
    stored = db.get(type(session), session.id)
    assert stored.expires_at == before  # архив не продлевается
    assert leases.is_live(session.id) is False


async def test_heartbeat_without_leases_is_noop(factory, db, leases, user) -> None:
    from app.workers.heartbeat import heartbeat_once

    session = create_research_session(db, user, "Тихая")
    before = session.expires_at
    db.commit()

    assert await heartbeat_once() == 0
    assert session.expires_at == before


# --------------------------------------------------------------------------- reaper
async def test_reaper_archives_expired_session(factory, db, user) -> None:
    from app.workers.reaper import reaper_once

    fresh = create_research_session(db, user, "Свежая")
    stale = create_research_session(db, user, "Протухшая")
    stale.expires_at = utcnow() - timedelta(days=1)
    db.commit()

    result = await reaper_once()

    assert result["archived"] == 1
    db.expire_all()
    assert db.get(type(stale), stale.id).status is SessionStatus.archived
    assert db.get(type(fresh), fresh.id).status is SessionStatus.active


async def test_reaper_purges_old_archive(factory, db, user, tmp_path,
                                         stub_registry) -> None:
    from app.db.models import DocumentCategory, DocumentVisibility
    from app.db.repositories.documents import upsert_document
    from app.workers.reaper import reaper_once

    session = create_research_session(db, user, "Старая")
    # файл сессии в её собственном каталоге + чанки в индексе
    session_dir = stub_registry.app.sessions_dir / session.id / "uploads"
    session_dir.mkdir(parents=True, exist_ok=True)
    stored_file = session_dir / "paper.md"
    stored_file.write_text("# Статья\n\nХлорофилл 1.85.\n", encoding="utf-8")

    upsert_document(db, dockey="d1", docname="paper", title="Статья",
                    filename="paper.md", path=str(stored_file), size_bytes=10,
                    category=DocumentCategory.temp_literature,
                    visibility=DocumentVisibility.session, session_id=session.id,
                    owner_user_id=user.id, added_by=user.id)
    await stub_registry.session_service(session.id).add_file(stored_file,
                                                            session_id=session.id)
    session.status = SessionStatus.archived
    session.archived_at = utcnow() - timedelta(days=session_ttl_days())
    db.commit()

    result = await reaper_once()

    assert result["purged"] == 1
    assert result["files_removed"] == 1
    assert result["chunks_removed"] >= 1
    assert not stored_file.exists()
    db.expire_all()
    stored = db.get(type(session), session.id)
    assert stored.purged_at is not None
    with pytest.raises(NotFoundError):
        get_owned_session(db, session.id, user)


def session_ttl_days() -> int:
    from app.config import get_settings

    return get_settings().session_ttl_days


async def test_reaper_keeps_fresh_archive(factory, db, user) -> None:
    from app.workers.reaper import reaper_once

    session = create_research_session(db, user, "Свежий архив")
    session.status = SessionStatus.archived
    session.archived_at = utcnow() - timedelta(days=5)
    db.commit()

    result = await reaper_once()

    assert result["purged"] == 0
    assert session.purged_at is None


async def test_reaper_purges_expired_refresh_tokens(factory, db, user) -> None:
    from app.core.security import hash_token
    from app.db.models import RefreshToken
    from app.workers.reaper import reaper_once

    db.add(RefreshToken(user_id=user.id, token_hash=hash_token("old"),
                        expires_at=utcnow() - timedelta(days=30)))
    db.add(RefreshToken(user_id=user.id, token_hash=hash_token("fresh"),
                        expires_at=utcnow() + timedelta(days=5)))
    db.commit()

    result = await reaper_once()

    assert result["refresh_tokens"] == 1
    assert db.query(RefreshToken).count() == 1


def test_remove_files_cleans_empty_dirs(tmp_path) -> None:
    from app.workers.reaper import remove_files

    deep = tmp_path / "sessions" / "abc" / "uploads"
    deep.mkdir(parents=True)
    first = deep / "a.md"
    second = deep / "b.md"
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")
    keeper = tmp_path / "sessions" / "abc" / "other.txt"
    keeper.write_text("keep", encoding="utf-8")

    assert remove_files([str(first), str(second)]) == 2
    assert not first.exists() and not deep.exists()
    assert keeper.exists()  # непустой каталог не трогаем


def test_remove_files_ignores_missing(tmp_path) -> None:
    from app.workers.reaper import remove_files

    assert remove_files([str(tmp_path / "нет.md")]) == 0
    assert remove_files([]) == 0