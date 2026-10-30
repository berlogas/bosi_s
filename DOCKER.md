# Запуск boasi_s через Docker (Windows)

Замена классического `scripts\start.bat` на Docker Compose.
Поднимаются три контейнера: **Ollama** (LLM), **backend** (FastAPI) и **webapp** (React/Vite).

## Что внутри

| Сервис | Порт на хосте | Назначение |
|--------|--------------|------------|
| `ollama` | 127.0.0.1:11434 | Локальная LLM (заменяет OpenAI) |
| `backend` | 127.0.0.1:8000 | FastAPI API, Swagger по `/api/docs` |
| `webapp` | 127.0.0.1:5173 | React-интерфейс (Vite dev-сервер) |

Данные хранятся в именованных томах Docker (`boasi_data`, `boasi_backups`, `boasi_ollama_models`), поэтому при пересоздании контейнеры не теряют базу, загруженные документы и модели Ollama.

---

## Предварительные требования

1. **Docker Desktop** для Windows: https://www.docker.com/products/docker-desktop/
   - После установки перезагрузите компьютер.
   - Проверьте: `docker --version` и `docker compose version` в PowerShell или cmd.
2. **Git** не обязателен (в отличие от классического запуска через `start.bat`).

---

## Первый запуск (пошагово)

### Шаг 1. Подготовить `.env`

```cmd
cd N:\Development\boasi_s
copy .env.example .env
```

### Шаг 2. Сгенерировать `SECRET_KEY`

Приложение не стартует с шаблонным ключом. Сгенерируйте и вставьте в `.env`:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

В `.env` замените строку:
```
SECRET_KEY=change-me-please-generate-48-bytes
```
на:
```
SECRET_KEY=<ваш_сгенерированный_ключ>
```

### Шаг 3. Запустить стек

```cmd
scripts\start-docker.bat
```

Или, если запускаете из PowerShell:
```powershell
.\scripts\start-docker.bat
```

Скрипт:
1. Проверит наличие Docker и `.env` с корректным `SECRET_KEY`;
2. Поднимет Ollama;
3. Соберёт и запустит backend и webapp;
4. Подождёт, пока backend ответит на `/api/health`;
5. Откроет браузер на `http://127.0.0.1:5173`.

**Первый запуск долгий:** скачиваются образ `ollama/ollama`, образ `node:20-alpine`, ставится Python-зависимости backend и загружается модель эмбеддингов. Ожидайте несколько минут.

### Шаг 4. Загрузить модели Ollama

Модели не встроены в образ (они велики). Скачайте нужную:

```cmd
docker exec -it boasi-ollama ollama pull qwen2.5:3b
```

Модель по умолчанию в `.env`: `LLM_MODEL=ollama/qwen2.5:3b`.

Можно также использовать готовый скрипт:
```cmd
.\scripts\pull_models.sh   # требует Git Bash
# или вручную:
docker compose exec ollama ollama pull qwen2.5:3b
```

### Шаг 5. Создать администратора

Регистрации в интерфейсе нет — учётку создаёт админ через CLI:

```cmd
docker compose exec backend python scripts/create_admin.py ivanov
```

Скрипт попросит ввести пароль (минимум 8 символов).

Если пароль забыт:
```cmd
docker compose exec backend python scripts/reset_password.py ivanov
```

---

## Управление стеком

| Команда | Действие |
|---------|----------|
| `scripts\start-docker.bat` | Запустить все контейнеры |
| `scripts\start-docker.bat stop` | Остановить и удалить контейнеры (данные в томах остаются) |
| `scripts\start-docker.bat restart` | Перезапустить с пересборкой |
| `scripts\start-docker.bat status` | Показать состояние контейнеров |
| `scripts\start-docker.bat logs` | Логи backend (последние 100 строк, follow) |
| `scripts\start-docker.bat logs ollama` | Логи Ollama |
| `scripts\start-docker.bat logs webapp` | Логи веб-интерфейса |

### Полный контроль через `docker compose` (альтернатива)

```cmd
docker compose up -d           # запустить в фоне
docker compose down            # остановить
docker compose up -d --build   # пересобрать и запустить
docker compose ps              # состояние
docker compose logs -f backend # логи backend в реальном времени
docker compose exec backend bash   # войти в контейнер backend
```

---

## Доступ

- **Интерфейс:** http://127.0.0.1:5173
- **API (Swagger):** http://127.0.0.1:8000/api/docs
- **Проверка здоровья:** http://127.0.0.1:8000/api/health
- **Ollama API:** http://127.0.0.1:11434

Вход в интерфейс — по логину и паролю, созданным через `create_admin.py`.

---

## Переменные окружения

Можно переопределить перед запуском:

```cmd
set API_PORT=9000
set WEBAPP_PORT=8600
set NO_BROWSER=1
scripts\start-docker.bat
```

| Переменная | По умолчанию | Назначение |
|------------|-------------|------------|
| `API_PORT` | 8000 | Порт backend на хосте |
| `WEBAPP_PORT` | 5173 | Порт веб-интерфейса на хосте |
| `NO_BROWSER` | (пусто) | Если `1` — не открывать браузер |

---

## Бэкапы и данные

Все данные живут в томах Docker:

- `boasi_data` — SQLite БД, загруженные документы, индекс эмбеддингов (`/data` внутри контейнера)
- `boasi_backups` — архивы бэкапов (`/backups`)
- `boasi_ollama_models` — модели Ollama (`/root/.ollama`)

Скрипты бэкапа (`scripts/backup.sh`, `scripts/restore.sh`) работают с данными тома `boasi_data`. Их можно запускать из Git Bash или WSL.

---

## Ограничения и отличия от обычного запуска

1. **Нет Git Bash** — не нужен. Всё через Docker Desktop и `docker compose`.
2. **Веб-интерфейс в контейнере** — в отличие от классического `start.sh`, где React запускается на хосте, здесь `webapp` — отдельный контейнер. Прокси API внутри Docker настроен через `VITE_API_TARGET=http://backend:8000`.
3. **Порты привязаны к 127.0.0.1** — доступны только с локальной машины, не из сети.
4. **Первый ответ долгий** — CPU-инференс через Ollama, это нормально (минуты, а не секунды).
5. **Пересборка backend** — при изменении кода backend выполните `docker compose up -d --build`.

---

## Удалить всё полностью (включая данные)

```cmd
docker compose down -v
docker volume rm boasi_ollama_models boasi_data boasi_backups
```

⚠️ Это безвозвратно удаляет базу, документы, сессии и модели Ollama.

---

## Файлы, изменённые или добавленные

| Файл | Что изменилось |
|------|---------------|
| `docker-compose.yml` | Добавлен сервис `webapp` |
| `docker-compose.prod.yml` | Добавлены лимиты и логи для `webapp` |
| `webapp/Dockerfile` | **Новый** — образ React + Vite |
| `webapp/.dockerignore` | **Новый** — исключает `node_modules`, `dist` и т.д. |
| `webapp/vite.config.ts` | Прокси API через `VITE_API_TARGET` (по умолчанию `localhost`, в Docker — `backend`) |
| `scripts/start-docker.bat` | **Новый** — замена `start.bat` для Docker |
| `DOCKER.md` | **Новый** — эта инструкция |
