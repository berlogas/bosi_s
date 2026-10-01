# SPICE_REPORT — Фаза 0: проверка допущений boasi_s

**Дата:** 2026-10-01
**Цель:** проверить, что стек `paper-qa + Ollama + локальные эмбеддинги` работоспособен на имеющемся железе, и зафиксировать реальные сигнатуры API, тайминги и грабли **до** написания продакшн-кода.

---

## 0. Итог одной строкой

✅ **Стек работает end-to-end** (загрузка → RAG → ответ с цитатами → удаление), персистентность состояния `Docs` подтверждена, API изучен.
⚠️ **Главное ограничение железа разработчика — CPU-only, 8 ядер, без GPU.** Ollama-эмбеддинги непригодны (10 мин на PDF и ошибка 400 на русском), генерация 8.6 ток/с → один RAG-ответ 1.5–6 мин.

> **Важно: замеры ниже — это dev-режим (слабая машина, worst case).** Разработка ведётся на CPU-машине без GPU, эксплуатация планируется на машине с GPU и большим объёмом памяти. Все выводы оформлены как профили `dev` / `prod` (см. `PLAN.md`, §1.1): в коде нет констант производительности, смена режима — только конфиг. Ожидаемое ускорение в prod на GPU — **5–15×**, но цифры prod-профиля нужно перезамерить отдельно.

---

## 1. Окружение

| Параметр | Значение |
| --- | --- |
| OS | Windows, dev через Git Bash |
| CPU | 8 ядер, **GPU отсутствует** (`nvidia-smi` не найден) |
| Python (системный) | 3.10.11 — **не подходит** (paper-qa требует ≥3.11) |
| Python (для проекта) | 3.11.9 в `.venv` (`py -3.11 -m venv .venv`) ✅ |
| Docker | CLI 29.4.3 / compose v5.1.3 установлены, **daemon не запущен** → для спайков Ollama запущен на хосте |
| Ollama | 0.20.5, сервер поднят локально, модели уже есть: `qwen2.5:3b`, `qwen2.5:7b-instruct`, `qwen2.5:14b`, `llama3.2:3b`, `nomic-embed-text` |
| paper-qa | **2026.8.12** (CalVer), `lmi` (fhlmi) 1.0.7, `fhaviary` 0.37.0, litellm 1.84.1, pypdf 6.19.0, numpy 2.4.6 |
| Сеть | есть (для pip и HF), но **в контуре приложения её не будет** → `use_doc_details=False` |
| API-ключи | отсутствуют → подтверждена обязательность явных `settings` при каждом вызове |

---

## 2. Сверка с ТЗ (`interface.md`) — фактический API

Проверено в `spikes/01_introspect.py` (+ исходники установленного пакета).

| Ожидание ТЗ | Факт `paper-qa==2026.8.12` | Действие |
| --- | --- | --- |
| `await docs.aadd(path)` → dockey | `aadd(path, citation, docname, dockey, title, doi, authors, settings, llm_model, embedding_model) -> str \| None` возвращает **`docname`**; `dockey` = md5 содержимого | обёртка хранит реестр `doc_id ↔ docname ↔ dockey` |
| `docs.delete(dockey) -> bool` | `delete(name=None, docname=None, dockey=None) -> None`, **синхронный**, `name` deprecated | bool формируем сами; отсутствие документа не бросает исключение |
| `docs.clear_docs()` | есть, синхронный, чистит `texts/docs/docnames/texts_index` | ✅ |
| `Docs.aadd_url` | есть (async) | ✅ |
| — | **`Docs.aadd_file(BinaryIO)`** есть, но **на Windows падает** (см. §4) | upload → сами пишем temp-файл → `aadd` |
| — | **`Docs.aadd_texts(texts, doc, settings, embedding_model)`** есть | **основа персистентности сессий** (§5) |
| — | `Docs.aget_evidence(session_or_query, ...)` — отдельный шаг ретривала+RCS | используем для RAG fusion и для переиспользования (§6) |
| `session.references` = список | `PQASession.references: str`; источники = `contexts[].text.doc` (`Doc.docname/dockey/citation/formatted_citation`) | свой DTO `sources[]` |
| `session.context` = list[dict] | `PQASession.context: str`; список чанков = `contexts: list[Context]` | свой DTO |
| `answer_max_sources` | `settings.answer.answer_max_sources` ✅ | ✅ |
| — | LLM-слой — **`lmi`**, не прямой `litellm`; `agent_query()` → `AnswerResponse` (поле `answer: PQASession`, `bibtex`, `status`, `timing_info`) | учитывать в Фазе 6/7 |
| — | `Settings.from_name("fast")` / `get_settings(dict)` — встроенные профили (в т.ч. `fast`, `high_quality`, `wikicrow`, `contracrow`), свои — в `~/.config/pqa/settings/*.json` | использовать `fast` для CPU-профиля |
| — | `extra` для Office: `office` (не `msoffice`) | ставить `paper-qa[office]` для docx/xlsx/pptx |
| — | `Docs` — pydantic-модель, пиклится целиком (`__getstate__`) | допустимо, но канонично — `aadd_texts` |

Полный машинно-читаемый дамп: `spikes/01_introspect.json`.

---

## 3. Производительность железа (ключевое)

### 3.1 Генерация (ollama `/api/generate`, 8 ядер CPU)

| Модель | Скорость | Время ответа ~180 токенов |
| --- | --- | --- |
| `qwen2.5:3b` | **8.6 ток/с** | 47–111 с |
| `qwen2.5:7b-instruct` | **3.9 ток/с** | 82–85 с |
| `qwen2.5:14b` | ~2 ток/с (оценка) | ~4–6 мин → **непригодна** |

`num_thread: 8` в options скорость не меняет (runner всё равно 4 потока) — влияет только на время загрузки модели.

### 3.2 Эмбеддинги — два ключевых вывода

**A. Эмбеддинги через Ollama (`nomic-embed-text`) — непригодны:**

| Вход | Результат |
| --- | --- |
| 500 симв | 20.7 с (11 ток/с) |
| 2000 симв | 86 с |
| 3000 симв | 125 с |
| **4000+ символов (рус.)** | **HTTP 400 «the input length exceeds the context length»** |
| PDF PaperQA2 (27 чанков по ~4000 симв.) | **10 мин 42 с** на один батч |

Причина: контекст модели 2048 ток, русский текст ~1.9 симв/ток, дефолтный `chunk_chars=5000` → всегда за пределами контекста и всегда минуты на CPU.

**B. Локальные sentence-transformers (`paper-qa[local]`, `embedding="st-multi-qa-MiniLM-L6-cos-v1"`) — рабочий вариант:**

| Документ | Время индексации (вместе с парсингом) |
| --- | --- |
| `biomass.md` (рус., 1 чанк) | 14–36 с (первый раз — скачивание модели) |
| `biomass_barents_2024.csv` | 2.8–2.9 с |
| **PaperQA2.pdf (25 стр., 27 чанков)** | **11.9–12.6 с** ← в ~50 раз быстрее Ollama |

Эмбеддинги 384-мерные, кириллица не теряется.

> **Решение для boasi_s:** `embedding="st-multi-qa-MiniLM-L6-cos-v1"` (локально, в контейнере), `nomic-embed-text` через Ollama — только опция, и только с `truncate=true` и `chunk_chars ≤ 1500`.

### 3.3 Стоимость одного RAG-запроса (`qwen2.5:3b`, evidence_k=4)

| Шаг | Время |
| --- | --- |
| `aget_evidence` (4 RCS-суммаризации) | **285–321 с** |
| `aquery(str)` (ретривал + генерация) | **374 с** |
| `aquery(PQASession)` (только генерация) | **118–122 с** |
| `evidence_skip_summary=True` | evidence 2.7 с, но ответ **817 с** (огромный prefill) — **не применять** |
| `fast`-профиль (k=5, max_concurrent=5) | evidence **451 с** (очередь на CPU), затем падение на парсинге score |

---

## 4. Грабли (обязательно учесть в коде)

1. **Каноническая форма `LLMConfig {"models": [...]}` ТЕРЯЕТСЯ.**
   `Settings.get_summary_llm()` делает `LiteLLMModel(name=..., config=...)`, а его валидатор, если в `config` нет ключа `model_list`, **пересобирает конфиг из `name`**, выбрасывая наши параметры. Итог: `timeout=60`, `max_retries=3`, `api_base=None`, `temperature=1.0`.
   → **Использовать только legacy-форму** `{"model_list": [{"model_name": ..., "litellm_params": {..., "timeout": 3600, "api_base": ...}}]}` (как в README paper-qa). Проверено: с legacy формой `timeout=3600`, `api_base` honored.
   Это же спасёт от молчаливого игнорирования `api_base=http://ollama:11434` в Docker.

2. **Дефолтный таймаут 60 с.** На CPU любой запрос дольше 60 с → `AllModelsExhaustedError`; lmi ретраит и в итоге всё проходит, но **каждый ретрай = ещё 60 с**. Всегда `timeout` ≥ 1800 в `litellm_params`.

3. **`prompts.pre` и `prompts.post` — это дополнительные вызовы LLM**, а не префикс/суффикс промпта (см. `docs.py`: отдельный `call_single`, результат `pre` подставляется в сериализацию контекста, `post` заменяет/дописывает ответ). Попытка «локализовать» через `pre` сорвала ответ 3b и стоила +136 с.
   → Локализация делается через **`prompts.system`** или шаблон **`prompts.qa`** (проверяется в спайке 07).

4. **`aadd_file(BinaryIO)` падает на Windows**: `PermissionError` — paperqa держит `NamedTemporaryFile` открытым и пытается открыть тот же путь на чтение.
   → Upload-обработчик: сохранить файл ourselves (`.tmp` в каталоге сессии) → `aadd(path)`. В Linux/Docker проблемы нет, но единый путь надёжнее.

5. **Повторный `aadd` того же файла возвращает `None`** (дедуп по `dockey`), а не исключение и не новый `docname`. Обёртка обязана трактовать `None` как «документ уже есть», а не как ошибку.

6. **Если не передать `settings` — уходит в OpenAI по умолчанию** и падает с `Missing credentials` (в оффлайн-контуре). Правило: `settings` передаётся **всем** вызовам без исключений; в сервисе — единственная фабрика `Settings`.

7. **`Settings.parsing.reader_config = {"chunk_chars": 5000, "overlap": 250}`** — дефолт плохо сочетается с русскими чанками и Ollama-эмбеддингами. Рабочий выбор: `chunk_chars=4000, overlap=200` (со ST-эмбеддингами) либо ≤1500 для Ollama.

8. `parsing.multimodal` по умолчанию `ON_WITH_ENRICHMENT` → выключить (`OFF`) на CPU: enrichment вызывает LLM на каждую картинку/таблицу.
9. `parsing.use_doc_details=True` по умолчанию → ходит в Crossref/Semantic Scholar; в оффлайне выключить (`False`) и задавать `citation` явно.
10. Для не-публикаций (CSV, MD, заметки) PaperQA не умеет строить цитату → всегда передавать `citation=...`, иначе LLM выдумывает «Unknown, ...».

---

## 5. Персистентность сессий — ПОДТВЕРЖДЕНА (`spikes/03_persistence.py`)

| Проверка | Результат |
| --- | --- |
| `pickle.dumps(Docs)` | ✅ 15.8 KiB (2 документа) |
| Пересборка через `Docs.aadd_texts()` в новый `Docs` | ✅ 7.3 с |
| **`aget_evidence` после восстановления vs до** | ✅ **идентичные `Context.score`** |
| `delete(docname=...)`, `delete(dockey=...)` | ✅ удаляют, возвращают `None` |
| `delete` отсутствующего | ✅ без исключения |
| Повторный `aadd` того же файла | ✅ `None`, дедуп по `dockey` |
| `clear_docs()` | ✅ полная очистка |

**Вывод для Фазы 5:** хранить `Text`+`Doc` (с `embedding`) в SQLite и пересобирать `Docs` при старте сессии — рабочая и точная схема; повторный парсинг PDF не нужен. Артефакт дампа: `spikes/fixture_state.json`.

---

## 6. Оптимизация запроса: переиспользование evidence (`spikes/06_*`)

`Docs.aquery()` принимает `PQASession`. Если передать сессию, полученную из `aget_evidence`, повторный ретривал **не выполняется**:

| Вызов | Время |
| --- | --- |
| `aquery("вопрос")` | 374 с |
| `aquery(session_from_aget_evidence)` | **118 с** (−68%) |

→ В RAG fusion (Фаза 6) обязательная схема: `aget_evidence` по N коллекциям → слияние → **один** `aquery(merged_session)`.

---

## 7. Качество ответа и локализация (3b, RU-вопрос) — `spikes/02`, `spikes/06`, `spikes/07`

Ретривал отличный: на русский вопрос верны GF/F, хлорофилл-а, потеря сухого вещества, ограничения CTD; ссылки проставлены (`(biomass_notes lines 0-0)`).

Проблемы дефолтной генерации:
* ответ на **английском** (промпты PaperQA англоязычные), «Баренцево море» → «Barren Sea», «CTD-зонд» → «CTD sondes»;
* для не-публикаций ссылка выглядит как `lines 0-0`, а не «стр. N» → нужен свой маппинг источников в UI.

**Локализация решена** (спайк 07): оба варианта дают корректный русский ответ с сохранением терминов:

| Вариант | Время | Результат |
| --- | --- | --- |
| **A: `prompts.system` = дефолт + правило языка** | **122 с** | ✅ «В Баренцевом море используются два метода… хлорофилл-а … стеклянных фильтров (GF/F)», цитаты на месте |
| B: `prompts.qa` = дефолтный шаблон + правило в user-сообщении | 147 с | ✅ аналогично, чуть более «свободный» текст |

→ **Рекомендация: вариант A + `prompts.system`, вынесенный в `~/.config/pqa/settings/boasi_s.json`.** Правило обязательно запрещает переводить географические объекты, приборы и аббревиатуры (иначе «Баренцево море» → «Barren Sea»).

**Профиль `fast` на русском не работает:** `fast` задаёт `prompts.use_json=False`, и парсер релевантности пытается извлечь score из свободного текста → `LLMBadContextJSONError: Extracting score from raw context ... failed`. 3b на русском этот формат не держит.
→ CPU-профиль boasi_s: `use_json=True` (дефолт), укороченные `evidence_summary_length="about 60 words"`, `answer_length="about 150 words"`, `agent_type="fake"` для быстрых путей.

**Ещё одна находка по параллелизму:** встроенный `fast` идёт с `max_concurrent_requests=5`; Ollama на CPU обслуживает запросы последовательно (`num_parallel=1`), поэтому 5 «параллельных» RCS-суммаризаций просто выстраиваются в очередь и запрос на `evidence` занял **7 мин 31 с**.
→ Для CPU: `answer.max_concurrent_requests = 1` (иначе растут таймауты без выигрыша по времени).

---

## 8. Рекомендации для Фаз 1–7

1. **Эмбеддинги:** `st-multi-qa-MiniLM-L6-cos-v1` локально; Ollama-эмбеддинги запретить в проде (feature flag).
2. **LLM:** дефолт `qwen2.5:3b` (8.6 ток/с). Для качества — `qwen2.5:7b-instruct` (3.9 ток/с) с удвоенным временем ответа. 14b — только при GPU.
3. **Профиль настроек:** свой `boasi_s` (на основе дефолта, `use_json=True`, короткие summary) вместо встроенного `fast` — он ломается на русском. `agent_type="fake"` для быстрых путей. `max_concurrent_requests=1` на CPU.
4. **Обязательные инварианты сервиса PaperQA:** фабрика `Settings` (legacy `model_list`, `timeout≥1800`), `use_doc_details=False`, `multimodal=OFF`, `chunk_chars=4000/overlap=200`, явный `citation` для каждого документа.
5. **Персистентность:** SQLite-дамп `Text`/`Doc` + `aadd_texts` при восстановлении.
6. **RAG fusion:** переиспользовать `PQASession` между `aget_evidence` и `aquery`.
7. **Инфраструктура:** замеры Фазы 0 сделаны на dev-машине (CPU, 8 ядер). Продакшн — GPU-машина с большим RAM: там ожидаемо 5–15× быстрее, плюс `evidence_k=10–15`, `max_concurrent_requests=4–8`. Разница только в конфиге — код общий (`PLAN.md` §1.1). В prod-модели обязательно заранее загружаются (`ollama pull`), а если ST-эмбеддинги используются — кэш HF-модели монтируется томом, т.к. интернета в контуре нет.

---

## 9. Артефакты

| Файл | Содержимое |
| --- | --- |
| `spikes/01_introspect.py` / `.json` | интроспекция API, все чек-листы из ТЗ |
| `spikes/02_e2e_ollama.py` / `02_result.json` | end-to-end: add/evidence/aquery/delete/clear |
| `spikes/03_persistence.py` / `.json` | персистентность, pickle, aadd_texts, delete, дедуп |
| `spikes/04_embed_bench.py` | бенчмарк Ollama-эмбеддингов (провал) |
| `spikes/05_st_embed_bench.py` / `.json` | бенчмарк sentence-transformers (успех) |
| `spikes/06_session_reuse_and_lang.py` / `.json` | переиспользование evidence, ловушка pre/post, skip_summary |
| `spikes/07_localization.py` / `.json` | локализация ответов + профиль `fast` |
| `spikes/fixtures/` | реальные фикстуры: PDF PaperQA2, русские заметки MD, CSV с данными |
| `.spike_pqa_home/` | PQA_HOME спайков (индексы paper-qa) |

Фикстуры переиспользуются в Фазе 2 как тестовые данные (`backend/tests/fixtures`).

## 10. Открытые вопросы для Фазы 1–2 (c учётом dev/prod-разделения)

1. **Dev-модель:** `dev` = `qwen2.5:3b`, `prod` = `qwen2.5:7b–14b` (per GPU). Принято ли это решение? (у нас это заложено в плане)
2. **Эмбеддинги в prod:** в prod на GPU использовать Ollama `nomic-embed-text` (GPU) или оставить ST как фолбэк?
3. **Office-документы:** ставим `paper-qa[office]` (docx/xlsx/pptx) сразу в Фазе 1?
4. **Docker prod:** `docker-compose.prod.yml` с GPU passthrough (для Ollama NVIDIA) делаем сразу или в Фазе 9?
5. **Промпты:** свой `boasi_s.json` в `~/.config/pqa/settings/` (prompts.system) — готовить сразу в Фазе 2?
6. **Агентный путь:** `agent_type="fake"` для dev, в prod допустим `ToolSelector` при 14b? Подтвердите режимы.