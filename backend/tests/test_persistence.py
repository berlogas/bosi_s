"""Персистентность: чанки переживают пересоздание сервиса и рестарт процесса.

Инвариант Фазы 0 (спайк 03): после восстановления через `aadd_texts` оценки
контекста совпадают, эмбеддинги не пересчитываются.
"""

from __future__ import annotations

import pytest

from app.services.paperqa_service import PaperQA2Service, session_collection


def _service(app, store, llm, collection="global") -> PaperQA2Service:
    return PaperQA2Service(app, collection, store, llm_model=llm)


async def test_persist_restore_equivalent_scores(
    service_app, chunk_store, stub_llm, sample_text, sample_csv
) -> None:
    service = _service(service_app, chunk_store, stub_llm)
    await service.add_files([sample_text, sample_csv])

    chunks_before, _ = await service.get_evidence("метод GF/F и хлорофилл-а")

    restored_service = _service(service_app, chunk_store, stub_llm)
    assert restored_service.list_documents() == []  # память пуста
    assert await restored_service.restore_state() == 2

    chunks_after, _ = await restored_service.get_evidence("метод GF/F и хлорофилл-а")

    assert [(c.dockey, c.score) for c in chunks_before] == [
        (c.dockey, c.score) for c in chunks_after]


async def test_restore_state_is_idempotent(
    service_app, chunk_store, stub_llm, sample_text
) -> None:
    service = _service(service_app, chunk_store, stub_llm)
    await service.add_file(sample_text)

    second = _service(service_app, chunk_store, stub_llm)
    assert await second.restore_state() == 1
    assert await second.restore_state() == 0  # повторно ничего не дублируется
    assert await second.restore_state(force=True) == 1  # принудительная перезагрузка
    assert len(second.list_documents()) == 1


async def test_restored_embeddings_are_reused(
    service_app, chunk_store, stub_llm, sample_text
) -> None:
    """Эмбеддинги хранятся в БД — восстановление не должно звать модель заново."""
    service = _service(service_app, chunk_store, stub_llm)
    await service.add_file(sample_text)

    stored = await chunk_store.load("global")
    assert stored and all(item.texts and item.texts[0].embedding for item in stored)

    second = _service(service_app, chunk_store, stub_llm)
    await second.restore_state()
    assert all(text.embedding is not None for text in second.docs.texts)


async def test_persist_state_updates_store(
    service_app, chunk_store, stub_llm, sample_text
) -> None:
    service = _service(service_app, chunk_store, stub_llm)
    await service.add_file(sample_text)

    assert await service.persist_state() == 1
    assert len(await chunk_store.list_documents("global")) == 1


async def test_collections_persist_independently(
    service_app, chunk_store, stub_llm, sample_text, sample_csv
) -> None:
    global_service = _service(service_app, chunk_store, stub_llm, "global")
    session_service = _service(service_app, chunk_store, stub_llm,
                               session_collection("s-42"))

    await global_service.add_file(sample_text)
    await session_service.add_file(sample_csv)

    assert len(await chunk_store.list_documents("global")) == 1
    assert len(await chunk_store.list_documents("session:s-42")) == 1

    fresh_global = _service(service_app, chunk_store, stub_llm, "global")
    fresh_session = _service(service_app, chunk_store, stub_llm, "session:s-42")
    assert await fresh_global.restore_state() == 1
    assert await fresh_session.restore_state() == 1
    assert {d.docname for d in fresh_global.list_documents()} != {
        d.docname for d in fresh_session.list_documents()}


async def test_rebuild_index_recomputes_embeddings(
    service_app, chunk_store, stub_llm, sample_text
) -> None:
    service = _service(service_app, chunk_store, stub_llm)
    await service.add_file(sample_text)

    stats = await service.rebuild_index()

    assert stats["documents"] == 1
    assert stats["chunks"] >= 1
    assert len(service.list_documents()) == 1

    chunks, _ = await service.get_evidence("биомасса")
    assert chunks


async def test_rebuild_index_on_empty_collection(
    service_app, chunk_store, stub_llm
) -> None:
    service = _service(service_app, chunk_store, stub_llm)
    assert await service.rebuild_index() == {"documents": 0, "chunks": 0}


async def test_chunks_survive_service_restart(
    service_app, db_engine, stub_llm, sample_text
) -> None:
    """Полный сценарий: сервис A пишет в БД, сервис B (новый процесс) читает."""
    from sqlalchemy.orm import sessionmaker

    from app.db.session import init_db
    from app.services.chunk_store import SqliteChunkStore

    init_db(db_engine)
    factory = sessionmaker(bind=db_engine, expire_on_commit=False, future=True)
    store = SqliteChunkStore(factory)

    writer = _service(service_app, store, stub_llm)
    document = await writer.add_file(sample_text)

    reader = _service(service_app, store, stub_llm)
    assert await reader.restore_state() == 1
    assert reader.list_documents()[0].dockey == document.dockey

    chunks, _ = await reader.get_evidence("хлорофилл-а")
    assert chunks and chunks[0].dockey == document.dockey


async def test_settings_md5_recorded(
    service_app, chunk_store, stub_llm, sample_text
) -> None:
    service = _service(service_app, chunk_store, stub_llm)
    await service.add_file(sample_text)

    stored = await chunk_store.list_documents("global")
    assert stored[0].settings_md5 == service.fingerprint


@pytest.mark.parametrize("keep_embeddings", [True, False])
async def test_restore_after_settings_change(
    service_app, chunk_store, stub_llm, sample_text, keep_embeddings
) -> None:
    """Смена профиля (например, другой embedding) требует переиндексации."""
    from app.services.pqa_profile import build_pqa_settings

    service = _service(service_app, chunk_store, stub_llm)
    await service.add_file(sample_text)

    changed = service_app.model_copy(update={"evidence_k": 5})
    other = PaperQA2Service(changed, "global", chunk_store,
                            pqa_settings=build_pqa_settings(changed), llm_model=stub_llm)
    assert other.fingerprint != service.fingerprint or not keep_embeddings

    await other.restore_state()
    chunks, _ = await other.get_evidence("биомасса")
    assert chunks  # контекст доступен в любом случае