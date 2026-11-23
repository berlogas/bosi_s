"""Персистентность: чанки переживают пересоздание сервиса и рестарт процесса.

Инвариант Фазы 0 (спайк 03): после восстановления через `aadd_texts` оценки
контекста совпадают, эмбеддинги не пересчитываются.
"""

from __future__ import annotations

import pytest

from app.services.paperqa_service import PaperQA2Service
from app.services.pqa_registry import session_collection


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
    restored, _ = await restored_service.restore_state()
    assert restored == 2

    chunks_after, _ = await restored_service.get_evidence("метод GF/F и хлорофилл-а")

    assert [(c.dockey, c.score) for c in chunks_before] == [
        (c.dockey, c.score) for c in chunks_after]


async def test_restore_state_is_idempotent(
    service_app, chunk_store, stub_llm, sample_text
) -> None:
    service = _service(service_app, chunk_store, stub_llm)
    await service.add_file(sample_text)

    second = _service(service_app, chunk_store, stub_llm)
    restored, _ = await second.restore_state()
    assert restored == 1
    assert await second.restore_state() == (0, 0)  # повторно ничего не дублируется
    restored, _ = await second.restore_state(force=True)
    assert restored == 1
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
    restored, _ = await fresh_global.restore_state()
    assert restored == 1
    restored, _ = await fresh_session.restore_state()
    assert restored == 1
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
    restored, _ = await reader.restore_state()
    assert restored == 1
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


async def test_legacy_fingerprint_rows_are_restored_and_migrated(
    service_app, chunk_store, stub_llm, sample_text
) -> None:
    """Записи без префикса версии — легаси, а не «устаревшие».

    До появления `v2:` в `settings_md5` лежал хеш всей конфигурации (или
    вовсе dockey). Если считать такие записи устаревшими, после обновления
    весь индекс молча пропадает из поиска и чат отвечает «база пуста» при
    полной базе. Поэтому легаси-записи восстанавливаются и пересохраняются
    с текущим отпечатком.
    """
    from app.services.pqa_profile import CHUNK_FINGERPRINT_PREFIX

    service = _service(service_app, chunk_store, stub_llm)
    await service.add_file(sample_text)
    assert service.fingerprint.startswith(CHUNK_FINGERPRINT_PREFIX)

    for item in chunk_store._data["global"].values():
        item.settings_md5 = "f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0"  # старый формат

    restored_service = _service(service_app, chunk_store, stub_llm)
    restored, stale = await restored_service.restore_state()
    assert restored == 1
    assert stale == 0
    assert restored_service.list_documents()

    stored = await chunk_store.list_documents("global")
    assert stored[0].settings_md5 == restored_service.fingerprint

    chunks, _ = await restored_service.get_evidence("биомасса")
    assert chunks

    # Повторное восстановление уже не считает запись легаси.
    third = _service(service_app, chunk_store, stub_llm)
    assert await third.restore_state() == (1, 0)


async def test_llm_change_keeps_chunks_valid(
    service_app, chunk_store, stub_llm, sample_text
) -> None:
    """Смена LLM не обесценивает индекс: чанки — это текст и эмбеддинги.

    Переход с облачной модели на локальную (или наоборот) меняет формулировки
    ответа, но не содержимое источников. Если бы отпечаток чанков зависел от
    LLM, каждая такая смена требовала бы переиндексации всей базы.
    """
    from app.services.pqa_profile import build_pqa_settings

    service = _service(service_app, chunk_store, stub_llm)
    await service.add_file(sample_text)

    changed = service_app.model_copy(update={"llm_model": "ollama/другая-модель"})
    other = PaperQA2Service(changed, "global", chunk_store,
                            pqa_settings=build_pqa_settings(changed), llm_model=stub_llm)
    assert other.fingerprint == service.fingerprint

    restored, stale = await other.restore_state()
    assert stale == 0
    assert restored >= 1
    chunks, _ = await other.get_evidence("биомасса")
    assert chunks  # источники на месте — индекс не пострадал


@pytest.mark.parametrize("keep_embeddings", [True, False])
async def test_restore_after_settings_change(
    service_app, chunk_store, stub_llm, sample_text, keep_embeddings
) -> None:
    """Смена модели эмбеддингов требует переиндексации."""
    from app.services.pqa_profile import build_pqa_settings

    service = _service(service_app, chunk_store, stub_llm)
    await service.add_file(sample_text)

    changed = service_app.model_copy(update={
        "embedding_model": "st-sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    })
    other = PaperQA2Service(changed, "global", chunk_store,
                            pqa_settings=build_pqa_settings(changed), llm_model=stub_llm)
    assert other.fingerprint != service.fingerprint or not keep_embeddings

    _, stale = await other.restore_state()
    assert stale >= 1  # настройки изменились — чанки помечены устаревшими
    chunks, _ = await other.get_evidence("биомасса")
    assert not chunks  # пока не сделан reindex — результатов нет
    result = await other.rebuild_index(drop_embeddings=True)
    assert result["documents"] >= 1
    chunks, _ = await other.get_evidence("биомасса")
    assert chunks  # после переиндексации контекст доступен

async def test_stale_schema_version_chunks_are_skipped(
    service_app, chunk_store, stub_llm, sample_text
) -> None:
    """Документы с несовпадающей версией схемы пропускаются при restore_state."""
    service = _service(service_app, chunk_store, stub_llm)
    await service.add_file(sample_text)

    # Эмулируем изменение схемы: портим schema_version напрямую в хранилище
    for item in chunk_store._data["global"].values():
        item.schema_version = 999

    # Новый сервис — старые чанки пропускаются на этапе load
    restored_service = _service(service_app, chunk_store, stub_llm)
    restored, stale = await restored_service.restore_state()
    assert restored == 0
    assert stale == 0  # load() отфильтровала чанки с несовпадающей схемой


async def test_schema_migration_rebuilds_embeddings(
    service_app, chunk_store, stub_llm, sample_text
) -> None:
    """Полный переход со старой схемы на новую: restore_state пропускает старые
    чанки, rebuild_index пересоздаёт их с текущим schema_version."""
    service = _service(service_app, chunk_store, stub_llm)
    await service.add_file(sample_text)

    # Эмулируем изменение схемы: старые чанки имеют версию 999, а текущая — SCHEMA_VERSION
    from app.services.chunk_store import SCHEMA_VERSION
    for item in chunk_store._data["global"].values():
        item.schema_version = 999  # старая версия

    # restore_state должен пропустить старые чанки (settings_md5 тоже может не совпадать,
    # но здесь фокус на schema_version — settings_md5 совпадает, а schema_version нет)
    restored_service = _service(service_app, chunk_store, stub_llm)
    restored, stale = await restored_service.restore_state()
    assert restored == 0  # ничего не восстановлено — старые чанки отфильтрованы load()
    assert stale == 0

    # rebuild_index пересоздаёт чанки с текущим SCHEMA_VERSION
    result = await restored_service.rebuild_index(drop_embeddings=True)
    assert result["documents"] >= 1
    assert result["chunks"] >= 1

    # После переиндексации чанки доступны и эмбеддинги пересчитаны
    chunks, _ = await restored_service.get_evidence("биомасса")
    assert chunks
    assert all(text.embedding is not None for text in restored_service.docs.texts)

    # schema_version у сохранённых чанков теперь текущий
    stored = await chunk_store.load("global")
    assert all(item.schema_version == SCHEMA_VERSION for item in stored)