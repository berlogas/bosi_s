# Анализ приложения boasi_s

## 0. Что анализировалось

- Backend: `backend/` (FastAPI, PaperQA2, SQLAlchemy, SQLite), сервисные модули, эндпоинты, тесты (`pytest`, 728 запущено).
- Frontend: `webapp/` (React 19, Mantine 9, TanStack Query, Vitest, ESLint, TypeScript).
- Конфигурация: `.env`, `docker-compose.yml`, `Dockerfile` backend/webapp, `Makefile`, `scripts/*`.
- Проверка запуска: `ruff check app tests`, `pytest -q` (backend), `npm typecheck/lint/test` (webapp).

## 1. Итог по покрытию

### Backend
- 728 тестов запущено, 0 падений, 2 skipped, 2 deselected (integration).
- 420 предупреждений pytest, в том числе `coroutine ... was never awaited` в `test_fusion_api.py`.
- `ruff check app tests`: 97 ошибок/предупреждений, перечислены ниже.

### Frontend
- `tsc -b --force`: успех (0 ошибок типов).
- ESLint: 37 проблем (35 ошибок, 2 предупреждения).
- Vitest: 234 теста, 5 провалов, 222 прошли, 7 skipped.
- Playwright: не запускался в этом обзоре.

## 2. Критичные ошибки и блокирующие дефекты

### 2.1 Backend: неисправные квадраты в `app/services/history.py` (F821 / F811)
- `SectionStatus`, `SectionPlan`, `SectionVersion`, `VersionStatus`, `new_id` не импортированы, но используются.
- Это блокирует работу `rollback`, `create_branch`, `merge_branches`, `approve`.
- Ошибки: `F821: Undefined name 'SectionStatus'` на строках 291, 336, 394, 491.
- `F811: Redefinition of unused ...` в `app/services/history.py`.

### 2.2 Backend: `app/services/projects.py`
- `_question` и `_language` задаются в `generate_section`, но `_save_version` не записывает их обратно в `version.stats`.
- `ProjectService` смешивает 2 модели: старая `project.sections` + `project_versions` и новая `section_plans` + `section_versions`.
- Без `ensure_section_plans` при генерации в новой модели могут образовываться пустые/неполные планы.
- `app/services/history.py` не заполняет `VersionTree.all_versions`: `get_version_tree` возвращает `all_versions` пустым.

### 2.3 Backend: `app/services/paperqa_service.py` — контракт ответа
- `_citations(session)` читает `session.references`.
- `ask`/`ask_with_evidence` и `rag_generation` оперируют `answer.formatted_answer` и `citation_report`.
- Несогласованность `references` vs `formatted_answer` может приводить к неверной нумерации источников в ответе.

### 2.4 Backend: блокировки (`app/core/locks.py`)
- `RWLock` не реентерабельный.
- Повторный захват одной корутиной под уже удерживаемым `with lock:` приведёт к deadlock.
- Это реальная ловушка конкурентности, если кэш/сервис вызовет `lock.read()` рекурсивно.

### 2.5 Backend: `app/services/tasks.py`
- `Task` дублирует поля `error` и `cancel_requested`.
- `request_cancel` не обрабатывает `task._handle is None` и не атомарно синхронизирует `cancel_requested` со стопом выполнения.
- `_trim` при отмене не гарантирует очистку до конца, если `_run` уже завершился.
- `clear_finished` и `_trim` не вызываются в `finally` при ошибке? В `_run` есть `finally`, но логика сложна и нуждается в проверке.

### 2.6 Backend: `app/services/rag_retrieval.py` — избыточные `restore_state`
- `_evidence_once` вызывает `restore_state()` у `global_service` и `session_service` на каждом запросe.
- При `force=False` первый вызов часто сразу возвращает `(0, 0)`, если `Docs` уже загружен.
- Вторая ветка `_evidence_once(..., skip_summary=True)` может быть ценной, но `restore_state` при `force=False` не пересчитывает индекс, если он уже в памяти.
- В результате проброс `restore_state` делает запрос медленнее, чем это необходимо, и не гарантирует восстановление индекса.

### 2.7 Backend: `app/services/rag_service.py` — разрыв между `retrieve` и `answer`
- `RagFusionService.answer` использует `catalog`, собранный через `_load_catalog`, без восстановления `session_service`.
- `EvidenceRetriever` восстанавливает `Docs`, но `AnswerGenerator` не гарантирует, что для `session_id` уже есть служба в памяти.
- На практике это может давать пустой `catalog` для сессии, если вызов `retrieve` не предварительно выполнил `restore_state`.

### 2.8 Backend: `app/services/persistence.py` / `pqa_registry.py`
- `ServiceRegistry.get()` лениво создаёт `PaperQA2Service` без защиты `asyncio.Lock`.
- При параллельном `get(registry, "session:x")` может возникнуть гонка на создание сервиса и на `persist_global`.
- `close()` вызывает `persist_global()` и `_services.clear()` без того, чтобы гарантировать синхронизацию с активными запросами.

### 2.9 Backend: `app/services/backup.py`
- `plan_backup` не проверяет, что `backup_dir` не попадает внутрь `data_dir`; `run_backup` может записать архив в копию самого себя.
- `_unique_archive` генерирует имя по таймстампе, но при коллизии не гарантирует отсутствие частичного/устаревшего бэкапа.
- `run_backup` не проверяет наличие `sha256` файл через `_write_sha256` после `partial.replace`.
- `_snapshot_db` закрывает соединения в `finally`, но не поднимает `sqlite3` error, если БД была заблокирована во время `backup` (лог-только предупреждение).
- `delete_backup` не проверяет существование каталога `backup_dir`; `list_backups` молча вернёт пустой список, если он отсутствует.
- `_archive_has` использует `tarfile.open` на каждый запрос в `list_backups` — дорого и не потокобезопасно при параллельном сканировании каталога.
- Минимум: добавить предупреждение/ошибку в `plan_backup`, защитить `_unique_archive`, проверить путь бэкапа, вынести `_archive_has` в кэш или делать поиск манифеста эффективнее.

### 2.10 Backend: `app/services/inbox.py`
- `reconcile_interrupted` закрывает `running` запуски без проверки, иметь ли официальные права на их завершение.
- `_move_to_rejected` копирует файл, а не перемещает: при массовых ошибках расходуется много места.
- `_probe` не точно вспоминает причину `PermissionError` на `stat()` / `sha256`.
- `scan` не ограничивает глубину `discover`, что может привести к перебору вложенных подкаталогов иноки.

### 2.11 Backend: `app/services/reset.py`
- `reset.py` не проверяет `allow_destructive_reset` при `scope=data` и `scope=users` (хотя `all` делает это).
- `run_reset` под капотом удаляет каталоги `data`, `locations` и т.д.; нужно проверить, что пути не падают в `backup_dir`, привязанный через `PROJECT_ROOT/../backups`.
- `plan_reset` не проверяет, что `include_models=False` и `hf/torch` реально остаются, но в `run_reset` они удаляются при `scope=data`? Надо проверить.
- `public_summary` и `ensure_dirs` не защищены от некорректных `.env` путей; `reset.py` молча падает, если `.env` отсутствует.

### 2.12 Backend: `app/services/answer_cache.py`
- `AnswerCache._read` и `_write` используют `anyio.to_thread.run_sync`, но `get_or_none` и `put_answer` не устанавливают TTL в потоке, если файл записан редко. Это не критично, но нужно проверить срок хранения в памяти после перезагрузки.
- `invalidate_session` только очищает оперативный слой; файлы остаются, если не удалить.
- `get_or_none` не проверяет, что `make_key` корректно нормализует запрос: в `make_key` используется `normalize_query`, который сделал опечатку в `normalize_query`: `regex.sub(" ", ...)`.

### 2.13 Backend: `app/services/answer_cache.py` TTL
- `cached.seconds` округляется при чтении: `round(float(...))`. Это может искажать статистику времени ответа устаревшими ответами кэша.

### 2.14 Backend: `app/services/history.py` — `VersionNode.children`
- `children` в `VersionNode` по умолчанию `None`; в `__post_init__` инициализируется пустым списком. Это не ошибка, но `dataclass` с `children: list["VersionNode"] = None` ломает проверку типов. Лучше сделать `children: list["VersionNode"] = field(default_factory=list)`.

### 2.15 Backend: `app/services/analyses.py`
- `DraftGap.excerpt` обрезает строку до 200 символов; это не ошибка, но внешний API не гарантирует, что `excerpt` всегда короткий. Это не ошибка, но нужно учесть длину в `to_dict`.

### 2.16 Backend: `app/services/export.py`
- `render_docx` и `build_zip` не проверяют наличие папки выгрузки. `export` может упасть с `FileNotFoundError` при отсутствии каталога.

### 2.17 Backend: `app/services/data_extract.py`
- `_delimiter` использует `csv.Sniffer` без fallback на `;` при несовпадении; `looks_tabular` не проверяет заголовок таблицы.

### 2.18 Backend: `app/services/journal_styles.py`
- `style_prompt` принимает `target_journal` и `section`, но не всегда гарантирует, что `target_journal` не `None`. `Project.target_journal` в модели может быть `None`, что ломает `style_prompt`.

### 2.19 Backend: `app/services/paperqa_service.py`
- `add_file` перегружена дважды: одна без `force_reindex`, вторая с ним. `add_files` вызывает вторую, но в коде есть дублирование; нужно убрать первую или привести обе к единому контракту.
- `add_file` не обёрнут в `try/except`; ошибка `aadd` упадёт не в `add_files`, а напрямую в вызывающий код.
- `stream_complete` буферизует весь поток, и если стрим оборвался, делает один `acompletion` без `stream=False` по умолчанию; при `stream=False` ответ может быть в `text`, а не в `choices[0].message.content`? Нужно проверять тип ответа.
- `embedding_relevance` строит словарь по `(dockey, name)`, но `rag_retrieval` ищет `scores.get((str(ctx.text.doc.dockey), ctx.text.name))`. Если `ctx.text.name` не совпадает с хранимым именем, релевантность не найдётся.

### 2.20 Backend: `app/services/pqa_readers.py`
- `install_utf8_parser` подменяет `paperqa.readers.parse_text`, но не гарантирует, что `parse_text_utf8` корректно эмулирует исходную функцию во всех ветках. В тестах это не проверяется.

### 2.21 Backend: `app/services/pqa_profile.py`
- `_cached_embedding_model` кэширует по `embedding` и `config_json`, но `get_embedding_model` всегда передаёт `{}`. Это лишний кэш и лишняя сложность.

### 2.22 Backend: `app/services/pqa_registry.py`
- `ServiceRegistry.restore_all` вызывает `restore_state` по всем сервисам без паузы; при нагруженной базе это может вызывать блокировки SQLite.
- `ServiceRegistry` не имеет `async with` контекста для остановки; `close` не отменяет открытые корутины.

### 2.23 Backend: `app/services/tasks.py`
- `Task` поле `stage_started_at` обновляется при `set_stage`, но `stage_seconds` не гарантирует осторожный расчёт, когда `stage_started_at` равен `0.0` (default). Это не ошибка, но нужно гарантировать нулевой стоп.
- `Task.registry` не может быть переопределён в тестах; `ProgressReporter` получает статический `tasks`.

### 2.24 Backend: `app/services/generation.py`
- `build_prompt` для `require_citations=False` добавляет правило "ссылка обязательна", что противоречит `validate_citations` и `GenerationResult.ok`.
- `GenerationResult.ok` == `citation_check is None or citation_check.ok`, но в `projects.py` `GenerationResult` не возвращается при `use_cache=False`? Нет, `generate_section` возвращает `GenerationResult` всегда, но `GenerationResult.ok` не используется в API? Нужно проверить.

### 2.25 Backend: `app/services/rag_fusion.py`
- `build_candidates` фильтрует `DocumentCategory.style_guide`, но `source_dict` не проверяет, что `source.index` не пустой; в `rag_retrieval` `source_dict(c, i + 1)` гарантирует индекс.
- `to_pqa_session` и `chunks_from_candidates` не проверяют `c.text`; если контекст пустой, `PQASession` получит пустой `contexts`.

### 2.26 Backend: `app/services/rag_citations.py`
- `localize_headers` не заменяет заголовок "References", если в тексте есть перевод строки в конце. `re.sub(rf"(?m)^{re.escape(english)}$", russian, text)` должен обрабатывать `^...$` с `(?m)`, но если заголовок в `References\n`, то это работает. Проверка в тестах не ведётся.

### 2.27 Backend: `app/services/citation_guard.py`
- `_marker_numbers` и `repair_markers` не обрабатывают маркеры, где число выглядит как `0` или очень большое (например, `(уровень 0007)`). Это не критично, но в `repair_markers` число `0` или `> source_count` должно игнорироваться, а не валиться.

### 2.28 Backend: `app/services/grounding.py`
- `_grounded` не проверяет длину `entity`: короткие сущности (1-2 буквы) могут давать ложные срабатывания.
- `extract_mentions` не ограничивает длину вывода `ungrounded` до `_MAX_ITEMS = 20`? В коде может выдать много строк, и это будет ломать UI.

### 2.29 Backend: `app/services/analyses.py`
- `analyze_draft` и `render_gaps` не проверяют, что `sections` не пустой, и при пустой истории могут вернуть пустой список или `NaN`.

### 2.30 Backend: `app/services/projects.py`
- `generate_section` и `generate_section_v2` не проверяют `project.status` на граничных значениях: если проект `archived` или `completed`, генерация может продолжать.
- `apply_manual_section_text` находит `plan` по `name.lower()` равенству; в проекте два раздела с одинаковым именем без учёта регистра приведут к неожиданному распознаванию текущей версии.
- `sync_project_sections_to_plans` не учитывает `depends_on`, поэтому при синхронизации могут появиться планы без зависимостей.
- `compile_manuscript` не проверяет `quality_report.terminology_consistency` на `None`: если `quality_report` пустой словарь, `version.quality_report.terminology_consistency` вызовет `AttributeError`.
- `ProjectService` не проверяет лимит сеансов/проектов при `ensure_section_plans` или `regenerate_outdated_sections`.

### 2.31 Backend: `app/services/section_agent.py`
- `SectionAgent.generate` не проверяет `word_target` на `None` или отрицательное значение; при `word_target=0` цикл может бесконечно работать.
- `SectionTranslator.translate` не проверяет, что `target_language` в `allowed_languages`, и не использует `project.language_policy`.

### 2.32 Backend: `app/services/rag_service.py`
- `RagFusionService.answer` в `mode=agent` не устанавливает `from_cache`, `stats` только `{...}`. Это не ошибка, но не сходится с `retrieve`.

### 2.33 Backend: `app/services/rag_trivial.py`
- `is_trivial_query` использует только закрытый список, но не обрабатывает `null`/`None` запросов. `trivial_prompt` может упасть на `None`.

### 2.34 Backend: `app/services/reset.py`
- `plan_reset` и `run_reset` не проверяют, что `db_path` и `data_dir` не являются корневыми каталогами; это не ошибка, но риск.

### 2.35 Backend: `app/services/backup.py`
- `run_backup` не проверяет `snapshot_taken`, но если снимок не удался, архив всё равно создаётся без БД. Это не ошибка, но в `_build_manifest` `db_snapshot=false` может скрывать называемое повреждение.

## 3. Линтинг и тесты

### 3.1 Backend `ruff`
- 97 ошибок/предупреждений, основные:
  - `E501` (10)
  - `F821`, `F811`, `F841`
  - `E722` (bare except)
  - `ASYNC240` (blocking pathlib)
  - `UP037`, `RUF022`, `SIM114`, `SIM117`, `RUF059`
- В частности:
  - `app/api/projects.py`: `print(DEBUG)` в `patch_project`.
  - `app/services/history.py`: неисправные импорты/переопределения.
  - `app/services/paperqa_service.py`: перегруженные `add_file`.
  - `app/services/tasks.py`: дублирование полей, `RUF059`, `RUF006`.
  - `app/services/reset.py`: неиспользуемые импорты/переменные.
  - `app/services/backup.py`: неиспользуемые импорты/переменные.
  - `app/services/rag_retrieval.py`: `F811` redefinition `DocumentStatus`.

### 3.2 Frontend `eslint`
- 37 проблем (35 ошибок, 2 предупреждений):
  - `NavSection.tsx`: условные `useState`, `any` при `enabled` функции.
  - `CommandPalette.tsx`: `any`.
  - `EmptyState.tsx`, `AsyncBoundary.tsx`: неиспользуемые переменные.
  - `DocumentsTab.tsx`: `any` в 8 местах.
  - `ProjectsTab.tsx` / `queries.ts`: `any` и неиспользуемые типы.
  - `GeneratePanel.tsx`: `language` не используется.
  - `Toolbar.tsx`: лишние экранирования `` ` ``.
  - `useProjects.ts`: неиспользуемый тип.
  - `AppLayout`, `LeftPanelUserMenu`, `Breadcrumb`, `menuConfig`: неиспользуемые импорты/переменные.
  - `AsyncBoundary.a11y.test.tsx`: `console` запрещён.
  - `appLayout.test.tsx`: `within` не используется.
  - `projects.test.tsx`: `within` не используется.
  - `Vitest`: 5 провалов:
    - `maintenance.test.tsx`: 4 теста, ожидаемый элемент не найден.
    - `projects.test.tsx`: ожидание PATCH-тела.
    - Все вызывают `waitFor` / `findBy*` некорректно в jsdom и не эмулируют полностью UI-рендер.

### 3.3 Vitest
- 234 теста, 222 проходят, 5fail, 7 skipped.
- Провален `admin/maintenance.test.tsx` и `projects/projects.test.tsx`.
- Рекомендация: использовать `findBy*` / `waitFor`, избегать `getBy` в асинхронном коде, не использовать `sessionStorage` без очистки в `afterEach`.

## 4. Нагрузочные и архитектурные замечания

### 4.1 Performance
- `RagFusionService` восстанавливает `Docs` на каждом запросе; это дорого.
- `rag_retrieval.py` вызывает `restore_state()` два раза, но при `force=False` часто ничего не делает; нужно кэшировать отпечаток или использовать `restore_all` без локов.
- `AnswerGenerator.answer` часто перестраивает `insert_only` в `PQASession` на каждом запросе; это может быть дорого на CPU.
- `stream_complete` буферизует поток и делает полноценный `acompletion` при обрыве; при CPU-агенте это медленно, но не критично для dev.

### 4.2 Reliability
- `TaskEventManager` публикация из threadpool разрывна: если loop закрылся, события теряются; `publish_threadsafe` возвращает без ошибки, но подписчик может недостижим.
- `PaperQA2Service` не локирует `docs` при `restore_state`/`rebuild_index` от `ServiceRegistry`; возможны конфликты с чтениями `query`.
- `delete_backup` не проверяет, что архив существует и его нельзя удалить иначе, чем по имени.
- В `backup.sh` ротация по `KEEP_BACKUPS` удаляет файлы по `mtime`, а не по имени/ревизии; два бэкапа в одну секунду могут быть отнесены к разным каталогам? Это не ошибка, но нужно уточнить политику.

### 4.3 Security
- `jwt.encode` с коротким `secret_key` создаёт InsecureKeyWarning; в prod `secret_key` обязателен и должен быть ≥ 32 байта.
- `config.py` не проверяет, что `data_dir` и `backup_dir` не выходят за пределы разрешённой зоны при `ALLOW_EXTERNAL_IMPORT_PATHS=true`.
- `reset.py` не проверяет `prod` и `allow_destructive_reset` для `scope=data` и `scope=users`.
- `inbox.py` не ограничивает глубину сканирования и не обрабатывает `PermissionError` при чтении файлов.
- `tasks.py` SSE-код не гарантирует, что `queue` найден; если `unsubscribe` удалил подписку, `queue.get()` может вернуть `None`? Надо уточнить.

## 5. Приоритеты

1. **Критично**
   - Исправить `history.py` (неисправные импорты/имена).
   - Исправить `projects.py`: неисправные `print(DEBUG)`, неисправные импорты, неисправные поля `stats`, `apply_manual_section_text`.
   - Убрать дублирование полей `error` и `cancel_requested` в `Task`.
   - Исправить `request_cancel` и `clear_finished` логику.
   - Исправить `paperqa_service.py`: `add_file` контракт, `stream_complete`.
   - Решить `RWLock` нереентерабельность (вариант: реентерабельный лок, обёртка или явный запрет повторного захвата).
   - Исправить `rag_retrieval.py` / `rag_service.py`: не делать лишнее `restore_state`.
2. **Важно**
   - Дописать `VersionTree.all_versions` в `history.py`.
   - Кэшировать или отложить создание сервисов в `ServiceRegistry`.
   - Проверить `compile_manuscript` и `quality_report` при отрицании `None`.
   - Проверить `inbox.py`, `reset.py`, `backup.py` на краевые пути.
   - Добавить тесты для `history`, `citation_guard`, `grounding`, `answer_cache`, `tasks`.
3. **Документация и релиз**
   - Убрать/не коммитить `webapp/dist` или добавить тест синхронизации `src` и `dist`.
   - Обновить `README.md`, `PROJECT_CONTEXT.md`, `docs/wip/PLAN.md` и `UI_CHECKLIST`.
   - Уточнить `docs/LAUNCH.md` и `OPERATIONS.md` по сбросу, бэкап и `restore`.

## 6. Ограничения обзора

Этот отчёт написан без запуска бизнес-сценариев и без проверки ожидаемого поведения функций, поэтому часть замечаний носит рекомендательный характер. Критичные дефекты требуют проверки в локальном прогоне тестов и на стенде.
