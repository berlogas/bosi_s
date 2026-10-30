# CHANGELOG

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Refactored `paperqa_service.py`: вынесение `ServiceRegistry` и `session_collection` в `pqa_registry.py`
- Вынесение `PaperQA2Persistence` в `pqa_persistence.py` — отдельный модуль для персистентности
- Добавлены delegate-методы на `PaperQA2Service`: `persist_state()`, `restore_state()`, `rebuild_index()`
- Исправлена типизация: `token_generator() -> AsyncIterator[str]` в `chat.py`
- Исправлена типизация: `ProjectVersionModel` вместо `ProjectVersion` в `projects.py`
- Добавлена аннотация `**kwargs: Any` в `pqa_readers.py`
- Обновлена документация: `RECOMMENDATIONS.md` п.3 помечена выполненным

### Changed
- Перенесен `get_registry` и связанные импорты из `paperqa_service.py` в `pqa_registry.py`
- Исправлены неиспользуемые импорты: `from sqlalchemy import select` удален из `documents.py`
- Обновлены пути к базе данных и настройки окружения
- Обновлена конфигурация `litellm` для поддержки модели `ministral-3b-latest`

### Fixed
- Исправление F821: `ProjectVersion` → `ProjectVersionModel` в `projects.py`
- Исправление ANN202: `token_generator` добавлена возвращаемая аннотип типа `AsyncIterator[str]`
- Исправление ANN003: `**kwargs: Any` добавлен в `pqa_readers.py`
- Удаление неиспользуемых imports в `documents.py` (`from sqlalchemy import select`)

## [0.1.0] - 2026-10-28

### Added
- Initial release of boasi_s — локальная научная RAG-платформа на PaperQA2 + Ollama + FastAPI + React
- Фазы 0-9 реализованы: загрузка документов, поиск, генерация ответов, управление сессиями, RAG Fusion, проекты статей, Docker-развертывание
- Создан `PHASE10_ACCEPTANCE.md` с чеклистом приёмки по сценарию
- Настроен `alembic` для миграций базы данных
- Настроен `ollama` с моделями `qwen2.5:3b` и `nomic-embed-text`

### Fixed
- Пофикшены стартовые скрипты и конфигурация окружения
- Устранены блокеры авторизации (частично — зависимость от litellm model pricing)

### Known Issues
- Авторизация через `POST /api/auth/login` блокируется из-за映射 модели `ministral-3b-latest` в litellm — требует настройки ценников
- Некоторые эндпоинты требуют доработки под конкретные нужды проекта
- Dev-модель `qwen2.5:3b` может давать некачественные русскоязычные ответы (ожидаемо для CPU-режима)