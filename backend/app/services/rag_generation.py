"""Генерация ответа через PaperQA2 и пост-обработка.

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

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from aviary.core import Message
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.errors import UpstreamError
from app.db.models import SearchMode
from app.services.answer_cache import (
    AnswerCache,
    CachedAnswer,
    get_answer_cache,
)
from app.services.citation_guard import repair_markers
from app.services.generation import parse_citations
from app.services.grounding import check_grounding
from app.services.paperqa_service import ServiceRegistry, get_registry
from app.services.pqa_profile import build_pqa_settings
from app.services.rag_citations import (
    apply_refusal,
    localize_headers,
    renumber_citations,
    strip_question_header,
    strip_references_block,
)
from app.services.rag_fusion import (
    DocumentCatalog,
    chunks_from_candidates,
    format_reference,
    reference_from_source,
    source_dict,
    to_pqa_session,
)
from app.services.rag_trivial import (
    ASSISTANT_NAME,
    is_identity_query,
    is_refusal,
    is_trivial_query,
    trivial_prompt,
)
from app.services.types import AnswerResult

log = logging.getLogger("boasi.services.rag")


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


class AnswerGenerator:
    """Генерация ответа через PaperQA2 с пост-обработкой."""

    def __init__(
        self,
        registry: ServiceRegistry | None = None,
        cache: AnswerCache | None = None,
        app: Any | None = None,
    ) -> None:
        self.registry = registry or get_registry()
        self.cache = cache or get_answer_cache()
        self._app = app or get_settings()

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
        candidates: list[Any] | None = None,
        catalog: DocumentCatalog | None = None,
        stamp: str = "",
    ) -> FusionResult:
        """Полный цикл: слияние коллекций -> rerank -> генерация.

        `on_stage(percent, label)` — колбэк прогресса для фоновой задачи:
        без него строка прогресса замирает на первом же проценте, пока
        LLM считает ответ минутами.
        """

        def _stage(percent: int, label: str) -> None:
            if on_stage is not None:
                on_stage(percent, label)

        # Болтовня («привет», «спасибо») в базе искать нечего: уходим сразу,
        # не грузя ни индекс, ни кэш. Иначе поиск возвращает мусор, и модель
        # пишет на него ответ со ссылками (замер 2026-10-18: ~43 с и ответ
        # «взгляд с информационной точки зрения» со ссылкой на чужой документ).
        if self._app.trivial_query_fast_path:
            # Вопрос о самом помощнике проверяется ПЕРВЫМ: «ты кто?» не болтовня,
            # но и не вопрос по теме, и в базе искать нечего. Без этой ветки он
            # доходил до paperqa и получал честный, но бесполезный отказ
            # «в источниках нет информации» (жалоба 2026-10-19).
            if is_identity_query(query):
                _stage(55, "ответ о помощнике")
                return await self._answer_trivial(
                    query, mode=mode, on_stage=on_stage, kind="identity")
            if is_trivial_query(query):
                _stage(55, "разговорный ответ (запрос без темы)")
                return await self._answer_trivial(query, mode=mode, on_stage=on_stage)

        if catalog is None:
            from app.services.rag_retrieval import EvidenceRetriever
            retriever = EvidenceRetriever(self.registry)
            catalog = retriever._load_catalog(db, session_id)

        if use_cache and stamp:
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

        if candidates is None:
            from app.services.rag_retrieval import EvidenceRetriever
            retriever = EvidenceRetriever(self.registry, self._app)
            candidates = await retriever._evidence(query, session_id, mode, k, catalog)

        _stage(35, "переранжирование кандидатов")
        from app.services.rag_fusion import merge_and_rerank
        selected = merge_and_rerank(
            candidates, mode=mode, k=k, query=query,
            min_relevance=self._app.evidence_min_relevance_score)

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
        # Служебные заголовки paperqa и повтор вопроса. Делаем после починки
        # цитат: citation_guard оперирует номерами [n], но текст на выходе
        # должен быть ровно таким, каким его увидит человек.
        answer.formatted_answer = strip_question_header(
            answer.formatted_answer, query)
        answer.formatted_answer = localize_headers(
            answer.formatted_answer, getattr(self._app, "answer_language", "ru"))
        answer.formatted_answer = strip_references_block(
            answer.formatted_answer)
        # Цитаты пересчитываем ПОСЛЕ удаления блока литературы: номера, которые
        # встречались только в нём, не должны считаться процитированными в
        # ответе, иначе в списке источников появятся документы, на которые
        # сам текст не ссылается.
        citation_report.cited = parse_citations(answer.formatted_answer)
        if citation_report.changed or not citation_report.ok or citation_report.uncited:
            log.warning("fusion: цитаты в ответе: %s", citation_report.to_dict())

        # Список источников показываем только по факту использования: документ,
        # на который модель не сослалась, в ответе не участвует и в интерфейсе
        # только мешает. После отсева перенумеровываем оставшиеся 1..N — иначе
        # единственный показанный источник вышел бы как «[4]», что читается как
        # баг. Перенумерация обязана затронуть и маркеры в тексте ответа,
        # поэтому одной сменой индексов в sources не обойтись.
        if citation_report.cited:
            used = sorted(set(citation_report.cited))
            filtered = [s for s in sources if s["index"] in used]
            if 0 < len(filtered) < len(sources):
                log.info("fusion: источников %d -> %d (в тексте ответа упомянуты %s)",
                         len(sources), len(filtered), used)
                if filtered[0]["index"] != 1 or len(used) != len(filtered):
                    answer.formatted_answer = renumber_citations(
                        answer.formatted_answer, used)
                    citation_report.cited = list(range(1, len(filtered) + 1))
                for new_index, source in enumerate(filtered, start=1):
                    source["index"] = new_index
                sources = filtered
                references = [reference_from_source(s) for s in filtered]
        else:
            log.info("fusion: в ответе нет маркеров [n] — показываем все источники")

        # Отказ paperqa («I cannot answer») — показываем по-русски и помечаем,
        # иначе пользователь видит англоязычную заглушку посреди ответа.
        refusal = apply_refusal(answer.formatted_answer)
        if refusal:
            answer.formatted_answer = refusal
            answer.answer = refusal
            answer.has_successful_answer = False
            # Модель честно сказала, что в базе нет ответа. Показывать 10 найденных
            # документов, на которые она не сослалась, бессмысленно: они не имеют
            # отношения к ответу, а выглядит как «вот что мы нашли вместо ответа».
            # Список очищаем, и предупреждение «ответ без ссылок» снимаем —
            # при отказе отсутствие ссылок это норма, а не проблема.
            sources = []
            references = []
            citation_report.uncited = False
            citation_report.warnings = [
                w for w in citation_report.warnings if "без ссылок" not in w]

        # Обоснованность: сущности ответа против найденного контекста.
        # Ловит выдуманные факты («дочерью Петра I»), которых нет в источниках,
        # и показывает их в stats["grounding"] вместе с цитатами.
        contexts = [c.text for c in answer.evidence] or [
            s.get("text", "") for s in sources]
        grounding = check_grounding(answer.formatted_answer, contexts)
        if not grounding.ok:
            log.warning("fusion: обоснованность ответа: %s", grounding.to_dict())

        # Флаг успеха приводим в соответствие с фактическим текстом: paperqa
        # помечает ответ неуспешным по своим внутренним правилам, а после
        # перевода отказа в русский текст (и тем более при частичном ответе
        # «в контексте упомянуто только…») флаг уезжает в False. В API и кэш
        # уходит именно он, поэтому здесь — единственное место, где он честен.
        if not refusal and answer.formatted_answer.strip():
            answer.has_successful_answer = True

        # источники нумеруем и приклеиваем ссылки к тексту ответа
        answer.citations = references
        answer.context = [{"marker": s["marker"], "text": s["text"],
                           "index": s["index"], "title": s["title"]}
                          for s in sources]

        result = FusionResult(
            answer=answer, sources=sources, references=references,
            mode=mode, question=query,
            stats={"candidates": len(candidates), "selected": len(sources),
                   "selected_before_citation_filter": len(selected),
                   "seconds": round(answer.seconds),
                   "citations": citation_report.to_dict(),
                   "grounding": grounding.to_dict(),
                   "refusal": bool(refusal)},
        )

        # Записываем в кэш ВСЕГДА: `no_cache` означает «не читать, а посчитать
        # заново», а не «выкинуть результат». Иначе принудительный пересчёт
        # оставлял бы следующий такой же вопрос снова без кэша.
        if stamp:
            await self.cache.put_answer(
                session_id=session_id, mode=mode.value, query=query, stamp=stamp,
                payload=CachedAnswer(answer=result.answer.formatted_answer,
                                     sources=sources, citations=references,
                                     seconds=answer.seconds,
                                     checks={"citations": citation_report.to_dict(),
                                             "grounding": grounding.to_dict(),
                                             "refusal": bool(refusal)}))
        return result

    async def _answer_trivial(
        self, query: str, *, mode: SearchMode, on_stage: Any = None,
        kind: str = "greeting",
    ) -> FusionResult:
        """Ответ на болтовню или на вопрос о помощнике: один короткий вызов LLM.

        Отдельный промпт, а не переиспользование `_answer_without_base`: там
        текст честно говорит «база пуста», а здесь база полна — просто вопрос
        не по теме. Врать пользователю о состоянии базы не нужно.

        `kind="identity"` — вопрос обо мне: модель представляется и объясняет,
        что умеет, вместо отказа «в источниках нет информации».
        """
        t0 = time.perf_counter()
        label = ("ответ о помощнике" if kind == "identity"
                 else "разговорный ответ (запрос без темы)")
        if on_stage is not None:
            on_stage(5, "подготовка запроса")
        text = ""
        try:
            # Модель из сервиса: в тестах это заглушка, а не сеть
            llm = self.registry.global_service().chat_llm
            if on_stage is not None:
                on_stage(10, "запрос к модели")
            result = await llm.call_single(
                messages=[Message(content=trivial_prompt(query, kind))],
                name="trivial")
            text = (getattr(result, "text", "") or "").strip()
        except Exception as exc:
            log.warning("fusion: разговорный ответ не удался: %s", exc)
        if on_stage is not None:
            on_stage(100, label)

        if not text:
            text = ("Здравствуйте! Спросите что-нибудь по базе знаний — "
                    "и я отвечу со ссылками на источники.")
        elif kind == "identity" and is_refusal(text):
            # Страховка от отказа: модель на маленькой модели иногда
            # возвращает «в источниках нет информации», а вопрос был о ней.
            text = (
                f"Меня зовут {ASSISTANT_NAME}. Я помощник исследователя в этой "
                "системе: ищу по загруженной базе знаний и отвечаю со ссылками "
                "на источники, работаю с сессиями и проектами статей."
            )
        answer = AnswerResult(
            question=query, answer=text, formatted_answer=text,
            citations=[], context=[], evidence=[], has_successful_answer=True,
            mode=mode.value, seconds=round(time.perf_counter() - t0),
            base_empty=True,
        )
        return FusionResult(
            answer=answer, sources=[], references=[], mode=mode,
            question=query,
            stats={"candidates": 0, "selected": 0, "trivial": True,
                   "identity": kind == "identity",
                   "citations": {"ok": True, "base_empty": True}},
        )

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
            seconds=round(time.perf_counter() - t0), base_empty=True,
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
            "Ты — Бо, ассистент научной поисковой системы. Отвечай по-усски, "
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
            f'\nСосообщение пользователя: «{query.strip()}»'
        )

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


__all__ = ["AnswerGenerator", "FusionResult"]
