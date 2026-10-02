"""Фаза 5 — сквозной сценарий ТЗ: понедельник → пятница → 2 месяца → 100 дней.

Проверяем DoD фазы:
  * сессия переживает работу с документами и заметками;
  * через 2 месяца тишины сессия жива и возвращает точку возврата;
  * через 100 дней без работы reaper архивирует её (только чтение);
  * после «рестарта процесса» сессия восстанавливается с документами,
    историей и заметками, а эмбеддинги не пересчитываются.

LLM не используется (заглушка), эмбеддинги — локальные sentence-transformers.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.errors import ConflictError
from app.core.leases import leases
from app.core.security import hash_password
from app.db.models import (
    DocumentCategory,
    DocumentVisibility,
    Message,
    Role,
    SessionStatus,
    utcnow,
)
from app.db.repositories import documents as docs_repo
from app.db.repositories import sessions as sessions_repo
from app.db.repositories.users import create_research_session, create_user
from app.services.paperqa_service import PaperQA2Service, session_collection


@pytest.fixture
def scenario(db_engine, service_app, chunk_store, stub_llm, monkeypatch):
    """Окружение сценария: фабрика сессий БД и заготовка сервиса."""
    monkeypatch.setattr(
        "app.db.session._session_factory",
        sessionmaker(bind=db_engine, expire_on_commit=False, future=True))

    with sessionmaker(bind=db_engine, expire_on_commit=False)() as db:
        user = create_user(db, username="ivanov", password="password-1234",
                           role=Role.researcher,
                           hashed_password=hash_password("password-1234"))
        db.commit()
        user_id = user.id

    service_app.data_dir = service_app.data_dir.parent / "scenario"
    service_app.ensure_dirs()

    # reaper чистит чанки через глобальный реестр — он должен видеть то же хранилище
    from app.services import paperqa_service as svc

    monkeypatch.setattr(svc, "_registry", svc.ServiceRegistry(service_app, chunk_store))

    leases.clear()
    yield {
        "user_id": user_id,
        "app": service_app,
        "chunk_store": chunk_store,
        "llm": stub_llm,
        "factory": lambda: sessionmaker(bind=db_engine,
                                        expire_on_commit=False)(),
    }
    leases.clear()


def _days_ago(days: int):
    return utcnow() - timedelta(days=days)


def _remember(db, session, *, tab: str, note: str | None = None) -> None:
    sessions_repo.save_state(
        db, session, snapshot={"tab": tab, "chat_scroll": 0},
        note=note, action_type="session.state", action_label=f"Вкладка {tab}")


def _add_message(db, session, question: str, answer: str) -> None:
    db.add(Message(user_id=session.user_id, session_id=session.id, role="user",
                   content=question))
    db.add(Message(user_id=session.user_id, session_id=session.id, role="assistant",
                   content=answer, mode=None))
    db.commit()


# --------------------------------------------------------------------------- сценарий
async def test_full_session_scenario(scenario, db_engine, tmp_path) -> None:
    from app.workers.heartbeat import heartbeat_once
    from app.workers.reaper import reaper_once

    user_id = scenario["user_id"]
    factory = scenario["factory"]
    app_settings = scenario["app"]

    literature = tmp_path / "kuznetsov_2019.md"
    literature.write_text(
        "# Кузнецов и др., 2019\n\n"
        "Биомасса водорослей в Баренцеве море измеряется методом GF/F.\n"
        "Хлорофилл-а определяют в ацетоне на спектрофотометре.\n",
        encoding="utf-8")
    data = tmp_path / "biomass.csv"
    data.write_text("station,depth_m,gf_f\nBS1,0,0.42\nBS2,10,0.28\n", encoding="utf-8")

    # ---------------------------------------------------------------- понедельник
    with factory() as db:
        session = create_research_session(db, _load_user(db, user_id), "Баренцево море, 2019")
        session_id = session.id

    def new_service() -> PaperQA2Service:
        """Новый экземпляр сервиса — эмуляция перезапуска процесса."""
        return PaperQA2Service(app_settings, session_collection(session_id),
                               scenario["chunk_store"], llm_model=scenario["llm"])

    collection = session_collection(session_id)
    service = new_service()

    with factory() as db:
        stored = _get_session(db, session_id)
        assert stored.status is SessionStatus.active
        assert stored.expires_at > utcnow() + timedelta(days=89)

        refs = await service.add_files([literature, data], session_id=session_id,
                                       category=DocumentCategory.temp_literature)
        assert len(refs.added) == 2

        for ref, source in zip(refs.added, (literature, data), strict=True):
            docs_repo.upsert_document(
                db, dockey=ref.dockey, docname=ref.docname, title=ref.title,
                filename=source.name, path=ref.path, size_bytes=ref.size_bytes,
                pages=ref.pages, chunk_count=ref.chunk_count, citation=ref.citation,
                content_hash=ref.content_hash,
                category=DocumentCategory.temp_literature,
                visibility=DocumentVisibility.session, session_id=session_id,
                owner_user_id=user_id, added_by=user_id, tags=["Баренцево"])
        _add_message(db, stored, "Как измеряют биомассу?", "Методом GF/F [1].")
        _remember(db, stored, tab="documents")

    with factory() as db:
        assert docs_repo.count_documents(db, session_id) == 2
        assert sessions_repo.state_snapshot(_get_session(db, session_id))["tab"] == "documents"

    # ---------------------------------------------------------------- пятница
    with factory() as db:
        stored = _get_session(db, session_id)
        notes = tmp_path / "notes.md"
        notes.write_text("# Заметки\n\nПроверить Smith 2023 по GF/F.\n", encoding="utf-8")
        ref = await service.add_file(notes, session_id=session_id)
        docs_repo.upsert_document(
            db, dockey=ref.dockey, docname=ref.docname, title="Заметки пятницы",
            filename=notes.name, path=ref.path, size_bytes=ref.size_bytes,
            chunk_count=ref.chunk_count, category=DocumentCategory.notes,
            visibility=DocumentVisibility.session, session_id=session_id,
            owner_user_id=user_id, added_by=user_id, tags=["заметки"])
        _remember(db, stored, tab="chat", note="не забыть Smith 2023")
        friday_expiry = stored.expires_at
    assert friday_expiry > utcnow() + timedelta(days=89)

    # ------------------------------------------------- два месяца тишины (heartbeat)
    with factory() as db:
        stored = _get_session(db, session_id)
        stored.expires_at = _days_ago(1)  # как будто давно не открывали
        db.commit()

    leases.touch(session_id, 600)
    assert await heartbeat_once() == 1  # сессия открыта в UI -> TTL продлён

    with factory() as db:
        stored = _get_session(db, session_id)
        assert stored.expires_at > utcnow() + timedelta(days=89)
        assert sessions_repo.days_left(stored) >= 89

    # ------------------------------------------------ 100 дней без работы -> архив
    with factory() as db:
        stored = _get_session(db, session_id)
        stored.expires_at = _days_ago(1)
        db.commit()
    leases.drop(session_id)

    result = await reaper_once()
    assert result["archived"] == 1

    with factory() as db:
        stored = _get_session(db, session_id)
        assert stored.status is SessionStatus.archived
        assert sessions_repo.days_left(stored) == 0
        with pytest.raises(ConflictError):
            sessions_repo.ensure_writable(stored)
        # содержимое на месте — сессия только читается
        assert docs_repo.count_documents(db, session_id) == 3
        assert db.query(Message).filter(Message.session_id == session_id).count() == 2
        assert stored.resume_note == "не забыть Smith 2023"

    # ------------------------------------------- «рестарт процесса»: память пуста
    restarted = new_service()
    assert restarted.list_documents() == []

    assert await restarted.restore_state() == 3
    assert len(restarted.list_documents()) == 3

    chunks_before, _ = await service.get_evidence("метод GF/F и хлорофилл-а")
    chunks_after, _ = await restarted.get_evidence("метод GF/F и хлорофилл-а")
    assert [(c.dockey, c.score) for c in chunks_before] == [
        (c.dockey, c.score) for c in chunks_after]

    # восстановленный индекс принадлежит коллекции этой сессии
    assert len(await scenario["chunk_store"].list_documents(collection)) == 3

    # -------------------------------------------------- purge после retention
    with factory() as db:
        stored = _get_session(db, session_id)
        stored.archived_at = _days_ago(app_settings.archive_retention_days + 1)
        db.commit()

    result = await reaper_once()
    assert result["purged"] == 1
    assert result["chunks_removed"] == 3

    with factory() as db:
        assert docs_repo.count_documents(db, session_id) == 0
        from app.core.errors import NotFoundError
        from app.db.repositories.users import get_owned_session

        with pytest.raises(NotFoundError):
            get_owned_session(db, session_id, _load_user(db, user_id))


# --------------------------------------------------------------------------- хелперы
def _load_user(db, user_id):
    from app.db.models import User

    return db.get(User, user_id)


def _get_session(db, session_id):
    from app.db.models import ResearchSession

    return db.get(ResearchSession, session_id)