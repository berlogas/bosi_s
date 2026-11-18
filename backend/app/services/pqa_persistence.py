"""Персистентность состояния PaperQA2: сохранение, восстановление, переиндексация.

PaperQA2 держит индекс в памяти процесса (`NumpyVectorStore`). Персистентность
обеспечивается через `document_chunks` в SQLite: при старте сессии `Docs`
собирается из БД за секунды, без повторного парсинга PDF и без пересчёта
эмбеддингов.
"""

from __future__ import annotations

import logging
from typing import Any

from paperqa import Docs

from app.services.pqa_profile import CHUNK_FINGERPRINT_PREFIX

log = logging.getLogger("boasi.services.pqa")


class PaperQA2Persistence:
    """Сохранение и восстановление состояния `Docs` в `ChunkStore`."""

    def __init__(self, service: Any) -> None:
        self.service = service

    async def persist_state(self) -> int:
        """Сохранить текущее состояние `Docs` в хранилище. Возвращает число документов."""
        saved = 0
        async with self.service.lock:
            for dockey, doc in self.service.docs.docs.items():
                texts = self.service._texts_of(str(dockey))
                if not texts:
                    continue
                await self.service.store.save(
                    self.service.collection, doc, texts, self.service.fingerprint)
                saved += 1
        log.info("persist_state: коллекция=%s документов=%d чанков=%d",
                 self.service.collection, saved, len(self.service.docs.texts))
        return saved

    async def restore_state(self, force: bool = False) -> tuple[int, int]:
        """Восстановить `Docs` из хранилища (чистый `Docs` + `aadd_texts`).

        `force=False` — если коллекция уже загружена в память, ничего не делаем
        (иначе вызов из API перетёр бы живое состояние).

        Возвращает ``(restored, stale)``: сколько документов восстановлено и
        сколько пропущено из-за несовпадения отпечатка настроек
        (``chunk_fingerprint``). Старые чанки требуют переиндексации.

        Записи без префикса версии отпечатка — легаси (до ``v2:`` в
        ``settings_md5`` лежал хеш всей конфигурации или dockey). Считать
        их устаревшими нельзя: содержимое чанков от смены формата отпечатка
        не меняется, а признание их устаревшими молча обнуляет поиск —
        чат начинает отвечать «база пуста» при полной базе. Поэтому
        легаси-записи восстанавливаем и сразу пересохраняем с текущим
        отпечатком, чтобы сравнение больше не зависело от истории.
        """
        stored = await self.service.store.load(self.service.collection)
        if not stored:
            return 0, 0
        if self.service.docs.docs and not force:
            return 0, 0
        current_fingerprint = self.service.fingerprint
        self.service.docs = Docs()
        restored = 0
        stale = 0
        migrated = 0
        async with self.service.lock:
            for item in stored:
                if item.doc is None or not item.texts:
                    continue
                is_legacy = not (item.settings_md5 or "").startswith(
                    CHUNK_FINGERPRINT_PREFIX)
                # Чанки были проиндексированы при других настройках —
                # эмбеддинги и семантика могут быть неактуальны. Пропускаем,
                # чтобы пользователь запустил переиндексацию явно.
                if not is_legacy and item.settings_md5 != current_fingerprint:
                    stale += 1
                    log.warning(
                        "restore_state: %s пропущен — настройки изменились "
                        "(stored=%s current=%s)",
                        item.docname, item.settings_md5, current_fingerprint,
                    )
                    continue
                try:
                    ok = await self.service.docs.aadd_texts(
                        item.texts, item.doc, self.service.pqa_settings,
                        **self.service._embedding_kwargs())
                except Exception as exc:
                    log.error("restore_state: %s пропущен: %s", item.docname, exc)
                    continue
                if not ok:
                    continue
                restored += 1
                if is_legacy:
                    # Отпечаток дорабатываем после успешного восстановления:
                    # если запись не встала в индекс, пересохранять нечего.
                    await self.service.store.save(
                        self.service.collection, item.doc, item.texts,
                        current_fingerprint)
                    migrated += 1
        log.info(
            "restore_state: коллекция=%s восстановлено=%d чанков=%d устарело=%d "
            "легаси=%d",
            self.service.collection, restored, len(self.service.docs.texts),
            stale, migrated,
        )
        return restored, stale

    async def rebuild_index(self, drop_embeddings: bool = True) -> dict[str, Any]:
        """Полная переиндексация: перечитать документы с нуля.

        Чанки достаются из хранилища (там лежит исходный текст), эмбеддинги
        пересчитываются, если `drop_embeddings=True`.

        Загружаются ВСЕ чанки, включая с устаревшей версией схемы — иначе
        rebuild_index не сможет обновить чанки после смены схемы.
        """
        stored = await self.service.store.load(self.service.collection,
                                                include_stale=True)
        if not stored:
            return {"documents": 0, "chunks": 0}

        import time
        t0 = time.perf_counter()
        self.service.docs = Docs()
        documents = chunks = 0
        async with self.service.lock:
            for item in stored:
                if item.doc is None or not item.texts:
                    continue
                texts = item.texts
                if drop_embeddings:
                    for text in texts:
                        text.embedding = None
                try:
                    ok = await self.service.docs.aadd_texts(
                        texts, item.doc, self.service.pqa_settings,
                        **self.service._embedding_kwargs())
                except Exception as exc:
                    log.error("rebuild_index: %s пропущен: %s", item.docname, exc)
                    continue
                if ok:
                    documents += 1
                    chunks += len(texts)
                    await self.service.store.save(
                        self.service.collection, item.doc, texts, self.service.fingerprint)
        elapsed = time.perf_counter() - t0
        log.info("rebuild_index: документов=%d чанков=%d за %.1fс", documents, chunks, elapsed)
        return {"documents": documents, "chunks": chunks, "seconds": round(elapsed, 1)}


__all__ = ["PaperQA2Persistence"]
