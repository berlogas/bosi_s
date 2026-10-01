# Фаза 1 — фундамент backend: отчёт

**Дата:** 2026-10-01 · **Статус:** ✅ выполнена

## Что сделано

| Блок | Артефакты |
| --- | --- |
| Конфигурация | `backend/app/config.py`, `.env`, `.env.example` — все параметры из окружения, лимиты ТЗ зафиксированы |
| Схема БД | `backend/app/db/models.py` — 8 таблиц: `users`, `research_sessions`, `documents`, `projects`, `document_links`, `messages`, `audit_log`, `refresh_tokens` |
| Миграции | `backend/alembic/` — Alembic, начальная ревизия `d5b608e3fdd6`, `render_as_batch=True` для SQLite |
| Безопасность | `backend/app/core/security.py` — argon2 (pwdlib), JWT access/refresh, `require_role()`, refresh-токены только в виде хэша |
| Потокобезопасность | `backend/app/core/locks.py` — сессионные `asyncio.Lock` + RW-lock глобального индекса |
| API | `/api/health`, `/api/health/locks`, `/api/auth/{login,refresh,logout,me}`, единый формат ошибок |
| Логирование | JSON-логи (`backend/app/core/logging.py`), аудит мутаций в БД |
| Docker | `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml`, `docker-compose.prod.yml` (GPU passthrough), `Makefile` |
| Зависимости | `backend/requirements.txt` + `requirements.lock` (**Linux-lock**, собран в контейнере: без `pywin32`, `torch==2.14.1+cpu`) |
| Тесты | 51 тест: `tests/test_config.py`, `test_security.py`, `test_models.py`, `test_locks.py`, `test_api.py` |

## DoD Фазы 1 — выполнены

- ✅ `docker compose up` поднимает весь стек (ollama + backend + frontend), все три сервиса `healthy`
- ✅ `/api/health` → `{"status":"ok","database":"ok",...}`, проверяет доступность Ollama и наличие модели
- ✅ Миграции применяются при старте контейнера (`alembic upgrade head` в CMD)
- ✅ 51 тест зелёный (`cd backend && pytest -q`)
- ✅ Аутентификация работает вживую: логин → токен → `/api/auth/me` (проверено и локально, и внутри контейнера)

## Решения, принятые в Фазе 1

1. **SQLAlchemy sync + FastAPI async.** Синхронные зависимости FastAPI выполняются в threadpool; тяжёлые LLM-вызовы (Фазы 2–7) асинхронные и вне транзакций БД.
2. **SQLite с WAL** + `busy_timeout=15s`: на dev-машине долгие RAG-запросы не должны блокировать запись аудита и heartbeat.
3. **`UTCDateTime` TypeDecorator.** SQLite не хранит часовой пояс → `DateTime(timezone=True)` возвращает naive-значения, и сравнения вроде `expires_at < now(UTC)` падают. Тип гарантирует tz-aware UTC на входе и выходе.
4. **Refresh-токены single-use с ротацией** и хранением только SHA-256 хэша.
5. **Линзы на скорость нет.** `evidence_k=10`, `answer_max_sources=5`, `chunk_chars=4000`, `timeout=3600`, `max_concurrent_requests=1` — последнее только ради корректности (Ollama на CPU последователен, параллелизм даёт очередь и таймауты).
6. **Модель — одна переменная** `LLM_MODEL`; в коде нет констант производительности.

## Найденные и исправленные грабли

| Грабля | Решение |
| --- | --- |
| `DocumentLink` имеет два FK на `documents.id` → `AmbiguousForeignKeysError` при маппинге | явный `foreign_keys="DocumentLink.document_id"` в обоих relationship |
| Неоднородный префикс роутеров: `/health` и `/api/auth/...` | единый префикс `/api` у всех роутеров |
| `settings.get_summary_llm()` **перезаписывает** канонический `LLMConfig {"models": [...]}` → теряются `timeout` и `api_base` | пока не используется (Фаза 2); зафиксировано в инвариантах |
| Windows `pip freeze` даёт `pywin32` → Linux-образ не собирается | lock собран **внутри** `python:3.11-slim` |
| Пустые переменные в `.env` (`PQA_HOME=`) превращались в `Path('.')` | валидатор `_empty_to_none` |
| Относительный `DATA_DIR` зависел от CWD | пути разрешаются от корня репозитория |
| Сравнение «naive vs aware» datetime в тестах TTL | `UTCDateTime` (см. решение 3) |
| `pip freeze` без платформенных маркеров ломал прод-сборку | Linux-lock + `torch==2.14.1+cpu` (в проде LLM считает Ollama на GPU, CPU-torch достаточно для эмбеддингов) |
| Порт 11434 занят хостовым Ollama из Фазы 0 | хостовый сервер остановлен, порт отдан контейнеру |

## Состояние окружения

```
docker compose ps
backend    running (healthy)   http://127.0.0.1:8000/api/health   (Swagger: /api/docs)
frontend   running (healthy)   http://127.0.0.1:8501
ollama     running (healthy)   http://127.0.0.1:11434
```

Модель `qwen2.5:3b` скачивается в том контейнера (`make models` — для повторения). Первый пользователь создаётся вручную или будет добавлена команда `make create-admin` (Фаза 3, вместе с админ-панелью управления пользователями).

## Что заложено на будущее

- `app/services/` — обёртка PaperQA (Фаза 2), `rag_fusion` (Фаза 6), генерация статей (Фаза 7)
- `app/workers/` — индексация, heartbeat сессий, reaper 90-дневных сессий (Фазы 4–5)
- `app/schemas/api.py` — DTO-контракт, расширяется в каждой фазе
- `locks.session_lock(session_id)` и `locks.global_index` — используются сервисами PaperQA
- `docker-compose.prod.yml` — GPU passthrough, автозапуск, лимиты ресурсов

## Дальше: Фаза 2 — обёртка `PaperQA2Service`

Инварианты Фазы 0 (обязательны к исполнению): ST-эмбеддинги, legacy-форма `model_list` в `llm_config`, `timeout=3600`, `use_doc_details=False`, `multimodal=OFF`, `chunk_chars=4000/overlap=200`, явный `citation`, `settings` во всех вызовах, `aadd → None` = «документ уже есть», персистентность через `aadd_texts`.