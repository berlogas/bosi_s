"""Генерация текста статей с обязательными цитатами (Фаза 7).

Ключевое требование ТЗ: **все утверждения подкреплены ссылками `[n]`**, причём
каждая цифра `[n]` обязана разрешаться в источник. Поэтому генерация устроена
так:

1. контекст собирается fusion-пайплайном Фазы 6 (глобальная база + документы
   проекта и сессии);
2. источники нумеруются `1..N` — это и есть «цитаты»;
3. LLM получает контекст с явными номерами и обязательные правила оформления;
4. результат проходит `validate_citations()`: цифры без источника, ссылки на
   несуществующий номер и разделы без единой ссылки — ошибка, а не «простите».

Если LLM не поставил ссылки — генерация помечается некорректной и в UI
показывается предупреждение, а не тихо публикуется текст без источников.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.services.types import AnswerResult

log = logging.getLogger("boasi.services.generation")

# [1], [2,3], [1-3]
CITE_RE = re.compile(r"\[(\d+(?:\s*[,\-–]\s*\d+)*)\]")
SECTION_RE = re.compile(r"^#{1,3}\s+(.+?)\s*$", re.MULTILINE)

# Стандартный план статьи (перезадаётся проектом)
DEFAULT_SECTIONS: tuple[dict[str, Any], ...] = (
    {"name": "Introduction", "required": True, "order": 1,
     "word_target": 600, "notes": "Актуальность, цель, вклад"},
    {"name": "Methods", "required": True, "order": 2,
     "word_target": 800, "notes": "Материалы, методы, оборудование"},
    {"name": "Results", "required": True, "order": 3,
     "word_target": 700, "notes": "Собственные данные"},
    {"name": "Discussion", "required": True, "order": 4,
     "word_target": 900, "notes": "Сопоставление с литературой, выводы"},
    {"name": "Conclusions", "required": True, "order": 5,
     "word_target": 300, "notes": "Выводы и перспективы"},
)


# --------------------------------------------------------------------------- цитаты
def parse_citations(text: str) -> list[int]:
    """Все номера источников, упомянутые в тексте (по возрастанию, без повторов)."""
    found: set[int] = set()
    for group in CITE_RE.findall(text or ""):
        for part in re.split(r"[,]", group):
            part = part.strip()
            span = re.match(r"^(\d+)\s*[-–]\s*(\d+)$", part)
            if span:
                start, end = int(span.group(1)), int(span.group(2))
                found.update(range(start, end + 1))
            elif part.isdigit():
                found.add(int(part))
    return sorted(found)


@dataclass
class CitationCheck:
    """Результат проверки цитат — контракт качества ответа."""

    ok: bool
    cited: list[int] = field(default_factory=list)
    available: list[int] = field(default_factory=list)
    dangling: list[int] = field(default_factory=list)  # [9], а источника 9 нет
    uncited_sources: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "cited": self.cited, "available": self.available,
                "dangling": self.dangling,
                "uncited_sources": self.uncited_sources,
                "warnings": self.warnings}


def validate_citations(text: str, source_count: int, *,
                       require_any: bool = True) -> CitationCheck:
    """Проверить, что каждая `[n]` разрешается в реальный источник.

    `source_count` — сколько источников подали в контекст. Нумерация в тексте
    начинается с 1, поэтому «доступны» номера `1..source_count`.
    """
    cited = parse_citations(text)
    available = list(range(1, source_count + 1))
    dangling = [n for n in cited if n not in available]
    uncited = [n for n in available if n not in cited]
    warnings: list[str] = []

    if dangling:
        warnings.append(
            f"Ссылки без источника: {', '.join(f'[{n}]' for n in dangling)}")
    if not cited and require_any and source_count:
        warnings.append("В тексте нет ни одной ссылки на источник")
    if uncited and not dangling and source_count > 5:
        warnings.append(f"Не использовано источников: {len(uncited)}")

    return CitationCheck(
        ok=not dangling and (bool(cited) or not source_count or not require_any),
        cited=cited, available=available, dangling=dangling,
        uncited_sources=uncited, warnings=warnings,
    )


# --------------------------------------------------------------------------- промпты
def _sources_block(sources: Sequence[dict[str, Any]]) -> str:
    """Контекст с явной нумерацией — ровно то, на что ссылается текст."""
    lines: list[str] = []
    for source in sources:
        scope = "глобальная база" if source.get("source_scope") == "global" \
            else "документ сессии"
        category = source.get("category") or "—"
        label = source.get("title") or source.get("docname") or source.get("dockey")
        lines.append(f"[{source['index']}] ({scope}; {category}) {label}\n"
                     f"    {source.get('text', '').strip()[:800]}")
    return "\n".join(lines)


def build_prompt(section: str, question: str, sources: Sequence[dict[str, Any]],
                 *, language: str = "ru", notes: str | None = None,
                 word_target: int | None = None) -> str:
    """Промпт генерации. Правила цитирования — жёсткие и явные."""
    lang = "русском" if language == "ru" else "английском"
    instructions = [
        f"Напиши раздел «{section}» научной статьи на языке {lang}.",
        "ЖЁСТКИЕ ПРАВИЛА:",
        "1. Каждое утверждение о фактах, числах или выводах других работ должно "
        "содержать ссылку вида [1], [2,3] на источник из списка ниже.",
        "2. Не выдумывай источники: допустимы только номера из списка.",
        "3. Если факта нет в источниках — не пиши его, либо скажи, что данных нет.",
        "4. Не ссылайся на источник, который не использовал.",
        "5. Пиши по-русски, научным стилем, без воды.",
        f"6. Объём: примерно {word_target or 500} слов.",
    ]
    if notes:
        instructions.append(f"7. Указания авторов к разделу: {notes}")
    return "\n".join(instructions) + (
        f"\n\nВопрос/задача: {question}\n\n"
        f"ИСТОЧНИКИ ({len(sources)}):\n{_sources_block(sources)}\n\n"
        f"РАЗДЕЛ «{section}»:\n"
    )


# --------------------------------------------------------------------------- результат
@dataclass
class GenerationResult:
    section: str
    content_md: str
    sources: list[dict[str, Any]] = field(default_factory=list)
    citation_check: CitationCheck | None = None
    citation_map: list[dict[str, Any]] = field(default_factory=list)
    seconds: float = 0.0
    from_cache: bool = False
    answer: AnswerResult | None = None
    # Дополнительные предупреждения вызывающего (например, «материала нет»).
    extra_warnings: list[str] = field(default_factory=list)
    # Структурированный разбор (пробелы в черновике) — только для draft_analysis.
    analysis: dict[str, Any] | None = None

    @property
    def warnings(self) -> list[str]:
        """Предупреждения контракта цитат + дополнительные, без дублей."""
        from_check = list(self.citation_check.warnings) if self.citation_check else []
        merged = list(dict.fromkeys(from_check + list(self.extra_warnings)))
        if self.citation_check is not None and not self.citation_check.ok \
                and self.sources and not any("нумераци" in w for w in merged):
            merged.append("Текст содержит ссылки без источника — "
                          "проверьте нумерацию в разделе")
        return merged

    @property
    def word_count(self) -> int:
        return len(self.content_md.split())

    @property
    def ok(self) -> bool:
        return self.citation_check is None or self.citation_check.ok

    def to_dict(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "content_md": self.content_md,
            "word_count": self.word_count,
            "sources": self.sources,
            "references": self.format_references(),
            "citations_ok": self.ok,
            "citation_check": (self.citation_check.to_dict()
                               if self.citation_check else None),
            "citations": self.citation_map,
            "warnings": self.warnings,
            "seconds": round(self.seconds, 2),
            "from_cache": self.from_cache,
            "analysis": self.analysis,
        }

    def format_references(self) -> list[str]:
        """Список источников в порядке цитирования: `[1] 📚 <название>`."""
        out: list[str] = []
        used = {c["index"] for c in self.citation_map} or {
            s["index"] for s in self.sources}
        for source in self.sources:
            if source["index"] not in used:
                continue
            marker = source.get("marker", "")
            if source.get("source_scope") == "global":
                label = source.get("citation") or source.get("title") or ""
            else:
                label = (f"{source.get('title') or source.get('docname')} "
                         f"({source.get('category') or 'без категории'})")
            out.append(f"[{source['index']}] {marker} {label}".strip())
        return out


def build_citation_map(text: str, sources: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Связать каждый источник с фрагментом текста, который на него ссылается."""
    check = parse_citations(text)
    by_index = {s["index"]: s for s in sources}
    result: list[dict[str, Any]] = []
    for index in check:
        source = by_index.get(index)
        if source is None:
            continue
        result.append({
            "index": index,
            "marker": source.get("marker"),
            "source_scope": source.get("source_scope"),
            "dockey": source.get("dockey"),
            "docname": source.get("docname"),
            "title": source.get("title"),
            "citation": source.get("citation"),
            "category": source.get("category"),
            "quote": (source.get("text") or "").strip()[:300],
        })
    return result


def normalize_sections(sections: Any) -> list[dict[str, Any]]:
    """Привести план разделов к канону: есть имя, порядок, объём, отметка required."""
    if not sections:
        return [dict(s) for s in DEFAULT_SECTIONS]
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(sections):
        item = dict(raw) if isinstance(raw, dict) else {"name": str(raw)}
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        normalized.append({
            "name": name,
            "required": bool(item.get("required", True)),
            "order": int(item.get("order") or index + 1),
            "word_target": int(item.get("word_target") or 500),
            "notes": item.get("notes") or "",
            "content_md": item.get("content_md") or "",
        })
    normalized.sort(key=lambda s: s["order"])
    return normalized


def missing_sections(sections: Sequence[dict[str, Any]]) -> list[str]:
    """Обязательные разделы, в которых ещё нет текста."""
    return [s["name"] for s in sections
            if s.get("required") and not (s.get("content_md") or "").strip()]


def progress(sections: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Прогресс по плану проекта — для дашборда."""
    total = len(sections)
    done = sum(1 for s in sections if (s.get("content_md") or "").strip())
    words = sum(len((s.get("content_md") or "").split()) for s in sections)
    target = sum(int(s.get("word_target") or 0) for s in sections)
    return {"sections": total, "written": done,
            "percent": round(100 * done / total) if total else 0,
            "words": words, "word_target": target}