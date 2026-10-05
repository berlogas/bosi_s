"""DTO-типы сервисного слоя PaperQA (не путать с HTTP-схемами в app/schemas)."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class DocStatus(str, enum.Enum):
    """Жизненный цикл документа."""

    PENDING = "pending"
    PARSING = "parsing"
    READY = "ready"
    ERROR = "error"


class SourceKind(str, enum.Enum):
    """Откуда взят источник — определяет разметку 📚 (глобальная) / 📁 (сессия)."""

    GLOBAL = "global"
    SESSION = "session"


SOURCE_MARK = {SourceKind.GLOBAL: "📚", SourceKind.SESSION: "📁"}


@dataclass(slots=True)
class DocumentRef:
    """Регистрация документа (зеркалирует строку таблицы `documents`)."""

    dockey: str
    docname: str
    path: str | None = None
    url: str | None = None
    title: str | None = None
    citation: str | None = None
    status: DocStatus = DocStatus.READY
    error: str | None = None
    size_bytes: int | None = None
    pages: int | None = None
    chunk_count: int = 0
    category: str | None = None
    project_id: str | None = None
    session_id: str | None = None
    created_at: datetime | None = None
    content_hash: str | None = None

    @property
    def ready(self) -> bool:
        return self.status is DocStatus.READY


@dataclass(slots=True)
class ScoredChunk:
    """Фрагмент контекста с оценкой релевантности (результат aget_evidence)."""

    dockey: str
    docname: str
    text: str
    score: int
    context: str | None = None
    citation: str | None = None
    title: str | None = None
    name: str | None = None  # страница/раздел внутри документа
    kind: SourceKind = SourceKind.GLOBAL
    chunk_index: int | None = None

    @property
    def marker(self) -> str:
        return SOURCE_MARK[self.kind]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dockey": self.dockey,
            "docname": self.docname,
            "marker": self.marker,
            "kind": self.kind.value,
            "text": self.text,
            "score": self.score,
            "context": self.context,
            "citation": self.citation,
            "title": self.title,
            "name": self.name,
            "chunk_index": self.chunk_index,
        }


@dataclass(slots=True)
class SearchResult:
    """Результат поиска без генерации ответа."""

    dockey: str
    docname: str
    text: str
    score: float | None = None
    citation: str | None = None
    path: str | None = None
    kind: SourceKind = SourceKind.GLOBAL

    @property
    def marker(self) -> str:
        return SOURCE_MARK[self.kind]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dockey": self.dockey,
            "docname": self.docname,
            "marker": self.marker,
            "kind": self.kind.value,
            "text": self.text,
            "score": self.score,
            "citation": self.citation,
            "path": self.path,
        }


@dataclass(slots=True)
class AnswerResult:
    """Ответ ассистента с цитатами."""

    question: str
    answer: str
    formatted_answer: str
    citations: list[str] = field(default_factory=list)
    context: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[ScoredChunk] = field(default_factory=list)
    # Три состояния от paperqa: True (уверен) / False (не уверен) / None (не оценивал)
    has_successful_answer: bool | None = True
    cost: float = 0.0
    token_counts: dict[str, Any] = field(default_factory=dict)
    mode: str | None = None
    seconds: float = 0.0
    used_context: bool = False  # True, если ответ построен на готовом PQASession
    # True, если ответ сгенерирован без опоры на базу (база пуста или
    # ничего не нашлось). Фронтенд по этому флагу объясняет пользователю,
    # почему ответ не со ссылками, вместо того чтобы молчать.
    base_empty: bool = False

    @property
    def empty(self) -> bool:
        return not (self.answer or "").strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "formatted_answer": self.formatted_answer,
            "citations": self.citations,
            "context": self.context,
            "evidence": [c.to_dict() for c in self.evidence],
            "has_successful_answer": self.has_successful_answer,
            "base_empty": self.base_empty,
            "cost": self.cost,
            "token_counts": self.token_counts,
            "mode": self.mode,
            "seconds": round(self.seconds, 2),
            "used_context": self.used_context,
        }


@dataclass(slots=True)
class DocumentBatchResult:
    """Результат массового добавления (часть файлов может не проиндексироваться)."""

    added: list[DocumentRef] = field(default_factory=list)
    duplicates: list[DocumentRef] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (путь, ошибка)

    @property
    def total(self) -> int:
        return len(self.added) + len(self.duplicates) + len(self.failed)