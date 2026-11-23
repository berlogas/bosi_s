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
from pydantic import ValidationError

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


def test_qa_prompt_passes_paperqa_variable_validation(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """paperqa сам ругается на неизвестные `{переменные}` — пусть ругается здесь."""
    # На машине может висеть одноимённая переменная окружения (AGENT=1):
    # pydantic-settings читает её как поле `agent` и ломает конструирование.
    monkeypatch.delenv("AGENT", raising=False)
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
    # `_env_file=None`: тест проверяет дефолт и merge-логику, а не содержимое
    # локального .env, где флаг может быть включён осознанно.
    app = _app(evidence_skip_summary=False)
    settings = build_pqa_settings(app)
    assert settings.answer.evidence_skip_summary is False

    fast = build_pqa_settings(app, answer={"evidence_skip_summary": True})
    assert fast.answer.evidence_skip_summary is True
    # переопределение одного ключа не должно терять соседи подраздела
    assert fast.answer.evidence_k == app.evidence_k
    assert fast.answer.max_concurrent_requests == app.max_concurrent_requests


def test_evidence_min_relevance_score_is_off_by_default_and_validated() -> None:
    # 0 = порог не применяется: на текущем корпусе абсолютный порог отсекает
    # релевантное вместе с посторонним (см. комментарий в config.py).
    assert AppSettings(secret_key="x" * 48).evidence_min_relevance_score == 0.0
    quiet = AppSettings(secret_key="x" * 48)
    assert not any("EVIDENCE_MIN_RELEVANCE_SCORE" in w for w in quiet.validate_runtime())

    noisy = AppSettings(secret_key="x" * 48, evidence_min_relevance_score=0.9)
    assert any("EVIDENCE_MIN_RELEVANCE_SCORE" in w for w in noisy.validate_runtime())

    for bad in (1.5, -0.1):
        with pytest.raises(ValidationError):
            AppSettings(secret_key="x" * 48, evidence_min_relevance_score=bad)


def test_validate_runtime_warns_about_skip_summary() -> None:
    app = AppSettings(secret_key="x" * 48, evidence_skip_summary=True)

    warnings = app.validate_runtime()

    assert any("EVIDENCE_SKIP_SUMMARY" in w for w in warnings)
    quiet = AppSettings(secret_key="x" * 48, evidence_skip_summary=False)
    assert not any("EVIDENCE_SKIP_SUMMARY" in w for w in quiet.validate_runtime())


def test_prompt_settings_default_still_valid() -> None:
    """Санити: дефолт paperqa не должен внезапно исчезнуть из апстрима."""
    assert "{answer_length}" in PromptSettings().qa


def test_refusal_rule_allows_partial_answer() -> None:
    """Модель должна отвечать по имеющемуся фрагменту, а не отказываться.

    Регрессия: на вопрос «что мы знаем о Кутузове?» релевантный текст был в
    контексте (косинус 0.815), но модель отвечала отказом. Правило отказа
    теперь разрешает частичный ответ с оговоркой, сохраняя запрет отказа,
    когда в контексте нет ничего.
    """
    from app.services.pqa_profile import _QA_GROUNDING, RU_RULE

    assert "REFUSAL RULE" in RU_RULE
    assert "только если НИ ОДИН фрагмент" in RU_RULE
    # частичный ответ предпочтительнее отказа — это и требовалось
    assert "отвечай по ним, даже если их мало" in RU_RULE
    # при этом фактическая строгость остаётся
    assert "FACT REQUIREMENT" in RU_RULE

    assert "If NO context fragment" in _QA_GROUNDING


def test_min_relevance_score_drives_paperqa_cutoff() -> None:
    """Наш порог выставляется в штатный `evidence_relevance_score_cutoff`.

    Два порога отсекают контексты независимо: наш работает до rerank,
    встроенный — при сборке контекста (`settings.py:1223`). Если выставлять
    только наш, фактический отсев остаётся `max(наш, 0.1)` из-за дефолта
    PaperQA, и получить «порог ниже 0.1» невозможно. Шкалы различаются в 10 раз.
    """
    off = build_pqa_settings(_app(evidence_min_relevance_score=0.0))
    assert off.answer.evidence_relevance_score_cutoff == 0

    tenth = build_pqa_settings(_app(evidence_min_relevance_score=0.1))
    assert tenth.answer.evidence_relevance_score_cutoff == 1

    high = build_pqa_settings(_app(evidence_min_relevance_score=0.86))
    assert high.answer.evidence_relevance_score_cutoff == 9


# ------------------------------------------------------------------ кэш эмбеддингов
def test_embedding_model_cached_reuse(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Повторный вызов `_cached_embedding_model` с теми же аргументами
    не перезагружает модель с диска (lru_cache срабатывает).

    2.4.1 Тесты кэша эмбеддингов: `_cached_embedding_model` кэширует до 8
    экземпляров; второй вызов с тем же именем модели и конфигом должен
    вернуть тот же объект без повторного вызова `embedding_model_factory`.
    """
    from app.services import pqa_profile

    calls = []
    fake_model = object()

    def _fake_factory(embedding: str, **kwargs) -> object:
        calls.append((embedding, kwargs))
        return fake_model

    monkeypatch.setattr(
        "lmi.embeddings.embedding_model_factory", _fake_factory)

    # Очищаем kэш перед тестом, чтобы не зависеть от других тестов
    pqa_profile._cached_embedding_model.cache_clear()

    model1 = pqa_profile._cached_embedding_model("st-multi-qa-MiniLM-L6-cos-v1",
                                                 "{}")
    model2 = pqa_profile._cached_embedding_model("st-multi-qa-MiniLM-L6-cos-v1",
                                                 "{}")

    assert model1 is model2 is fake_model
    assert len(calls) == 1, (
        f"fabrik должен быть вызван 1 раз, а вызван {len(calls)}")

    # Другая модель — другой кэш-слот, фабрика вызывается повторно
    model3 = pqa_profile._cached_embedding_model("other-model", "{}")
    assert model3 is fake_model  # та же заглушка
    assert len(calls) == 2

    pqa_profile._cached_embedding_model.cache_clear()


# ------------------------------------------------------------------ метрика загрузки модели эмбеддингов
def test_embedding_model_load_count_metric(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """2.4.2 Метрика загрузки модели эмбеддингов.

    `embedding_model_load_count()` должна увеличиваться только при реальной
    загрузке с диска (промахе kэша), а не при каждом вызове
    `get_embedding_model` / `_cached_embedding_model`.
    """
    from app.services import pqa_profile

    calls = []
    fake_model = object()

    def _fake_factory(embedding: str, **kwargs) -> object:
        calls.append((embedding, kwargs))
        return fake_model

    monkeypatch.setattr(
        "lmi.embeddings.embedding_model_factory", _fake_factory)

    pqa_profile._cached_embedding_model.cache_clear()
    # Сбрасываем счётчик метрики (глобальная переменная модуля)
    pqa_profile._embedding_model_loads = 0

    assert pqa_profile.embedding_model_load_count() == 0

    # Первый вызов — промах кэша, модель загружается
    m1 = pqa_profile._cached_embedding_model("model-a", "{}")
    assert pqa_profile.embedding_model_load_count() == 1
    assert len(calls) == 1

    # Второй вызов с теми же аргументами — попадание в кэш, загрузки нет
    m2 = pqa_profile._cached_embedding_model("model-a", "{}")
    assert m1 is m2
    assert pqa_profile.embedding_model_load_count() == 1
    assert len(calls) == 1

    # Другая модель — снова промах кэша
    pqa_profile._cached_embedding_model("model-b", "{}")
    assert pqa_profile.embedding_model_load_count() == 2
    assert len(calls) == 2

    pqa_profile._cached_embedding_model.cache_clear()
    pqa_profile._embedding_model_loads = 0
