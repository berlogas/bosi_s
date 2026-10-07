# boasi_s — план агентной разработки

Локальная научная RAG-платформа: **PaperQA2 (`paper-qa`) + Ollama + FastAPI + Streamlit + Docker**.

Документ produced по результатам анализа `boasi_s. prompt.md` (требования) и `interface.md` (интерфейс-ТЗ к PaperQA2) + сверки с актуальным API `paper-qa`.

---

## 0. Сверка ТЗ с реальностью paper-qa (обязательно до старта кода)

Проверено по исходникам `main` и PyPI: **paper-qa `2026.8.12`**, `requires_python >= 3.11`, пакет импортируется как `paperqa`. С декабря 2025 — CalVer (`v2025.12.x`, далее `v2026.x`), гарантий обратной совместимости нет → **пиним версию в `requirements.lock`**.

Расхождения `interface.md` с фактическим API (их нужно учесть в обёртке):

| Ожидание в `interface.md` | Факт в paper-qa |
| --- | --- |
| `await docs.aadd(path)` → возвращает dockey | `aadd(path, citation=, docname=, dockey=, title=, doi=, authors=, settings=, llm_model=, embedding_model=) -> str \| None` возвращает **`docname`**; `dockey` по умолчанию = md5 содержимого файла |
| `docs.delete(dockey) -> bool` | `delete(name=None, docname=None, dockey=None) -> None`, **синхронный**, `name` deprecated; bool-результат строим сами |
| `session.references` — список | `PQASession.references: str`; список источников = `session.contexts[].text.doc` (`Doc.docname/dockey/citation/formatted_citation`) |
| `session.context` — list[dict] | `session.context: str` (склеенный текст), а список чанков — `session.contexts: list[Context]` (`Context.context`, `.text`, `.score`, `.question`, `.id`) |
| `answer_max_sources` через `settings.answer.answer_max_sources` | ✅ верно |
| `Docs.aadd_url` может отсутствовать | ✅ есть (async) |
| — | Есть **`Docs.aadd_file(file: BinaryIO, ...)`** — загрузка без временных файлов (важно для upload-эндпоинта) |
| — | Есть **`Docs.aadd_texts(texts, doc, settings, embedding_model)`** — восстановление индекса из внешнего БД без перечитывания PDF (ключ для персистентности сессий) |
| — | `docs.aget_evidence(session, ...)` — отдельный шаг retrieval+rerank, можно переиспользовать для RAG fusion |
| — | `agent_query() -> AnswerResponse` (aliased поле `answer: PQASession`, `bibtex`, `status`, `timing_info`, `stats`) |
| — | LLM-слой — пакет **`lmi`** (над `litellm`), не прямой `litellm` |
| — | Индексы/парсеры кэшируются в `PQA_HOME` (по умолчанию `~/.pqa`), имя индекса = хэш `Settings` |

**Ограничения окружения (обнаружено):** локальный `python` = 3.10 (paper-qa требует ≥3.11), но есть `py -3.11/3.13/3.14`. Ollama-клиент есть, сервер не запущен. `nvidia-smi` отсутствует → **инференс CPU-only**: для PaperQA2 (RCS требует много инструкций) 7–8B модели на CPU практически непригодны. Это влияет на выбор дефолтной модели и на объём RAG-пайплайна — решается в Фазе 0.

---

## 1. Целевая архитектура

```
docker compose
├── ollama        — LLM + embeddings (qwen2.5 / llama3.1, nomic-embed-text), volume с моделями
├── backend       — FastAPI + uvicorn: auth, RBAC, sessions, documents, projects, chat, RAG fusion
│                   тома: /data (PQA_HOME, sqlite, файлы сессий), доступ ТОЛЬКО локально
└── frontend      — Streamlit: login → dashboard → session workspace → admin panel
```

Ключевые подсистемы backend:

- `auth` — JWT,bcrypt, роли `admin` / `researcher`
- `store` — SQLite (WAL) + JSON-совместимость: `users`, `sessions`, `documents`, `projects`, `messages`, `audit`
- `papers` — реестр `Docs`-объектов: **одиin `Docs` на глобальную базу + один `Docs` на сессию**, ленивая реконструкция
- `rag` — fusion: `aget_evidence` по 2+ коллекциям → merge + rerank по приоритетам → генерация через `lmi`
- `workers` — индексация и тяжёлые запросы в фоне + heartbeat-таск

Индексы PaperQA держатся в памяти процесса (`NumpyVectorStore`) — отсюда решение: **индексы персистивны через `Docs.aadd_texts()` в SQLite (чанки+эмбеддинги)**, при старте сессии `Docs` собирается из БД за секунды, без повторного парсинга PDF.

---

## 1.1 Стратегия dev / prod: одна модель, разные машины

**Разработка** ведётся на слабой машине (8 CPU, без GPU) с моделью **`qwen2.5:3b`** — и это осознанный выбор: медленная генерация **не является проблемой**, а скорость работы **не оптимизируется**. В боевом режиме будет использоваться **намного более мощная модель** на машине с GPU и большим объёмом памяти.

Принципы:

1. **Модель — одна переменная конфигурации** `LLM_MODEL` (дефолт `ollama/qwen2.5:3b`). В коде нет ни одной константы, завязанной на скорость: замена на 14b/32b/70b в prod — только значение в `.env`, без правок кода.
2. **Никакой оптимизации производительности.** Не сокращаем `evidence_k`, не подбираем модели под скорость, не отказываемся от качественных промптов (RCS). Медленный ответ на dev — это норма, а не баг.
3. **Но и не «зависание».** Раз запрос занимает минуты, всё долгое уходит в фоновые задачи с прогрессом и статусом; UI не блокируется, запрос можно отменить. Это требование удобства, а не оптимизации.
4. **Таймауты и параллелизм — только ради корректности.** `timeout=3600` (иначе lmi-ретраи по 60 с), `answer.max_concurrent_requests=1` (Ollama на CPU обрабатывает запросы последовательно — параллелизм создаёт очередь и таймауты, но не выигрыш).
5. **Эмбеддинги — единственное место, где dev-профиль отличается по существу.** На dev — локальные sentence-transformers (`st-multi-qa-MiniLM-L6-cos-v1`): Ollama-эмбеддинги на CPU дают 10 мин на PDF и HTTP 400 на русском тексте. В prod на GPU можно оставить тот же ST (работает везде, без сети) — смена на Ollama-эмбеддинги лишь опциональна и делается конфигом, не кодом.
6. **Один код, одни тесты, один приёмочный сценарий** для обеих машин.

| Параметр | Разработка (CPU, 8 ядер) | Боевой режим (GPU + RAM) |
| --- | --- | --- |
| LLM | `ollama/qwen2.5:3b` (8.6 ток/с) | мощная модель (14b/32b/70b — по VRAM), меняется в `.env` |
| Эмбеддинги | `st-multi-qa-MiniLM-L6-cos-v1` (локально, без сети) | тот же ST (по умолчанию) либо Ollama-эмбеддинги на GPU — конфиг |
| `timeout` LLM | 3600 | 3600 (то же значение, безопасно) |
| `max_concurrent_requests` | 1 | 1 или больше — конфиг |
| `evidence_k` / `answer_max_sources` | 10 / 5 (качество, не скорость) | те же значения |
| Очередь задач | фоновые задачи + прогресс (медленно — ок) | то же + больше воркеров |
| Compose | `docker-compose.yml` | `docker-compose.prod.yml` (GPU passthrough, автозапуск) |

7. **Приватность (жёсткое требование ТЗ):** ни dev, ни prod не обращаются в интернет во время работы — `parsing.use_doc_details=False`, ключи Crossref/Semantic Scholar не используются, модели и кэш — в локальных volume, предзагружаются скриптом `make pull-models`.

**Что это меняет в фазах:**

- **Фаза 1** — `config.py` с `LLM_MODEL` и остальными параметрами в `.env` (без «профилей скорости»); `docker-compose.yml`.
- **Фаза 2** — фабрика `Settings`; бэкенд эмбеддингов выбирается конфигом, дефолт `st`.
- **Фаза 8 (UI)** — прогресс и статус долгих операций, возможность отмены, индикатор модели в подвале.
- **Фаза 9** — `docker-compose.prod.yml` с GPU passthrough, `make pull-models`, бэкапы.
- **Фаза 10** — приёмка на dev-машине (долго — ожидаемо); на prod машина заменяет только модель.

> Цифры Фазы 0 (8.6 ток/с, 1.5–6 мин на ответ) — нижняя граница. Улучшать их в рамках разработки не планируется.

---

## 2. Репозиторий

```
boasi_s/
├── docker-compose.yml
├── .env.example
├── Makefile
├── backend/
│   ├── Dockerfile, pyproject.toml, requirements.lock
│   ├── app/
│   │   ├── main.py, config.py, deps.py
│   │   ├── core/          # security, locks, errors, logging
│   │   ├── db/            # models, session, migrations, repositories
│   │   ├── schemas/       # pydantic DTO (API contract)
│   │   ├── services/      # paperqa_service.py, rag_fusion.py, sessions.py, projects.py, generation.py
│   │   ├── api/           # routers: auth, admin, sessions, documents, chat, projects, quick
│   │   └── workers/       # indexer.py, heartbeat.py, reaper.py (90 дней)
│   └── tests/
└── webapp/               # React-интерфейс (заменил frontend/, Streamlit удалён)
    ├── src/               # features: auth, sessions, documents, projects, chat, admin
    └── e2e/               # Playwright
```

---

## 3. Фазы агентной разработки

Каждая фаза = отдельный агент-исполнитель, вход/выход и DoD. Фазы 0–2 блокирующие, 8–10 распараллеливаемы после Фазы 5.

### Фаза 0 — Spike: проверка допущений (1–2 дня, агент-исследователь) ✅ **ВЫПОЛНЕНА 2026-10-01**
Результаты: `docs/SPICE_REPORT.md`, `spikes/*` (7 спайков, все артефакты — в `spikes/*.json`).
Ключевые выводы: локальные ST-эмбеддинги (PDF 25 стр. = 12 с) вместо Ollama (10 мин 42 с); CPU-ответ = 1.5–6 мин; канонический `LLMConfig{"models":[]}` теряется валидатором paperqa; `prompts.pre/post` — доп. вызовы LLM; локализация через `prompts.system` работает; персистентность через `aadd_texts` подтверждена.

---

### Фаза 1 — Фундамент backend (3–4 дня) ✅ **ВЫПОЛНЕНА 2026-10-01**
- `pyproject.toml` (Python 3.11), `requirements.lock` (pin `paper-qa`, `lmi`, `fastapi`, `uvicorn`, `sqlalchemy`, `alembic`, `pydantic-settings`, `passlib[bcrypt]`, `python-jose`/`pyjwt`, `python-multipart`, `pytest`, `httpx`).
- `config.py` (pydantic-settings): модели, `PQA_HOME`, пути, лимиты, TTL сессий.
- `db/`: модели (`users`, `sessions`, `documents`, `projects`, `messages`, `links`, `audit`), Alembic-миграции, WAL.
- `core/security.py`: хеширование паролей, JWT (access+refresh), `require_role("admin")`.
- `core/locks.py`: `asyncio.Lock` на `session_id`, `RWLock`-обёртка на global index.
- `app/main.py`: lifespan, health-check `/api/health`, CORS (только localhost), тома.
- Тесты: `pytest` на config, миграции, auth-логику.

**DoD:** `docker compose up backend` поднимается, `/api/health` = ok, миграции применяются, тесты зелёные.

---

### Фаза 2 — Обёртка `PaperQA2Service` (4–5 дней, ключевой агент) ✅ **ВЫПОЛНЕНА 2026-10-01**
Отчёт: `docs/PHASE2_REPORT.md`. Итог: 90 тестов (из них 2 интеграционных с живым Ollama), ruff чист.
Файл `app/services/paperqa_service.py` — **исправленный по факту API** вариант из `interface.md`.

```python
class PaperQA2Service:
    def __init__(self, settings: PQAProfile, collection: str) -> None: ...
    async def add_files(paths, category, project_id=None) -> list[DocumentRef]
    async def add_uploads(files: list[BinaryIO], category, ...) -> list[DocumentRef]   # через aadd_file
    async def add_url(url, category) -> DocumentRef
    async def delete_document(doc_id) -> bool        # сам возвращает bool
    async def list_documents() -> list[DocumentRef]
    async def get_evidence(query, k) -> list[ScoredChunk]   # aget_evidence, без генерации
    async def ask(query, mode, max_sources) -> AnswerResult
    async def persist_state() / restore_state()     # aadd_texts-реконструкция
    async def rebuild_index()                       # переиндексация
```

Обязательные детали:
- `dockey` = md5 содержимого (совпадает с поведением paper-qa), `docname` = человекочитаемое уникальное имя → `aadd(docname=..., citation=..., dockey=...)`; **реестр path→docname→dockey в БД**.
- `DocumentRef`: `id, dockey, docname, title, citation, path, url, category, project_id, status(pending|parsing|ready|error), error, size_bytes, pages, created_at`.
- `parsing.use_doc_details=False` в оффлайн-режиме (нет Semantic Scholar/Crossref), иначе — нестабильные задержки; DOI/авторы из CSV-манифеста (`Doc.to_csv`).
- `citation` для не-публикаций: `"<title> (загружено пользователем)"` — PaperQA не умеет цитировать код/таблицы сам.
- `.docx/.xlsx/.pptx` — через `pip install paper-qa[msoffice]` (проверить наличие в Фазе 0); иначе конвертация.
- Персистентность: после `aadd` дамп `docs.texts` (list[Text]) + `docs.docs` в SQLite (`session_chunks` BLOB/JSON) → `restore_state()` = чистый `Docs()` + `aadd_texts(texts, doc)`. Проверка: `aquery` даёт те же `Context.score`.
- Лок-стратегия: `write`-операции под `session lock`, `aget_evidence` без лока (RAG-модуль сам immutable).

Тесты (из `interface.md` §10, на tmp_path + txt/небольшие md, без сети, мок LLM):
`test_add_file`, `test_add_upload`, `test_delete_returns_bool`, `test_missing_file_raises`, `test_clear_docs`, `test_persist_restore_equivalence`, `test_ask_returns_citations_and_formatted_answer`, `test_aget_evidence_scores`.

**DoD:** тесты зелёные на моке; на реальном Ollama — 1 интеграционный тест; чанки переживают рестарт процесса.

**Инварианты, установленные Фазой 0** (обязательны в реализации):
* `embedding="st-multi-qa-MiniLM-L6-cos-v1"` (локально). Ollama-эмбеддинги запрещены (10 мин/PDF + 400 на русском >3.8k симв.).
* `llm_config` **только** в legacy-форме `{"model_list": [{"model_name", "litellm_params": {..., "timeout": 3600, "api_base": ...}}]}`; каноническая `{"models": [...]}` перезаписывается валидатором paperqa и теряет timeout/api_base.
* `parsing = {use_doc_details: False, multimodal: OFF, reader_config: {chunk_chars: 4000, overlap: 200}}`.
* `answer.max_concurrent_requests = 1` на CPU (Ollama последователен, параллелизм упирается в очередь).
* `prompts.system` = дефолт + правило русского языка (файл `boasi_s.json` в `~/.config/pqa/settings/`).
* `settings` передаётся **каждому** вызову `aadd`/`aquery`/`aget_evidence` — иначе уход в OpenAI по умолчанию.
* `aadd` может вернуть `None` (дедуп по `dockey`) — не ошибка; `delete()` возвращает `None` — bool строим сами.
* Персистентность: `pickle(Docs)` работает, но канонично — дамп `Text`+`Doc` в БД и `aadd_texts` (проверено: идентичные `Context.score` после восстановления, 7.3 с).
* Upload: `aadd_file(BinaryIO)` на Windows падает → писать свой temp-файл → `aadd(path)`.

---

### Фаза 3 — Auth + RBAC + аудит (3 дня) ✅ **ВЫПОЛНЕНА**
- `POST /api/auth/login|logout|refresh|me`, `POST /api/auth/register` — **только админ** создаёт пользователей (`/api/admin/users` CRUD + смена роли/пароля/блокировка).
- Роли: `admin` (глобальная база, управление пользователями, аудит, все сессии), `researcher` (только свои сессии).
- Middleware: авторизация по `session_id` + сверка владельца на каждом `/sessions/{id}/*`; запрет researcher → `/admin/*` (403).
- Аудит-лог: `actor, action, target_type, target_id, ip, ts, meta` — запись всех мутаций и всех запросов к глобальной базе.

**DoD:** негативные тесты (researcher не видит чужих сессий, не может стать админом), полный audit-трейл.

---

### Фаза 4 — Глобальная база знаний (3 дня) ✅ **ВЫПОЛНЕНА**
- `POST /api/admin/documents` — одиночная загрузка; `POST /api/admin/documents/bulk` — пачкой (ZIP/многострочный список путей), лимит 200 файлов, статусная очередь.
- Очередь индексации в фоне (FastAPI `BackgroundTasks`/araios), прогресс-эндпоинт `GET /api/admin/indexing/status`.
- `DELETE /api/admin/documents/{id}`, `POST /api/admin/reindex` (полная переиндексация, с локом глобального индекса).
- Поля документа: `visibility=global`, `category`, `tags`, `source`, `added_by`, `version`.
- Ограничения лимитов из ТЗ (для админа — отдельно, с настраиваемыми значениями).

**DoD:** админ загружает 5 PDF → `status=ready` у всех, поиск по базе находит ответ с цитатами; удаление действительно убирает документ из выдачи.

---

### Фаза 5 — Сессии: модель данных + персистентность (5–6 дней, самое важное) ✅ **ВЫПОЛНЕНА**
- Модель сессии: `id, user_id, title, status(active|paused|archived), active_project_id, last_activity_at, expires_at, last_action{type,label,at}, notes, created_at`.
- **TTL 90 дней**: `expires_at = last_activity_at + 90d`; heartbeat-таск каждые 5 минут пишет `last_activity_at` для активных сессий; `reaper` архивирует истёкшие (`archived`, read-only) и удаляет файлы по retention-политике (архив хранить N дней, затем purge — значение в `.env`).
- Автосохранение состояния: debounce-5мин снапшот `session_state` (активный проект, вкладка, позиция чата, черновики в редакторе) — «точка возврата».
- Лимиты: ≤10 сессий, ≤50 документов, ≤500 МБ, ≤5 проектов на сессию — валидация в сервисе с внятными 409-ошибками.
- Resume: `POST /api/sessions/{id}/resume` → реконструкция `Docs` из БД, отдача `last_action` и снапшота.
- Схема линков: `documents.categories` (project_draft / project_data / temp_literature / notes / supplementary), `document_links` (cites/supports/contradicts/uses), `tags`.

**DoD:** сценарий из ТЗ (понедельник→пятница→2 месяца→100 дней) проходит end-to-end; после рестарта контейнера сессия восстанавливается с документами, историей и заметками. ✅ Выполнено: `tests/test_phase5_scenario.py` (сквозной сценарий) + `tests/test_chat_history.py` (история), 175 тестов, ruff чист. Отчёт — `docs/PHASE5_REPORT.md`.

---

### Фаза 6 — RAG Fusion (5 дней) ✅ **ВЫПОЛНЕНА 2026-10-02**
- `POST /api/chat/query` c режимами `hybrid` (по умолчанию) / `project_focus` / `session_only` / `global_only`.
- **Обязательная оптимизация (подтверждена Фазой 0):** один `aget_evidence` на каждую коллекцию → слияние → **один** `aquery(PQASession)`. Повторный вызов `aquery(str)` удваивает время запроса (374 с против 118 с на CPU).
- Пайплайн: параллельный `aget_evidence` по коллекциям (глобальная Docs; сессионная Docs, разбитая по категориям) → нормализация → **merge + приоритетный rerank** (вес: проект 1.0 > project_data/draft 0.8 > temp_literature 0.6 > global 0.4; бонус за совпадение тега/категории; штраф за dedup) → top-k → генерация через `lmi` с явным контекстом и нумерацией источников.
- Разметка источников в ответе: `📚 <formatted_citation>` (глобальная) vs `📁 <title> (категория)` (сессионная); в JSON — `source_scope: global|session`, `category`, `doc_id`, `page`, `score`.
- `GET /api/chat/suggest-queries` — LLM предлагает 3–5 уточняющих вопроса.
- Быстрый режим без сессии: `POST /api/quick-query` → только глобальная база, отдельная история `quick_messages` (по пользователю), без создания сессии.
- Кэш ответов в `PQA_HOME` (paperqa сам индексирует ответы) + защита от повторных вопросов.

**DoD:** на тестовом наборе hybrid даёт источники обоих типов; `project_focus` ранжирует выше; приоритет детерминирован (юнит-тест merge/rerank). ✅ Выполнено: 46 тестов, отчёт — `docs/PHASE6_REPORT.md`. Отступление: сессия остаётся одной коллекцией, категория взвешивается на rerank (иначе 6 вызовов `aget_evidence` вместо двух).

---

### Фаза 7 — Проекты статей и генерация (6 дней) ✅ **ВЫПОЛНЕНА 2026-10-02**
- CRUD проектов: `title, target_journal, status(planning|drafting|reviewing|done), sections[{name, required, order, word_target, notes, content_md}]`.
- Привязка документов к проекту: роль `reference|data|draft`; авто-подстановка черновиков из `project_draft`.
- Генерация: literature review, разделы (Introduction/Methods/Results/Discussion/Conclusions) по плану проекта, **сравнение своих данных с литературой** (CSV/таблица → извлечение сводки → сопоставление с контекстом), отчёты (шаблон HELCOM: конфигурируемый markdown-template + секции), поиск пробелов в литературе, анализ черновика (недостающие цитаты, слабые аргументы) — контрактные тесты + кэш.
- Все генерации — с обязательными цитатами `[n]`; проверка: каждая цифра `[n]` разрешается в `context`.
- Экспорт: Markdown, DOCX (шаблон журнала), BibTeX, ZIP с вложенными `references/`.
- Версионирование черновиков (снапшот на генерацию + diff).

**DoD:** сгенерированный Discussion по реальной сессии содержит ссылки на `project_data` и на литературу; экспорт открывается в Word; анализ черновика находит ≥1 реальный пробел. ✅ Выполнено полностью: CRUD проектов, план разделов, привязка документов с ролью, генерация с контрактом цитат, literature review, сверка данных с литературой (сводка CSV считается программно), поиск пробелов, детерминированный анализ черновика, отчёт по шаблону, версионирование + diff, экспорт md/docx/zip/bibtex — 112 тестов. Отчёт — `docs/PHASE7_REPORT.md`.

---

### Фаза 8 — Frontend Streamlit (6–7 дней, можно параллельно с 6–7 после Фазы 5) ✅ **ВЫПОЛНЕНА 2026-10-02**
- `login`; `dashboard` (быстрый вопрос, карточки сессий с превью `last_action`, «Продолжить», «Новая сессия», индикатор срока жизни, статус архива).
- `session_workspace` — вкладки: Документы (загрузка с категорией, drag&drop, список по категориям, лимиты), Проекты статей (структура разделов, статус, привязки), Чат (режим поиска, индикация `📚/📁`, экспорт диалога), Заметки/точка возврата.
- `admin_panel`: пользователи, глобальная база (single/bulk), очередь индексации, переиндексация, аудит, все сессии.
- UX: индикаторы прогресса индексации и долгих запросов, статус фоновой задачи, кнопка «Отменить», кнопка «Пауза с заметкой». Долгие операции (минуты) не должны оставлять «висящий» спиннер — вместо этого статус задачи и возможность свернуться.
- Тесты: `streamlit.testing.v1.AppTest` на логин, на создание сессии, на загрузку файла.

**DoD:** весь сценарий ТЗ проходится кликами в UI; на 1366×768 без горизонтального скролла; запрос дольше минуты показывает прогресс и остаётся отменяемым. ✅ Выполнено: логин, дашборд, рабочее пространство (документы/проекты/чат/заметки), админ-панель; реестр фоновых задач с прогрессом и отменой, фоновые режимы чата и массовой индексации; 26 тестов (17 задач + 10 UI на AppTest). Не проверено: рендер на 1366×768 — нужен браузер. Отчёт — `docs/PHASE8_REPORT.md`.

---

### Фаза 9 — Docker, эксплуатация, качество (4 дня) ✅ **ВЫПОЛНЕНА 2026-10-02**
- `docker-compose.yml`: ollama (+`MODELS` pre-pull), backend, frontend; volumes; healthchecks; `depends_on: service_healthy`; лимит ресурсов; `PQA_HOME=/data/pqa` на volume.
- `.env.example`, `Makefile` (`up`, `down`, `logs`, `test`, `pull-models`, `reindex`).
- Бэкап: дамп SQLite + каталога `PQA_HOME` + скрипт `restore`.
- Логи/метрики: структурные логи, `GET /api/health` с состоянием Ollama и индексов, `/metrics` (опц. Prometheus).
- `docker-compose.prod.yml`: GPU passthrough для Ollama (NVIDIA), автозапуск, лимиты ресурсов — боевой режим на машине с GPU.
- Hardening: `SECRET_KEY` из `.env`, rate-limit на login, `max upload size`, валидация путей (нет выхода за пределы каталога сессии), `parsing.multimodal=OFF`.

**DoD:** `docker compose up` с нуля на чистой машине → работающая система; восстановление из бэкапа; корректная работа с двумя-тремя сессиями подряд (без требований к скорости). ✅ Код и скрипты готовы, 29 тестов hardening (388 всего), compose валиден. ⚠ НЕ проверено на живой машине: `docker compose up`, восстановление из бэкапа — Docker-демон в среде разработки недоступен. Отчёт — `docs/PHASE9_REPORT.md`.

---

### Фаза 10 — Приёмка по сценарию (2–3 дня)
- Скрипт `scripts/acceptance_scenario.md` — сценарий «Исследователь Иванов» по пунктам ТЗ, прогон с реальными артефактами (тестовый PDF, CSV с биомассой, 3 заметки).
- Регрессионный набор: `pytest` (юнит) + 6–10 e2e-сценариев (Playwright либо API-уровень).
- `docs/ADMIN_GUIDE.md` (админ), `docs/USER_GUIDE.md` (исследователь), `docs/OPERATIONS.md` (бэкап/восстановление/обновление моделей).
- Итог: `docs/SPICE_REPORT.md`, `docs/DECISIONS.md` (почему CPU-модель, почему CalVer-pin, почему JSON/SQLite), Known limitations.

**DoD:** сценарий проходит от первого логина до экспорта DOCX; все DoD предыдущих фаз подтверждены чек-листом.

---

## 4. Матрица агентов

| Агент | Фазы | Ключевой артефакт |
| --- | --- | --- |
| A0 Исследователь | 0 | `docs/SPICE_REPORT.md`, `spikes/*` |
| A1 Backend-каркас | 1, 3 | каркас, auth, аудит |
| A2 Интегратор PaperQA | 2 | `paperqa_service.py` + тесты |
| A3 Данные/сессии | 4, 5 | global KB, персистентность сессий |
| A4 RAG/генерация | 6, 7 | fusion, проекты статей, генерация |
| A5 Frontend | 8 | Streamlit UI |
| A6 DevOps/QA | 9, 10 | compose, бэкапы, приёмка |

Правила: контракты API (`schemas/`) фиксирует A1 в начале и не меняет без согласования; A2 и A4 могут идти параллельно после Фазы 2; A5 стартует после Фазы 5.

## 5. Риски и решения

| Риск | Решение |
| --- | --- |
| Медленный inference на dev-машине (CPU) | **Осознанно не оптимизуется** — разработка на `qwen2.5:3b`, скорость в бой не идёт. Важно только, чтобы UI не «зависал»: фоновые задачи, прогресс, отмена |
| 3B-модель не следует инструкциям PaperQA2 | Русскоязычные промпты в `prompts.system` (проверено), `agent={"agent_type":"fake"}` для быстрых путей, `verbosity` для диагностики. Качество на 3b может быть неточным — это ожидаемо, прод на сильной модели |
| CalVer ломает API между релизами | Pin `paper-qa==2026.8.12` в `requirements.lock`; CI-тест на `dir(Docs)` сверку |
| Нет интернета в контуре (метаданные Semantic Scholar/Crossref) | `parsing.use_doc_details=False`, manifest-CSV с DOI; фича-флаг `OFFLINE=1` |
| Потеря состояния `NumpyVectorStore` при рестарте | Персистентность через `aadd_texts` + периодический дамп чанков (Фаза 2/5) |
| **Потребление ресурсов на dev-машине** | Медленный ответ — норма, но следить за RAM: один `Docs` на сессию в памяти; кэш чанков в SQLite; фоновые задачи с ограничением одновременной индексации |
| «Живой» UI на долгих LLM-запросах | Async-эндпоинты + polling статуса задачи, `verbosity=1` |
| Утечка между сессиями | Строгая проверка владельца + физически раздельные каталоги файлов на сессию |

## 6. Порядок запуска агентов (первая итерация)

1. A0 (спайк) — блокирует всё.
2. A1 (каркас+auth) ∥ A2 (обёртка PaperQA).
3. A3 (global KB + сессии) → затем A5 (frontend).
4. A4 (fusion + генерация) ∥ A5.
5. A6 (docker/QA/приёмка).

Оценка: ~7 недель последовательной работы, ~4.5–5 недель при 3 параллельных агентах.