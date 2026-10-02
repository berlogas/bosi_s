"""Оркестратор RAG-fusion (Фаза 6).

Связывает три слоя, которые иначе не видят друг друга:
  * реестр `documents` — категории, теги, привязка к проектам;
  * коллекции PaperQA — глобальная база и коллекция сессии;
  * генерация — ровно один вызов `aquery(PQASession)` на объединённый контекст.

Поток запроса:
    параллельно aget_evidence(глобальная, сессия)
      -> DocumentCatalog
      -> merge + приоритетный rerank (rag_fusion)
      -> top-k
      -> один aquery(PQASession)
      -> ответ + источники 📚/📁
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import UpstreamError
from app.db.models import Document, DocumentLink, DocumentStatus, SearchMode
from app.services.answer_cache import (
    AnswerCache,
    CachedAnswer,
    get_answer_cache,
    index_stamp,
)
from app.services.paperqa_service import ServiceRegistry, get_registry
from app.services.pqa_profile import build_pqa_settings
from app.services.rag_fusion import (
    Candidate,
    DocumentCatalog,
    SourceScope,
    build_candidates,
    chunks_from_candidates,
    format_reference,
    merge_and_rerank,
    source_dict,
    to_pqa_session,
)
from app.services.types import AnswerResult

log = logging.getLogger("boasi.services.rag")

# Сколько кандидатов берём у каждой коллекции ДО rerank. Берём с запасом:
# rerank работает по приоритету, а не по score, поэтому кандидатов нужно
# больше, чем останется в выдаче. Лишние кандидаты бесплатны — они уже в
# индексе, повторного поиска не происходит.
def _evidence_k(k: int) -> int:
    return max(k, 20) if k >= 5 else max(k * 2, 10)


@dataclass
class FusionResult:
    """Ответ fusion вместе с источниками и признаком кэша."""

    answer: AnswerResult
    sources: list[dict[str, Any]] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    mode: SearchMode = SearchMode.hybrid
    question: str = ""
    from_cache: bool = False
    stats: dict[str, Any] = field(default_factory=dict)


class RagFusionService:
    def __init__(self, registry: ServiceRegistry | None = None,
                 cache: AnswerCache | None = None) -> None:
        self.registry = registry or get_registry()
        self.cache = cache or get_answer_cache()

    # ------------------------------------------------------------- каталог
    @staticmethod
    def load_catalog(db: Session, session_id: str | None) -> tuple[DocumentCatalog, str]:
        """Собрать метаданные документов (сессии + глобальные) и отпечаток индекса."""
        scope = (
            select(Document).where(
                Document.session_id.is_(None),
                Document.status != DocumentStatus.error,
            )
            if session_id is None
            else select(Document).where(
                (Document.session_id == session_id)
                | Document.session_id.is_(None),
                Document.status != DocumentStatus.error,
            )
        )
        rows = list(db.scalars(scope))

        projects_by_document: dict[str, set[str]] = {}
        for link in db.scalars(select(DocumentLink).where(
                DocumentLink.session_id == session_id)):
            if link.project_id:
                projects_by_document.setdefault(link.document_id, set()).add(
                    link.project_id)

        catalog = DocumentCatalog.from_rows(rows, projects_by_document)
        chunks = sum(row.chunks_count or 0 for row in rows)
        stamp = index_stamp(session_id, len(rows), chunks)
        return catalog, stamp

    # ------------------------------------------------------------- поиск
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
        catalog, stamp = self.load_catalog(db, session_id)
        candidates = await self._evidence(query, session_id, mode, k, catalog)
        selected = merge_and_rerank(candidates, mode=mode, k=k, query=query)
        sources = [source_dict(c, i + 1) for i, c in enumerate(selected)]
        stats = {"candidates": len(candidates), "selected": len(selected),
                 "stamp": stamp}
        return sources, stats

    async def _evidence(self, query: str, session_id: str | None, mode: SearchMode,
                        k: int, catalog: DocumentCatalog) -> list[Candidate]:
        """Параллельно собрать кандидаты из разрешённых режимом коллекций."""
        take = _evidence_k(k)
        tasks: list[Any] = []

        if mode is not SearchMode.session_only:
            tasks.append(self.registry.global_service().get_evidence(query, k=take))
        if session_id and mode is not SearchMode.global_only:
            tasks.append(self.registry.session_service(session_id).get_evidence(
                query, k=take))

        if not tasks:
            return []

        scopes = []
        if mode is not SearchMode.session_only:
            scopes.append(SourceScope.GLOBAL)
        if session_id and mode is not SearchMode.global_only:
            scopes.append(SourceScope.SESSION)

        results = await asyncio.gather(*tasks, return_exceptions=True)
        candidates: list[Candidate] = []
        for scope, result in zip(scopes, results, strict=False):
            if isinstance(result, BaseException):
                log.warning("fusion: aget_evidence(%s) не удался: %s", scope.value, result)
                continue
            candidates.extend(build_candidates(result[1].contexts, scope, catalog))
        return candidates

    # ------------------------------------------------------------- ответ
    async def answer(
        self,
        db: Session,
        *,
        query: str,
        session_id: str | None = None,
        mode: SearchMode = SearchMode.hybrid,
        k: int = 10,
        max_sources: int = 5,
        use_cache: bool = True,
    ) -> FusionResult:
        """Полный цикл: слияние коллекций -> rerank -> генерация."""
        catalog, stamp = self.load_catalog(db, session_id)

        if use_cache:
            cached = await self.cache.get_or_none(
                session_id=session_id, mode=mode.value, query=query, stamp=stamp)
            if cached is not None:
                log.info("fusion: ответ из кэша (%s)", stamp)
                return FusionResult(
                    answer=AnswerResult(question=query, answer=cached.answer,
                                        formatted_answer=cached.answer,
                                        citations=cached.citations,
                                        seconds=cached.seconds,
                                        mode=mode.value, used_context=True),
                    sources=list(cached.sources),
                    references=list(cached.citations),
                    mode=mode, question=query, from_cache=True,
                    stats={"candidates": 0, "selected": len(cached.sources)},
                )

        candidates = await self._evidence(query, session_id, mode, k, catalog)
        selected = merge_and_rerank(candidates, mode=mode, k=k, query=query)

        if not selected:
            return FusionResult(
                answer=AnswerResult(question=query, answer="", formatted_answer="",
                                    has_successful_answer=False, mode=mode.value),
                mode=mode, question=query,
                stats={"candidates": len(candidates), "selected": 0},
            )

        sources = [source_dict(c, i + 1) for i, c in enumerate(selected)]
        references = [format_reference(c, i + 1) for i, c in enumerate(selected)]

        generator = (self.registry.session_service(session_id) if session_id
                     else self.registry.global_service())
        pqasession = to_pqa_session(query, selected)
        try:
            answer = await generator.ask(
                pqasession, mode=mode.value, max_sources=max_sources,
                evidence=chunks_from_candidates(selected))
        except Exception as exc:  # генерация упала — отдаём контекст без ответа
            log.exception("fusion: генерация не удалась")
            raise UpstreamError(
                f"Не удалось получить ответ: {type(exc).__name__}: {exc}") from exc

        # источники нумеруем и приклеиваем ссылки к тексту ответа
        answer.citations = references
        answer.context = [{"marker": s["marker"], "text": s["text"],
                           "index": s["index"], "title": s["title"]}
                          for s in sources]

        result = FusionResult(
            answer=answer, sources=sources, references=references,
            mode=mode, question=query,
            stats={"candidates": len(candidates), "selected": len(selected),
                   "seconds": round(answer.seconds, 2)},
        )

        # Записываем в кэш ВСЕГДА: `no_cache` означает «не читать, а посчитать
        # заново», а не «выкинуть результат». Иначе принудительный пересчёт
        # оставлял бы следующий такой же вопрос снова без кэша.
        await self.cache.put_answer(
            session_id=session_id, mode=mode.value, query=query, stamp=stamp,
            payload=CachedAnswer(answer=result.answer.formatted_answer,
                                 sources=sources, citations=references,
                                 seconds=answer.seconds))
        return result

    # ------------------------------------------------------------- уточнения
    async def suggest_queries(self, query: str, *, limit: int = 4) -> list[str]:
        """3–5 уточняющих вопросов по теме запроса (через LLM, при отказе — [])."""
        if not query.strip():
            return []
        prompt = (
            "Пользователь задал вопрос в научной поисковой системе:\n"
            f"{query}\n\n"
            f"Напиши от {limit} до {limit + 1} уточняющих вопросов, которые помогли бы "
            "найти более точные ответы. По одному в строке, без нумерации и пояснений, "
            "только сами вопросы."
        )
        try:
            llm = build_pqa_settings(self.registry.app).get_llm()
            result = await llm.call_single(messages=[{"role": "user",
                                                       "content": prompt}],
                                           name="suggest")
            text = getattr(result, "text", "") or ""
        except Exception as exc:
            log.warning("fusion: suggest_queries не удался: %s", exc)
            return []
        return _parse_suggestions(text, limit)


def _parse_suggestions(text: str, limit: int) -> list[str]:
    out: list[str] = []
    for line in (text or "").splitlines():
        cleaned = line.strip().lstrip("-*0123456789. )").strip()
        if len(cleaned) < 8:
            continue
        out.append(cleaned)
        if len(out) >= limit + 1:
            break
    return out