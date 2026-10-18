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
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from aviary.core import Message
from paperqa.prompts import CANNOT_ANSWER_PHRASE
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.errors import UpstreamError
from app.db.models import Document, DocumentLink, DocumentStatus, SearchMode
from app.services.answer_cache import (
    AnswerCache,
    CachedAnswer,
    get_answer_cache,
    index_stamp,
)
from app.services.citation_guard import repair_markers
from app.services.generation import parse_citations
from app.services.grounding import check_grounding
from app.services.paperqa_service import ServiceRegistry, get_registry
from app.services.pqa_profile import build_pqa_settings, settings_fingerprint
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

# Заголовки, которые paperqa жёстко вписывает в formatted_answer
# (paperqa/types.py: `f"Question: {question}..."` и `f"\n\nReferences\n\n..."`).
# Приложение русскоязычное, поэтому переводим их на выходе. Правка самого
# ответа делается до repair_markers — тот работает по номерам [n] и заголовки
# не трогает, но текст меняется уже после починки, чтобы отчёт о починке
# показывал то, что видит пользователь.
_HEADER_LABELS = {
    "ru": (("References", "Ссылки"),),
    "en": (),
}


def _localize_headers(text: str, language: str) -> str:
    """Перевести служебный заголовок paperqa «References» на язык приложения.

    Без `\s*$` в шаблоне: `\\s` съел бы и перевод строки, склеив заголовок с
    текстом ответа. Пустые строки вокруг сохраняем — по ним Markdown режет
    абзацы, без них ответ и список ссылок слипаются в одну строку.
    """
    if not text:
        return text
    for english, russian in _HEADER_LABELS.get((language or "ru").lower(), ()):
        text = re.sub(rf"(?m)^{re.escape(english)}$", russian, text)
    return text


def _strip_question_header(text: str, question: str) -> str:
    """Убрать повтор вопроса в начале ответа.

    paperqa начинает `formatted_answer` со строки «Question: <вопрос>», но в чате
    вопрос и так уже написан пользователем над ответом — в ответе он лишний.
    Удаляем только если это действительно наш вопрос (совпадение по тексту):
    иначе рискуем срезать первую строку содержательного ответа.
    """
    if not text or not question:
        return text
    lines = text.splitlines()
    if not lines:
        return text
    first = lines[0].strip()
    if not first.startswith("Question:"):
        return text
    echoed = first[len("Question:"):].strip()
    if echoed != question.strip():
        return text
    rest = lines[1:]
    while rest and not rest[0].strip():
        rest.pop(0)
    return "\n".join(rest)


def _renumber_citations(text: str, used: list[int]) -> str:
    """Сдвинуть маркеры `[old]` в `[new]` по порядку номеров `used`.

    Учитывается и многoисточниковый формат «[4, 7]» — citation_guard собирает
    именно его, когда модель ссылается на несколько документов одним маркером.

    Замена делается одной регуляркой с подстановкой по словарю, а не цепочкой
    `str.replace`: при последовательных заменах («4→1», затем «1→2») старые
    номера затирали бы друг друга.
    """
    mapping = {old: new for new, old in enumerate(used, start=1)}

    def _sub(match: re.Match[str]) -> str:
        numbers = [int(part) for part in re.findall(r"\d{1,3}", match.group(1))]
        if not all(number in mapping for number in numbers):
            return match.group(0)
        # «[4, 7]» — несколько источников в одном маркере: переносим вместе.
        return "[" + ", ".join(str(mapping[number]) for number in numbers) + "]"

    return re.sub(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]", _sub, text)


def _strip_references_block(text: str) -> str:
    """Убрать служебный список литературы в конце ответа paperqa.

    PaperQA дописывает в `formatted_answer` блок «References» со списком ключей
    (types.py:522). В интерфейсе тот же список показывается отдельным блоком
    «Источники» — и он полнее: с областью хранения, категорией и
    релевантностью. Дубликат убираем, экономя место; маркеры `[n]` внутри
    самого ответа остаются, они и нужны для связи утверждения с источником.
    """
    for heading in ("References", "Ссылки"):
        match = re.search(rf"(?m)^{heading}\s*$", text)
        if match and match.start() > 0:
            return text[:match.start()].rstrip() + "\n"
    return text


def _apply_refusal(text: str) -> str | None:
    """Русский текст отказа, если paperqa ответил отказом; иначе `None`."""
    return REFUSAL_TEXT if CANNOT_ANSWER_PHRASE in (text or "") else None

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


# --------------------------------------------------------------- болтовня
# Здравствуйте, спасибо и подобное: запрос, по которому в базе искать нечего.
# Гонять такие фразы в RAG дорого и бессмысленно: замер 2026-10-18 показал,
# что «привет» стоит ~43 с (12 параллельных сводок плюс автоматический повтор
# поиска без сводок), и примерно половина этого уходит впустую.
#
# Хуже того, поиск по базе на болтовню возвращает мусор, и модель пишет на него
# ответ С ССЫЛКАМИ. Это прямое нарушение GROUNDING RULES из промпта paperqa
# («нет подходящего контекста — ответ отказывается отвечать»), причём
# заметное пользователю: на «привет» он получал рассуждение о «взгляде с
# информационной точки зрения» со ссылкой на чужой документ. Для приветствия
# отказ неуместен, поэтому здесь нужен разговорный ответ.
#
# Список закрытый, проверка строгая: срабатывает ТОЛЬКО когда запрос целиком
# совпал с одной из фраз. «привет» — болтовня, «привет, что такое CTD?» —
# нормальный вопрос. Никаких эвристик по длине или знакам препинания: они дали
# бы ложные срабатывания на коротких, но содержательных запросах («GF/F?»,
# «хлорофилл»), а цена ошибки — потерянный ответ по теме.
TRIVIAL_QUERIES = frozenset({
    "привет", "приветик", "приветики", "здравствуй", "здравствуйте",
    "добрый день", "доброе утро", "добрый вечер", "доброго дня",
    "доброй ночи", "хай", "спасибо", "спасибочки", "благодарю",
    "пожалуйста", "простите", "извините", "пока", "до свидания",
    "прощай", "да", "нет", "ага", "угу", "ок", "окей", "хорошо",
    "ясно", "понятно", "принято", "тест", "тестик", "йо", "хеллоу",
    "hi", "hello", "hey", "thanks", "thank you", "ok", "okay", "yes", "no",
})


def is_trivial_query(query: str) -> bool:
    """Болтовня ли это — запрос, для которого поиск по базе не нужен.

    Проверка намеренно примитивная: сравнение строки целиком по закрытому
    списку. Словарь состоит из слов, поэтому термин с такой же формой
    («нет») в него не попадает.
    """
    normalized = re.sub(r"[^\w\s]", " ", (query or "").lower(), flags=re.UNICODE)
    normalized = " ".join(normalized.split())
    if not normalized or len(normalized.split()) > 3:
        return False
    return normalized in TRIVIAL_QUERIES


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
                 cache: AnswerCache | None = None,
                 app: Any | None = None) -> None:
        self.registry = registry or get_registry()
        self.cache = cache or get_answer_cache()
        self._app = app or get_settings()
        # Отпечаток настроек входит в ключ кэша: правка промпта или смена модели
        # обязана делать старые ответы недействительными, иначе пользователь
        # продолжает получать ответ по прежним правилам.
        self._config_stamp = settings_fingerprint(build_pqa_settings(self._app))

    # ------------------------------------------------------------- каталог
    @staticmethod
    def load_catalog(db: Session, session_id: str | None,
                     config: str | None = None) -> tuple[DocumentCatalog, str]:
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
        stamp = index_stamp(session_id, len(rows), chunks, config)
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
        catalog, stamp = self.load_catalog(db, session_id, self._config_stamp)
        candidates = await self._evidence(query, session_id, mode, k, catalog)
        selected = merge_and_rerank(
            candidates, mode=mode, k=k, query=query,
            min_relevance=self._app.evidence_min_relevance_score)
        sources = [source_dict(c, i + 1) for i, c in enumerate(selected)]
        stats = {"candidates": len(candidates), "selected": len(selected),
                 "stamp": stamp}
        return sources, stats

    async def _evidence(self, query: str, session_id: str | None, mode: SearchMode,
                        k: int, catalog: DocumentCatalog) -> list[Candidate]:
        """Параллельно собрать кандидаты из разрешённых режимом коллекций.

        Режим сводок (`EVIDENCE_SKIP_SUMMARY=false`) — рекомендация PaperQA, но
        он опирается на `relevance_score` от LLM. С облачной моделью оценка
        нестабильна: нередко приходит 0, и paperqa отбрасывает ВСЕ контексты
        (`c.score > 0` в docs.py), запрос при этом тратит время впустую
        (замер 2026-10-12: 83 с и 0 кандидатов). Поэтому при пустом результате
        делаем один повтор без сводок — тогда релевантность считается по
        эмбеддингам (см. _restore_relevance). Медленно, но не «нет данных».
        """
        candidates = await self._evidence_once(query, session_id, mode, k, catalog,
                                                skip_summary=None)
        if candidates or self._app.evidence_skip_summary:
            return candidates
        log.warning("fusion: сводки не дали ни одного контекста — повтор без них")
        return await self._evidence_once(query, session_id, mode, k, catalog,
                                         skip_summary=True)

    async def _evidence_once(self, query: str, session_id: str | None,
                             mode: SearchMode, k: int, catalog: DocumentCatalog,
                             skip_summary: bool | None) -> list[Candidate]:
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
    async def _restore_relevance(service, query: str,  # noqa: ANN001
                                 contexts: list) -> None:
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

        # Болтовня («привет», «спасибо») в базе искать нечего: уходим сразу,
        # не грузя ни индекс, ни кэш. Иначе поиск возвращает мусор, и модель
        # пишет на него ответ со ссылками (замер 2026-10-18: ~43 с и ответ
        # «взгляд с информационной точки зрения» со ссылкой на чужой документ).
        if self._app.trivial_query_fast_path and is_trivial_query(query):
            _stage(55, "разговорный ответ (запрос без темы)")
            return await self._answer_trivial(query, mode=mode, on_stage=on_stage)

        catalog, stamp = self.load_catalog(db, session_id, self._config_stamp)

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
        answer.formatted_answer = _strip_question_header(
            answer.formatted_answer, query)
        answer.formatted_answer = _localize_headers(
            answer.formatted_answer, getattr(self._app, "answer_language", "ru"))
        answer.formatted_answer = _strip_references_block(
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
                    answer.formatted_answer = _renumber_citations(
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
        refusal = _apply_refusal(answer.formatted_answer)
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
    async def _answer_trivial(
        self, query: str, *, mode: SearchMode, on_stage: Any = None,
    ) -> FusionResult:
        """Ответ на болтовню: один короткий вызов LLM, без поиска и ссылок.

        Отдельный промпт, а не переиспользование `_answer_without_base`: там
        текст честно говорит «база пуста», а здесь база полна — просто вопрос
        не по теме. Врать пользователю о состоянии балы не нужно.
        """
        t0 = time.perf_counter()
        if on_stage is not None:
            on_stage(55, "генерация ответа (LLM)")
        text = ""
        try:
            # Модель из сервиса: в тестах это заглушка, а не сеть
            llm = self.registry.global_service().chat_llm
            result = await llm.call_single(
                messages=[Message(content=self._trivial_prompt(query))],
                name="trivial")
            text = (getattr(result, "text", "") or "").strip()
        except Exception as exc:
            log.warning("fusion: разговорный ответ не удался: %s", exc)

        if not text:
            text = ("Здравствуйте! Спросите что-нибудь по базе знаний — "
                    "и я отвечу со ссылками на источники.")
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
                   "citations": {"ok": True, "base_empty": True}},
        )

    @staticmethod
    def _trivial_prompt(query: str) -> str:
        """Промпт для болтовни: коротко, по-русски, без ссылок и выдумки."""
        return (
            "Пользователь написал в поисковой системе по научной литературе "
            f"ровно это: {query!r}. Это не вопрос по теме, а приветствие, "
            "благодарность или прощальная реплика."
            "\n\n"
            + "Ответь по-русски, дружелюбно и ОЧЕНЬ кратко (1-2 предложения). "
            "Ничего не цитируй и не выдумывай: предложи спросить про базу "
            "знаний или уточнить тему."
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