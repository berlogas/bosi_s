"""Справочник требований журналов и их подстановка в промпт.

Требования читаются с официальных гайдов журналов: числа в тестах — это
цитаты из них, а не округлённые «на глаз» значения. Если требования у
журнала изменятся, тесты напомнят обновить запись.
"""

from __future__ import annotations

from app.services import analyses
from app.services.generation import build_prompt
from app.services.journals import (
    JOURNALS,
    journal_options,
    journal_profile,
    style_block,
)

SOURCES: list[dict] = [
    {"index": 1, "dockey": "k1", "title": "Annesen 2009",
     "text": "Хлорофилл-а в Баренцевом море", "category": "temp_literature",
     "source_scope": "session"},
]


def test_profile_is_found_regardless_of_spelling() -> None:
    """Поле заполняют руками: «Nature», «nature» и псевдоним — один журнал."""
    for name in ("Nature", "nature", "  NATURE  "):
        assert journal_profile(name) is not None, name
    assert journal_profile("nature").title == "Nature"
    assert journal_profile("plos").title == "PLOS ONE"
    assert journal_profile("Science").title == "Science"


def test_unknown_journal_is_not_an_error() -> None:
    """Журнала нет в справочнике — работаем как раньше, а не падаем."""
    assert journal_profile("Journal of Applied Ichthyology") is None
    assert journal_profile("") is None
    assert journal_profile(None) is None
    assert style_block(None) == ""


def test_limits_come_from_official_guides() -> None:
    """Nature: 2500 слов и 50 ссылок. PLOS ONE: без ограничения на объём."""
    assert journal_profile("Nature").body_words == 2500
    assert journal_profile("Nature").references_limit == 50
    assert journal_profile("Nature").abstract_words == 200
    assert journal_profile("Science").abstract_words == 125
    assert journal_profile("PLOS ONE").body_words is None
    assert journal_profile("PLOS ONE").abstract_words == 300
    assert journal_profile("Scientific Reports").body_words == 4500


def test_every_profile_points_to_its_source() -> None:
    """Молча править требования без ссылки нельзя — это ломает доверие."""
    for profile in JOURNALS:
        if profile.key == "generic":
            continue
        assert profile.source.startswith("https://"), profile.key
        assert profile.style_notes, profile.key


def test_style_block_mentions_limits_and_citation_style() -> None:
    block = style_block(journal_profile("Nature"))

    assert "NATURE" in block
    assert "2500 слов" in block
    assert "надстрочный" in block
    assert "УЧТИ" not in block, "призыв к учёту добавляет промпт, не справочник"


def test_prompt_carries_journal_rules() -> None:
    """Требования журнала обязаны попасть в промпт генерации раздела."""
    plain = build_prompt("Introduction", "тема", SOURCES)
    with_journal = build_prompt("Introduction", "тема", SOURCES,
                                journal=journal_profile("Nature"))

    assert "ТРЕБОВАНИЯ ЖУРНАЛА" not in plain
    assert "ТРЕБОВАНИЯ ЖУРНАЛА NATURE" in with_journal
    assert "УЧТИ эти требования" in with_journal
    # правила цитат остаются: требования журнала их не заменяют
    assert "содержать ссылку вида [1]" in with_journal


def test_all_generation_kinds_receive_journal() -> None:
    """Каждый вид генерации строит свой промпт — правила должны быть везде."""
    nature = journal_profile("Nature")
    prompts = {
        "literature_review": analyses.literature_review_prompt("т", SOURCES,
                                                               journal=nature),
        "data_comparison": analyses.data_comparison_prompt("т", [], SOURCES,
                                                           journal=nature),
        "discussion": analyses.discussion_prompt("т", "текст", [], SOURCES,
                                                 journal=nature),
        "gap_analysis": analyses.gap_analysis_prompt("т", "покрытие", SOURCES,
                                                     journal=nature),
        "report": analyses.report_prompt("# Шаблон", SOURCES, journal=nature),
    }

    missing = [kind for kind, text in prompts.items()
               if "ТРЕБОВАНИЯ ЖУРНАЛА NATURE" not in text]
    assert not missing, f"требования не попали в промпты: {missing}"


def test_prompts_without_journal_stay_clean() -> None:
    assert "ТРЕБОВАНИЯ" not in analyses.discussion_prompt("т", "", [], SOURCES)


def test_options_expose_limits_for_the_selector() -> None:
    options = journal_options()

    titles = {item["title"] for item in options}
    assert "Nature" in titles
    # служебный профиль без требований в интерфейс не попадает
    assert "Без требований" not in titles
    nature = next(item for item in options if item["title"] == "Nature")
    assert "2500 слов" in nature["limits"]
    assert nature["source"].startswith("https://")