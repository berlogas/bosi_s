"""Сбор кандидатов из коллекций PaperQA и их слияние.

PaperQA умеет искать по одной коллекции (`Docs`). Исследователю нужны ответы с
указанием источника: 📚 глобальная база и 📁 документы его сессии. Поэтому мы
собираем контекст сами:

1. параллельно зовём `aget_evidence` у глобальной и сессионной коллекций;
2. сливаем кандидатов и переоцениваем их по приоритету (merge + rerank);
3. берём top-k и **один раз** вызываем `aquery(PQASession)`.

Шаг 3 — не оптимизация ради скорости, а корректность: `aquery` со строкой
сам повторно вызывает `aget_evidence` (спайк Фазы 0: 374 с против 118 с).
`Docs.aquery` при готовых `contexts` повторный поиск не делает.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import SearchMode
from app.services.paperqa_service import ServiceRegistry, get_registry
from app.services.rag_fusion import (
    Candidate,
    DocumentCatalog,
    SourceScope,
    build_candidates,
    merge_and_rerank,
    source_dict,
)

log = logging.getLogger("boasi.services.rag")

# Сколько кандидатов берём у каждой коллекции ДО rerank. Берём с запасом:
# rerank работает по приоритету, а не по score, поэтому кандидатов нужно
# больше, чем останется в выдаче. Лишние кандидаты бесплатны — они уже в
# индексе, повторного поиска не происходит.
def _evidence_k(k: int) -> int:
    # Каждый фрагмент сверх отсева уходит в LLM на сводку (≈7 с на облаке),
    # поэтому раздувать take дорого: 20 сводок на коллекцию давали 120 с на
    # вопрос. 12 — эмпирическая середина: хватает, чтобы нужный фрагмент
    # попал в выдачу, и заметно дешевле.
    return max(k, 12) if k >= 5 else max(k * 2, 10)


class EvidenceRetriever:
    """Сбор и слияние кандидатов из разрешённых режимом коллекций."""

    def __init__(self, registry: ServiceRegistry | None = None,
                 app: Any | None = None) -> None:
        self.registry = registry or get_registry()
        self._app = app or get_settings()

    async def retrieve(
        self,
        db: Session,
        *,
        query: str,
        session_id: str | None = None,
        mode: SearchMode = SearchMode.hybrid,
        k: int = 10,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Только источники, без генерации.

        Нужен Фазе 7: генератор разделов сам строит промпт со своими
        правилами цитирования, а не отдаёт вопрос PaperQA.
        """
        catalog = self._load_catalog(db, session_id)
        candidates = await self._evidence(query, session_id, mode, k, catalog)
        selected = merge_and_rerank(
            candidates, mode=mode, k=k, query=query,
            min_relevance=self._app.evidence_min_relevance_score)
        sources = [source_dict(c, i + 1) for i, c in enumerate(selected)]
        stats = {"candidates": len(candidates), "selected": len(selected)}
        return sources, stats

    async def _evidence(
        self,
        query: str,
        session_id: str | None,
        mode: SearchMode,
        k: int,
        catalog: DocumentCatalog,
    ) -> list[Candidate]:
        """Параллельно собрать кандидатов из разрешённых режимом коллекций.

        Режим сводок (`EVIDENCE_SKIP_SUMMARY=false`) — рекомендация PaperQA, но
        он опирается на `relevance_score` от LLM. С облачной моделью оценка
        нестабильна: нередко приходит 0, и paperqa отбрасывает ВСЕ контексты
        (`c.score > 0` в docs.py), запрос при этом тратит время впустую
        (замер 2026-10-12: 83 с и 0 кандидатов). Поэтому при пустом результате
        делаем один повтор без сводок — тогда релевантность считается по
        эмбеддингам (см. _restore_relevance). Медленно, но не «нет данных».
        """
        candidates = await self._evidence_once(
            query, session_id, mode, k, catalog, skip_summary=None)
        if candidates or self._app.evidence_skip_summary:
            return candidates
        log.warning("fusion: сводки не дали ни одного контекста — повтор без них")
        return await self._evidence_once(
            query, session_id, mode, k, catalog, skip_summary=True)

    async def _evidence_once(
        self,
        query: str,
        session_id: str | None,
        mode: SearchMode,
        k: int,
        catalog: DocumentCatalog,
        skip_summary: bool | None,
    ) -> list[Candidate]:
        take = _evidence_k(k)
        tasks: list[Any] = []

        # Коллекции наполняются в память лениво: при старте приложения
        # восстанавливается только глобальная (main.lifespan), а сервис сессии
        # создаётся при первом обращении и по умолчанию пуст. Без restore_state
        # здесь поиск по сессии молча возвращает 0 кандидатов.
        if mode is not SearchMode.session_only:
            await self.registry.global_service().restore_state()
        if session_id and mode is not SearchMode.global_only:
            await self.registry.session_service(session_id).restore_state()

        if mode is not SearchMode.session_only:
            tasks.append(self.registry.global_service().get_evidence(
                query, k=take, skip_summary=skip_summary))
        if session_id and mode is not SearchMode.global_only:
            tasks.append(self.registry.session_service(session_id).get_evidence(
                query, k=take, skip_summary=skip_summary))

        if not tasks:
            return []

        scopes = []
        services = []
        if mode is not SearchMode.session_only:
            scopes.append(SourceScope.GLOBAL)
            services.append(self.registry.global_service())
        if session_id and mode is not SearchMode.global_only:
            scopes.append(SourceScope.SESSION)
            services.append(self.registry.session_service(session_id))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        candidates: list[Candidate] = []
        for scope, service, result in zip(scopes, services, results, strict=False):
            if isinstance(result, BaseException):
                # С трассировкой, а не только строкой: часть таких сбоев
                # приходит изнутри paperqa, и без стека видно только
                # «expected string or bytes-like object, got 'list'» —
                # почему модель вернула не строку, по этому не понять.
                log.warning("fusion: aget_evidence(%s) не удался: %s",
                            scope.value, result, exc_info=result)
                continue
            contexts = result[1].contexts
            await self._restore_relevance(service, query, contexts)
            candidates.extend(build_candidates(contexts, scope, catalog))
            log.info(
                "fusion: retrieval[%s] вернул %d кандидатов (%s)",
                scope.value,
                len(contexts),
                [c.docname or (c.context.text.doc.dockey or "")[:12]
                 for c in candidates if c.scope is scope][:10],
            )
        return candidates

    @staticmethod
    async def _restore_relevance(
        service: Any,
        query: str,
        contexts: list[Any],
    ) -> None:
        """Заменить синтетический score на косинус, когда сводки отключены.

        При `EVIDENCE_SKIP_SUMMARY=true` paperqa не просит у LLM оценку
        релевантности и ставит всем контекстам 5 — тогда `final_score` зависит
        только от категории документа, и в выдачу одинаково попадают и
        релевантные, и совершенно посторонние тексты. Считаем релевантность
        сами по уже посчитанным при индексации эмбеддингам.
        """
        if not contexts or len({ctx.score for ctx in contexts}) > 1:
            return  # оценки разные — значит, сводки отработали и оценка настоящая
        scores = await service.embedding_relevance(query, contexts)
        if not scores:
            return
        for ctx in contexts:
            value = scores.get((str(ctx.text.doc.dockey), ctx.text.name))
            if value is not None:
                ctx.score = float(value) * 10.0  # шкала paperqa — 0..10

        log.info(
            "fusion: релевантность пересчитана по эмбеддингам для %d контекстов "
            "(skip_summary=%s), top=%.2f",
            len(contexts),
            getattr(service.app, "evidence_skip_summary", None),
            max(scores.values()),
        )

    @staticmethod
    def _load_catalog(
        db: Session,
        session_id: str | None,
    ) -> DocumentCatalog:
        """Собрать метаданные документов (сессии + глобальные)."""
        from app.db.models import Document, DocumentLink, DocumentStatus
        from app.services.rag_fusion import DocumentCatalog

        scope = (
            __import__('sqlalchemy').select(Document).where(
                Document.session_id.is_(None),
                Document.status != DocumentStatus.error,
            )
            if session_id is None
            else __import__('sqlalchemy').select(Document).where(
                (Document.session_id == session_id)
                | Document.session_id.is_(None),
                Document.status != DocumentStatus.error,
            )
        )
        rows = list(db.scalars(scope))

        projects_by_document: dict[str, set[str]] = {}
        for link in db.scalars(__import__('sqlalchemy').select(DocumentLink).where(
                DocumentLink.session_id == session_id)):
            if link.project_id:
                projects_by_document.setdefault(link.document_id, set()).add(
                    link.project_id)

        return DocumentCatalog.from_rows(rows, projects_by_document)


__all__ = ["EvidenceRetriever"]
