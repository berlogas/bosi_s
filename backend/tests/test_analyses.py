"""Фаза 7, часть 2 — анализы: пробелы в черновике, сверка с данными,
обзор литературы, поиск пробелов, отчёт по шаблону.

DoD фазы требует, чтобы анализ черновика находил ≥1 **реальный** пробел, поэтому
пробелы ищутся детерминированно (правила, не мнение модели) и проверяются
юнит-тестами на конкретных примерах.
"""

from __future__ import annotations

from app.services.analyses import (
    DEFAULT_REPORT_TEMPLATE,
    analyze_draft,
    coverage_line,
    data_comparison_prompt,
    find_citation_gaps,
    find_methodology_gaps,
    find_structure_gaps,
    gap_analysis_prompt,
    literature_review_prompt,
    render_gaps,
    report_prompt,
)
from app.services.generation import normalize_sections


# --------------------------------------------------------------------------- цитаты
def test_number_without_citation_is_a_gap() -> None:
    gaps = find_citation_gaps("Средняя биомасса составила 1,85 мг/м3.")

    assert len(gaps) == 1
    assert gaps[0].kind == "uncited_number"
    assert gaps[0].severity == "medium"
    assert "1,85" in gaps[0].excerpt


def test_cited_number_is_not_a_gap() -> None:
    assert find_citation_gaps("Средняя биомасса 1,85 мг/м3 [1].") == []


def test_strong_claim_without_number_is_a_gap() -> None:
    gaps = find_citation_gaps("Это подтверждает гипотезу о восстановлении популяции.")

    assert len(gaps) == 1
    assert gaps[0].kind == "weak_claim"


def test_number_and_strong_claim_is_high_severity() -> None:
    gaps = find_citation_gaps("Обнаружен рост биомассы на 30% [нет ссылки].".replace(
        "[нет ссылки]", ""))

    assert gaps and gaps[0].severity == "high"


def test_plain_sentence_is_not_a_gap() -> None:
    assert find_citation_gaps("В работе рассматриваются две станции.") == []


def test_gap_records_line_number() -> None:
    text = "Введение.\n\nНаше значение 0,42 превышает среднее."
    gaps = find_citation_gaps(text)
    assert gaps[0].line == 3


def test_headings_and_list_items_are_ignored() -> None:
    assert find_citation_gaps("## Заголовок 2024\n- пункт 1\n- пункт 2") == []


# --------------------------------------------------------------------------- методика
def test_results_without_methodology_is_a_gap() -> None:
    gaps = find_methodology_gaps("Полученные результаты показывают рост 5%.")
    assert gaps and gaps[0].severity == "high"


def test_methodology_mention_closes_the_gap() -> None:
    assert find_methodology_gaps(
        "Результаты получены методом спектрофотометрии.") == []


def test_no_results_no_gap() -> None:
    assert find_methodology_gaps("Тема работы — биомасса.") == []


# --------------------------------------------------------------------------- структура
def test_missing_required_sections_are_gaps() -> None:
    sections = normalize_sections([
        {"name": "Введение", "content_md": "текст"},
        {"name": "Методы", "content_md": "  "},
    ])
    gaps = find_structure_gaps(sections)

    assert [g.where for g in gaps] == ["Методы"]
    assert gaps[0].kind == "missing_section"


def test_optional_missing_section_is_not_a_gap() -> None:
    sections = normalize_sections([{"name": "Приложение", "required": False}])
    assert find_structure_gaps(sections) == []


# --------------------------------------------------------------------------- сводный разбор
def test_analyze_draft_finds_real_gap() -> None:
    """DoD: анализ черновика находит ≥1 реальный пробел."""
    sections = normalize_sections([
        {"name": "Introduction", "required": True,
         "content_md": "Биомасса измеряется методом GF/F [1]."},
        {"name": "Methods", "required": True,
         "content_md": "Пробы отбирали на горизонтах 0 и 10 м [2]."},
        {"name": "Results", "required": True,
         "content_md": "Средняя биомасса составила 1,85 мг/м3."},
        {"name": "Conclusions", "required": True, "content_md": ""},
    ])

    analysis = analyze_draft(sections)

    assert analysis.has_gaps
    kinds = {g.kind for g in analysis.gaps}
    assert "uncited_number" in kinds
    assert "missing_section" in kinds
    assert analysis.by_severity["high"] >= 1
    assert analysis.sections_written == 3
    assert analysis.sections_total == 4
    assert analysis.citations_found == [1, 2]


def test_analyze_clean_draft_has_no_gaps() -> None:
    sections = normalize_sections([
        {"name": "Введение", "content_md": "Метод GF/F описан в [1]."},
        {"name": "Методы", "content_md": "Отбор проб по [2]."},
        {"name": "Results", "required": False, "content_md": ""},
    ])

    analysis = analyze_draft(sections)
    assert not analysis.has_gaps, [g.to_dict() for g in analysis.gaps]


def test_analysis_serializes() -> None:
    payload = analyze_draft(normalize_sections(
        [{"name": "X", "content_md": "Значение 5 [9]."}])).to_dict()

    assert set(payload) >= {"gaps", "has_gaps", "by_severity", "sections_total",
                            "sections_written", "citations_found", "words"}


def test_render_gaps_for_clean_draft() -> None:
    assert "Пробелов не найдено" in render_gaps(
        analyze_draft(normalize_sections([{"name": "X", "content_md": "Текст [1]."}])))


def test_render_gaps_lists_hints() -> None:
    text = render_gaps(analyze_draft(normalize_sections(
        [{"name": "Results", "content_md": "Значение 5."}])))
    assert "Найдено пробелов" in text
    assert "Добавьте ссылку" in text


def test_gaps_sorted_by_severity() -> None:
    sections = normalize_sections([
        {"name": "A", "required": True, "content_md": "Число 5."},
        {"name": "B", "required": True, "content_md": "Обнаружен рост на 10%."},
    ])
    severities = [g.severity for g in analyze_draft(sections).gaps]
    assert severities == sorted(severities, key=lambda s: {"high": 0, "medium": 1}[s])


# --------------------------------------------------------------------------- промпты
def _sources(n: int = 2) -> list[dict]:
    return [{"index": i, "marker": "📚", "source_scope": "global",
             "dockey": f"d{i}", "docname": f"n{i}", "title": f"Источник {i}",
             "citation": f"Cite {i}", "category": "global_knowledge",
             "text": f"текст {i}"} for i in range(1, n + 1)]


def test_literature_review_prompt_requires_grouping() -> None:
    prompt = literature_review_prompt("биомасса Баренцева", _sources())

    assert "Группируй источники по темам" in prompt
    assert "противоречия" in prompt
    assert "[1]" in prompt


def test_gap_analysis_prompt_lists_coverage() -> None:
    prompt = gap_analysis_prompt("тема", coverage_line(_sources()), _sources())

    assert "пробел" in prompt.lower()
    assert "ЧТО УЖЕ ИЗУЧЕНО" in prompt
    assert "[1]" in prompt


def test_data_comparison_prompt_contains_computed_numbers() -> None:
    import tempfile
    from pathlib import Path

    from app.services.data_extract import summarize_file

    path = Path(tempfile.gettempdir()) / "cmp.csv"
    path.write_text("depth;gf_f\n0;0.42\n10;0.28\n", encoding="utf-8")
    summary = summarize_file(path, title="Данные")

    prompt = data_comparison_prompt("согласуются ли данные?", [summary], _sources())

    assert "СВОИ ДАННЫЕ" in prompt
    assert "gf_f" in prompt
    assert "соглас" in prompt.lower()
    assert "не пересчитывай" in prompt


def test_data_comparison_prompt_without_data() -> None:
    prompt = data_comparison_prompt("вопрос", [], _sources())
    assert "Сводка данных недоступна" in prompt


def test_report_prompt_keeps_template() -> None:
    prompt = report_prompt(DEFAULT_REPORT_TEMPLATE, _sources(), question="мониторинг")

    assert "Материал и методы" in prompt
    assert "Список использованных источников" in prompt
    assert "мониторинг" in prompt
    assert "н/д" in prompt, "запрет выдумывать данные"


def test_report_prompt_without_question() -> None:
    assert "ТЕМА ОТЧЁТА" not in report_prompt(DEFAULT_REPORT_TEMPLATE, _sources())


def test_coverage_line_is_empty_without_sources() -> None:
    assert coverage_line([]) == ""