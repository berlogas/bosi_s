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
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from aviary.core import Message
from paperqa.prompts import CANNOT_ANSWER_PHRASE
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
from app.services.citation_guard import repair_markers
from app.services.grounding import check_grounding
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
    reference_from_source,
    source_dict,
    to_pqa_session,
)
from app.services.types import AnswerResult

log = logging.getLogger("boasi.services.rag")

# Дружелюбный отказ вместо англоязычной заглушки paperqa («I cannot answer»).
# Формулировка совпадает с тем, что обещает system-промпт: ответа в
# источниках нет — говорим об этом прямо, а не подаём выдумку.
REFUSAL_TEXT = (
    "В предоставленных источниках нет информации, чтобы ответить на этот "
    "вопрос. Уточните запрос или загрузите документы с нужными данными."
)


def _apply_refusal(text: str) -> str | None:
    """Русский текст отказа, если paperqa ответил отказом; иначе `None`."""
    return REFUSAL_TEXT if CANNOT_ANSWER_PHRASE in (text or "") else None

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

    # Ключи stats, которые сохраняются в историю и показываются UI:
    # остальное (кандидаты, секунды) пользователю не нужно.
    CHECK_KEYS = ("citations", "grounding", "refusal")

    @property
    def checks(self) -> dict[str, Any]:
        """Отчёты проверок ответа — то, что пишется в `messages.checks`."""
        return {key: self.stats[key] for key in self.CHECK_KEYS
                if key in self.stats}


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
        on_stage: Callable[[int, str], None] | None = None,
    ) -> FusionResult:
        """Полный цикл: слияние коллекций -> rerank -> генерация.

        `on_stage(percent, label)` — колбэк прогресса для фоновой задачи:
        без него строка прогресса замирает на первом же проценте, пока
        LLM считает ответ минутами.
        """

        def _stage(percent: int, label: str) -> None:
            if on_stage is not None:
                on_stage(percent, label)

        catalog, stamp = self.load_catalog(db, session_id)

        if use_cache:
            cached = await self.cache.get_or_none(
                session_id=session_id, mode=mode.value, query=query, stamp=stamp)
            if cached is not None:
                log.info("fusion: ответ из кэша (%s)", stamp)
                # Кэш мог сохранить ответ ДО починки маркеров: старые записи
                # содержат «(docname lines 0-0)» — резолвим в номера при чтении,
                # иначе пользователь навсегда увидит мусор из старого ответа.
                answer_text, cached_report = repair_markers(
                    cached.answer, len(cached.sources), sources=cached.sources)
                checks = dict(cached.checks or {
                    "citations": {"ok": True, "cached": True}})
                if cached_report.changed:
                    log.warning("fusion: цитаты из кэша починены: %s",
                                cached_report.to_dict())
                    checks["citations"] = cached_report.to_dict()
                # Ссылки пересобираем из источников: старые записи кэша
                # собраны до нумерации «[n]», а пользователь сверяет их
                # с цитатами в тексте ответа.
                references = ([reference_from_source(s)
                               for s in cached.sources]
                              or list(cached.citations))
                return FusionResult(
                    answer=AnswerResult(question=query, answer=answer_text,
                                        formatted_answer=answer_text,
                                        citations=references,
                                        seconds=cached.seconds,
                                        mode=mode.value, used_context=True),
                    sources=list(cached.sources),
                    references=references,
                    mode=mode, question=query, from_cache=True,
                    stats={"candidates": 0, "selected": len(cached.sources),
                           **checks},
                )

        candidates = await self._evidence(query, session_id, mode, k, catalog)
        _stage(35, "переранжирование кандидатов")
        selected = merge_and_rerank(candidates, mode=mode, k=k, query=query)

        if not selected:
            return await self._answer_without_base(
                db, query=query, mode=mode, catalog=catalog,
                session_id=session_id, on_stage=on_stage)

        sources = [source_dict(c, i + 1) for i, c in enumerate(selected)]
        references = [format_reference(c, i + 1) for i, c in enumerate(selected)]

        generator = (self.registry.session_service(session_id) if session_id
                     else self.registry.global_service())
        pqasession = to_pqa_session(query, selected)
        # самый долгий этап (несколько минут): здесь LLM пишет ответ
        _stage(55, "генерация ответа (LLM)")
        try:
            answer = await generator.ask(
                pqasession, mode=mode.value, max_sources=max_sources,
                evidence=chunks_from_candidates(selected))
        except Exception as exc:  # генерация упала — отдаём контекст без ответа
            log.exception("fusion: генерация не удалась")
            raise UpstreamError(
                f"Не удалось получить ответ: {type(exc).__name__}: {exc}") from exc

        _stage(85, "починка цитат и проверка обоснованности")

        # Маркеры цитат: слабая LLM пишет «(степень 1)» вместо ключей pqac.
        # Чиним в ссылки [n] (нумерация источников в интерфейсе), удаляем
        # номера за пределами выдачи и прогоняем отчёт в лог/stats.
        formatted, citation_report = repair_markers(
            answer.formatted_answer, len(sources), sources=sources)
        if citation_report.changed:
            answer.formatted_answer = formatted
            answer.answer, _ = repair_markers(answer.answer, len(sources),
                                              sources=sources)
        if citation_report.changed or not citation_report.ok or citation_report.uncited:
            log.warning("fusion: цитаты в ответе: %s", citation_report.to_dict())

        # Отказ paperqa («I cannot answer») — показываем по-русски и помечаем,
        # иначе пользователь видит англоязычную заглушку посреди ответа.
        refusal = _apply_refusal(answer.formatted_answer)
        if refusal:
            answer.formatted_answer = refusal
            answer.answer = refusal
            answer.has_successful_answer = False

        # Обоснованность: сущности ответа против найденного контекста.
        # Ловит выдуманные факты («дочерью Петра I»), которых нет в источниках,
        # и показывает их в stats["grounding"] вместе с цитатами.
        contexts = [c.text for c in answer.evidence] or [
            s.get("text", "") for s in sources]
        grounding = check_grounding(answer.formatted_answer, contexts)
        if not grounding.ok:
            log.warning("fusion: обоснованность ответа: %s", grounding.to_dict())

        # источники нумеруем и приклеиваем ссылки к тексту ответа
        answer.citations = references
        answer.context = [{"marker": s["marker"], "text": s["text"],
                           "index": s["index"], "title": s["title"]}
                          for s in sources]

        result = FusionResult(
            answer=answer, sources=sources, references=references,
            mode=mode, question=query,
            stats={"candidates": len(candidates), "selected": len(selected),
                   "seconds": round(answer.seconds, 2),
                   "citations": citation_report.to_dict(),
                   "grounding": grounding.to_dict(),
                   "refusal": bool(refusal)},
        )

        # Записываем в кэш ВСЕГДА: `no_cache` означает «не читать, а посчитать
        # заново», а не «выкинуть результат». Иначе принудительный пересчёт
        # оставлял бы следующий такой же вопрос снова без кэша.
        await self.cache.put_answer(
            session_id=session_id, mode=mode.value, query=query, stamp=stamp,
            payload=CachedAnswer(answer=result.answer.formatted_answer,
                                 sources=sources, citations=references,
                                 seconds=answer.seconds,
                                 checks={"citations": citation_report.to_dict(),
                                         "grounding": grounding.to_dict(),
                                         "refusal": bool(refusal)}))
        return result

    # ------------------------------------------------- ответ без опоры на базу
    async def _answer_without_base(
        self,
        db: Session,
        *,
        query: str,
        mode: SearchMode,
        catalog: DocumentCatalog,
        session_id: str | None = None,
        on_stage: Callable[[int, str], None] | None = None,
    ) -> FusionResult:
        """Ответ, когда по базе нечего процитировать.

        Раньше здесь возвращался `AnswerResult(answer="")`, и интерфейс
        показывал голое «Ответ пуст»: пользователю непонятно, сломалось
        ли что-то или документы просто не загружены. Теперь это обычный
        разговорный ответ LLM, который честно говорит, что база пуста,
        — поэтому на «привет» отвечает приветом, а не молчит.
        """
        base_empty = not catalog.by_dockey
        t0 = time.perf_counter()
        prompt = self._no_base_prompt(query, base_empty=base_empty)
        if on_stage is not None:
            # тот же «длинный» LLM-этап, что и в основном пути
            on_stage(55, "генерация ответа (LLM)")
        text = ""
        try:
            llm = build_pqa_settings(self.registry.app).get_llm()
            result = await llm.call_single(
                # Именно Message, а не dict: LLM внутри зовёт model_dump()
                # и на dict падает с AttributeError.
                messages=[Message(content=prompt)], name="no_base")
            text = (getattr(result, "text", "") or "").strip()
        except Exception as exc:
            log.warning("fusion: ответ без базы не удался: %s", exc)

        if not text:
            # LLM не ответил — всё равно не оставляем пользователя с пустотой.
            text = (
                "База знаний пуста — загрузите документы, и я смогу отвечать "
                "по ним со ссылками на источники."
                if base_empty else
                "По базе ничего не нашлось. Уточните запрос или загрузите "
                "подходящие документы."
            )

        answer = AnswerResult(
            question=query, answer=text, formatted_answer=text,
            citations=[], context=[], evidence=[],
            has_successful_answer=True, mode=mode.value,
            seconds=round(time.perf_counter() - t0, 2), base_empty=True,
        )
        return FusionResult(
            answer=answer, sources=[], references=[], mode=mode,
            question=query,
            stats={"candidates": 0, "selected": 0, "base_empty": base_empty,
                   "citations": {"ok": True, "base_empty": True}},
        )

    @staticmethod
    def _no_base_prompt(query: str, *, base_empty: bool) -> str:
        """Промпт для диалога без RAG-контекста."""
        state = (
            "База знаний сейчас ПУСТА: в неё не загружено ни одного документа."
            if base_empty else
            "В базе есть документы, но по этому запросу ничего не нашлось."
        )
        return (
            f"{state}\n\n"
            "Ты — Бо, ассистент научной поисковой системы. Отвечай по-русски, "
            "дружелюбно и кратко (2–4 предложения), как в обычном чате.\n"
            "Правила:\n"
            "- На приветствие, благодарность или вопрос «делаешь ли ты что-то» "
            "отвечай человечески: поздоровайся и кратко объясни, кто ты: "
            "зовут Бо, ты ассистент этой научной системы.\n"
            "- Обязательно упомяни, что база пуста и поэтому фактические вопросы "
            "пока не на что опереть, и предложи загрузить документы.\n"
            "- Если вопрос содержательный, честно скажи, что без документов "
            "нельзя дать ответ со ссылками на источники. Не выдумывай "
            "источники, цифры и цитаты.\n"
            "- Пиши ТОЛЬКО текст ответа. Не повторяй инструкцию, её пункты и "
            "строку «Сообщение пользователя», не используй служебные метки.\n"
            f'\nСообщение пользователя: «{query.strip()}»'
        )

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
            result = await llm.call_single(messages=[Message(content=prompt)],
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