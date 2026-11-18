"""Grounding сверяет ответ с ИСХОДНЫМ текстом источников, а не со сводками LLM.

Случай из жизни (Ollama 3B на CPU, 2026-11-11): модель в сводке фрагмента
написала «сушка при 105 °C», хотя в документе — «сушка при 60 °C». Проверка
обоснованности сравнивала ответ со сводками, а «105 °C» уже было в сводке, —
поэтому выдумка проходила как подтверждённый факт (ok=true).

Сводка — пересказ, сделанный той же моделью, что и ответ: доверять ей нельзя.
Исходный текст документа выдумать нельзя, он написан автором.
"""

from __future__ import annotations

import pytest

from app.services.grounding import check_grounding, extract_mentions

SOURCE_TEXT = (
    "# Методы измерения биомассы\n\n"
    "Фильтры GF/F: фильтрация 1-2 л воды, сушка при 60 °C, взвешивание 0.1 мг.\n"
    "Отношение биомассы к хлорофиллу-а 0,52 (0,42-0,63).\n"
)

# Что модель написала в сводке фрагмента: здесь появилась выдумка.
SUMMARY_TEXT = (
    "Биомассу оценивают методом GF/F — прямым взвешиванием сухого остатка "
    "после сушки при 105 °C, а также пересчётом из хлорофилла-а "
    "с коэффициентом 0,52."
)

ANSWER = (
    "**Метод GF/F** — взвешивание сухого остатка после сушки при 105 °C [1], "
    "плюс пересчёт по хлорофиллу-а с коэффициентом 0,52 [1]."
)


def test_number_in_summary_only_is_ungrounded() -> None:
    """«105 °C» есть в сводке, но нет в источнике — значит, это выдумка."""
    # Проверка по сводке (как было) — домысел проходит:
    by_summary = check_grounding(ANSWER, [SUMMARY_TEXT])
    assert by_summary.ok, "сводка содержит «105» — по ней выдумка не видна"

    # Проверка по исходному тексту (как должно быть) — выдумка видна:
    by_source = check_grounding(ANSWER, [SOURCE_TEXT])
    assert not by_source.ok
    assert "105" in by_source.ungrounded
    # Реальный факт из документа при этом остаётся обоснованным:
    assert "0,52" not in by_source.ungrounded


def test_grounding_uses_source_text_not_summary() -> None:
    """Сверка идёт по исходнику: числа сводки, которых нет в документе, — мимо."""
    mentions = extract_mentions(ANSWER)
    assert "105" in mentions

    report = check_grounding(ANSWER, [SOURCE_TEXT])
    assert report.ungrounded == ["105"]
    assert report.warnings, "о неподтверждённом факте должно быть предупреждение"


def test_factual_answer_passes_with_source_text() -> None:
    """Правдивый ответ по тому же документу проходит без замечаний."""
    answer = ("**Метод GF/F** — фильтрация и сушка при 60 °C с взвешиванием [1], "
              "плюс пересчёт по хлорофиллу-а с коэффициентом 0,52 [1].")

    report = check_grounding(answer, [SOURCE_TEXT])

    assert report.ok
    assert report.ungrounded == []


@pytest.mark.parametrize("contexts,expected", [
    # Нет источников — проверять нечего, ложных срабатываний быть не должно.
    ([], True),
    # Есть источник — «105» ловится.
    ([SOURCE_TEXT], False),
])
def test_grounding_source_vs_summary(contexts, expected) -> None:
    """Контекст проверки — исходные тексты источников."""
    report = check_grounding(ANSWER, contexts)

    assert report.ok is expected
