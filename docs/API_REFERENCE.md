# API Reference

Докуссыяет публичные эндпоинты бэкенда boasi_s. Авторизация требуется для большинства эндпоинтов, за исключением健康-проверки и некоторых административных операций.

## Базовая информация

- **Базовый URL:** `http://127.0.0.1:8000`
- **Схема авторизации:** JWT-токены через `POST /api/auth/login`
- **Формат ответов:** JSON

## Эндпоинты аутентификации

### `POST /api/auth/login`

Вход в систему.

**Request:**
```json
{
  "username": "admin",
  "password": "admin123"
}
```

**Response:**
```json
{
  "tokens": {
    "access_token": "jwt-token",
    "refresh_token": "refresh-token",
    "expires_in": 1800
  },
  "user": {
    "id": "uuid",
    "username": "admin",
    "role": "admin",
    "is_active": true
  }
}
```

### `POST /api/auth/refresh`

Обновление access-токена через refresh-токен.

### `POST /api/auth/logout`

Выход из системы.

### `POST /api/auth/register`

Регистрация нового пользователя (только для администратора).

### `GET /api/auth/me`

Получение информации о текущем пользователе.

## Эндпоинты сессий

### `GET /api/sessions`

Список всех сессий.

### `POST /api/sessions`

Создание новой сессии.

### `GET /api/sessions/{session_id}`

Получение сессии по ID.

### `PATCH /api/sessions/{session_id}`

Обновление сессии.

### `DELETE /api/sessions/{session_id}`

Удаление сессии.

### `GET /api/sessions/{session_id}/state`

Получение состояния сессии.

### `POST /api/sessions/{session_id}/pause`

Приостановка сессии.

### `POST /api/sessions/{session_id}/archive`

Архивация сессии.

### `POST /api/sessions/{session_id}/resume`

Возобновление сессии.

### `POST /api/sessions/{session_id}/heartbeat`

Отправка heartbeat для сессии.

### `GET /api/sessions/{session_id}/documents`

Список документов в сессии.

### `POST /api/sessions/{session_id}/documents/upload`

Загрузка документа в сессию.

### `POST /api/sessions/{session_id}/documents/path`

Загрузка документа по пути.

### `PATCH /api/sessions/{session_id}/documents/{document_id}`

Обновление документа.

### `DELETE /api/sessions/{session_id}/documents/{document_id}`

Удаление документа.

### `POST /api/sessions/{session_id}/documents/restore`

Восстановление документа.

### `POST /api/sessions/{session_id}/documents/{document_id}/links`

Добавление ссылки на документ.

### `GET /api/sessions/{session_id}/documents/links`

Список ссылок на документ.

### `DELETE /api/sessions/{session_id}/documents/links/{link_id}`

Удаление ссылки.

## Эндпоинты проектов

### `GET /api/sessions/{session_id}/projects`

Список проектов в сессии.

### `POST /api/sessions/{session_id}/projects`

Создание проекта.

### `GET /api/sessions/{session_id}/projects/{project_id}`

Получение проекта по ID.

### `PATCH /api/sessions/{session_id}/projects/{project_id}`

Обновление проекта.

### `DELETE /api/sessions/{session_id}/projects/{project_id}`

Удаление проекта.

### `GET /api/sessions/{session_id}/projects/{project_id}/sections`

Список секций в проекте.

### `PUT /api/sessions/{session_id}/projects/{project_id}/sections/{name}`

Создание секции в проекте.

### `GET /api/sessions/{session_id}/projects/{project_id}/documents`

Список документов в проекте.

### `POST /api/sessions/{session_id}/projects/{project_id}/documents`

Добавление документа в проект.

### `DELETE /api/sessions/{session_id}/projects/{project_id}/documents/{document_id}`

Удаление документа из проекта.

### `GET /api/sessions/{session_id}/projects/{project_id}/sections/{name}`

Получение секции по имени.

### `GET /api/sessions/{session_id}/projects/{project_id}/draft-analysis`

Анализ черновика проекта.

### `POST /api/sessions/{session_id}/projects/{project_id}/generate`

Генерация раздела проекта.

### `POST /api/sessions/{session_id}/projects/{project_id}/generate-async`

Асинхронная генерация раздела проекта.

### `GET /api/sessions/{session_id}/projects/{project_id}/eta`

Получение оценки времени (ETA) для генерации раздела.

### `GET /api/sessions/{session_id}/projects/{project_id}/versions`

Список версий проекта.

### `GET /api/sessions/{session_id}/projects/{project_id}/versions/diff`

Сравнение версий проекта.

### `GET /api/sessions/{session_id}/projects/{project_id}/progress`

Прогресс генерации раздела.

### `GET /api/sessions/{session_id}/projects/{project_id}/export`

Экспорт проекта в Word.

## Эндпоинты чата

### `POST /api/chat/query`

Синхронный запрос с генерацией ответа и источниками.

### `POST /api/chat/stream`

Потоковый запрос с генерацией ответа (SSE).

### `POST /api/chat/query-async`

Асинхронный фоновый запрос.

### `POST /api/chat/quick-query`

Быстрый запрос по глобальной базе.

### `GET /api/chat/suggest-queries`

Предложение уточняющих вопросов.

### `GET /api/chat/quick-history`

История быстрых запросов.

### `GET /api/chat/messages`

Список сообщений в чате.

### `DELETE /api/chat/messages`

Удаление всех сообщений.

### `DELETE /api/chat/messages/{message_id}`

Удаление конкретного сообщения.

### `POST /api/chat/quick-message`

Быстрое отправление сообщения.

## Эндпоинты документов

### `GET /api/documents`

Список документов.

### `GET /api/documents/stats`

Статистика по документам.

### `POST /api/admin/documents/upload`

Загрузка документа (требует администратора).

### `POST /api/admin/documents/bulk`

Пакетная загрузка документов.

### `POST /api/admin/documents/bulk-upload`

Пакетная загрузка (асинхронная).

### `POST /api/admin/documents/bulk-async`

Пакетная загрузка (асинхронная с прогрессом).

### `POST /api/admin/documents/path`

Загрузка документа по файловому пути.

### `PATCH /api/admin/documents/{document_id}`

Обновление документа.

### `DELETE /api/admin/documents/{document_id}`

Удаление документа.

### `GET /api/admin/documents/{document_id}`

Получение документа по ID.

### `POST /api/admin/documents/reindex`

Переиндексация документа.

### `POST /api/admin/documents/persist`

Сохранение состояния документа.

## Эндпоинты метрики

### `GET /api/metrics.json`

Метрики производительности системы.

## Эндпоинты PaperQA2

### `POST /api/pqa/reindex`

Полная переиндексация коллекции PaperQA2. Перечитывает документы из хранилища, пересчитывает эмбеддинги (если `drop_embeddings=true`) и сохраняет результат обратно. Требует прав администратора.

**Request:**
```json
{
  "drop_embeddings": true
}
```

**Response:**
```json
{
  "documents": 4,
  "chunks": 4,
  "seconds": 16.2,
  "collection": "global",
  "meta": {"source": "api", ...}
}
```

### `GET /api/pqa/citation-report`

Отчёт о цитировании последнего ответа чата. Возвращает `CitationReport` из последнего ответа `/api/chat/query`: какие маркеры починили, какие удалили, предупреждения о сломанных ссылках. Требует прав администратора.

**Response:**
```json
{
  "ok": true,
  "changed": false,
  "repaired": [],
  "dropped": [],
  "reflowed": [],
  "cited": [1, 2],
  "dangling": [],
  "uncited": false,
  "warnings": []
}
```

## Авторизация

Большинство эндпоинтов требуют авторизации через `POST /api/auth/login`. Неавторизованный доступ имеет ограниченный набор эндпоинтов:
- `GET /api/health`
- `GET /api/openapi.json`

Для авторизации передавайте JWT-токен в заголовке `Authorization: Bearer <token>` или используйте форму логина `POST /api/auth/login`.

## Методы PaperQA2Service

Публичный API `PaperQA2Service` (`app/services/paperqa_service.py`) — единственная точка доступа к PaperQA2. Один экземпляр `Docs` на коллекцию (`global` или `session:<uuid>`).

### Добавление документов

| Метод | Описание |
|-------|----------|
| `add_file(path, ...)` | Добавить один файл в коллекцию |
| `add_files(paths, ...)` | Добавить несколько файлов |
| `add_uploads(files, ...)` | Добавить загруженные через HTTP файлы |
| `add_url(url, ...)` | Добавить документ по URL |

### Управление документами

| Метод | Описание |
|-------|----------|
| `delete_document(dockey\|path\|docname)` | Удалить документ из коллекции |
| `clear_documents()` | Очистить всю коллекцию |
| `list_documents()` | Документы в памяти |
| `documents_on_disk()` | Реестр документов из БД |

### Поиск и ответ

| Метод | Описание |
|-------|----------|
| `get_evidence(query, k, ...)` | Найти контекст без генерации |
| `search(query, limit)` | Поиск фрагментов без ответа |
| `ask(query, ...)` | Базовый RAG-ответ |
| `ask_with_evidence(query, k, ...)` | RAG-fusion без повторного поиска |
| `agent_ask(query, ...)` | Ответ через PaperQA-агент |

### Персистентность

| Метод | Описание |
|-------|----------|
| `persist_state()` | Сохранить состояние Docs в хранилище |
| `restore_state(force)` | Восстановить Docs из хранилища |
| `rebuild_index(drop_embeddings)` | Полная переиндексация |

## Модели данных

### User

```json
{
  "id": "uuid",
  "username": "admin",
  "role": "admin | researcher",
  "is_active": true,
  "last_login_at": "2026-10-28T09:30:30.722291"
}
```

### TokenPair

```json
{
  "access_token": "jwt-token",
  "refresh_token": "refresh-token",
  "expires_in": 1800
}
```
