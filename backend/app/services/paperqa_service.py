"""`PaperQA2Service` — единственная точка доступа к PaperQA2.

Сервис владеет одним экземпляром `Docs` на «коллекцию»:
  * ``"global"``          — глобальная база знаний (наполняет только админ);
  * ``"session:<uuid>"``  — личная база исследователя.

Все инварианты Фазы 0 (см. `docs/SPICE_REPORT.md` и `app/services/pqa_profile.py`)
соблюдаются внутри этого модуля; наружу торчат только типизированные DTO.

Особенности, которые отличают реальный API paperqa от документации:

* ``Docs.aadd()`` возвращает **docname**, а не dockey; dockey берём из ``docs.docs``;
  ``None`` означает «документ уже был в коллекции» (дедуп по dockey);
* ``Docs.delete()`` синхронный и возвращает ``None`` — bool строим сами;
* ``Docs.aadd_file(BinaryIO)`` падает на Windows (``PermissionError`` от
  ``NamedTemporaryFile``) — загруженные файлы пишем сами во временный файл;
* ``aquery(str)`` заново ищет контекст (на dev-машине 374 с), а
  ``aquery(PQASession)`` переиспользует найденный (118 с) — поэтому
  :meth:`get_evidence` и :meth:`ask` разделены, а :meth:`ask` умеет принимать
  готовую сессию (``reuse_session=True``);
* LLM вызывается только для evidence/ответа: ``aadd`` приходит к LLM, только если
  не передан ``citation`` — поэтому сервис всегда передаёт citation сам.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import anyio
from paperqa import Context, Docs, PQASession
from paperqa.settings import Settings

from app.config import Settings as AppSettings
from app.config import get_settings
from app.core.errors import DocumentProcessingError, UpstreamError
from app.core.locks import locks
from app.services.chunk_store import ChunkStore, SqliteChunkStore
from app.services.pqa_profile import build_pqa_settings, settings_fingerprint
from app.services.pqa_readers import install_utf8_parser
from app.services.types import (
    SOURCE_MARK,
    AnswerResult,
    DocStatus,
    DocumentBatchResult,
    DocumentRef,
    ScoredChunk,
    SourceKind,
)

log = logging.getLogger(__name__)

# Парсинг документов — только в UTF-8: paperqa читает файлы в кодировке
# локали (cp1251 на Windows), и кириллица превращается в «Р‘РёРѕРјР°ССЃР°».
install_utf8_parser()

GLOBAL_COLLECTION = "global"
SESSION_PREFIX = "session:"


def session_collection(session_id: str) -> str:
    return f"{SESSION_PREFIX}{session_id}"


def collection_kind(collection: str) -> SourceKind:
    return SourceKind.SESSION if collection.startswith(SESSION_PREFIX) else SourceKind.GLOBAL


def normalize_collection(collection: str) -> str:
    if not collection or collection == GLOBAL_COLLECTION:
        return GLOBAL_COLLECTION
    return collection if collection.startswith(SESSION_PREFIX) else session_collection(collection)


def _has_content(path: Path) -> bool:
    """Есть ли в скачанном файле хоть какие-то данные (блокирующий вызов -> в thread)."""
    return path.exists() and path.stat().st_size > 0


class PaperQA2Service:
    """Обёртка над `Docs` с персистентностью, блокировками и типизированным API."""

    def __init__(
        self,
        settings: AppSettings | None = None,
        collection: str = GLOBAL_COLLECTION,
        chunk_store: ChunkStore | None = None,
        pqa_settings: Settings | None = None,
        docs: Docs | None = None,
        llm_model: Any | None = None,
        **_ignored: Any,
    ) -> None:
        self.app = settings or get_settings()
        self.collection = normalize_collection(collection)
        self.kind = collection_kind(self.collection)
        self.store: ChunkStore = chunk_store or SqliteChunkStore()
        self.pqa_settings = pqa_settings or build_pqa_settings(self.app)
        self.fingerprint = settings_fingerprint(self.pqa_settings)
        self.docs = docs if docs is not None else Docs()
        # подмена LLM для тестов/оффлайн-режима (None -> реальная модель из конфига)
        self._llm_model = llm_model
        self._lock_key = self.collection

    # ------------------------------------------------------------------ служебное
    @property
    def lock(self):  # noqa: ANN201
        return locks.session_lock(self._lock_key)

    @property
    def read_lock(self):  # noqa: ANN201
        """Блокировка глобального индекса для чтения (параллельные запросы)."""
        if self.kind is SourceKind.GLOBAL:
            return locks.global_index.read()
        return locks.session_lock(self._lock_key)

    def _llm_kwargs(self) -> dict[str, Any]:
        """`aadd` принимает `llm_model` (основная модель)."""
        return {"llm_model": self._llm_model} if self._llm_model is not None else {}

    def _summary_llm_kwargs(self) -> dict[str, Any]:
        """`aget_evidence` принимает `summary_llm_model` (имя параметра другое!)."""
        return {"summary_llm_model": self._llm_model} if self._llm_model is not None else {}

    def _query_kwargs(self) -> dict[str, Any]:
        """`aquery` использует обе модели: он сам вызывает `aget_evidence`."""
        if self._llm_model is None:
            return {}
        return {"llm_model": self._llm_model, "summary_llm_model": self._llm_model}

    def make_citation(self, path: Path, title: str | None = None) -> str:
        """Цитата для не-публикаций (PaperQA не умеет цитировать код/таблицы сам)."""
        name = title or path.stem.replace("_", " ").strip() or path.name
        return f"{name} (загружено пользователем)"

    def unique_docname(self, base: str) -> str:
        """Человекочитаемое уникальное имя документа внутри коллекции."""
        base = base or "document"
        if base not in self.docs.docnames:
            return base
        return f"{base}_{uuid.uuid4().hex[:8]}"

    def _texts_of(self, dockey: str) -> list[Any]:
        return [t for t in self.docs.texts if t.doc.dockey == dockey]

    def storage_dir(self, session_id: str | None = None, kind: str = "files") -> Path:
        """Каталог хранения файлов: у каждой сессии свой (изоляция сессий).

        Глобальная база (`session_id=None`) лежит в `documents_dir`, сессионные
        файлы — в `sessions_dir/<id>/<kind>`. Так удаление сессии чистит ровно
        её файлы и не задевает чужие.
        """
        if session_id:
            path = self.app.sessions_dir / session_id / kind
        else:
            path = self.app.documents_dir / kind
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _doc_of(self, dockey: str) -> Any:
        return self.docs.docs.get(dockey)

    # ------------------------------------------------------------ добавление
    async def add_files(
        self,
        paths: Sequence[str | os.PathLike[str]],
        category: str | None = None,
        project_id: str | None = None,
        session_id: str | None = None,
        citation: str | None = None,
    ) -> DocumentBatchResult:
        """Добавить файлы с диска (проверка существования и расширения)."""
        result = DocumentBatchResult()
        for raw in paths:
            path = Path(raw)
            try:
                ref = await self.add_file(
                    path, category=category, project_id=project_id,
                    session_id=session_id, citation=citation,
                )
            except Exception as exc:
                log.warning("add_files: %s не проиндексирован: %s", path.name, exc)
                result.failed.append((str(path), f"{type(exc).__name__}: {exc}"))
                continue
            if ref is None:
                result.duplicates.append(DocumentRef(
                    dockey=self._dockey_for_path(path), docname=path.stem, path=str(path),
                    status=DocStatus.READY,
                ))
            else:
                result.added.append(ref)
        return result

    async def add_file(
        self,
        path: str | os.PathLike[str],
        category: str | None = None,
        project_id: str | None = None,
        session_id: str | None = None,
        citation: str | None = None,
        title: str | None = None,
    ) -> DocumentRef | None:
        """Добавить один файл.

        Возвращает `DocumentRef`, либо `None` — документ с таким dockey уже есть
        (дедуп по содержимому, поведение `Docs.aadd`).
        """
        file_path = Path(path)
        if not await anyio.to_thread.run_sync(file_path.exists):
            raise FileNotFoundError(f"Файл не найден: {file_path}")
        if not await anyio.to_thread.run_sync(file_path.is_file):
            raise DocumentProcessingError(f"Это не файл: {file_path}")
        self._check_extension(file_path)

        file_citation = citation or self.make_citation(file_path, title)
        docname = self.unique_docname(file_path.stem[:80] or "document")

        async with self.lock:
            before = set(self.docs.docs)
            t0 = time.perf_counter()
            returned = await self.docs.aadd(
                str(file_path),
                citation=file_citation,
                docname=docname,
                settings=self.pqa_settings,
                **self._llm_kwargs(),
            )
            elapsed = time.perf_counter() - t0
            new_keys = set(self.docs.docs) - before
            if not new_keys:
                # aadd вернул None -> документ с таким dockey уже в коллекции
                log.info("add_file: %s уже в коллекции (dockey-дедуп, returned=%r)",
                         file_path.name, returned)
                return None
            dockey = str(next(iter(new_keys)))
            doc = self._doc_of(dockey)
            texts = self._texts_of(dockey)
            await self.store.save(self.collection, doc, texts, self.fingerprint)

        log.info("add_file: %s -> docname=%s dockey=%s чанков=%d за %.1fс",
                 file_path.name, docname, dockey[:12], len(texts), elapsed)
        return DocumentRef(
            dockey=dockey,
            docname=doc.docname,
            path=str(file_path),
            title=title or file_path.stem,
            citation=doc.citation,
            status=DocStatus.READY,
            size_bytes=await anyio.to_thread.run_sync(lambda: file_path.stat().st_size),
            pages=self._page_count(texts),
            chunk_count=len(texts),
            category=category,
            project_id=project_id,
            session_id=session_id,
            content_hash=doc.content_hash,
        )

    async def add_uploads(
        self,
        files: Iterable[Any],
        category: str | None = None,
        project_id: str | None = None,
        session_id: str | None = None,
    ) -> DocumentBatchResult:
        """Добавить загруженные файлы (`UploadFile` или file-like).

        `Docs.aadd_file()` на Windows падает с PermissionError, поэтому запись
        во временный файл делаем сами (спайк 02, примечание к API).
        """
        result = DocumentBatchResult()
        upload_dir = self.storage_dir(session_id, "uploads")

        for uploaded in files:
            name = getattr(uploaded, "filename", None) or getattr(uploaded, "name", "upload")
            name = os.path.basename(str(name))
            target = upload_dir / f"{uuid.uuid4().hex[:8]}_{name}"
            try:
                data = await self._read_upload(uploaded)
                limit = self.app.upload_max_mb * 1024 * 1024
                if len(data) > limit:
                    raise DocumentProcessingError(
                        f"Файл больше {self.app.upload_max_mb} МБ: {name}")
                await anyio.to_thread.run_sync(target.write_bytes, data)
                ref = await self.add_file(
                    target, category=category, project_id=project_id,
                    session_id=session_id, title=Path(name).stem,
                )
            except Exception as exc:
                log.warning("add_uploads: %s не загружен: %s", name, exc)
                result.failed.append((name, f"{type(exc).__name__}: {exc}"))
                continue
            if ref is None:
                result.duplicates.append(DocumentRef(
                    dockey=self._dockey_for_path(target), docname=Path(name).stem,
                    path=str(target), status=DocStatus.READY))
            else:
                result.added.append(ref)
        return result

    async def add_url(
        self,
        url: str,
        category: str | None = None,
        project_id: str | None = None,
        session_id: str | None = None,
    ) -> DocumentRef:
        """Добавить документ по URL.

        В оффлайн-контуре внешние источники недоступны, поэтому файл качаем сами
        (`aadd_url` полагается на сеть и не проходит проверку размера/типа).
        """
        import httpx

        if not url.lower().startswith(("http://", "https://")):
            raise DocumentProcessingError(f"Некорректный URL: {url}")

        tmp_dir = self.storage_dir(session_id, "urls")
        target = tmp_dir / f"{uuid.uuid4().hex[:8]}{self._extension_from_url(url)}"
        try:
            async with (
                httpx.AsyncClient(follow_redirects=True, timeout=60) as client,
                client.stream("GET", url) as response,
            ):
                if response.status_code >= 400:
                    raise UpstreamError(
                        f"Источник вернул HTTP {response.status_code}: {url}")
                limit = self.app.upload_max_mb * 1024 * 1024
                size = 0
                with target.open("wb") as handle:
                    async for part in response.aiter_bytes():
                        size += len(part)
                        if size > limit:
                            raise DocumentProcessingError(
                                f"Файл больше {self.app.upload_max_mb} МБ")
                        await anyio.to_thread.run_sync(handle.write, part)
        except httpx.HTTPError as exc:
            await anyio.to_thread.run_sync(lambda: target.unlink(missing_ok=True))
            raise UpstreamError(
                f"Не удалось скачать {url}: {exc}. "
                "В оффлайн-режиме доступны только локальные файлы."
            ) from exc

        if not await anyio.to_thread.run_sync(_has_content, target):
            await anyio.to_thread.run_sync(lambda: target.unlink(missing_ok=True))
            raise DocumentProcessingError(f"Пустой ответ по URL: {url}")

        ref = await self.add_file(target, category=category, project_id=project_id,
                                  session_id=session_id,
                                  citation=f"{url} (загружено по URL)")
        if ref is None:
            raise ConflictDocument(url)
        ref.url = url
        return ref

    # ------------------------------------------------------------- удаление/список
    async def delete_document(
        self,
        dockey: str | None = None,
        path: str | None = None,
        docname: str | None = None,
    ) -> bool:
        """Удалить документ. `Docs.delete()` возвращает None — bool строим сами."""
        if not any((dockey, path, docname)):
            raise ValueError("Нужен dockey, docname или path")
        if dockey is None and path is not None:
            dockey = self._dockey_for_path(Path(path))
        if dockey is None and docname is not None:
            dockey = next((k for k, d in self.docs.docs.items() if d.docname == docname), None)
        if dockey is None or dockey not in self.docs.docs:
            return False

        async with self.lock:
            self.docs.delete(dockey=dockey)
            deleted = dockey not in self.docs.docs
            if deleted:
                await self.store.delete(self.collection, dockey)
        log.info("delete_document: dockey=%s удалён=%s", dockey[:12], deleted)
        return deleted

    async def clear_documents(self) -> int:
        """Полная очистка коллекции (Docs + хранилище чанков). Возвращает число документов."""
        async with self.lock:
            count = len(self.docs.docs)
            self.docs.clear_docs()
            await self.store.clear(self.collection)
        log.info("clear_documents: удалено документов=%d", count)
        return count

    def list_documents(self) -> list[DocumentRef]:
        """Документы коллекции, известные в памяти (`Docs.docs`)."""
        result: list[DocumentRef] = []
        for dockey, doc in self.docs.docs.items():
            texts = self._texts_of(dockey)
            result.append(DocumentRef(
                dockey=str(dockey),
                docname=doc.docname,
                citation=doc.citation,
                status=DocStatus.READY,
                chunk_count=len(texts),
                pages=self._page_count(texts),
                content_hash=doc.content_hash,
            ))
        return result

    async def documents_on_disk(self) -> list[DocumentRef]:
        """Реестр из БД — работает и до `restore_state()`."""
        return [
            DocumentRef(
                dockey=item.dockey, docname=item.docname, citation=item.citation,
                status=DocStatus.READY, chunk_count=item.chunk_count, created_at=item.updated_at,
            )
            for item in await self.store.list_documents(self.collection)
        ]

    async def stats(self) -> dict[str, Any]:
        return {
            "collection": self.collection,
            "kind": self.kind.value,
            "documents_in_memory": len(self.docs.docs),
            "documents_in_store": len(await self.store.list_documents(self.collection)),
            "chunks_in_memory": len(self.docs.texts),
            "chunks_in_store": await self.store.count_chunks(self.collection),
            "settings_md5": self.fingerprint,
            "embedding": self.pqa_settings.embedding,
            "llm": self.pqa_settings.llm,
        }

    # ------------------------------------------------------------------ поиск/ответ
    async def get_evidence(
        self,
        query: str,
        k: int | None = None,
        doc_filter: Any | None = None,
    ) -> tuple[list[ScoredChunk], PQASession]:
        """Найти контекст без генерации ответа.

        Возвращает и чанки, и саму `PQASession`: её можно передать в :meth:`ask`,
        чтобы не искать контекст второй раз (Фаза 0: 374 с -> 118 с на dev-машине).
        """
        settings = self._settings_with_k(k)
        async with self.read_lock:
            session = await self.docs.aget_evidence(
                query, settings=settings, **self._summary_llm_kwargs(),
            )
        return self._to_chunks(session.contexts), session

    async def search(self, query: str, limit: int = 10) -> list[ScoredChunk]:
        """Поиск фрагментов без генерации ответа (обёртка над `aget_evidence`)."""
        chunks, _ = await self.get_evidence(query)
        return chunks[:limit]

    async def ask(
        self,
        query: str | PQASession,
        mode: str | None = None,
        max_sources: int | None = None,
        evidence: list[ScoredChunk] | None = None,
        settings: Settings | None = None,
    ) -> AnswerResult:
        """Ответить на вопрос. Принимает `PQASession` для переиспользования контекста."""
        reuse = isinstance(query, PQASession)
        pqa_settings = settings or self._settings_with_sources(max_sources)
        t0 = time.perf_counter()
        async with self.read_lock:
            result = await self.docs.aquery(query, settings=pqa_settings, **self._query_kwargs())
        elapsed = time.perf_counter() - t0

        return AnswerResult(
            question=result.question or ("" if reuse else str(query)),
            answer=result.answer,
            formatted_answer=result.formatted_answer or result.answer,
            citations=self._citations(result),
            context=[self._context_dict(c) for c in result.contexts],
            evidence=evidence or self._to_chunks(result.contexts),
            has_successful_answer=result.has_successful_answer,
            cost=result.cost,
            token_counts=dict(result.token_counts or {}),
            mode=mode,
            seconds=elapsed,
            used_context=reuse,
        )

    async def ask_with_evidence(
        self, query: str, k: int | None = None, mode: str | None = None,
        max_sources: int | None = None,
    ) -> AnswerResult:
        """Схема RAG-fusion: сначала контекст, затем ответ по нему (без повторного поиска)."""
        chunks, session = await self.get_evidence(query, k=k)
        return await self.ask(session, mode=mode, max_sources=max_sources, evidence=chunks)

    # -------------------------------------------------------------- персистентность
    async def persist_state(self) -> int:
        """Сохранить текущее состояние `Docs` в хранилище. Возвращает число документов."""
        saved = 0
        async with self.lock:
            for dockey, doc in self.docs.docs.items():
                texts = self._texts_of(str(dockey))
                if not texts:
                    continue
                await self.store.save(self.collection, doc, texts, self.fingerprint)
                saved += 1
        log.info("persist_state: коллекция=%s документов=%d чанков=%d",
                 self.collection, saved, len(self.docs.texts))
        return saved

    async def restore_state(self, force: bool = False) -> int:
        """Восстановить `Docs` из хранилища (чистый `Docs` + `aadd_texts`).

        `force=False` — если коллекция уже загружена в память, ничего не делаем
        (иначе вызов из API перетёр бы живое состояние).
        """
        stored = await self.store.load(self.collection)
        if not stored:
            return 0
        if self.docs.docs and not force:
            return 0
        self.docs = Docs()
        restored = 0
        async with self.lock:
            for item in stored:
                if item.doc is None or not item.texts:
                    continue
                try:
                    ok = await self.docs.aadd_texts(
                        item.texts, item.doc, self.pqa_settings)
                except Exception as exc:
                    log.error("restore_state: %s пропущен: %s", item.docname, exc)
                    continue
                restored += bool(ok)
        log.info("restore_state: коллекция=%s восстановлено=%d чанков=%d",
                 self.collection, restored, len(self.docs.texts))
        return restored

    async def rebuild_index(self, drop_embeddings: bool = True) -> dict[str, Any]:
        """Полная переиндексация: перечитать документы с нуля.

        Чанки достаются из хранилища (там лежит исходный текст), эмбеддинги
        пересчитываются, если `drop_embeddings=True`.
        """
        stored = await self.store.load(self.collection)
        if not stored:
            return {"documents": 0, "chunks": 0}

        t0 = time.perf_counter()
        self.docs = Docs()
        documents = chunks = 0
        async with self.lock:
            for item in stored:
                if item.doc is None or not item.texts:
                    continue
                texts = item.texts
                if drop_embeddings:
                    for text in texts:
                        text.embedding = None
                try:
                    ok = await self.docs.aadd_texts(texts, item.doc, self.pqa_settings)
                except Exception as exc:
                    log.error("rebuild_index: %s пропущен: %s", item.docname, exc)
                    continue
                if ok:
                    documents += 1
                    chunks += len(texts)
                    await self.store.save(self.collection, item.doc, texts, self.fingerprint)
        elapsed = time.perf_counter() - t0
        log.info("rebuild_index: документов=%d чанков=%d за %.1fс", documents, chunks, elapsed)
        return {"documents": documents, "chunks": chunks, "seconds": round(elapsed, 1)}

    # ------------------------------------------------------------------ helpers
    def _settings_with_k(self, k: int | None) -> Settings:
        if k is None or k == self.app.evidence_k:
            return self.pqa_settings
        return build_pqa_settings(self.app, answer={"evidence_k": k})

    def _settings_with_sources(self, max_sources: int | None) -> Settings:
        if max_sources is None or max_sources == self.app.answer_max_sources:
            return self.pqa_settings
        return build_pqa_settings(self.app, answer={"answer_max_sources": max_sources})

    def _check_extension(self, path: Path) -> None:
        suffix = path.suffix.lower()
        if suffix not in {e.lower() for e in self.app.allowed_extensions}:
            raise DocumentProcessingError(
                f"Неподдерживаемый тип файла: {suffix or '(без расширения)'}")

    def _extension_from_url(self, url: str) -> str:
        name = url.split("?")[0].split("#")[0]
        suffix = Path(name).suffix
        return suffix if suffix else ".pdf"

    def _dockey_for_path(self, path: Path) -> str:
        from paperqa.docs import md5sum

        try:
            return str(md5sum(path))
        except (OSError, FileNotFoundError):
            return ""

    def _page_count(self, texts: list[Any]) -> int | None:
        pages = {t.name for t in texts if t.name and t.name.isdigit()}
        return len(pages) or None

    def _to_chunks(self, contexts: list[Context]) -> list[ScoredChunk]:
        chunks: list[ScoredChunk] = []
        for index, ctx in enumerate(contexts or []):
            doc = ctx.text.doc
            chunks.append(ScoredChunk(
                dockey=str(doc.dockey),
                docname=doc.docname,
                text=ctx.text.text,
                score=int(ctx.score or 0),
                context=ctx.context,
                citation=doc.citation,
                name=ctx.text.name,
                kind=self.kind,
                chunk_index=index,
            ))
        return sorted(chunks, key=lambda c: -c.score)

    def _context_dict(self, ctx: Context) -> dict[str, Any]:
        return {
            "source": f"{self.kind.value}:{ctx.text.doc.docname}",
            "marker": SOURCE_MARK[self.kind],
            "docname": ctx.text.doc.docname,
            "dockey": str(ctx.text.doc.dockey),
            "citation": ctx.text.doc.citation,
            "name": ctx.text.name,
            "score": ctx.score,
            "text": ctx.text.text[:1000],
            "context": ctx.context,
        }

    @staticmethod
    def _citations(session: PQASession) -> list[str]:
        """`session.references` — строка, а не список (реальный API)."""
        references = session.references or ""
        return [line.strip("-* ") for line in references.splitlines() if line.strip()]

    # ------------------------------------------------------------------ LLM-промпты
    async def complete(self, prompt: str, *, name: str = "completion") -> str:
        """Один вызов LLM с произвольным промптом.

        Использует ту же модель, что и поиск и ответы: подменённую в тестах
        (`_llm_model`) либо модель из настроек. Поэтому генератор разделов
        (Фаза 7) и чат (Фаза 6) говорят с одной и той же моделью.
        """
        llm = self._llm_model if self._llm_model is not None else self.pqa_settings.get_llm()
        result = await llm.call_single(messages=[{"role": "user", "content": prompt}],
                                       name=name)
        return (getattr(result, "text", "") or "").strip()

    async def _read_upload(self, uploaded: Any) -> bytes:
        read = getattr(uploaded, "read", None)
        if read is None:
            raise DocumentProcessingError(f"Нечитаемый объект загрузки: {type(uploaded).__name__}")
        data = read()
        if isinstance(data, str):
            data = data.encode("utf-8")
        if hasattr(data, "__await__"):
            data = await data
        return bytes(data)


class ConflictDocument(Exception):
    """URL уже присутствует в коллекции (тот же dockey)."""

    def __init__(self, url: str) -> None:
        super().__init__(f"Документ по URL {url} уже загружен")
        self.url = url


class ServiceRegistry:
    """Реестр сервисов по коллекциям: один `Docs` на глобальную базу и на сессию."""

    def __init__(self, app: AppSettings | None = None,
                 store: ChunkStore | None = None) -> None:
        self.app = app or get_settings()
        self.store = store or SqliteChunkStore()
        self._services: dict[str, PaperQA2Service] = {}
        self._meta_lock = asyncio.Lock()

    def get(self, collection: str = GLOBAL_COLLECTION) -> PaperQA2Service:
        key = normalize_collection(collection)
        service = self._services.get(key)
        if service is None:
            service = PaperQA2Service(
                settings=self.app, collection=key, chunk_store=self.store)
            self._services[key] = service
        return service

    def global_service(self) -> PaperQA2Service:
        return self.get(GLOBAL_COLLECTION)

    def session_service(self, session_id: str) -> PaperQA2Service:
        return self.get(session_collection(session_id))

    async def restore_all(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for key, service in list(self._services.items()):
            result[key] = await service.restore_state()
        return result

    async def persist_global(self) -> int:
        """Сохранить состояние всех загруженных коллекций (остановка приложения)."""
        total = 0
        for service in list(self._services.values()):
            total += await service.persist_state()
        return total

    async def close(self) -> None:
        await self.persist_global()
        self._services.clear()


_registry: ServiceRegistry | None = None


def get_registry(app: AppSettings | None = None) -> ServiceRegistry:
    global _registry
    if _registry is None:
        _registry = ServiceRegistry(app)
    return _registry


def reset_registry() -> None:
    global _registry
    _registry = None