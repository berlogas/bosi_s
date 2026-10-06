"""Фаза 10 — промпты и настройки генерации против галлюцинаций.

Три рычага, которые проверяются здесь (без LLM):

* qa-промпт: требование «писать как научную статью» заменено на GROUNDING
  RULES с явным отказом ``I cannot answer`` и без лишних шаблонных переменных;
* system-правило: FACT REQUIREMENT — факты только из контекста;
* `Settings`: короткий ответ, больше источников, флаг `evidence_skip_summary`
  (и предупреждение `validate_runtime`, если его включили).
"""

from __future__ import annotations

import re

import pytest
from paperqa import Settings as PqaSettings
from paperqa.prompts import CANNOT_ANSWER_PHRASE
from paperqa.settings import PromptSettings

from app.config import Settings as AppSettings
from app.services import pqa_profile
from app.services.pqa_profile import (
    EN_RULE,
    RU_RULE,
    build_pqa_settings,
    build_qa_prompt,
    build_system_prompt,
)

# Переменные, которые paperqa умеет подставлять в qa-промпт.
ALLOWED_QA_VARS = {"context", "question", "example_citation", "answer_length",
                   "prior_answer_prompt"}


def _app(**update: object) -> AppSettings:
    """Настройки приложения без переопределений из .env."""
    base = {"prompts_system": None, "prompts_qa": None}
    return AppSettings().model_copy(update={**base, **update})


# ------------------------------------------------------------------- qa-промпт
def test_qa_prompt_replaces_article_style_with_grounding() -> None:
    qa = build_qa_prompt(_app())

    assert "GROUNDING RULES" in qa
    assert "scientific article" not in qa
    assert "no introduction, no conclusions" in qa
    assert f'"{CANNOT_ANSWER_PHRASE}."' in qa


def test_qa_prompt_keeps_required_placeholders() -> None:
    qa = build_qa_prompt(_app())

    assert "{context}" in qa
    assert "{question}" in qa
    assert "{answer_length}" in qa


def test_qa_prompt_passes_paperqa_variable_validation() -> None:
    """paperqa сам ругается на неизвестные `{переменные}` — пусть ругается здесь."""
    qa = build_qa_prompt(_app())

    assert set(re.findall(r"\{(\w+)\}", qa)) <= ALLOWED_QA_VARS
    PqaSettings(qa=qa)  # ValueError, если переменные лишние


def test_qa_prompt_falls_back_when_default_changes(
        monkeypatch: pytest.MonkeyPatch) -> None:
    class _StubPromptSettings:
        def __init__(self) -> None:
            self.qa = "Context: {context}\nAnswer ({answer_length}):"

    monkeypatch.setattr(pqa_profile, "PromptSettings", _StubPromptSettings)

    qa = build_qa_prompt(_app())

    # правила должны стоять до строки ответа, иначе модель их не увидит
    assert qa.index("GROUNDING RULES") < qa.index("Answer ({answer_length}):")
    assert "{context}" in qa


def test_prompts_qa_from_env_wins() -> None:
    custom = "Свой шаблон {context} {question}"
    assert build_qa_prompt(_app(prompts_qa=custom)) == custom


# ------------------------------------------------------------------ system-правило
def test_rules_contain_fact_requirement() -> None:
    for rule in (RU_RULE, EN_RULE):
        assert "FACT REQUIREMENT" in rule
        assert CANNOT_ANSWER_PHRASE in rule
        assert "CITATION REQUIREMENT" in rule


def test_ru_rule_forbids_invented_markers() -> None:
    assert "(степень 1)" in RU_RULE
    assert "Valid Keys" in RU_RULE


def test_system_prompt_embeds_the_rule() -> None:
    system = build_system_prompt(_app())

    assert system is not None
    assert "FACT REQUIREMENT" in system
    assert "LANGUAGE REQUIREMENT" in system


# ------------------------------------------------------------------ Settings
def test_settings_wire_qa_and_system_prompts() -> None:
    app = _app()

    settings = build_pqa_settings(app)

    assert settings.prompts.qa == build_qa_prompt(app)
    assert "FACT REQUIREMENT" in (settings.prompts.system or "")


def test_settings_keep_generation_narrow() -> None:
    app = _app()

    settings = build_pqa_settings(app)

    assert settings.answer.answer_max_sources == app.answer_max_sources
    assert settings.answer.answer_length == app.answer_length
    # короткий ответ: развёрнутый текст сильнее «дорисовывает» факты
    assert "120" in app.answer_length
    assert app.answer_max_sources >= 8


def test_evidence_skip_summary_defaults_off_and_merges_when_on() -> None:
    app = _app()
    settings = build_pqa_settings(app)
    assert settings.answer.evidence_skip_summary is False

    fast = build_pqa_settings(app, answer={"evidence_skip_summary": True})
    assert fast.answer.evidence_skip_summary is True
    # переопределение одного ключа не должно терять соседи подраздела
    assert fast.answer.evidence_k == app.evidence_k
    assert fast.answer.max_concurrent_requests == app.max_concurrent_requests


def test_validate_runtime_warns_about_skip_summary() -> None:
    app = AppSettings(secret_key="x" * 48, evidence_skip_summary=True)

    warnings = app.validate_runtime()

    assert any("EVIDENCE_SKIP_SUMMARY" in w for w in warnings)
    quiet = AppSettings(secret_key="x" * 48, evidence_skip_summary=False)
    assert not any("EVIDENCE_SKIP_SUMMARY" in w for w in quiet.validate_runtime())


def test_prompt_settings_default_still_valid() -> None:
    """Санити: дефолт paperqa не должен внезапно исчезнуть из апстрима."""
    assert "{answer_length}" in PromptSettings().qa
