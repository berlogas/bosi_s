"""Двуязычные подписи разделов — то, что видит исследователь.

Имя раздела в плане остаётся английским (это контракт API), но в подсказках
разбора и в тексте ошибки раздел называется «Введение (Introduction)».
"""

from __future__ import annotations

from app.services.analyses import analyze_draft, render_gaps
from app.services.section_labels import section_title


def test_section_title_keeps_english_name() -> None:
    assert section_title("Introduction") == "Введение (Introduction)"
    assert section_title("Methods") == "Методы исследования (Methods)"
    assert section_title("Results") == "Результаты (Results)"
    assert section_title("Discussion") == "Обсуждение (Discussion)"
    assert section_title("Conclusions") == "Заключение (Conclusions)"


def test_section_title_accepts_singular_and_any_case() -> None:
    assert section_title("Conclusion") == "Заключение (Conclusion)"
    assert section_title("results") == "Результаты (results)"
    assert section_title("  Methods  ") == "Методы исследования (Methods)"


def test_own_section_name_is_not_replaced() -> None:
    """Свой раздел показываем как есть: «Раздел «» не написан» бесполезно."""
    assert section_title("Приложение А") == "Приложение А"
    assert section_title("") == ""


def test_gap_hint_names_section_in_both_languages() -> None:
    sections = [{"name": "Methods", "required": True, "order": 1,
                 "word_target": 800, "notes": "", "content_md": ""}]

    rendered = render_gaps(analyze_draft(sections))

    assert "Раздел «Методы исследования (Methods)» не написан." in rendered


def test_gap_location_names_section_in_both_languages() -> None:
    """`where` в пробеле — техническое имя; в тексте разбора оно двуязычное."""
    sections = [{"name": "Discussion", "required": True, "order": 1,
                 "word_target": 900, "notes": "",
                 "content_md": "Результат показан без ссылки 5,5."}]

    analysis = analyze_draft(sections)
    rendered = render_gaps(analysis)

    assert all(gap.where == "Discussion" for gap in analysis.gaps), (
        "техническое имя в gaps.where не меняется — по нему UI ищет раздел")
    assert "Обсуждение (Discussion)" in rendered