"""Фаза 7 — контракт цитат и генерация разделов.

Ключевое требование ТЗ: каждая цифра `[n]` в сгенерированном тексте обязана
разрешаться в реальный источник. Здесь это проверяется как чистая функция —
без LLM и без сети.
"""

from __future__ import annotations

import pytest

from app.services.generation import (
    DEFAULT_SECTIONS,
    GenerationResult,
    build_citation_map,
    build_prompt,
    missing_sections,
    normalize_sections,
    parse_citations,
    progress,
    validate_citations,
)


# --------------------------------------------------------------------------- парсинг
@pytest.mark.parametrize("text, expected", [
    ("Просто текст без ссылок.", []),
    ("Факт [1].", [1]),
    ("Факты [1] и [2].", [1, 2]),
    ("Факты [1,2].", [1, 2]),
    ("Факты [1, 3].", [1, 3]),
    ("Диапазон [1-3].", [1, 2, 3]),
    ("Диапазон [1–3].", [1, 2, 3]),
    ("Смесь [2], [1,4], [3-5].", [1, 2, 3, 4, 5]),
    ("Повтор [1] и снова [1].", [1]),
    ("Не ссылка (1) и не [x].", []),
])
def test_parse_citations(text: str, expected: list[int]) -> None:
    assert parse_citations(text) == expected


# --------------------------------------------------------------------------- валидация
def test_valid_citations_pass() -> None:
    check = validate_citations("Факты [1] и [2].", source_count=3)

    assert check.ok is True
    assert check.dangling == []
    assert check.cited == [1, 2]
    assert check.uncited_sources == [3]


def test_dangling_reference_fails() -> None:
    check = validate_citations("Факт [1] и несуществующий [9].", source_count=2)

    assert check.ok is False
    assert check.dangling == [9]
    assert any("без источника" in w for w in check.warnings)


def test_text_without_citations_fails_when_sources_exist() -> None:
    check = validate_citations("Текст вообще без ссылок.", source_count=3)

    assert check.ok is False
    assert check.cited == []
    assert any("нет ни одной ссылки" in w for w in check.warnings)


def test_no_sources_and_no_citations_is_ok() -> None:
    """Нечего цитировать — отсутствие ссылок не ошибка."""
    assert validate_citations("Материала нет.", source_count=0).ok is True


def test_require_any_can_be_disabled() -> None:
    check = validate_citations("Текст без ссылок.", source_count=2, require_any=False)
    assert check.ok is True


def test_many_uncited_sources_produce_warning() -> None:
    check = validate_citations("Факт [1].", source_count=10)
    assert any("Не использовано" in w for w in check.warnings)


def test_check_serializes() -> None:
    payload = validate_citations("Факт [1].", source_count=2).to_dict()
    assert set(payload) == {"ok", "cited", "available", "dangling",
                            "uncited_sources", "warnings"}


# --------------------------------------------------------------------------- промпт
def _sources(n: int = 2) -> list[dict]:
    return [
        {"index": i, "marker": "📚" if i == 1 else "📁", "source_scope":
         "global" if i == 1 else "session", "dockey": f"d{i}",
         "docname": f"n{i}", "title": f"Документ {i}", "citation": f"Cite {i}",
         "category": "project_data" if i == 2 else "global_knowledge",
         "text": f"текст источника {i} " * 5}
        for i in range(1, n + 1)
    ]


def test_prompt_contains_sources_and_strict_rules() -> None:
    prompt = build_prompt("Discussion", "Как соотносятся данные?", _sources())

    assert "Discussion" in prompt
    assert "[1]" in prompt and "[2]" in prompt
    assert "Не выдумывай источники" in prompt
    assert "Как соотносятся данные?" in prompt


def test_prompt_includes_notes_and_word_target() -> None:
    prompt = build_prompt("Methods", "Как мерили?", _sources(),
                          notes="только акустический метод", word_target=800)

    assert "акустический метод" in prompt
    assert "800 слов" in prompt


def test_prompt_language_switch() -> None:
    assert "английском" in build_prompt("Results", "q", _sources(), language="en")


# --------------------------------------------------------------------------- карта цитат
def test_citation_map_links_sources() -> None:
    sources = _sources()
    mapping = build_citation_map("Факты [1] и [2].", sources)

    assert [m["index"] for m in mapping] == [1, 2]
    assert mapping[0]["marker"] == "📚"
    assert mapping[1]["marker"] == "📁"
    assert mapping[1]["category"] == "project_data"
    assert mapping[0]["quote"]


def test_citation_map_skips_dangling() -> None:
    mapping = build_citation_map("Факт [1] и [7].", _sources())
    assert [m["index"] for m in mapping] == [1]


# --------------------------------------------------------------------------- план
def test_normalize_sections_fills_defaults() -> None:
    sections = normalize_sections([{"name": "Введение"}])

    assert sections[0]["word_target"] == 500
    assert sections[0]["required"] is True
    assert sections[0]["order"] == 1


def test_normalize_sections_sorts_by_order() -> None:
    sections = normalize_sections([
        {"name": "Выводы", "order": 5},
        {"name": "Введение", "order": 1},
        {"name": "Методы", "order": 2},
    ])
    assert [s["name"] for s in sections] == ["Введение", "Методы", "Выводы"]


def test_normalize_sections_drops_unnamed() -> None:
    """Раздел без имени выбрасывается; нумерация остальных не сбивается."""
    sections = normalize_sections([{"name": "  "}, {"name": "Ок"}])
    assert [s["name"] for s in sections] == ["Ок"]


def test_normalize_sections_keeps_gaps_in_order() -> None:
    """Пропуск не перенумеровывает: порядок задаёт автор, а не позиция в списке."""
    sections = normalize_sections([{"name": "Введение", "order": 1},
                                   {"name": "Выводы", "order": 5}])
    assert [s["order"] for s in sections] == [1, 5]


def test_default_plan_has_standard_sections() -> None:
    names = [s["name"] for s in normalize_sections(None)]
    assert names == [s["name"] for s in DEFAULT_SECTIONS]
    assert "Discussion" in names


def test_missing_sections_finds_required_only() -> None:
    sections = normalize_sections([
        {"name": "Введение", "content_md": "написан"},
        {"name": "Методы", "content_md": "   "},
        {"name": "Приложение", "required": False},
    ])
    assert missing_sections(sections) == ["Методы"]


def test_progress_counts_words() -> None:
    sections = normalize_sections([
        {"name": "Введение", "content_md": "раз два три", "word_target": 100},
        {"name": "Методы", "content_md": "", "word_target": 200},
    ])
    stats = progress(sections)

    assert stats["sections"] == 2
    assert stats["written"] == 1
    assert stats["percent"] == 50
    assert stats["words"] == 3
    assert stats["word_target"] == 300


def test_progress_of_empty_plan() -> None:
    assert progress([])["percent"] == 0


# --------------------------------------------------------------------------- результат
def test_generation_result_word_count_and_references() -> None:
    result = GenerationResult(
        section="Discussion",
        content_md="Факты [1] и [2].",
        sources=_sources(),
        citation_map=build_citation_map("Факты [1] и [2].", _sources()),
    )

    assert result.word_count == 4
    assert result.ok is True
    references = result.format_references()
    assert len(references) == 2
    assert references[0].startswith("[1] 📚")
    assert references[1].startswith("[2] 📁")


def test_generation_result_flags_bad_citations() -> None:
    result = GenerationResult(
        section="Results", content_md="Факт [9].",
        sources=_sources(),
        citation_check=validate_citations("Факт [9].", 2))

    assert result.ok is False
    assert result.warnings, "предупреждения контракта подставляются автоматически"


def test_generation_result_merges_extra_warnings() -> None:
    result = GenerationResult(
        section="Results", content_md="Факт [1].",
        sources=_sources(),
        citation_check=validate_citations("Факт [1].", 2),
        extra_warnings=["Материала мало"])

    assert "Материала мало" in result.warnings
    assert len(result.warnings) == 1  # дубли не повторяются


def test_generation_result_to_dict_shape() -> None:
    payload = GenerationResult(section="X", content_md="[1]").to_dict()
    assert {"section", "content_md", "word_count", "sources", "references",
            "citations_ok", "citation_check", "warnings", "from_cache"} <= set(payload)


def test_references_only_include_cited_sources() -> None:
    result = GenerationResult(
        section="X", content_md="только [2]",
        sources=_sources(3),
        citation_map=build_citation_map("только [2]", _sources(3)))

    references = result.format_references()
    assert all(r.startswith("[2]") for r in references)