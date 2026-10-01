# Фаза 2 — обёртка `PaperQA2Service`: отчёт

**Дата:** 2026-10-01 · **Статус:** ✅ выполнена

## Что сделано

| Файл | Назначение |
| --- | --- |
| `backend/app/services/pqa_profile.py` | Сборка `paperqa.Settings` из конфигурации — все инварианты Фазы 0 в одном месте |
| `backend/app/services/types.py` | DTO: `DocumentRef`, `ScoredChunk`, `AnswerResult`, `DocumentBatchResult`, разметка 📚/📁 |
| `backend/app/services/chunk_store.py` | Персистентность чанков в SQLite (zlib+JSON, не pickle): `SqliteChunkStore`, `MemoryChunkStore` |
| `backend/app/services/paperqa_service.py` | `PaperQA2Service` + `ServiceRegistry` (по экземпляру `Docs` на коллекцию) |
| `backend/app/db/models.py` + миграция `605775f630d8` | Таблица `document_chunks` — состояние PaperQA |
| `backend/app/main.py` | lifespan восстанавливает и сохраняет состояние PaperQA |
| Тесты | 28 сервисных + 11 персистентностных + 2 интеграционных |

## Публичный API

```python
service = get_registry().global_service()          # или .session_service(session_id)

await service.add_files([...])          -> DocumentBatchResult(added, duplicates, failed)
await service.add_file(path)            -> DocumentRef | None      # None = дедуп по dockey
await service.add_uploads(upload_files) -> DocumentBatchResult
await service.add_url(url)              -> DocumentRef
await service.delete_document(dockey=|path=|docname=) -> bool
await service.clear_documents()         -> int
service.list_documents()                -> list[DocumentRef]      # из памяти Docs
await service.documents_on_disk()       -> list[DocumentRef]      # из БД (до restore_state)
await service.get_evidence(q, k)        -> (list[ScoredChunk], PQASession)
await service.search(q, limit)          -> list[ScoredChunk]
await service.ask(q | PQASession, ...)  -> AnswerResult
await service.ask_with_evidence(q, k)   -> AnswerResult           # RAG-fusion
await service.persist_state()           -> int
await service.restore_state(force=False)-> int
await service.rebuild_index()           -> {documents, chunks, seconds}
await service.stats()                   -> dict
```

## DoD Фазы 2 — выполнены

- ✅ Тесты на моке зелёные: **90 passed** (`pytest -q`), без сети и без Ollama
- ✅ Интеграционный тест с **реальным Ollama**: `2 passed in 273.63s` (`pytest -m integration`)
- ✅ Чанки переживают рестарт процесса: проверено в тестах и вживую в контейнере (том `/data`)
- ✅ Ruff: `All checks passed!`

## Ключевые решения

1. **`llm_config` только в legacy-форме.** Сборка в `pqa_profile.build_llm_config()`; тест `test_settings_keep_phase0_invariants` фиксирует `timeout=3600` и `api_base`, чтобы регрессия не проскочила.
2. **Переопределение раздела — слияние, а не замена.** `build_pqa_settings(..., answer={"evidence_k": 2})` не теряет `max_concurrent_requests` (иначе тихо уехали бы 10 параллельных запросов в прод на GPU-машине).
3. **Персистентность — `Text` + `Doc` с эмбеддингами** в `document_chunks` (zlib+JSON). `restore_state()` = чистый `Docs()` + `aadd_texts`; эмбеддинги из БД переиспользуются (`aadd_texts` пропускает модель, если `texts[0].embedding` задан), поэтому рестарт не платит за переэмбеддинг.
4. **`restore_state(force=False)`** — повторный вызов из API не перетирает живое состояние в памяти.
5. **LLM вызывается только для evidence/ответа.** `Docs.aadd` идёт в LLM только если не передан `citation` — сервис всегда формирует citation сам (`"<название> (загружено пользователем)"`), поэтому индексация полностью офлайн и дешёвая.
6. **Загрузки пишем сами во временный файл** (`Docs.aadd_file` падает на Windows). Файлы не удаляются после `aadd`: они остаются путями документов.
7. **Блокировки по назначению:** запись (`add/delete/clear/rebuild/persist`) — под session-lock, чтение (`aget_evidence`/`aquery`) — под read-lock глобального индекса, поэтому параллельные запросы не блокируют друг друга.
8. **Файловые операции вынесены в `anyio.to_thread`**, чтобы медленный диск не вставал в event loop.
9. **Частичный успех разрешён:** `add_files`/`add_uploads` возвращают разбор `added / duplicates / failed` — один плохой файл не роняет загрузку пачки.
10. **`url` добавляется скачиванием файла ourselves** (`aadd_url` не проверяет размер/тип и требует сеть).

## Найденные и исправленные грабли

| Грабля | Решение |
| --- | --- |
| `aget_evidence()` принимает `summary_llm_model`, а не `llm_model` — заглушка не подхватывалась | раздельные `_llm_kwargs()` / `_summary_llm_kwargs()` / `_query_kwargs()`; `aquery` получает обе модели (он сам вызывает `aget_evidence`) |
| `aquery` при `llm_model=None` уходил в litellm с моделью `stub/model` → `LLM Provider NOT provided` | явная передача обеих моделей в `aquery` |
| `LLMResult` требует поле `model` — заглушка падала с ValidationError | `LLMResult(text=..., model=self.name)` |
| `has_successful_answer` — три состояния (`True/False/None`), а не bool | проброшено как есть + комментарий в DTO |
| `PQASession.references` — **строка**, а не список (документация обещает список) | `_citations()` режет по строкам |
| Переопределение `answer=` затирало весь раздел Settings | глубокое слияние подразделов в `_merge()` |
| Лок-инвариант «restore_state дважды» оказался неверным: каждый вызов создавал новый `Docs()` | `force=False` — не трогать уже загруженную коллекцию |
| `pip freeze` на Windows → pywin32 в образе; ruff-конфиг конфликтовал с массой `# noqa` | Linux-lock (сделан в Фазе 1), `per-file-ignores` для тестов |

## Проверено вживую

```
# Docker: индекс → персистентность → восстановление → удаление
добавлен: biomass | чанков: 1 | dockey: 35e7c4df96
в БД документов: 1
восстановлено: 1 | в памяти: 1
удалён: True

# интеграция с реальной моделью (qwen2.5:3b, русский вопрос по Баренцеву морю)
2 passed in 273.63s
```

## Производительность (dev-машина, 3b на CPU)

Ожидаемо медленно — скорость не оптимизируем по условию задачи. Замеры интеграционного прогона: `add` md/CSV — секунды (эмбеддинги локальные), `aget_evidence` + `aquery(PQASession)` ≈ 2 мин суммарно на тест.

## Дальше: Фаза 3 — Auth + RBAC + аудит

* `/api/admin/users` (создание только админом, смена роли/пароля, блокировка), регистрация закрыта;
* проверка владельца на каждом `/sessions/{id}/*`;
* аудит всех мутаций и обращений к глобальной базе;
* `make create-admin` — создание первого администратора из CLI.