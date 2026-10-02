"""Специальные генерации Фазы 7: обзор литературы, сверка с данными,
поиск пробелов, анализ черновика, отчёт по шаблону.

Отличаются от обычного раздела тем, что у них своя постановка вопроса и своё
предобработка. Общее у них одно — тот же контракт цитат (Фаза 7): все они
обязаны ссылаться на источники и проверяются `validate_citations`.

Поиск пробелов и анализ черновика частично **детерминированы**: пробелы ищутся
по правилам (нет цитаты на абзац с числами, раздел без текста), а не по
«мнение модели». Это сделано намеренно — иначе результат нельзя проверить.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.services.data_extract import DataSummary
from app.services.generation import _sources_block, normalize_sections, parse_citations

# Абзац с числом или сильным утверждением требует ссылки.
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
NUMBER_RE = re.compile(r"\d")
STRONG_CLAIM_RE = re.compile(
    r"\b(значительн|существенн|подтвержд|доказал|обнаружен|обнаружил|"
    r"превосход|превыш|установлен|выявлен|значимо|существенно)\w*",
    re.IGNORECASE,
)
METHODOLOGY_HINT_RE = re.compile(
    r"\b(метод|методик|методолог|оборудован|протокол|измерен|анализ)\w*",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------- пробелы
@dataclass
class DraftGap:
    """Конкретный пробел в черновике — то, что нужно закрыть."""

    kind: str            # missing_citation | uncited_number | weak_claim | missing_section
    severity: str        # high | medium | low
    where: str           # раздел
    line: int | None = None
    excerpt: str = ""
    hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "severity": self.severity, "where": self.where,
                "line": self.line, "excerpt": self.excerpt, "hint": self.hint}


@dataclass
class DraftAnalysis:
    gaps: list[DraftGap] = field(default_factory=list)
    sections_total: int = 0
    sections_written: int = 0
    citations_found: list[int] = field(default_factory=list)
    words: int = 0

    @property
    def has_gaps(self) -> bool:
        return bool(self.gaps)

    @property
    def by_severity(self) -> dict[str, int]:
        out = {"high": 0, "medium": 0, "low": 0}
        for gap in self.gaps:
            out[gap.severity] += 1
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "gaps": [g.to_dict() for g in self.gaps],
            "has_gaps": self.has_gaps,
            "by_severity": self.by_severity,
            "sections_total": self.sections_total,
            "sections_written": self.sections_written,
            "citations_found": self.citations_found,
            "words": self.words,
        }


def _sentences(text: str) -> list[tuple[int, str]]:
    """Абзацы с их номерами строк (строки нужны для указания места)."""
    result: list[tuple[int, str]] = []
    for line_no, line in enumerate((text or "").splitlines(), start=1):
        stripped = line.strip()
        if stripped and not stripped.startswith(("#", "-", "|")):
            for sentence in SENTENCE_SPLIT_RE.split(stripped):
                if sentence.strip():
                    result.append((line_no, sentence.strip()))
    return result


def find_citation_gaps(text: str, *, where: str = "черновик") -> list[DraftGap]:
    """Утверждения с числами или силовыми словами без ссылки `[n]`."""
    gaps: list[DraftGap] = []
    for line_no, sentence in _sentences(text):
        if parse_citations(sentence):
            continue
        has_number = bool(NUMBER_RE.search(sentence))
        has_claim = bool(STRONG_CLAIM_RE.search(sentence))
        if not (has_number or has_claim):
            continue
        if has_number and has_claim:
            severity, kind = "high", "uncited_number"
        elif has_number:
            severity, kind = "medium", "uncited_number"
        else:
            severity, kind = "medium", "weak_claim"
        gaps.append(DraftGap(
            kind=kind, severity=severity, where=where, line=line_no,
            excerpt=sentence[:200],
            hint="Добавьте ссылку [n] на источник этого утверждения."))
    return gaps


def find_structure_gaps(sections: Sequence[dict[str, Any]]) -> list[DraftGap]:
    """Обязательные разделы, которых ещё нет."""
    gaps: list[DraftGap] = []
    for section in sections:
        if not section.get("required"):
            continue
        content = (section.get("content_md") or "").strip()
        if content:
            continue
        gaps.append(DraftGap(
            kind="missing_section", severity="high", where=section["name"],
            excerpt="", hint=f"Раздел «{section['name']}» не написан."))
    return gaps


def find_methodology_gaps(text: str, *, where: str = "черновик") -> list[DraftGap]:
    """Есть результаты, но не описана методика — классический пробел."""
    lowered = (text or "").lower()
    has_results = any(word in lowered for word in
                      ("результат", "наблюден", "измерен", "получен"))
    if not has_results or METHODOLOGY_HINT_RE.search(lowered):
        return []
    return [DraftGap(
        kind="weak_claim", severity="high", where=where, line=None,
        excerpt="", hint="Результаты описаны без указания методики их получения.")]


def analyze_draft(sections: Sequence[dict[str, Any]]) -> DraftAnalysis:
    """Полный разбор черновика: пробелы по цитатам, структуре и методике."""
    normalized = normalize_sections(sections)
    analysis = DraftAnalysis(
        sections_total=len(normalized),
        sections_written=sum(1 for s in normalized
                            if (s.get("content_md") or "").strip()),
    )
    for section in normalized:
        content = section.get("content_md") or ""
        if not content.strip():
            continue
        analysis.words += len(content.split())
        analysis.citations_found = sorted(set(analysis.citations_found)
                                          | set(parse_citations(content)))
        analysis.gaps.extend(find_citation_gaps(content, where=section["name"]))
        analysis.gaps.extend(find_methodology_gaps(content, where=section["name"]))
    analysis.gaps.extend(find_structure_gaps(normalized))
    analysis.gaps.sort(key=lambda g: ({"high": 0, "medium": 1, "low": 2}[g.severity],
                                      g.where, g.line or 0))
    return analysis


def render_gaps(analysis: DraftAnalysis, limit: int = 20) -> str:
    """Текст разбора для показа пользователю и для подсказки модели."""
    if not analysis.has_gaps:
        return ("Пробелов не найдено: все обязательные разделы написаны, "
                "утверждения с числами подкреплены ссылками.")
    lines = [f"Найдено пробелов: {len(analysis.gaps)} "
             f"(критичных {analysis.by_severity['high']}, "
             f"средних {analysis.by_severity['medium']}).", ""]
    for gap in analysis.gaps[:limit]:
        location = f"{gap.where}" + (f", строка {gap.line}" if gap.line else "")
        lines.append(f"- [{gap.severity}] {location}: {gap.hint}")
        if gap.excerpt:
            lines.append(f"    «{gap.excerpt}»")
    return "\n".join(lines)


# --------------------------------------------------------------------------- промпты
def literature_review_prompt(topic: str, sources: Sequence[dict[str, Any]],
                             *, word_target: int = 1200) -> str:
    """Обзор литературы: сгруппируй источники, а не перечисли их по одному."""
    return (
        "Напиши обзор литературы по теме:\n"
        f"{topic}\n\n"
        "ЖЁСТКИЕ ПРАВИЛА:\n"
        "1. Группируй источники по темам и подходам, а не перечисляй по одному.\n"
        "2. Каждое утверждение подкрепляй ссылкой [n] на источник из списка.\n"
        "3. Отметь противоречия между работами, если они есть.\n"
        "4. Не выдумывай источники и не ссылайся на номера вне списка.\n"
        "5. Укажи, какие вопросы остаются нерешёнными.\n"
        f"6. Объём: примерно {word_target} слов.\n\n"
        f"ИСТОЧНИКИ ({len(sources)}):\n{_sources_block(sources)}\n\n"
        "ОБЗОР ЛИТЕРАТУРЫ:\n"
    )


def data_comparison_prompt(question: str, summaries: Sequence[DataSummary],
                           sources: Sequence[dict[str, Any]],
                           *, word_target: int = 800) -> str:
    """Сверка своих чисел с литературой: числа уже посчитаны, модель их трактует."""
    data_block = "\n\n".join(s.render() for s in summaries) or "Сводка данных недоступна."
    return (
        "Сопоставь СВОИ ДАННЫЕ с литературой по вопросу:\n"
        f"{question}\n\n"
        "ЖЁСТКИЕ ПРАВИЛА:\n"
        "1. Опирайся ровно на приведённые числа — не пересчитывай и не выдумывай.\n"
        "2. Каждое утверждение о литературе подкрепляй ссылкой [n].\n"
        "3. Отдельно укажи, где ваши данные согласуются с источниками, а где "
        "расходятся, и объясни возможную причину расхождения.\n"
        "4. Если сравнивать нечего — прямо скажи это, не выдумывай выводы.\n"
        f"5. Объём: примерно {word_target} слов.\n\n"
        f"СВОИ ДАННЫЕ (сводка посчитана программно):\n{data_block}\n\n"
        f"ИСТОЧНИКИ ЛИТЕРАТУРЫ ({len(sources)}):\n{_sources_block(sources)}\n\n"
        "СРАВНЕНИЕ:\n"
    )


def gap_analysis_prompt(topic: str, coverage: str,
                        sources: Sequence[dict[str, Any]]) -> str:
    """Поиск пробелов в литературе: что изучали, а что нет."""
    return (
        "Определи пробелы в литературе по теме:\n"
        f"{topic}\n\n"
        "ЖЁСТКИЕ ПРАВИЛА:\n"
        "1. Сравни список покрытых тем с тем, что обычно требуется в работе.\n"
        "2. Каждый вывод о недостающей работе опирай на источник [n] или "
        "явно помечай как «не найдено в источниках».\n"
        "3. Не выдумывай несуществующие исследования.\n\n"
        f"ЧТО УЖЕ ИЗУЧЕНО (по найденным источникам):\n{coverage or '—'}\n\n"
        f"ИСТОЧНИКИ ({len(sources)}):\n{_sources_block(sources)}\n\n"
        "ПРОБЕЛЫ В ЛИТЕРАТУРЕ:\n"
    )


def coverage_line(sources: Sequence[dict[str, Any]]) -> str:
    """Что реально покрыто найденными источниками — факт, а не пересказ."""
    if not sources:
        return ""
    return "\n".join(
        f"- [{s['index']}] {s.get('title') or s.get('docname')}"
        f" ({s.get('category') or 'без категории'}): "
        f"{(s.get('text') or '')[:160].strip()}"
        for s in sources
    )


def report_prompt(template: str, sources: Sequence[dict[str, Any]],
                  *, question: str = "") -> str:
    """Отчёт по готовому шаблону: структуру задаёт шаблон, факты — источники."""
    return (
        "Заполни отчёт по шаблону ниже, используя факты из источников.\n\n"
        "ЖЁСТКИЕ ПРАВИЛА:\n"
        "1. Сохрани заголовки и структуру шаблона.\n"
        "2. Каждое утверждение подкрепляй ссылкой [n].\n"
        "3. Не выдумывай данных; если данных нет — напиши «н/д».\n\n"
        + (f"ТЕМА ОТЧЁТА: {question}\n\n" if question else "")
        + f"ИСТОЧНИКИ ({len(sources)}):\n{_sources_block(sources)}\n\n"
        f"ШАБЛОН:\n{template}\n\n"
        "ЗАПОЛНЕННЫЙ ОТЧЁТ:\n"
    )


# --------------------------------------------------------------------------- отчёт
DEFAULT_REPORT_TEMPLATE = """# Отчёт

## Общая информация

## Материал и методы

## Результаты

## Обсуждение

## Выводы и рекомендации

## Список использованных источников
"""