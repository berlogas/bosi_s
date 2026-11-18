# Публичное API PaperQA2Service

Список всех публичных методов `PaperQA2Service` (`app/services/paperqa_service.py`) с сигнатурами, входом, выходом и возможными ошибками.

## Добавление документов

### `add_file(path, category, project_id, session_id, citation, title, force_reindex) -> DocumentRef \| None`

Добавить один файл в коллекцию.

- **Вход:** путь к файлу, опциональные метаданные, флаг принудительной переиндексации
- **Выход:** `DocumentRef` или `None` (если документ с таким dockey уже есть и `force_reindex=False`)
- **Ошибки:** `FileNotFoundError`, `DocumentProcessingError`

### `add_files(paths, ...) -> DocumentBatchResult`

Добавить несколько файлов. Результат содержит списки `added`, `duplicates`, `failed`.

### `add_uploads(files, ...) -> DocumentBatchResult`

Добавить загруженные через HTTP файлы (`UploadFile`). Запись во временный файл делается на стороне boasi_s (обход `PermissionError` на Windows).

### `add_url(url, ...) -> DocumentRef`

Добавить документ по URL. В автономном контуре файл качается boasi_s сам.

## Управление документами

### `delete_document(dockey\|path\|docname) -> bool`

Удалить документ. Возвращает `True` если удалён.

### `clear_documents() -> int`

Полная очистка коллекции. Возвращает количество удалённых документов.

### `list_documents() -> list[DocumentRef]`

Документы, известные в памяти (`Docs.docs`).

### `documents_on_disk() -> list[DocumentRef]`

Реестр из БД — работает до `restore_state()`.

## Поиск и ответ

### `get_evidence(query, k, doc_filter, skip_summary) -> (list[ScoredChunk], PQASession)`

Найти контекст без генерации ответа. Возвращает чанки и сессию для переиспользования в `ask()`.

### `search(query, limit) -> list[ScoredChunk]`

Поиск фрагментов без генерации (обёртка над `get_evidence`).

### `ask(query\|PQASession, mode, max_sources, evidence, settings) -> AnswerResult`

Ответить на вопрос. Принимает `PQASession` для переиспользования контекста (не искать контекст второй раз).

### `ask_with_evidence(query, k, mode, max_sources) -> AnswerResult`

RAG-fusion: сначала контекст (`get_evidence`), затем ответ по нему без повторного поиска.

### `agent_ask(query, mode, max_sources, settings) -> AnswerResult`

Ответ через PaperQA-агент (`agent_query`). Агент сам выбирает инструменты: поиск, сбор доказательств, генерацию.

## Персистентность

### `persist_state() -> int`

Сохранить состояние `Docs` в хранилище. Возвращает число документов.

### `restore_state(force=False) -> (int, int)`

Восстановить `Docs` из хранилища. Возвращает `(восстановлено, устарело)`.

### `rebuild_index(drop_embeddings=True) -> dict`

Полная переиндексация. Возвращает `{"documents", "chunks", "seconds"}`.

## Вспомогательное

### `make_citation(path, title) -> str`

Цитата для пользовательского файла.

### `unique_docname(base) -> str`

Уникальное имя документа внутри коллекции.

### `storage_dir(session_id, kind) -> Path`

Каталог хранения файлов.

### `complete(prompt, name) -> str`

Один вызов LLM.

### `stream_complete(prompt, name) -> AsyncIterator[str]`

Потоковый вызов LLM (SSE).

### `embedding_relevance(question, contexts) -> dict`

Косинусное сходство вопроса к контекстам.

## AnswerResult

| Поле | Описание |
|------|----------|
| `question` | Вопрос |
| `answer` | Ответ LLM |
| `formatted_answer` | Отформатированный ответ |
| `citations` | Список цитат |
| `context` | Контекстные фрагменты |
| `evidence` | Список scored chunks |
| `has_successful_answer` | Был ли успешный ответ |
| `cost` | Стоимость запроса |
| `token_counts` | Количество токенов |
| `mode` | Режим (hybrid / agent / ...) |
| `seconds` | Время ответа (целие число) |
| `used_context` | Переиспользован ли контекст |
| `agent_status` | Статус агента (для `agent_ask`) |

## Примеры вызовов

### Простой вопрос (базовый RAG)
```python
service = PaperQA2Service(settings=app, collection="global", chunk_store=store, llm_model=stub_llm)
result = await service.ask("Что сказано в документе про хлорофилл-а?")
print(result.formatted_answer)
print(result.citations)
```

### Вопрос через агент (глубокий анализ)
```python
result = await service.agent_ask("Сравните данные по биомассе из всех документов")
print(result.formatted_answer)
print(result.agent_status)
```

### Переиндексация после смены настроек
```python
result = await service.rebuild_index(drop_embeddings=True)
print(f"Переиндексировано документов: {result['documents']}, чанков: {result['chunks']}")
```

### Отчёт о цитировании (API)
```bash
curl http://127.0.0.1:8000/api/pqa/citation-report
```
