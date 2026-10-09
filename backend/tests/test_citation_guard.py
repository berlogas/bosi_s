"""Фаза 6 — маркеры цитат в ответах чата: починка и отчёт.

Слабая офлайн-LLM пишет «(степень 1)» вместо ключей PaperQA и уводит номера
за пределы выдачи. Здесь проверяется чистая функция `repair_markers()`:
маркированные скобки становятся ссылками `[n]`, несуществующие номера
удаляются, обычный текст не страдает, а отчёт готов для `stats["citations"]`.
"""

from __future__ import annotations

import json

import pytest

from app.services.citation_guard import CitationReport, repair_markers


# --------------------------------------------------------------------------- починка
def test_label_markers_become_numbered_citations() -> None:
    text = "Политика (степень 1, степень 2) и ещё (степень 3)."

    fixed, report = repair_markers(text, source_count=5)

    assert fixed == "Политика [1, 2] и ещё [3]."
    assert report.changed is True
    assert report.ok is True
    assert report.dropped == []
    assert report.cited == [1, 2, 3]


def test_marker_out_of_range_is_removed() -> None:
    text = "Утверждение (степень 7) подтверждено."

    fixed, report = repair_markers(text, source_count=5)

    assert fixed == "Утверждение подтверждено."
    assert report.dropped == ["(степень 7)"]
    assert report.repaired == []
    assert report.ok is False
    assert "степень" not in fixed


def test_duplicate_numbers_in_marker_collapse() -> None:
    fixed, report = repair_markers("Факт (источник 2, источник 2).",
                                   source_count=3)

    assert fixed == "Факт [2]."
    assert report.repaired == ["(источник 2, источник 2) → [2]"]


@pytest.mark.parametrize("marker, expected", [
    ("(уровень 3)", "[3]"),
    ("(цитата 1)", "[1]"),
    ("(source 2)", "[2]"),
    ("(degree 1)", "[1]"),
    ("(степень1)", "[1]"),
])
def test_synonym_markers_repaired(marker: str, expected: str) -> None:
    fixed, _ = repair_markers(f"Текст {marker} конец.", source_count=5)

    assert fixed == f"Текст {expected} конец."


# ----------------------------------------------------------------------- что не трогаем
def test_legitimate_text_is_not_touched() -> None:
    text = ("Полином (степень 2 полинома), список (1), "
            "(см. источник 3), (степень доверия).")

    fixed, report = repair_markers(text, source_count=5)

    assert fixed == text
    assert report.changed is False
    assert report.ok is True


def test_parenthetical_with_words_around_number_is_not_a_marker() -> None:
    fixed, _ = repair_markers("Уточнение (см. источник 3 выше).", source_count=5)

    assert fixed == "Уточнение (см. источник 3 выше)."


# --------------------------------------------------------------------------- проверка
def test_dangling_bracket_is_reported_but_kept() -> None:
    fixed, report = repair_markers("Факт [1] и выдумка [9].", source_count=3)

    assert fixed == "Факт [1] и выдумка [9]."
    assert report.cited == [1, 9]
    assert report.dangling == [9]
    assert report.ok is False
    assert any("[9]" in warning for warning in report.warnings)


def test_no_markers_returns_text_unchanged() -> None:
    """Текст не трогаем, но отсутствие ссылок при источниках — повод для ⚠."""
    fixed, report = repair_markers("Обычный ответ без ссылок.", source_count=3)

    assert fixed == "Обычный ответ без ссылок."
    assert report.ok is True
    assert report.changed is False
    assert report.uncited is True
    assert any("без ссылок" in warning for warning in report.warnings)


def test_no_markers_without_sources_is_silent() -> None:
    """Нет источников — нечего и предупреждать (ответ по памяти модели)."""
    _, report = repair_markers("Ответ без ссылок.", source_count=0)

    assert report.uncited is False
    assert report.warnings == []


def test_answer_with_citations_has_no_uncited_warning() -> None:
    _, report = repair_markers("Факт [1] подтверждён.", source_count=3)

    assert report.uncited is False
    assert report.warnings == []


def test_empty_text_is_safe() -> None:
    fixed, report = repair_markers("", source_count=0)

    assert fixed == ""
    assert report.to_dict()["ok"] is True


def test_markers_dropped_when_no_sources() -> None:
    fixed, report = repair_markers("Ответ (источник 1) и (степень 2).",
                                   source_count=0)

    assert "источник" not in fixed
    assert "степень" not in fixed
    assert report.dropped == ["(источник 1)", "(степень 2)"]


def test_report_serializes_for_api_stats() -> None:
    _, report = repair_markers("Факт (степень 1) и (степень 9).",
                               source_count=3)
    payload = report.to_dict()

    assert set(payload) == {"ok", "changed", "repaired", "dropped",
                            "reflowed", "cited", "dangling", "uncited",
                            "warnings"}
    assert payload["ok"] is False
    assert payload["repaired"] and payload["dropped"]
    assert payload["warnings"]
    json.dumps(payload, ensure_ascii=False)  # стат уходит в JSON-ответ API


def test_report_is_a_dataclass_with_defaults() -> None:
    report = CitationReport()

    assert report.ok is True
    assert report.changed is False


# --------------------------------------------------------------- реальный ответ LLM
def test_real_answer_with_hallucinated_markers() -> None:
    """Ответ qwen2.5:3b из data/pqa/answers: 5 источников, маркеры 1..7."""
    text = (
        "Её основной политикой было стремление упорядочить управление страны "
        "и поддержать просвещение народов (степень 1, степень 2).\n\n"
        "Важным ограничением является то, что она не отменила крепостное "
        "право (степень 6).\n\n"
        "Она также поддерживала религиозную терпимость (степень 7)."
    )

    fixed, report = repair_markers(text, source_count=5)

    assert "(степень 1, степень 2)" not in fixed
    assert "[1, 2]" in fixed
    assert "(степень 6)" not in fixed and "(степень 7)" not in fixed
    assert report.dropped == ["(степень 6)", "(степень 7)"]
    assert report.ok is False


# ------------------------------------------------- маркеры paperqa «docname lines»
# Имя фрагмента, которое paperqa даёт LLM и блоку References: его надо
# превратить в номер источника — пользователь понимает [n], а не «lines 0-0».
NAMED_SOURCES = [
    {"index": 1, "docname": "2b_context", "page": "2b_context lines 0-47"},
    {"index": 2, "docname": "2b_context", "page": "2b_context lines 47-77"},
    {"index": 3, "docname": "hot_facts", "page": "hot_facts lines 0-12"},
]


def test_named_marker_resolves_to_source_number() -> None:
    fixed, report = repair_markers("Факт (2b_context lines 47-77) подтверждён.",
                                   source_count=3, sources=NAMED_SOURCES)

    assert fixed == "Факт [2] подтверждён."
    assert report.repaired == ["(2b_context lines 47-77) → [2]"]
    assert report.cited == [2]
    assert report.ok is True


def test_named_marker_maps_by_docname_after_reindex() -> None:
    """Номера строк сместились при переиндексации — документ в выдаче один."""
    fixed, _ = repair_markers("Факт (hot_facts lines 5-9).",
                              source_count=3, sources=NAMED_SOURCES)

    assert fixed == "Факт [3]."


def test_named_marker_exact_match_beats_docname_rule() -> None:
    fixed, _ = repair_markers("Первый (2b_context lines 0-47) и хвост "
                              "(2b_context lines 47-77).",
                              source_count=3, sources=NAMED_SOURCES)

    assert fixed == "Первый [1] и хвост [2]."


def test_ambiguous_named_marker_is_dropped() -> None:
    """Документ известен, но фрагментов несколько — номер не выдумать."""
    fixed, report = repair_markers("Факт (2b_context lines 99-199).",
                                   source_count=3, sources=NAMED_SOURCES)

    assert fixed == "Факт."
    assert report.dropped == ["(2b_context lines 99-199)"]
    assert report.ok is False
    assert any("неоднозначна" in w for w in report.warnings)


def test_named_marker_of_unknown_document_is_dropped() -> None:
    fixed, report = repair_markers("Факт (no_such_file lines 0-0).",
                                   source_count=3, sources=NAMED_SOURCES)

    assert "no_such_file" not in fixed
    assert report.dropped == ["(no_such_file lines 0-0)"]
    assert any("несуществующие" in w for w in report.warnings)


def test_ordinary_parens_survive_named_pass() -> None:
    """Скообки без хвоста «lines/pages N-M» — не маркеры, их не трогаем."""
    samples = (
        "Годы разделов (1772-1795) важны.",
        "Уточнение (степень 2 полинома) в задаче.",
        "См. раздел (hot_facts lines) ниже.",
        "Цитата (hot lines 0-12 extra) — хвост лишний.",
    )
    for text in samples:
        fixed, report = repair_markers(text, source_count=3,
                                       sources=NAMED_SOURCES)
        assert fixed == text, text
        assert report.changed is False, text


def test_named_markers_kept_when_sources_not_passed() -> None:
    """Без списка источников резолвить нечего — текст не трогаем."""
    fixed, report = repair_markers("Факт (2b_context lines 0-0).",
                                   source_count=3)

    assert "(2b_context lines 0-0)" in fixed
    assert report.changed is False


def test_mixed_markers_in_one_answer() -> None:
    text = ("Политика (степень 1) и родословная (2b_context lines 47-77), "
            "а также (no_such_file lines 0-0).")

    fixed, report = repair_markers(text, source_count=3, sources=NAMED_SOURCES)

    assert fixed == "Политика [1] и родословная [2], а также."
    assert report.cited == [1, 2]
    assert report.dropped == ["(no_such_file lines 0-0)"]


def test_real_cached_answer_gets_numeric_references() -> None:
    """Живой ответ с блоком References «(docname lines 0-0)» из data/pqa."""
    import json
    from pathlib import Path

    path = (Path(__file__).resolve().parents[2]
            / "data/pqa/answers/f3"
            / "f3e0d735ef56953bea1feae44044dd978bccc9d0030e2a25cb1f84e07a9421c8.json")
    if not path.exists():
        pytest.skip("нет кэша ответов (data/ не в репозитории)")
    payload = json.loads(path.read_text(encoding="utf-8"))

    fixed, report = repair_markers(payload["answer"],
                                   source_count=len(payload["sources"]),
                                   sources=payload["sources"])

    assert "lines 0-0" not in fixed
    assert "lines 0-47" not in fixed
    # в этом ответе два документа: контекст (page = «…_context lines 0-0»,
    # первый фрагмент = 1) и hot_facts (единственный фрагмент = 3)
    assert "[1]" in fixed and "[3]" in fixed
    assert report.changed is True
    assert report.dangling == []


# ------------------------------------------------- блок References и ссылки без скобок
def test_reference_line_dropped_when_no_link_resolves() -> None:
    """Запись «2.: цитата» хуже, чем отсутствие записи — удаляем строку."""
    text = ("Факт подтверждён.\n\nReferences\n\n"
            "1. (no_such_file lines 0-0): выдуманная цитата\n")

    fixed, report = repair_markers(text, source_count=2, sources=NAMED_SOURCES)

    assert "выдуманная цитата" not in fixed
    assert "no_such_file" not in fixed
    # заголовок остался бы висеть без единой записи — убираем и его
    assert "References" not in fixed
    assert "Факт подтверждён." in fixed
    assert report.dropped == ["(no_such_file lines 0-0)"]
    assert any("целые строки блока источников" in w for w in report.warnings)


def test_reference_line_survives_when_one_link_resolves() -> None:
    text = ("References\n\n"
            "1. (2b_context lines 47-77): доклад\n"
            "2. (ghost lines 0-0): выдумка\n")

    fixed, report = repair_markers(text, source_count=2, sources=NAMED_SOURCES)

    assert "1. [2] доклад" in fixed      # двоеточие убрано для markdown
    assert "1. [2]:" not in fixed
    assert "выдумка" not in fixed
    assert "References" in fixed   # запись осталась — заголовок на месте
    assert report.dropped == ["(ghost lines 0-0)"]


def test_reference_line_with_valid_number_is_kept() -> None:
    text = "References\n\n1. (степень 7): несуществующий источник\n"

    fixed, _ = repair_markers(text, source_count=2, sources=NAMED_SOURCES)

    assert "References" not in fixed
    assert "(степень 7)" not in fixed
    assert "несуществующий источник" not in fixed


def test_bare_marker_in_prose_is_rewritten() -> None:
    text = "Смотри hot_facts lines 5-9: там про Пруссии."

    fixed, report = repair_markers(text, source_count=3, sources=NAMED_SOURCES)

    assert fixed == "Смотри [3]: там про Пруссии."
    assert report.repaired == ["hot_facts lines 5-9 → [3]"]


def test_bare_marker_of_unknown_or_ambiguous_document_stays() -> None:
    samples = (
        "См. no_such_file lines 0-0 в приложении.",   # документа нет в выдаче
        "См. 2b_context lines 47-77 в приложении.",   # фрагментов четыре
    )
    for text in samples:
        fixed, report = repair_markers(text, source_count=3,
                                       sources=NAMED_SOURCES)
        assert fixed == text, text
        assert report.changed is False, text


def test_parenthesized_marker_is_not_touched_twice() -> None:
    """Скобочный маркер обрабатывает основной проход, а не проход по прозе."""
    fixed, _ = repair_markers("Факт (hot_facts lines 0-12) тут.",
                              source_count=3, sources=NAMED_SOURCES)

    assert fixed == "Факт [3] тут."


def test_reference_entry_loses_colon_for_markdown() -> None:
    """«1. [2]: doc (…)» markdown превращал в пустой пункт («1. 2.»).

    `[2]: doc (title)` разбирается как определение ссылки-сноски и
    съедается — в ответе оставались одни номера. Двоеточие убираем,
    номера и текст записи не меняются, это косметика, а не поломка.
    """
    text = ("Факт [2] и [3].\n\nReferences\n\n"
            "1. [2]: ekaterina_hot_facts (загружено пользователем)\n\n"
            "2. [3]: ekaterina_context (загружено пользователем)")
    fixed, report = repair_markers(text, source_count=3)

    assert "]:" not in fixed
    assert "1. [2] ekaterina_hot_facts (загружено пользователем)" in fixed
    assert "2. [3] ekaterina_context" in fixed
    assert report.changed is True and report.reflowed
    assert report.ok is True, "косметика не должна ломать ok"
    assert report.warnings == [], "пугать предупреждением некорректно"
    assert report.cited == [2, 3] and report.dangling == []
