"""Сборка `paperqa.Settings` из конфигурации boasi_s.

Все правила Фазы 0 (спайки 02–07) зафиксированы здесь и не должны размазываться
по коду сервисов:

* эмбеддинги — локальные sentence-transformers (Ollama-эмбеддинги: 10 мин на PDF
  и HTTP 400 на русском тексте длиннее ~3.8k символов);
* `llm_config` — ТОЛЬКО legacy-форма `model_list`: канонический `{"models": [...]}`
  перезаписывается валидатором paperqa (`LiteLLMModel(name=..., config=...)`) и
  теряет `timeout` (падает на 60 с) и `api_base` (в Docker уходит не туда);
* `parsing.use_doc_details=False` в оффлайне (нет Crossref / Semantic Scholar);
* `answer.max_concurrent_requests=1` — Ollama на CPU обрабатывает запросы
  последовательно, параллелизм упирается в очередь и таймауты;
* локализация — через `prompts.system` (дефолт + правило языка), а не через
  `prompts.pre/post`: это дополнительные вызовы LLM (+136 с на dev-машине);
* `evidence_skip_summary` и встроенный профиль `fast` не используются (см. отчёт).
"""

from __future__ import annotations

from typing import Any

from paperqa import Settings
from paperqa.settings import MultimodalOptions, PromptSettings

from app.config import Settings as AppSettings

# Правило языка добавляется к дефолтному system-промпту paperqa.
RU_RULE = (
    "LANGUAGE REQUIREMENT (обязательно): отвечай ТОЛЬКО на русском языке. "
    "Не переводи и не перефразируй названия географических объектов, приборов, методов "
    "и аббревиатуры: «Баренцево море», «CTD-зонд», «хлорофилл-а», «GF/F», "
    "«потеря сухого вещества». Каждое утверждение снабжай ключом источника из контекста."
)

EN_RULE = (
    "LANGUAGE REQUIREMENT (mandatory): answer in English only. "
    "Cite the source key for every claim."
)

LANGUAGE_RULES = {"ru": RU_RULE, "en": EN_RULE}

_built: dict[str, Settings] = {}

# Подразделы Settings: переопределение должно менять один ключ, а не весь раздел
# (иначе теряются max_concurrent_requests / use_doc_details и т.п.)
_SUB_SECTIONS = ("answer", "parsing", "prompts", "agent")


def _merge(payload: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Глубокое слияние на один уровень (dict-подразделы Settings)."""
    merged = dict(payload)
    for key, value in overrides.items():
        if key in _SUB_SECTIONS and isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def build_llm_config(app: AppSettings) -> dict[str, Any]:
    """Legacy-форма llm_config, совместимая с валидатором paperqa."""
    model = app.llm_model
    return {
        "model_list": [
            {
                "model_name": model,
                "litellm_params": {
                    "model": model,
                    "api_base": app.ollama_base_url,
                    "timeout": app.llm_timeout_seconds,
                    "max_retries": app.llm_max_retries,
                },
            }
        ]
    }


def build_system_prompt(app: AppSettings) -> str | None:
    """Дефолтный system-промпт paperqa + правило языка (или явно заданный в .env)."""
    if app.prompts_system:
        return app.prompts_system
    rule = LANGUAGE_RULES.get((app.answer_language or "ru").lower())
    if not rule:
        return None
    default = PromptSettings().system
    return f"{default}\n\n{rule}" if default else rule


def build_pqa_settings(app: AppSettings | None = None, **overrides: Any) -> Settings:
    """Собрать `Settings`; результат кэшируется (сборка не бесплатная)."""
    from app.config import get_settings  # локальный импорт: избегаем цикла

    app = app or get_settings()
    prompts: dict[str, Any] = {}
    system_prompt = build_system_prompt(app)
    if system_prompt:
        prompts["system"] = system_prompt

    llm_config = build_llm_config(app)
    payload: dict[str, Any] = {
        "llm": app.llm_model,
        "llm_config": llm_config,
        "summary_llm": app.resolved_summary_llm,
        "summary_llm_config": llm_config,
        "embedding": app.embedding_model,
        "temperature": 0.0,
        "answer": {
            "evidence_k": app.evidence_k,
            "answer_max_sources": app.answer_max_sources,
            "answer_length": app.answer_length,
            # Ollama на CPU последователен: параллельные запросы дают очередь в минуты
            "max_concurrent_requests": app.max_concurrent_requests,
        },
        "parsing": {
            # оффлайн: без Crossref/Semantic Scholar (иначе — минутные задержки)
            "use_doc_details": not app.offline_mode,
            "multimodal": MultimodalOptions.ON if app.multimodal else MultimodalOptions.OFF,
            "reader_config": {
                "chunk_chars": app.chunk_chars,
                "overlap": app.chunk_overlap,
            },
        },
        "agent": {
            "agent_llm": app.llm_model,
            "agent_llm_config": llm_config,
            "timeout": app.llm_timeout_seconds,
        },
    }
    if prompts:
        payload["prompts"] = prompts
    payload = _merge(payload, overrides)

    cache_key = repr(sorted(payload.items(), key=lambda kv: kv[0]))
    cached = _built.get(cache_key)
    if cached is not None:
        return cached

    settings = Settings(**payload)
    _built[cache_key] = settings
    return settings


def settings_fingerprint(settings: Settings) -> str:
    """Отпечаток конфигурации: смена модели/чанков требует переиндексации."""
    return settings.md5