# Рекомендации по Docker-развёртыванию boasi_s

**Дата:** 2026-11-13  
**Статус:** черновик для внедрения  
**Область:** `docker-compose.yml`, `docker-compose.prod.yml`, `backend/Dockerfile`, `webapp/Dockerfile`, `scripts/start-docker.bat`, `.env`, `.env.example`

---

## 1. Текущее состояние

| Компонент | Файл | Что есть |
|---|---|---|
| Оркестрация | `docker-compose.yml` | ollama + backend + webapp, порты `127.0.0.1:11434/8000/5173` |
| Продакшн-переопределение | `docker-compose.prod.yml` | NVIDIA GPU, лимиты ресурсов, ротация логов |
| Backend-образ | `backend/Dockerfile` | `python:3.11-slim`, CPU torch, `requirements.lock` |
| Webapp-образ | `webapp/Dockerfile` | `node:20-alpine`, `npm run dev` |
| Запуск Windows | `scripts/start-docker.bat` | Batch-обёртка над `docker compose` |
| Запуск Linux/macOS | — | отсутствует, только ручной `docker compose` |
| Документация | `DOCKER.md` | только Windows-инструкция |

Приложение стартует и под Windows, и под Linux, но с оговорками (см. §3).

---

## 2. Найденные ошибки

### Критические (блокируют комфортную работу на одной из ОС)

| # | Ошибка | Где | Последствие |
|---|---|---|---|
| E1 | Нет скрипта запуска для Linux/macOS | `scripts/` | Пользователь на Linux должен вручную набирать `docker compose`, выставить `DOCKER_UID`/`DOCKER_GID`, ждать healthcheck, открывать браузер вручную |
| E2 | Бэкенд по умолчанию работает от root (UID 0) | `docker-compose.yml:31` | На Linux файлы в `data/` становятся `root:root`, хостовый пользователь не может их удалить без `sudo`. На Windows переменные UID/GID игнорируются Docker Desktop, но compose всё равно подставляет `0:0` |
| E3 | `USER boasi` в `backend/Dockerfile` перебивается `user: 0:0` в compose | `backend/Dockerfile:34` + `docker-compose.yml:31` | Намеренное создание непривилегированного пользователя в образе отменяется при отсутствии переменных окружения |
| E4 | Webapp работает на Vite dev-сервере, не на production-сборке | `webapp/Dockerfile:14` | Dev-сервер не предназначен для продакшена: медленнее, больше памяти, нет оптимизации бандлов |
| E5 | `tests/` копируются в продакшен-образ бэкенда | `backend/Dockerfile:28` | Увеличивает размер образа и поверхность атаки, тесты не нужны в runtime |
| E6 | Порты жёстко заданы в compose, но документированы как настраиваемые | `docker-compose.yml:51,87` + `DOCKER.md:156-158` | `API_PORT`/`WEBAPP_PORT` из `.env` не влияют на compose без правки файла |
| E7 | CORS не включает порт веб-приложения (5173) | `.env:8`, `.env.example:8` | При открытии фронтенда напрямую (мимо Vite-прокси) браузер блокирует запросы к API |

### Средние (операционные риски)

| # | Ошибка | Где | Последствие |
|---|---|---|---|
| E8 | Нет `.dockerignore` в `backend/` | `backend/` | Контекст сборки может включать `__pycache__`, `.pytest_cache`, `.ruff_cache` |
| E9 | Нет healthcheck у `webapp` | `docker-compose.yml:74-87` | Нельзя отследить состояние фронтенда через `docker compose ps` |
| E10 | `start-docker.bat` поднимает ollama дважды | `scripts/start-docker.bat:55,63` | Избыточно, первый вызов безвреден, но запутывает |
| E11 | Модели Ollama в именованном томе, данные — в bind-mount | `docker-compose.yml:11,57` | Бэкап скриптами захватывает `data/`, но не модели Ollama (только через `MODELS_BACKUP=1`). `docker compose down -v` удаляет модели отдельно — неочевидно |
| E12 | `.env` и `.env.example` расходятся по `LLM_MODEL` | `.env:47` vs `.env.example:59` | Новый пользователь получает другую модель по умолчанию |

---

## 3. Рекомендации

### Обязательные (Windows + Linux)

**R1. Добавить `scripts/start-docker.sh` — аналог `start-docker.bat` для Linux/macOS**  
То же самое поведение: проверка Docker Compose, проверка `.env` с `SECRET_KEY`, запуск Ollama, сборка и запуск стека, ожидание `/api/health`, открытие браузера (`xdg-open` на Linux, `open` на macOS). Команды: `up`, `stop`, `restart`, `rebuild`, `status`, `logs [service]`, `help`.

**R2. Не запускать бэкенд от root по умолчанию**  
В `docker-compose.yml` заменить:

```yaml
user: "${DOCKER_UID:-0}:${DOCKER_GID:-0}"
```

на:

```yaml
user: "${DOCKER_UID:-1000}:${DOCKER_GID:-1000}"
```

На Windows Docker Desktop игнорирует UID/GID, на Linux файлы в `data/` будут принадлежать хостовому пользователю. Альтернатива — оставить `USER boasi` из Dockerfile и убрать `user:` из compose полностью.

**R3. Перевести webapp на production-сборку**  
В `webapp/Dockerfile` добавить `RUN npm run build` и заменить `CMD` на `vite preview` (или статическую раздачу). Если нужна горячая перезагрузка при разработке — вынести `dev` в профиль `dev`:

```yaml
profiles: ["dev"]
```

и запускать через `docker compose --profile dev up webapp`.

**R4. Убрать `COPY tests ./tests` из `backend/Dockerfile`**  
Тесты не нужны в runtime-образе.

**R5. Синхронизировать зависимости**  
Dockerfile использует `requirements.lock`, `make install` — `requirements.txt`. Выбрать один файл (рекомендуется `requirements.lock`) и использовать его везде, либо явноdocumentировать различие.

**R6. Сделать порты настраиваемыми через переменные окружения**  
В `docker-compose.yml`:

```yaml
ports:
  - "${API_PORT:-8000}:8000"
  - "${WEBAPP_PORT:-5173}:5173"
```

**R7. Добавить `http://127.0.0.1:5173` и `http://localhost:5173` в `CORS_ORIGINS`**  
В `.env` и `.env.example`.

### Желательные

**R8. Добавить `backend/.dockerignore`**  
Исключить `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `*.pyc`, `.venv/`.

**R9. Добавить healthcheck для `webapp`**  
Например:

```yaml
healthcheck:
  test: ["CMD-SHELL", "wget -qO- http://localhost:5173/ || exit 1"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 10s
```

**R10. Вынести повторяющиеся фрагменты в YAML-якоря (`x-`)**  
`deploy.resources.limits`, `logging`, `restart` дублируются между сервисами и файлами.

**R11. Добавить поддержку GPU в базовом `docker-compose.yml` через профиль**  
Чтобы не обязательно было тащить `docker-compose.prod.yml` для WSL2+NVIDIA на Windows.

**R12. Синхронизировать `LLM_MODEL` между `.env` и `.env.example`**  
Оба файла должны иметь одинаковую модель по умолчанию (`ollama/qwen2.5:3b` или `ollama/ministral-3:3b`).

**R13. Интегрировать backup/restore в скрипты запуска**  
Добавить команды `backup` и `restore` в `start-docker.bat` и `start-docker.sh`.

---

## 4. Пример изменений в `docker-compose.yml`

```yaml
services:
  ollama:
    image: ollama/ollama:latest
    container_name: boasi-ollama
    restart: unless-stopped
    volumes:
      - ollama_models:/root/.ollama
    ports:
      - "127.0.0.1:11434:11434"
    healthcheck:
      test: ["CMD-SHELL", "ollama list >/dev/null 2>&1 || exit 1"]
      interval: 15s
      timeout: 10s
      retries: 10
      start_period: 30s

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: boasi-backend
    restart: unless-stopped
    user: "${DOCKER_UID:-1000}:${DOCKER_GID:-1000}"
    depends_on:
      ollama:
        condition: service_healthy
    env_file: [.env]
    environment:
      DATA_DIR: /data
      DATABASE_URL: sqlite:////data/boasi.sqlite3
      PQA_HOME: /data/pqa
      BACKUP_DIR: /backups
      BACKUP_KEEP: "14"
      INBOX_DIR: /data/inbox
      LIBRARY_DIR: /data/documents/library
      REJECTED_DIR: /data/rejected
      OLLAMA_BASE_URL: http://ollama:11434
    ports:
      - "${API_PORT:-8000}:8000"
    volumes:
      - ./data:/data
      - ./backups:/backups
    healthcheck:
      test: ["CMD-SHELL", "curl -fsS http://127.0.0.1:8000/api/health || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 180s
    deploy:
      resources:
        limits:
          cpus: "4.0"
          memory: 8G

  webapp:
    build:
      context: ./webapp
      dockerfile: Dockerfile
    container_name: boasi-webapp
    restart: unless-stopped
    depends_on:
      backend:
        condition: service_healthy
    environment:
      VITE_API_TARGET: http://backend:8000
    ports:
      - "${WEBAPP_PORT:-5173}:5173"
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://localhost:5173/ || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s

volumes:
  ollama_models:
    name: boasi_ollama_models
```

---

## 5. Приоритет внедрения

| Приоритет | Рекомендация | Сложность | Эффект |
|---|---|---|---|
| 1 | R2 (права пользователя, не root) | Низкая | Исправляет проблемы с правами на `data/` в Linux |
| 2 | R1 (скрипт `start-docker.sh`) | Средняя | Единая точка входа для Linux и Windows |
| 3 | R3 (production webapp) | Средняя | Фронтенд готов к продакшену |
| 4 | R4, R5, R6, R7 | Низкая | Чистота образов, настраиваемость, CORS |
| 5 | R8–R13 | Низкая/Средняя | Операционное удобство |

---

## 6. Проверка после внедрения

1. **Windows:** `scripts\start-docker.bat up` — стек поднимается, браузер открывается на `http://127.0.0.1:5173`, `/api/health` отвечает.
2. **Linux:** `./scripts/start-docker.sh up` — то же самое, файлы в `data/` принадлежат пользователю, запустившему compose.
3. **Права:** после остановки стек можно перезапустить без `sudo`, хостовый пользователь может удалять файлы в `data/`.
4. **Production:** `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d` — GPU виден Ollama, логи ротируются.

---

*Не изменяйте код приложения — этот документ касается только инфраструктуры развёртывания.*