"""Фаза 10 — проверка обоснованности ответа (grounding).

Эвристика ловит самый частый класс галлюцинаций слабой модели: утверждения,
которых нет ни в одном найденном фрагменте («дочь Петра I», «брак с
Александром I», «Наполеон»). Важны обе стороны:

* находка — выдуманные сущности попадают в `ungrounded` и `warnings`;
* безопасность — нормальный ответ про то же документооборот не ополчается
  на склонения, номера и служебные заглавные слова.
"""

from __future__ import annotations

from pathlib import Path

from app.services.grounding import (
    GroundingReport,
    check_grounding,
    extract_mentions,
    normalize_text,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REAL_DOC = (PROJECT_ROOT
            / "data/sessions/f28a4402-daca-411c-bfc1-9e591adca5b0"
            / "uploads/2b319e4a_ekaterina_alekseevna_context.md")


# ------------------------------------------------------------------ извлечение
def test_mentions_include_names_years_and_numbers() -> None:
    text = "Екатерина II родилась в 1729 году в Штеттине. Доход равен 1200."

    mentions = extract_mentions(text)

    assert "Екатерина II" in mentions
    assert "1729" in mentions
    assert "Штеттине" in mentions
    assert "1200" in mentions


def test_sentence_initial_capital_is_not_a_mention() -> None:
    mentions = extract_mentions("Я родилась в Штеттине. Она стала императрицей.")

    assert "Я" not in mentions
    # «Она» — тоже: одиночное заглавное в начале предложения
    assert "Она" not in mentions
    assert "Штеттине" in mentions


def test_question_prefix_is_ignored() -> None:
    text = "Question: Когда родилась Екатерина?\n\nОтвет: в 1729 году."

    mentions = extract_mentions(text)

    assert "Когда" not in mentions
    assert "1729" in mentions


def test_mentions_are_deduplicated() -> None:
    mentions = extract_mentions("В 1772 делили. Снова в 1772.")

    assert mentions.count("1772") == 1


# ------------------------------------------------------------------ сверка
def test_fabricated_entity_is_flagged() -> None:
    context = ["Екатерина родилась в Штеттине в 1729 году и взошла на престол "
               "в 1762 году."]
    answer = "Она была дочерью Петра I и супругой Александра I."

    report = check_grounding(answer, context)

    assert report.ok is False
    assert "Петра I" in report.ungrounded
    assert "Александра I" in report.ungrounded
    assert report.warnings and "не подтверждены" in report.warnings[0]


def test_fact_present_in_context_is_grounded() -> None:
    context = ["Екатерина II родилась в Штеттине в 1729 году и пригласила "
               "Вольтера в Россию."]
    answer = "Екатерина II родилась в 1729 году и переписывалась с Вольтером."

    report = check_grounding(answer, context)

    assert report.ok is True
    assert report.ungrounded == []
    assert report.checked > 0
    assert report.ratio == 1.0


def test_declensions_are_tolerated_via_word_stems() -> None:
    context = ["Григорий Орлов помог Екатерине взойти на престол."]
    answer = "Взойти Екатерине помог Григорьевич Орлов."

    report = check_grounding(answer, context)

    # основы слов (≥4 букв) переживают склонения и отчество
    assert report.ungrounded == []


def test_year_must_match_exactly() -> None:
    context = ["Первый раздел Речи Посполитой произошёл в 1772 году."]
    answer = "Раздел произошёл в 1773 году."

    report = check_grounding(answer, context)

    assert "1773" in report.ungrounded


def test_no_context_skips_the_check_with_warning() -> None:
    report = check_grounding("Любой ответ", [])

    assert report.ok is True
    assert report.checked == 0
    assert report.ratio == 1.0
    assert report.warnings and "пропущена" in report.warnings[0]


def test_report_serializes_for_stats() -> None:
    report = check_grounding("Наполеон победил в 1812 году",
                             ["Крым присоединён в 1783 году."])

    payload = report.to_dict()

    assert set(payload) == {"ok", "checked", "grounded", "ratio",
                            "ungrounded", "warnings"}
    assert payload["ok"] is False
    assert payload["ratio"] < 1.0
    assert isinstance(GroundingReport(), GroundingReport)


def test_normalize_text_handles_yo_and_case() -> None:
    # пробелы/знаки нормализация не схлопывает — сравниваем по словам
    assert normalize_text("Ёлка — Ёжик").split() == normalize_text("елка ежик").split()


# ------------------------------------------------- регрессия на живых файлах
def test_real_defective_answer_is_caught() -> None:
    """Ответ с выдуманной родословной ловится на реальном документе."""
    if not REAL_DOC.exists():
        import pytest

        pytest.skip("нет выгрузки документа (data/ не в репозитории)")
    context = [REAL_DOC.read_text(encoding="utf-8")]
    answer = ("Екатерина Алексеевна была дочерью Петра I, супругой Александра I; "
              "Наполеон предлагал ей союз. Она упорядочила управление в 1775 году.")

    report = check_grounding(answer, context)

    assert "Петра I" in report.ungrounded
    assert "Александра I" in report.ungrounded
    assert "Наполеон" in report.ungrounded
    # а реальный факт из документа остаётся обоснованным
    assert "1775" not in report.ungrounded


def test_roman_numerals_and_latin_words_survive() -> None:
    """«II» не должен схлопываться в «I», а «Cisco» — в «C»."""
    mentions = extract_mentions("Правил Пётр II, визит в Cisco был в 1762 году.")

    # именованная последовательность тянет соседние заглавные слова — важно,
    # что римский разряд не схлопнут и латинское слово не обрезано
    assert any("Пётр II" in m for m in mentions)
    assert "Cisco" in mentions
    assert not any("Пётр I," in m or m.endswith("Пётр I") for m in mentions)


def test_mixed_script_name_is_grounded() -> None:
    """Имя частично латиницей («Гриgorия») должно найтись в контексте.

    Такой текст иногда выдаёт LLM; без свертки латиницы проверка
    обоснованности давала ложное срабатывание на корректном утверждении.
    """
    report = check_grounding(
        "Фаворитом был Григория Орлов, а ещё Мария Фёдоровна.",
        ["Григорий Орлов — мой фаворит, помог мне взойти на престол."])

    assert report.ungrounded == ["Мария Фёдоровна"]
