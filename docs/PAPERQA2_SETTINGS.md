# Настройки PaperQA2 (Settings)

Описание всех секций `paperqa.Settings`, которые собирает `build_pqa_settings()` из конфигурации boasi_s (`app/config.py`).

## Сборка настроек

Функция `build_pqa_settings(app)` в `app/services/pqa_profile.py` собирает объект `paperqa.Settings` из настроек приложения `AppSettings`. Результат кэшируется (сборка не бесплатная).

Отпечаток конфигурации — `settings_fingerprint(settings)` — возвращает `settings.md5`. При смене любого параметра fingerprint меняется, старые чанки в хранилище помечаются устаревшими и требуют переиндексации.

## Секция LLM

| Параметр | Источник | Значение по умолчанию | Описание |
|----------|----------|----------------------|----------|
| `llm` | `LLM_MODEL` | `ollama/qwen2.5:3b` | Модель языка для генерации ответов |
| `llm_config.api_base` | `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Endpoint Ollama |
| `llm_config.timeout` | `LLM_TIMEOUT_SECONDS` | `600` | Таймаут одного вызова LLM (секунды) |
| `llm_config.max_retries` | `LLM_MAX_RETRIES` | `2` | Количество повторов при ошибке |

Для облачного режима вместо `ollama_base_url` используется `LLM_API_BASE` + `LLM_API_KEY`.

## Секция эмбеддингов

| Параметр | Источник | Значение по умолчанию | Описание |
|----------|----------|----------------------|----------|
| `embedding` | `EMBEDDING_MODEL` | `st-intfloat/multilingual-e5-small` | Модель эмбеддингов (обязательно мультиязычная) |

> **Внимание:** смена модели эмбеддингов требует полной переиндексации (`make reindex` или кнопка «Переиндексировать» в админке).

## Секция Parsing

| Параметр | Значение | Описание |
|----------|----------|----------|
| `use_doc_details` | `False` (оффлайн) | В автономном контуре нет Crossref / Semantic Scholar |

## Секция Answer

| Параметр | Источник | Значение по умолчанию | Описание |
|----------|----------|----------------------|----------|
| `answer_max_sources` | `ANSWER_MAX_SOURCES` | `8` | Количество источников в ответе |
| `answer_length` | `ANSWER_LENGTH` | `no more than 120 words` | Длина ответа |
| `evidence_relevance_score_cutoff` | `EVIDENCE_MIN_RELEVANCE_SCORE * 10` | `0` | Порог релевантности PaperQA (шкала 0..10) |
| `evidence_skip_summary` | `EVIDENCE_SKIP_SUMMARY` | `False` | Сырой текст вместо LLM-сводок (быстрее, но больше prefill) |
| `max_concurrent_requests` | `MAX_CONCURRENT_REQUESTS` | `1` (Оllama CPU) / `4` (облако/GPU) | Параллельных вызовов LLM |

## Секция Agent

| Параметр | Источник | Значение по умолчанию | Описание |
|----------|----------|----------------------|----------|
| `agent_type` | `AGENT_TYPE` | `fake` | Тип агента (`fake` — детерминистичный офлайн) |
| `agent_llm` | `LLM_MODEL` | как `llm` | Модель для агента |
| `agent_llm_config` | как `llm_config` | как `llm_config` | Конфиг LLM для агента |

## Секция языка

| Параметр | Источник | Значение по умолчанию | Описание |
|----------|----------|----------------------|----------|
| `prompts.system` | `build_system_prompt()` | Дефолт PaperQA + правило языка (`answer_language`) | System-промпт с GROUNDING RULES |
| `prompts.qa` | `build_qa_prompt()` | Дефолт PaperQA + GROUNDING RULES | QA-промпт |

## Переменные окружения (.env)

Все переменные задокументированы в `.env.example`:

```
LLM_MODEL=ollama/qwen2.5:3b
OLLAMA_BASE_URL=http://127.0.0.1:11434
LLM_TIMEOUT_SECONDS=600
LLM_MAX_RETRIES=2
EMBEDDING_MODEL=st-intfloat/multilingual-e5-small
CHUNK_CHARS=4000
CHUNK_OVERLAP=200
EVIDENCE_K=5
EVIDENCE_MIN_RELEVANCE_SCORE=0
ANSWER_MAX_SOURCES=8
ANSWER_LENGTH=no more than 120 words
EVIDENCE_SKIP_SUMMARY=false
MAX_CONCURRENT_REQUESTS=4
AGENT_TYPE=fake
ANSWER_LANGUAGE=ru
OFFLINE_MODE=true
MULTIMODAL=false
PROMPTS_SYSTEM=
PROMPTS_QA=
```

## Приоритет порогов релевантности

Два порога действуют одновременно:

1. **Наш порог** (`evidence_min_relevance_score`, 0..1) — применяется до rerank в `merge_and_rerank()`. Шкала 0..1 соответствует `relevance_score / 10` от LLM.
2. **Встроенный PaperQA** (`evidence_relevance_score_cutoff`, 0..10) — применяется при сборке контекста.

Фактический отсев — больший из двух. Значение нашего порога умножается на 10 и записывается в `evidence_relevance_score_cutoff`.
