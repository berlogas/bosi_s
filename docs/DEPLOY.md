# Перенос boasi_s с Windows на сервер Linux и запуск через Docker

Пошаговая инструкция: что делать на Windows-машине, что — на сервере, как перенести код, настроить и запустить стек.

---

## Содержание

1. [Требования к серверу](#1-требования-к-серверу)
2. [Шаг 0 — подготовить проект на Windows](#2-шаг-0---подготовить-проект-на-windows)
3. [Шаг 1 — перенести код на сервер](#3-шаг-1---перенести-код-на-сервер)
4. [Шаг 2 — установить Docker на сервере](#4-шаг-2---установить-docker-на-сервере)
5. [Шаг 3 — настроить .env и SECRET_KEY](#5-шаг-3---настроить-env-и-secret_key)
6. [Шаг 4 — первый запуск и скачивание моделей](#6-шаг-4---первый-запуск-и-скачивание-моделей)
7. [Шаг 5 — создать администратора](#7-шаг-5---создать-администратора)
8. [Шаг 6 — бэкап и восстановление](#8-шаг-6---бэкап-и-восстановление)
9. [Шаг 7 — обновление после правок кода](#9-шаг-7---обновление-после-правок-кода)
10. [Управление стеком (шпаргалка)](#10-управление-стеком-шпаргалка)
11. [Где лежат данные на сервере](#11-где-лежат-данные-на-сервере)
12. [Чек-лист перед вводом в эксплуатацию](#12-чеклист-перед-вводом-в-эксплуатацию)

---

## 1. Требования к серверу

| Компонент | Версия | Зачем |
|-----------|--------|-------|
| Linux (Ubuntu 20.04+, Debian 11+, RHEL 8+) | — | ОС сервера |
| Docker Engine | 24+ | Запуск контейнеров |
| Docker Compose | v2 (плагин `docker compose`) | Управление стеком |
| Git | 2+ | Клонирование репозитория |
| RAM | от 8 ГБ | Backend + Ollama + модель эмбеддингов |
| Диск | от 40 ГБ свободного | Тома с данными, образы, модели Ollama |

---

## 2. Шаг 0 — подготовить проект на Windows

На вашей Windows-машине в папке `N:\Development\boasi_s`:

### 2.1. Создать `.env` (если ещё нет)

```cmd
cd N:\Development\boasi_s
copy .env.example .env
```

### 2.2. Сгенерировать SECRET_KEY

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Скопируйте результат. Позже вставите в `.env` на сервере.

### 2.3. Сохранить текущие данные (опционально, если есть работающая БД)

Если на Windows уже есть данные в `data/boasi.sqlite3`, которые нужно перенести:

```cmd
bash scripts/backup.sh
```

Архив появится в папке `backups/`. Его потом перенесём на сервер и восстановим.

---

## 3. Шаг 1 — перенести код на сервер

### Вариант А — через Git (рекомендуется, если репозиторий доступен)

На сервере Linux:

```bash
sudo mkdir -p /opt/boasi_s
sudo chown $USER:$USER /opt/boasi_s
cd /opt
git clone <URL-вашего-репозитория> boasi_s
cd boasi_s
```

### Вариант Б — через rsync / scp с Windows

Если нет Git-репозитория, скопируйте папку проекта с Windows на сервер.

**С сервера Linux (через Git Bash / WSL / терминал Linux):**

```bash
rsync -avz --progress \
  --exclude='.venv/' \
  --exclude='node_modules/' \
  --exclude='__pycache__/' \
  --exclude='.git/' \
  --exclude='data/' \
  --exclude='*.db' \
  --exclude='backups/' \
  --exclude='logs/' \
  N:/Development/boasi_s/ user@server:/opt/boasi_s/
```

**С Windows PowerShell:**

```powershell
scp -r N:\Development\boasi_s\* user@server:/opt/boasi_s/
```

> Исключаем `data/`, `.venv/`, `node_modules/`, `backups/`, `logs/` — они будут созданы на сервере заново. Переносим только исходный код, конфиги и скрипты.

---

## 4. Шаг 2 — установить Docker на сервере

Подключитесь к серверу по SSH:

```bash
ssh user@server
```

### Ubuntu / Debian

```bash
sudo apt update
sudo apt install -y ca-certificates curl gnupg lsb-release

# Официальный репозиторий Docker
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

sudo systemctl enable --now docker
sudo usermod -aG docker $USER
```

После `usermod` **перелогиньтесь** (выйдите и зайдите снова по SSH), чтобы права вступили в силу.

Проверьте:

```bash
docker --version
docker compose version
```

---

## 5. Шаг 3 — настроить .env и SECRET_KEY

```bash
cd /opt/boasi_s

# Скопировать шаблон
cp .env.example .env

# Сгенерировать ключ на сервере (или вставить тот, что сгенерировали на Windows)
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Отредактируйте `.env` (редактор `nano` или `vi`):

```bash
nano .env
```

Обязательно замените:

```env
SECRET_KEY=<вставить_сгенерированный_ключ_без_пробелов>
```

Проверьте остальные важные параметры:

```env
APP_ENV=dev
DATA_DIR=./data
OLLAMA_BASE_URL=http://127.0.0.1:11434
LLM_MODEL=ollama/qwen2.5:3b
EMBEDDING_MODEL=st-intfloat/multilingual-e5-small
ANSWER_LANGUAGE=ru
```

> Порты в `docker-compose.yml` уже ограничены `127.0.0.1` (доступ только с сервера). Для внешнего доступа поставьте перед стеком reverse proxy (Nginx/Traefik) — это отдельная задача.

---

## 6. Шаг 4 — первый запуск и скачивание моделей

```bash
cd /opt/boasi_s

# 1. Поднять Ollama
docker compose up -d ollama

# 2. Скачать модель LLM (один раз, несколько гигабайт, подождите)
docker exec -it boasi-ollama ollama pull qwen2.5:3b

# 3. Собрать и запустить backend + webapp
docker compose up -d --build
```

Первый запуск долгий: Docker скачает образы, установит Python-зависимости, соберёт React-интерфейс. Может занять 5–15 минут.

### Проверить, что всё поднялось

```bash
# Состояние контейнеров
docker compose ps

# Backend должен отвечать
curl -fsS http://127.0.0.1:8000/api/health
```

Откройте в браузере: `http://<IP-СЕРВЕРА>:5173`

Если нужно перенести старые данные из бэкапа Windows — см. раздел 8.

---

## 7. Шаг 5 — создать администратора

Войти в контейнер backend и создать первого админа:

```bash
docker compose exec backend python scripts/create_admin.py admin
```

Скрипт спросит пароль (минимум 8 символов). Запомните его.

Другие операции с пользователями:

```bash
# Список пользователей
docker compose exec backend python scripts/reset_password.py --list

# Сброс пароля
docker compose exec backend python scripts/reset_password.py admin
```

Откройте `http://<IP-СЕРВЕРА>:5173` и войдите под созданным логином/паролем.

---

## 8. Шаг 6 — бэкап и восстановление

Если вы сняли бэкап на Windows (раздел 2.3), перенесите файл архива на сервер:

```bash
# С сервера Linux
scp user@windows: N:/Development/boasi_s/backups/boasi-*.tar.gz /opt/boasi_s/backups/
# или через rsync / ftp / любую удобную команду
```

### Сделать новый бэкап на сервере

```bash
cd /opt/boasi_s
bash scripts/backup.sh
```

Сохранить ещё и `.env` отдельным файлом:
```bash
CONFIG_BACKUP=1 bash scripts/backup.sh
```

### Восстановить из бэкапа

**Важно:** стек должен быть остановлен.

```bash
# 1. Остановить
docker compose down

# 2. Восстановить (при запросе введите слово ВОССТАНОВИТЬ)
bash scripts/restore.sh backups/boasi-YYYYmmdd-HHMMSS.tar.gz

# 3. Запустить снова
docker compose up -d

# 4. Проверить
curl -fsS http://127.0.0.1:8000/api/health
```

Страховочная копия текущего состояния сохранится в `backups/pre-restore/`.

### Автоматические бэкапы (cron)

```bash
crontab -e
```

Добавить строку для ежедневного бэкапа в 03:00:

```cron
0 3 * * * cd /opt/boasi_s && /bin/bash scripts/backup.sh >> /var/log/boasi_backup.log 2>&1
```

---

## 9. Шаг 7 — обновление после правок кода

Если вы изменили код на сервере (или загрузили новую версию через Git):

```bash
cd /opt/boasi_s
git pull                      # если код через Git

# Пересобрать только то, что изменилось
docker compose up -d --build backend   # только backend
docker compose up -d --build webapp    # только интерфейс
# или всё вместе:
docker compose up -d --build
```

После пересборки backend подождите ответа `/api/health` — восстанавливается индекс и загружается модель эмбеддингов (минуты).

---

## 10. Управление стеком (шпаргалка)

Все команды выполняются в `/opt/boasi_s`:

```bash
docker compose up -d           # запустить в фоне
docker compose down            # остановить (данные в томах остаются)
docker compose up -d --build   # пересобрать после правок кода
docker compose ps              # состояние контейнеров
docker compose logs -f backend # логи backend
docker compose logs -f webapp  # логи интерфейса
docker compose logs -f ollama  # логи Ollama
```

Удалить **включая данные** (безвозвратно):
```bash
docker compose down -v
docker volume rm boasi_ollama_models
```

---

## 11. Где лежат данные на сервере

### 11.1. Docker-тома (данные живут здесь после остановки контейнеров)

| Том Docker | Путь внутри контейнера | Содержимое |
|------------|------------------------|------------|
| каталог `data/` | `/data` | Основное хранилище: SQLite БД, сессии, документы, индекс, кэш моделей (bind-mount на хоста) |
| `boasi_backups` | `/backups` | Архивы бэкапов (ротацией управляет backend, `BACKUP_KEEP`) |
| `boasi_ollama_models` | `/root/.ollama` | Модели Ollama (скачаны через `ollama pull`) |

#### Внутри тома `boasi_data` (`/data`)

| Подпапка | Назначение |
|----------|------------|
| `/data/boasi.sqlite3` | SQLite база данных |
| `/data/sessions/` | Сессии пользователей |
| `/data/documents/` | Загруженные документы |
| `/data/documents/library/YYYY-MM/` | Постоянное хранилище импортированных файлов (из inbox) |
| `/data/inbox/` | Папка-приёмник массового импорта (смонтирована с хоста) |
| `/data/rejected/` | Файлы, которые не удалось разобрать (битый PDF и т.п.) |
| `/data/pqa/` | PaperQA home (включает `/data/pqa/answers` — кэш ответов) |
| `/data/hf/` | Кэш моделей HuggingFace (эмбеддинги) |
| `/data/torch/` | Кэш PyTorch |

> Все эти подпапки создаются автоматически при старте backend (`settings.ensure_dirs()`).

### 11.2. Папки на хосте (создать вручную перед первым запуском)

| Папка на хосте | Назначение | Привязка к контейнеру |
|----------------|------------|----------------------|
| `/opt/boasi_s/inbox/` | Массовый импорт документов — кладете файлы сюда, бэкенд индексирует | смонтирована как `/data/inbox` |
| `/opt/boasi_s/backups/` | Архивы бэкапов от скрипта `scripts/backup.sh` | не смонтирована — пишется на хост |
| `/opt/boasi_s/logs/` | Логи приложения (создаётся скриптом запуска) | не используется в Docker-контейнерах |
| `/opt/boasi_s/.run/` | PID-файры процессов (создаётся скриптом запуска) | не используется в Docker-контейнерах |

```bash
cd /opt/boasi_s
mkdir -p inbox backups logs .run
```

> Архивы бэкапов **не попадают внутрь Docker-тома** `boasi_data` — они хранятся на хосте в `backups/`. Поэтому при `docker compose down -v` они не удаляются.

⚠️ `docker compose down -v` **удаляет тома вместе с базой, документами, сессиями и кэшем моделей** — не используйте без необходимости.

### 11.3. Что создаётся автоматически, а что вручную

| Что | Кто создаёт | Когда |
|-----|-------------|-------|
| `/opt/boasi_s/inbox/` | Вы (вручную) | Перед первым запуском |
| `/opt/boasi_s/backups/` | Вы (вручную) | Перед первым запуском |
| `/opt/boasi_s/logs/` | Вы (вручную) | Перед первым запуском |
| `/opt/boasi_s/.run/` | Вы (вручную) | Перед первым запуском |
| `/data/sessions/`, `/data/documents/`, `/data/pqa/`, `/data/hf/`, `/data/torch/` | Backend (`ensure_dirs()`) | При первом старте контейнера |
| `/root/.ollama/` | Ollama | При первом запуске контейнера Ollama |
| `backups/boasi-*.tar.gz` | Скрипт `scripts/backup.sh` | При каждом бэкапе |

---

## 12. Чек-лист перед вводом в эксплуатацию

- [ ] Docker и `docker compose` установлены на сервере
- [ ] Код проекта скопирован в `/opt/boasi_s`
- [ ] `.env` скопирован из `.env.example`, `SECRET_KEY` сгенерирован и заменён
- [ ] Модель Ollama `qwen2.5:3b` скачана (`docker exec boasi-ollama ollama list`)
- [ ] Администратор создан через `create_admin.py`
- [ ] Интерфейс открывается по `http://<IP-СЕРВЕРА>:5173`
- [ ] Первый бэкап снят и проверен через `bash scripts/verify_backup.sh ...`
- [ ] Cron для автоматических бэкапов настроен
