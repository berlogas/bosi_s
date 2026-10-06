"""RAG Fusion: слияние коллекций и приоритетный rerank (Фаза 6).

Зачем это нужно
---------------
PaperQA умеет искать по одной коллекции (`Docs`). Исследователю нужны ответы с
указанием источника: 📚 глобальная база и 📁 документы его сессии. Поэтому мы
собираем контекст сами:

1. параллельно зовём `aget_evidence` у глобальной и сессионной коллекций;
2. сливаем кандидатов и переоцениваем их по приоритету (merge + rerank);
3. берём top-k и **один раз** вызываем `aquery(PQASession)`.

Шаг 3 — не оптимизация ради скорости, а корректность: `aquery` со строкой
сам повторно вызывает `aget_evidence` (спайк Фазы 0: 374 с против 118 с).
`Docs.aquery` при готовых `contexts` повторный поиск не делает.

Отступление от плана
--------------------
План предполагал «сессионную Docs, разбитую по категориям». Мы держим одну
`Docs` на сессию (так её строит и восстанавливает Фаза 2/5: один `Docs` =
одна коллекция `session:<id>`, один набор чанков в `document_chunks`).
Категорию берём из реестра `documents` по `dockey` и взвешиваем на этапе
rerank. Иначе пришлось бы делать 6 вызовов `aget_evidence` вместо двух, что на
CPU-инференсе означает кратный рост времени ответа.

Детерминизм
-----------
Приоритет — функция только от (режим, категория, теги, dockey). Сортировка по
`(-final_score, dockey, name, текст)`, поэтому один и тот же вопрос на одном
индексе всегда даёт один и тот же порядок источников.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from paperqa import Context, PQASession

from app.db.models import DocumentCategory, SearchMode
from app.services.types import SOURCE_MARK, ScoredChunk, SourceKind

# --------------------------------------------------------------------------- веса
# Приоритет из ТЗ: проект 1.0 > project_data/draft 0.8 > temp_literature 0.6
# > глобальная база 0.4.
WEIGHT_PROJECT = 1.0
WEIGHT_PROJECT_DOC = 0.8
WEIGHT_SESSION_MISC = 0.6
WEIGHT_GLOBAL = 0.4
WEIGHT_GLOBAL_IN_PROJECT_FOCUS = 0.1  # глобальная база почти не мешает проекту

PROJECT_CATEGORIES = frozenset({
    DocumentCategory.project_draft.value,
    DocumentCategory.project_data.value,
})
SESSION_MISC_CATEGORIES = frozenset({
    DocumentCategory.temp_literature.value,
    DocumentCategory.notes.value,
    DocumentCategory.supplementary.value,
})

# Бонусы и штрафы (детерминированные константы, не «коэффициенты под настроение»).
TAG_MATCH_BONUS = 0.10
PROJECT_LINK_BONUS = 0.05
DEDUP_PENALTY = 0.50

_WORD_RE = re.compile(r"[\w\-]+", re.UNICODE)

# Русские падежные окончания, которые достаточно срезать, чтобы «Баренцево» и
# «Баренцеве» стали одним словом. Полноценный стеммер тянет за собой словари и
# сеть, а контур работает оффлайн — поэтому лёгкое усечение хвоста.
_ENDINGS = ("иями", "ями", "ами", "ыми", "иях", "ях", "ией", "ей", "ий",
            "ый", "ая", "ое", "ые", "ой", "ов", "ев", "ам", "ям", "ах", "ях",
            "ию", "ью", "ия", "ья", "ов", "ем", "ом", "им", "ым", "у", "ю",
            "я", "а", "о", "е", "и", "ы", "ь", "й")
_MIN_STEM = 4


def stem(word: str) -> str:
    """Грубая основа слова: без морфологии теги и вопрос не сойдутся."""
    w = word.lower()
    for ending in _ENDINGS:
        if w.endswith(ending) and len(w) - len(ending) >= _MIN_STEM:
            return w[: -len(ending)]
    return w


def tokenize(text: str) -> set[str]:
    """Слова запроса длиной от 2 символов — для сопоставления с тегами."""
    return {t.lower() for t in _WORD_RE.findall(text or "") if len(t) >= 2}


def stems(text: str) -> set[str]:
    """Основы слов — по ним сопоставляем теги с вопросом."""
    return {stem(t) for t in tokenize(text)}


class SourceScope(str, Enum):
    GLOBAL = "global"
    SESSION = "session"


# --------------------------------------------------------------------------- каталог
@dataclass(slots=True)
class DocumentMeta:
    """Метаданные документа из реестра `documents`."""

    dockey: str
    title: str | None = None
    category: str | None = None
    tags: tuple[str, ...] = ()
    session_id: str | None = None
    linked_projects: tuple[str, ...] = ()

    @property
    def is_project_linked(self) -> bool:
        return bool(self.linked_projects)


@dataclass
class DocumentCatalog:
    """Карта `dockey -> DocumentMeta` для быстрого обогащения кандидатов."""

    by_dockey: dict[str, DocumentMeta] = field(default_factory=dict)

    def get(self, dockey: str) -> DocumentMeta:
        return self.by_dockey.get(dockey) or DocumentMeta(dockey=dockey)

    def update(self, meta: DocumentMeta) -> None:
        self.by_dockey[meta.dockey] = meta

    @classmethod
    def from_rows(cls, rows: Iterable[Any],
                  projects_by_document: dict[str, set[str]] | None = None,
                  ) -> DocumentCatalog:
        catalog = cls()
        for row in rows:
            dockey = getattr(row, "dockey", None)
            if not dockey:
                continue
            catalog.update(DocumentMeta(
                dockey=str(dockey),
                title=getattr(row, "title", None),
                category=getattr(getattr(row, "category", None), "value", None),
                tags=tuple(getattr(row, "tags", None) or ()),
                session_id=getattr(row, "session_id", None),
                linked_projects=tuple(sorted((projects_by_document or {}).get(
                    str(dockey), set()))),
            ))
        return catalog

    def __len__(self) -> int:
        return len(self.by_dockey)


# --------------------------------------------------------------------------- кандидаты
@dataclass(slots=True)
class Candidate:
    """Фрагмент контекста с оценками до и после rerank."""

    context: Context
    scope: SourceScope
    meta: DocumentMeta
    raw_score: float
    priority: float = 0.0
    final_score: float = 0.0
    dedup_penalty: float = 0.0
    docname: str = ""

    @property
    def dockey(self) -> str:
        return str(self.context.text.doc.dockey)

    @property
    def name(self) -> str | None:
        return self.context.text.name

    @property
    def text(self) -> str:
        return self.context.text.text or ""

    @property
    def marker(self) -> str:
        return SOURCE_MARK[SourceKind.GLOBAL if self.scope is SourceScope.GLOBAL
                           else SourceKind.SESSION]


def category_weight(category: str | None, scope: SourceScope,
                     *, mode: SearchMode, project_linked: bool = False) -> float:
    """Вес источника по категории и режиму поиска."""
    if mode is SearchMode.global_only:
        return WEIGHT_GLOBAL if scope is SourceScope.GLOBAL else 0.0
    if mode is SearchMode.session_only and scope is SourceScope.GLOBAL:
        return 0.0
    if scope is SourceScope.GLOBAL:
        return (WEIGHT_GLOBAL_IN_PROJECT_FOCUS if mode is SearchMode.project_focus
                else WEIGHT_GLOBAL)

    if project_linked:
        return WEIGHT_PROJECT
    if category in PROJECT_CATEGORIES:
        return WEIGHT_PROJECT_DOC
    if category in SESSION_MISC_CATEGORIES or not category:
        return WEIGHT_SESSION_MISC
    return WEIGHT_SESSION_MISC


def is_allowed(candidate_category: str | None, scope: SourceScope, *,
               mode: SearchMode, project_linked: bool = False) -> bool:
    """Отсев кандидатов, которые не должны попасть в выдачу режима."""
    if mode is SearchMode.global_only:
        return scope is SourceScope.GLOBAL
    if mode is SearchMode.session_only:
        return scope is SourceScope.SESSION
    if mode is SearchMode.project_focus:
        if scope is SourceScope.GLOBAL:
            return True  # но с минимальным весом
        return project_linked or candidate_category in PROJECT_CATEGORIES
    return True  # hybrid


def score_candidate(candidate: Candidate, *, mode: SearchMode,
                    query_tokens: set[str]) -> None:
    """Проставить `priority` и `final_score` (детерминированно)."""
    category = candidate.meta.category
    candidate.priority = category_weight(
        category, candidate.scope, mode=mode,
        project_linked=candidate.meta.is_project_linked)

    bonus = 0.0
    if query_tokens:
        tag_stems = {stem(t) for t in candidate.meta.tags}
        if tag_stems & query_tokens:
            bonus += TAG_MATCH_BONUS
        if category and stem(category) in query_tokens:
            bonus += TAG_MATCH_BONUS
    if candidate.meta.is_project_linked:
        bonus += PROJECT_LINK_BONUS

    candidate.final_score = (candidate.raw_score * candidate.priority
                             + bonus - candidate.dedup_penalty)
    candidate.docname = str(candidate.context.text.doc.docname or "")


def _dedup_key(candidate: Candidate) -> tuple[str, str, str]:
    """Ключ для отсева дубликатов: один документ + начало текста."""
    return (candidate.dockey, candidate.name or "", candidate.text[:80].strip())


def merge_and_rerank(
    candidates: Sequence[Candidate],
    *,
    mode: SearchMode = SearchMode.hybrid,
    k: int = 10,
    query: str = "",
) -> list[Candidate]:
    """Слить кандидатов из нескольких коллекций и выбрать top-k.

    Штраф за дубликат: если тот же фрагмент пришёл и из глобальной базы, и из
    сессии (пользователь загрузил копию статьи в сессию), вторая копия
    получает `DEDUP_PENALTY`, чтобы не занимать два места в выдаче.
    """
    query_tokens = stems(query)

    kept: list[Candidate] = []
    seen: dict[tuple[str, str, str], int] = {}
    for candidate in candidates:
        if not is_allowed(candidate.meta.category, candidate.scope, mode=mode,
                          project_linked=candidate.meta.is_project_linked):
            continue
        score_candidate(candidate, mode=mode, query_tokens=query_tokens)
        key = _dedup_key(candidate)
        if key in seen:
            candidate.dedup_penalty = DEDUP_PENALTY
        else:
            seen[key] = 1
        kept.append(candidate)

    kept.sort(key=_sort_key)
    top = kept[:k]

    # после обрезки пересчитываем итог, чтобы штраф был виден в порядке
    for candidate in top:
        score_candidate(candidate, mode=mode, query_tokens=query_tokens)
    top.sort(key=_sort_key)
    return top


def _sort_key(candidate: Candidate) -> tuple:
    """Полностью детерминированный ключ сортировки."""
    return (-candidate.final_score, candidate.dockey, candidate.name or "",
            candidate.text[:40])


# --------------------------------------------------------------------------- сборка
def build_candidates(contexts: Iterable[Context], scope: SourceScope,
                     catalog: DocumentCatalog) -> list[Candidate]:
    result: list[Candidate] = []
    for ctx in contexts or []:
        dockey = str(ctx.text.doc.dockey)
        result.append(Candidate(
            context=ctx,
            scope=scope,
            meta=catalog.get(dockey),
            raw_score=float(ctx.score or 0.0),
        ))
    return result


def to_pqa_session(question: str, candidates: Sequence[Candidate]) -> PQASession:
    """Собрать `PQASession` с готовым контекстом — повторный поиск не нужен."""
    return PQASession(question=question,
                      contexts=[c.context for c in candidates],
                      has_successful_answer=None)


def source_dict(candidate: Candidate, index: int) -> dict[str, Any]:
    """Источник в формате API: разметка 📚/📁 + метаданные реестра."""
    meta = candidate.meta
    scope = "global" if candidate.scope is SourceScope.GLOBAL else "session"
    return {
        "index": index,
        "marker": candidate.marker,
        "source_scope": scope,
        "dockey": candidate.dockey,
        "docname": candidate.docname,
        "title": meta.title or candidate.docname,
        "citation": str(candidate.context.text.doc.citation or ""),
        "category": meta.category,
        "tags": list(meta.tags),
        "page": candidate.name,
        "score": candidate.final_score,
        "raw_score": candidate.raw_score,
        "priority": candidate.priority,
        "dedup_penalty": candidate.dedup_penalty,
        "projects": list(meta.linked_projects),
        "text": candidate.text[:1000],
    }


def build_reference(marker: str, index: int, label: str) -> str:
    """Единый формат ссылки API: `📁 [n] Название (категория)`.

    Номер обязателен: в тексте ответа модель цитирует `[n]`, и без него
    пользователь не сопоставит список с цитатой. Формат дублирует
    `boasi_ui.components.ui.source_list`.
    """
    return f"{marker} [{index}] {label}"


def format_reference(candidate: Candidate, index: int) -> str:
    """Человекочитаемая ссылка: `📚 [n] <citation>` или `📁 [n] <title> (категория)`."""
    scope = "global" if candidate.scope is SourceScope.GLOBAL else "session"
    if scope == "global":
        label = str(candidate.context.text.doc.citation or candidate.docname)
    else:
        label = (f"{candidate.meta.title or candidate.docname} "
                 f"({candidate.meta.category or 'без категории'})")
    return build_reference(candidate.marker, index, label)


def reference_from_source(source: dict[str, Any]) -> str:
    """Тот же формат для ответа из кэша: кандидатов там нет, только словари."""
    scope = str(source.get("source_scope") or "session")
    # маркер мог отсутствовать в старых записях кэша — выводим из области
    marker = str(source.get("marker") or ("📚" if scope == "global" else "📁"))
    if scope == "global":
        label = str(source.get("citation") or source.get("docname") or "")
    else:
        label = (f"{source.get('title') or source.get('docname') or ''} "
                 f"({source.get('category') or 'без категории'})")
    return build_reference(marker, int(source.get("index") or 0), label)


def chunks_from_candidates(candidates: Sequence[Candidate]) -> list[ScoredChunk]:
    """Перевести выбранные кандидаты в сервисные `ScoredChunk`."""
    return [
        ScoredChunk(
            dockey=candidate.dockey,
            docname=candidate.docname,
            text=candidate.text,
            score=int(candidate.final_score),
            context=candidate.context.context,
            citation=str(candidate.context.text.doc.citation or ""),
            title=candidate.meta.title,
            name=candidate.name,
            kind=SourceKind.GLOBAL if candidate.scope is SourceScope.GLOBAL
            else SourceKind.SESSION,
            chunk_index=index,
        )
        for index, candidate in enumerate(candidates)
    ]


__all__ = [
    "Candidate",
    "DocumentCatalog",
    "DocumentMeta",
    "SourceScope",
    "build_candidates",
    "build_reference",
    "category_weight",
    "chunks_from_candidates",
    "format_reference",
    "is_allowed",
    "merge_and_rerank",
    "reference_from_source",
    "score_candidate",
    "source_dict",
    "stem",
    "stems",
    "to_pqa_session",
    "tokenize",
]