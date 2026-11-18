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

import contextlib
import logging
import os
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

import anyio
from aviary.core import Message
from paperqa import Context, Docs, PQASession
from paperqa.agents import AnswerResponse, agent_query
from paperqa.settings import Settings

from app.config import Settings as AppSettings
from app.config import get_settings
from app.core.errors import DocumentProcessingError
from app.core.locks import locks
from app.services.chunk_store import ChunkStore, SqliteChunkStore
from app.services.pqa_persistence import PaperQA2Persistence
from app.services.pqa_profile import (
    build_pqa_settings,
    chunk_fingerprint,
    get_embedding_model,
)
from app.services.pqa_readers import install_utf8_parser
from app.services.pqa_registry import GLOBAL_COLLECTION, collection_kind, normalize_collection
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
        self.fingerprint = chunk_fingerprint(self.pqa_settings)
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

    def _embedding_kwargs(self) -> dict[str, Any]:
        """Общая модель эмбеддингов вместо новой на каждый вызов paperqa.

        Без этого `Settings.get_embedding_model()` создаёт экземпляр заново, а
        `SentenceTransformer` каждый раз заново читает веса с диска.
        """
        return {"embedding_model": get_embedding_model(self.app)}

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
        force_reindex: bool = False,
    ) -> DocumentBatchResult:
        """Добавить файлы с диска (проверка существования и расширения)."""
        result = DocumentBatchResult()
        for raw in paths:
            path = Path(raw)
            try:
                ref = await self.add_file(
                    path, category=category, project_id=project_id,
                    session_id=session_id, citation=citation,
                    force_reindex=force_reindex,
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
        force_reindex: bool = False,
        filename: str | None = None,
    ) -> DocumentRef | None:
        """Добавить один файл.

        Возвращает `DocumentRef`, либо `None` — документ с таким dockey уже есть
        (дедуп по содержимому, поведение `Docs.aadd`).

        Если `force_reindex=True`, документ будет удалён и проиндексирован
        заново независимо от того, изменился ли контент.

        `filename` — имя файла как его знает пользователь: для загрузок путь
        указывает на временный файл с техническим префиксом, а в реестр
        должно попасть исходное имя.
        """
        file_path = Path(path)
        if not await anyio.to_thread.run_sync(file_path.exists):
            raise FileNotFoundError(f"Файл не найден: {file_path}")
        if not await anyio.to_thread.run_sync(file_path.is_file):
            raise DocumentProcessingError(f"Это не файл: {file_path}")
        self._check_extension(file_path)

        file_citation = citation or self.make_citation(file_path, title)
        docname = self.unique_docname(file_path.stem[:80] or "document")

        # Вычисляем dockey заранее, чтобы при повторной загрузке того же файла
        # с другим содержимым удалить старую версию перед переиндексацией
        # (реализует 1.3.2: переиндексация при изменении контента).
        dockey = self._dockey_for_path(file_path)

        async with self.lock:
            existing = self.docs.docs.get(dockey)
            if existing is not None:
                if not force_reindex:
                    # Документ с таким dockey уже есть — дедуп по содержимому,
                    # возвращаем None без переиндексации.
                    log.info("add_file: %s уже в коллекции (dockey=%s)",
                             file_path.name, dockey[:12])
                    return None
                # force_reindex=True — удаляем старую версию перед переиндексацией
                self.docs.delete(dockey=dockey)
                await self.store.delete(self.collection, dockey)
                log.info("add_file: %s переиндексирован по force_reindex",
                         file_path.name)

            t0 = time.perf_counter()
            await self.docs.aadd(
                str(file_path),
                citation=file_citation,
                docname=docname,
                settings=self.pqa_settings,
                **self._llm_kwargs(),
                **self._embedding_kwargs(),
            )
            elapsed = time.perf_counter() - t0
            doc = self._doc_of(dockey)
            texts = self._texts_of(dockey)
            await self.store.save(self.collection, doc, texts, self.fingerprint)

        log.info("add_file: %s -> docname=%s dockey=%s чанков=%d за %.1fс",
                 file_path.name, docname, dockey[:12], len(texts), elapsed)
        return DocumentRef(
            dockey=dockey,
            docname=doc.docname,
            path=str(file_path),
            filename=filename or file_path.name,
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
        force_reindex: bool = False,
    ) -> DocumentBatchResult:
        """Добавить загруженные файлы (`UploadFile` или file-like).

        `Docs.aadd_file()` на Windows падает с PermissionError, поэтому запись
        во временный файл делаем сами (спайк 02, примечание к API).
        """
        staged, failed = await self.stage_uploads(files, session_id)
        result = await self.index_staged(
            staged, category=category, project_id=project_id,
            session_id=session_id, force_reindex=force_reindex,
        )
        result.failed = failed + result.failed
        return result

    async def stage_uploads(
        self,
        files: Iterable[Any],
        session_id: str | None = None,
    ) -> tuple[list[tuple[Path, str]], list[tuple[str, str]]]:
        """Сохранить загруженные файлы на диск, не индексируя их.

        Отделено от индексации намеренно: объект загрузки FastAPI закрывается
        вместе с запросом, а фоновая задача живёт дольше. Поэтому файлы должны
        оказаться на диске до старта задачи.

        Возвращает `(сохранённые, ошибки)`: `(путь, имя)` и `(имя, причина)`.
        """
        upload_dir = self.storage_dir(session_id, "uploads")
        staged: list[tuple[Path, str]] = []
        failed: list[tuple[str, str]] = []

        for uploaded in files:
            name = getattr(uploaded, "filename", None) or getattr(uploaded, "name", "upload")
            name = os.path.basename(str(name))
            target = upload_dir / f"{uuid.uuid4().hex[:8]}_{name}"
            try:
                limit = self.app.upload_max_mb * 1024 * 1024
                # Размер проверяем до чтения в память: файл в 2 ГБ не должен
                # целиком попадать в RAM до отказа (D8).
                size = getattr(uploaded, "size", None)
                if size is not None and size > limit:
                    raise DocumentProcessingError(
                        f"Файл больше {self.app.upload_max_mb} МБ: {name}")
                data = await self._read_upload(uploaded)
                if len(data) > limit:
                    raise DocumentProcessingError(
                        f"Файл больше {self.app.upload_max_mb} МБ: {name}")
                await anyio.to_thread.run_sync(target.write_bytes, data)
            except Exception as exc:
                log.warning("stage_uploads: %s не сохранён: %s", name, exc)
                failed.append((name, f"{type(exc).__name__}: {exc}"))
                with contextlib.suppress(OSError):
                    target.unlink(missing_ok=True)
                continue
            staged.append((target, name))
        return staged, failed

    async def index_staged(
        self,
        staged: Sequence[tuple[Path, str]],
        category: str | None = None,
        project_id: str | None = None,
        session_id: str | None = None,
        force_reindex: bool = False,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> DocumentBatchResult:
        """Проиндексировать уже сохранённые файлы.

        `on_progress(номер, всего, имя)` зовётся после каждого файла — по нему
        фоновая задача показывает этап «файл 2/7: paper.pdf».
        """
        result = DocumentBatchResult()
        total = len(staged)

        for index, (target, name) in enumerate(staged, start=1):
            try:
                ref = await self.add_file(
                    target, category=category, project_id=project_id,
                    session_id=session_id, title=Path(name).stem,
                    force_reindex=force_reindex, filename=name,
                )
            except Exception as exc:
                log.warning("index_staged: %s не проиндексирован: %s", name, exc)
                result.failed.append((name, f"{type(exc).__name__}: {exc}"))
                # Временный файл не проиндексировали — убираем с диска (D6).
                await anyio.to_thread.run_sync(
                    lambda t=target: t.unlink(missing_ok=True))
                continue
            if ref is None:
                # Дубликат содержимого: временный файл больше не нужен (D6).
                await anyio.to_thread.run_sync(
                    lambda t=target: t.unlink(missing_ok=True))
                result.duplicates.append(DocumentRef(
                    dockey=self._dockey_for_path(target), docname=Path(name).stem,
                    path=str(target), filename=name, status=DocStatus.READY))
            else:
                result.added.append(ref)
            if on_progress is not None:
                on_progress(index, total, name)
        return result

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
        skip_summary: bool | None = None,
    ) -> tuple[list[ScoredChunk], PQASession]:
        """Найти контекст без генерации ответа.

        Возвращает и чанки, и саму `PQASession`: её можно передать в :meth:`ask`,
        чтобы не искать контекст второй раз (Фаза 0: 374 с -> 118 с на dev-машине).
        """
        settings = self._settings_with_k(k, skip_summary)
        async with self.read_lock:
            session = await self.docs.aget_evidence(
                query, settings=settings, **self._summary_llm_kwargs(),
                **self._embedding_kwargs(),
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
            result = await self.docs.aquery(
                query, settings=pqa_settings, **self._query_kwargs(),
                **self._embedding_kwargs())
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
            # Время ответа наружу — целыми секундами. Сырой float вида
            # 12.157697999999073 в API, БД и логах выглядит как мусор, а
            # разница меньше секунды для пользователя ничего не значит.
            seconds=round(elapsed),
            used_context=reuse,
        )

    async def ask_with_evidence(
        self, query: str, k: int | None = None, mode: str | None = None,
        max_sources: int | None = None,
    ) -> AnswerResult:
        """Схема RAG-fusion: сначала контекст, затем ответ по нему (без повторного поиска)."""
        _chunks, _session = await self.get_evidence(query, k=k)
        return await self.ask(_session, mode=mode, max_sources=max_sources, evidence=_chunks)

    async def agent_ask(
        self,
        query: str,
        mode: str | None = "agent",
        max_sources: int | None = None,
        settings: Settings | None = None,
    ) -> AnswerResult:
        """Ответить на вопрос через PaperQA-агент (по умолчанию офлайн «fake»-агент).

        Agent сам выбирает инструменты: поиск документов, сбор доказательств,
        генерацию ответа. В офлайн-режиме (agent_type=\"fake\") вызовы LLM
        детерминистичны — без внешних зависимостей, подходит для тестов.
        """
        pqa_settings = settings or self._settings_with_sources(max_sources)
        t0 = time.perf_counter()
        async with self.read_lock:
            response: AnswerResponse = await agent_query(
                query,
                settings=pqa_settings,
                docs=self.docs,
                agent_type=self.app.agent_type,
            )
            session = response.session
        elapsed = time.perf_counter() - t0

        return AnswerResult(
            question=session.question or str(query),
            answer=session.answer,
            formatted_answer=session.formatted_answer or session.answer,
            citations=self._citations(session),
            context=[self._context_dict(c) for c in session.contexts],
            evidence=self._to_chunks(session.contexts),
            has_successful_answer=bool(session.has_successful_answer),
            cost=session.cost,
            token_counts=dict(session.token_counts or {}),
            mode=mode,
            seconds=round(elapsed),
            agent_status=response.status.value if response.status else None,
        )
    # -------------------------------------------------------------- персистентность
    # -------------------------------------------------------------- персистентность
    async def persist_state(self) -> int:
        """Сохранить текущее состояние `Docs` в хранилище."""
        return await PaperQA2Persistence(self).persist_state()

    async def restore_state(self, force: bool = False) -> tuple[int, int]:
        """Восстановить `Docs` из хранилища (см. :class:`PaperQA2Persistence`)."""
        return await PaperQA2Persistence(self).restore_state(force=force)

    async def rebuild_index(self, drop_embeddings: bool = True) -> dict[str, Any]:
        """Полная переиндексация (см. :class:`PaperQA2Persistence`)."""
        return await PaperQA2Persistence(self).rebuild_index(drop_embeddings=drop_embeddings)




    # ------------------------------------------------------------------ helpers
    def _settings_with_k(self, k: int | None,
                         skip_summary: bool | None = None) -> Settings:
        overrides: dict[str, Any] = {}
        if k is not None and k != self.app.evidence_k:
            overrides["evidence_k"] = k
        if skip_summary is not None:
            overrides["evidence_skip_summary"] = skip_summary
        if not overrides:
            return self.pqa_settings
        return build_pqa_settings(self.app, answer=overrides)

    def _settings_with_sources(self, max_sources: int | None) -> Settings:
        if max_sources is None or max_sources == self.app.answer_max_sources:
            return self.pqa_settings
        return build_pqa_settings(self.app, answer={"answer_max_sources": max_sources})

    def _check_extension(self, path: Path) -> None:
        suffix = path.suffix.lower()
        if suffix not in {e.lower() for e in self.app.allowed_extensions}:
            raise DocumentProcessingError(
                f"Неподдерживаемый тип файла: {suffix or '(без расширения)'}")

    def _dockey_for_path(self, path: Path) -> str:
        from paperqa.docs import md5sum

        try:
            return str(md5sum(path))
        except (OSError, FileNotFoundError):
            return ""

    def _page_count(self, texts: list[Any]) -> int | None:
        pages = {t.name for t in texts if t.name and t.name.isdigit()}
        return len(pages) or None

    async def embedding_relevance(
        self, question: str, contexts: Iterable[Context],
    ) -> dict[tuple[str, str], float]:
        """Косинус вопроса к каждому контексту (0..1).

        Нужен при `evidence_skip_summary=true`: тогда paperqa не спрашивает у LLM
        `relevance_score` и проставляет всем контекстам синтетическую 5, из-за чего
        ранжирование теряет релевантность целиком и в выдачу попадают любые
        документы коллекции. Эмбеддинги текстов уже посчитаны при индексации,
        поэтому стоимость — один вызов модели на вопрос.
        """
        wanted: dict[tuple[str, str], Context] = {
            (str(ctx.text.doc.dockey), ctx.text.name): ctx for ctx in contexts}
        if not wanted:
            return {}

        vectors: dict[tuple[str, str], list[float]] = {}
        for text in self.docs.texts:
            key = (str(text.doc.dockey), text.name)
            if key in wanted and text.embedding is not None:
                vectors[key] = text.embedding

        if not vectors:
            return {}

        import numpy as np

        model = get_embedding_model(self.app)
        query_vector = (await model.embed_documents([question]))[0]
        scores: dict[tuple[str, str], float] = {}
        for key, vector in vectors.items():
            left = np.asarray(query_vector, dtype=float)
            right = np.asarray(vector, dtype=float)
            denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
            scores[key] = float(left @ right / denominator) if denominator else 0.0
        return scores

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
    @property
    def chat_llm(self) -> Any:
        """Модель для коротких вызовов вне поиска.

        Та же подмена, что в `complete()`: заглушка из тестов или модель
        из настроек. Отдельный `get_llm()` в rag_service отличался — в тестах
        он уходил в сеть (замер: 5,9 с на вызов), хотя сервис уже был заглушен.
        """
        if self._llm_model is not None:
            return self._llm_model
        return self.pqa_settings.get_llm()

    async def complete(self, prompt: str, *, name: str = "completion") -> str:
        """Один вызов LLM с произвольным промптом.

        Использует ту же модель, что и поиск и ответы: подменённую в тестах
        (`_llm_model`) либо модель из настроек. Поэтому генератор разделов
        (Фаза 7) и чат (Фаза 6) говорят с одной и той же моделью.
        """

        llm = self._llm_model if self._llm_model is not None else self.pqa_settings.get_llm()
        # Именно Message, а не dict: LLM внутри зовёт model_dump() и на dict
        # падает с AttributeError (как в rag_service).
        result = await llm.call_single(messages=[Message(content=prompt)], name=name)
        return (getattr(result, "text", "") or "").strip()

    async def complete_with_cost(
        self, prompt: str, *, name: str = "completion"
    ) -> tuple[str, dict[str, Any]]:
        """Вызов LLM с возвратом стоимости и токенов.

        Возвращает (text, cost_info) где cost_info содержит:
        - cost_usd: float
        - prompt_tokens: int
        - completion_tokens: int
        - cache_read_tokens: int
        - cache_creation_tokens: int
        - model: str
        """
        llm = self._llm_model if self._llm_model is not None else self.pqa_settings.get_llm()
        result = await llm.call_single(messages=[Message(content=prompt)], name=name)
        text = (getattr(result, "text", "") or "").strip()
        cost_info = {
            "cost_usd": getattr(result, "cost", 0.0) or 0.0,
            "prompt_tokens": getattr(result, "prompt_count", 0) or 0,
            "completion_tokens": getattr(result, "completion_count", 0) or 0,
            "cache_read_tokens": getattr(result, "cache_read_tokens", 0) or 0,
            "cache_creation_tokens": getattr(result, "cache_creation_tokens", 0) or 0,
            "model": getattr(result, "model", "") or "",
        }
        return text, cost_info

    async def stream_complete(
        self,
        prompt: str,
        *,
        name: str = "completion",
    ) -> AsyncIterator[str]:
        """Потоковый вызов LLM с произвольным промптом.

        Yield'ит текстовые фрагменты по мере генерации модели.
        Используется для SSE-стриминга ответа в чате.
        """
        llm = self._llm_model if self._llm_model is not None else self.pqa_settings.get_llm()

        # lmi.LLMModel.acompletion — КОРУТИНА (возвращает list[LLMResult]),
        # итерировать её через `async for` нельзя (ошибка:
        # "'async for' requires an object with __aiter__ method, got coroutine").
        # `acompletion_iter` накапливает весь поток и отдаёт один итоговый
        # LLMResult — токенным стримингом тоже не помогает. Поэтому стримим
        # напрямую через litellm.acompletion(stream=True) с теми же параметрами
        # модели, что использует lmi (spec из llm_config), — litellm уже
        # пропатчен импортом lmi (retry/rate-limit), вызов проходит через него.
        import litellm

        try:
            spec = llm.llm_config.models[0]
            call_kwargs = spec.to_litellm_kwargs()
        except AttributeError:  # тестовый двойник без llm_config
            call_kwargs = {"model": llm.name}

        call_kwargs["messages"] = [
            m.model_dump(by_alias=True) for m in [Message(content=prompt)]
        ]
        call_kwargs["stream"] = True

        stream = await litellm.acompletion(**call_kwargs)

        # Провайдер (облачная Mistral) ломает SSE: шлёт контент пачкой в первую
        # секунду, затем молчит ~150 с и рвёт соединение (часто посередине
        # ответа; httpx: "peer closed ... incomplete chunked read").
        # Стратегия: буферизуем чанки, а отдаём текст только когда поток
        # закрылся ШТАТНО (StopAsyncIteration или finish=stop). Если же
        # провайдер «затих» по idle-таймауту или уронил соединение — делаем
        # один надёжный не-стриминговый перезапрос (обычный чат работает).
        import asyncio as _asyncio

        collected: list[str] = []
        complete = False
        try:
            while True:
                try:
                    chunk = await _asyncio.wait_for(
                        stream.__anext__(), timeout=12.0)
                except StopAsyncIteration:
                    complete = True
                    break
                except (_asyncio.TimeoutError, TimeoutError):
                    # затих по idle: у этого провайдера конец потока не
                    # приходит — считаем соединение потерянным
                    break
                choices = getattr(chunk, "choices", None)
                if choices:
                    finish_reason = getattr(choices[0], "finish_reason", None)
                    delta = getattr(choices[0], "delta", None)
                    text = getattr(delta, "content", None) if delta else None
                    if text:
                        collected.append(text)
                    if finish_reason == "stop":
                        complete = True
                        break
        except Exception:
            complete = False
        finally:
            if hasattr(stream, "close"):
                await stream.close()

        if complete and collected:
            # поток закрылся целым — отдаём накопленный текст
            for text in collected:
                yield text
            return

        # стрим оборван — гарантированный не-стриминговый перезапрос
        retry = await litellm.acompletion(**{**call_kwargs, "stream": False})
        text = (getattr(retry.choices[0].message, "content", "") or "").strip()
        if text:
            yield text

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

    # ------------------------------------------------------------------ перевод
    async def translate_text(
        self,
        text: str,
        target_language: str,
        source_language: str | None = None,
    ) -> str:
        """Перевести текст через LLM с сохранением научной терминологии.

        Использует ту же модель LLM, что и для генерации ответов. Сохраняет
        названия географических объектов, приборов, методов и аббревиатуры,
        структуру markdown, формулы и цитаты [n].
        """
        source = source_language or self.app.answer_language or "ru"

        prompt = (
            "Переведите следующий текст с "
            f"{source} на {target_language}.\n\n"
            "Правила перевода научной статьи:\n"
            "1. Сохраняйте все названия географических объектов, приборов, "
            "методов и аббревиатуры без перевода (например: «Баренцево море», "
            "«CTD-зонд», «хлорофилл-а», «GF/F»).\n"
            "2. Сохраняйте все формулы, уравнения и математические "
            "обозначения без изменений.\n"
            "3. Сохраняйте структуру markdown: заголовки, списки, таблицы, "
            "цитаты [n], ссылки на источники.\n"
            "4. Переводите только естественно-языковый текст, не изменяя "
            "смысл.\n"
            "5. Сохраняйте стиль научной статьи — формальный, объективный, "
            "без эмоциональных окрасок.\n\n"
            f"Текст для перевода:\n{text}\n\n"
            "Перевод:"
        )

        result = await self.complete(prompt, name="translate_section")
        return result.strip()
