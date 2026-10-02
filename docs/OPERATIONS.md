# Эксплуатация boasi_s

Документ для того, кто разворачивает и сопровождает платформу.
Для пользователей — [USER_GUIDE.md](USER_GUIDE.md), для администраторов —
[ADMIN_GUIDE.md](ADMIN_GUIDE.md).

## 1. Требования

| Компонент | Минимум | Комментарий |
| --- | --- | --- |
| Docker + Compose | 24.x / v2 | Проверено на Compose v5 |
| CPU | 4 ядра | Dev-машина: 8 ядер, без GPU |
| RAM | 8 ГБ | Индекс PaperQA держится в памяти процесса |
| Диск | 20 ГБ + модели | Модель `qwen2.5:3b` ~2 ГБ |
| GPU | не требуется | В бою — см. `docker-compose.prod.yml` |

## 2. Первый запуск

```bash
git clone https://github.com/berlogas/bosi_s.git
cd bosi_s

cp .env.example .env
# ОБЯЗАТЕЛЬНО: сгенерировать ключ подписи токенов
python -c "import secrets; print(secrets.token_urlsafe(48))"   # вставить в SECRET_KEY

make pull-models     # скачать модели Ollama (контур работает оффлайн)
make up              # поднять ollama + backend + frontend
```

Проверка:

```bash
make health          # http://127.0.0.1:8000/api/health
```

Ожидается `status: ok`, `database: ok`, `ollama.reachable: true`.
Если `ollama.reachable: false` — модель не скачана: `make pull-models`.

Первый вход: создать администратора (регистрации в UI нет).

```bash
make create-admin
```

URL: <http://127.0.0.1> (порт 80).

## 3. Что где лежит

| Путь | Содержимое | Бэкапится |
| --- | --- | --- |
| том `boasi_data` | **всё состояние** | да |
| `/data/boasi.sqlite3` | пользователи, сессии, документы, сообщения, аудит | да |
| `/data/pqa/` | кэш PaperQA, кэш ответов, модели эмбеддингов (HF) | частично |
| `/data/sessions/<id>/` | файлы документов сессии | да |
| том `boasi_ollama_models` | скачанные модели Ollama | нет (качаются заново) |

## 4. Бэкап и восстановление

```bash
make backup                       # -> backups/boasi-YYYYmmdd-HHMMSS.tar.gz
make restore ARCHIVE=backups/....tar.gz
```

Скрипты снимают том `boasi_data`; при запущенном стеке сначала делается
консистентный снимок SQLite (WAL), затем пакуются файлы. Восстановление
требует остановленного стека (`make down`) и полностью заменяет содержимое тома.

Автоматизация (cron, раз в сутки):

```cron
30 3 * * * cd /opt/bosi_s && make backup >> /var/log/boasi-backup.log 2>&1
```

**Проверка бэкапа** (её надо делать руками, автомат не проверит):

```bash
make restore ARCHIVE=backups/последний.tar.gz && make up
make health
```

## 5. Обновление

```bash
make backup                                   # сначала
git pull && make up --build                   # пересборка
```

Миграции применяются автоматически при старте контейнера
(`alembic upgrade head` в CMD). Откат миграций не автоматизирован.

## 6. Модели

`LLM_MODEL` — единственный параметр смены модели. Скорость на dev-машине
не оптимизируется, в бою меняется только значение в `.env`:

```bash
# в бою на GPU-машине
LLM_MODEL=ollama/qwen2.5:14b
make pull-models && make up
```

Код не содержит ни одной константы, завязанной на скорость: `evidence_k`,
`answer_max_sources`, таймауты LLM — только из конфигурации.

## 7. Наблюдаемость

| Что | Где |
| --- | --- |
| Здоровье | `GET /api/health` — статус, БД, модель, доступность Ollama |
| Метрики (Prometheus) | `GET /api/metrics` — текстовый формат |
| Метрики (глазами) | `GET /api/metrics.json` |
| Блокировки | `GET /api/health/locks` |
| Логи | `docker compose logs -f backend` — JSON в stdout |
| Аудит действий | вкладка «Аудит» в админ-панели, таблица `audit_log` |

Логи структурированы: `{"ts", "level", "logger", "msg", ...}`.

Что стоит смотреть в первую очередь при жалобах «медленно»:

```bash
make metrics    # uptime, документы, чанки, активные задачи
```

Медленный ответ — это норма для CPU-инференса (Фаза 0: 1,5–6 минут на ответ
при `qwen2.5:3b`). Смотрите, не выполняется ли вместо одного запроса два.

## 8. Диагностика

| Симптом | Причина | Что делать |
| --- | --- | --- |
| Backend не стартует, в логах про `SECRET_KEY` | ключ короче 32 символов или шаблонный | сгенерировать новый (раздел 2) |
| `/api/health` = `degraded` | недоступна БД | проверить том `boasi_data` и права |
| `ollama.reachable: false` | модель не скачана или сервис не поднят | `make pull-models` |
| Ответ «модель не найдена» | нет `LLM_MODEL` в томе Ollama | `make pull-models` |
| Индекс пуст после рестарта | повреждён `PQA_HOME` | восстановить из бэкапа, затем `make reindex` |
| Долгий логин, 429 | сработал rate-limit | подождать `LOGIN_LOCKOUT_SECONDS` |

Частые логи и их смысл:

```bash
docker compose logs backend | grep -E '"level": "(ERROR|WARNING)"' | tail -50
```

## 9. Безопасность (hardening)

Что включено:

* `SECRET_KEY` обязателен: короткий или шаблонный — приложение не стартует;
* rate-limit на `/api/auth/login`: неудачных попыток не больше
  `LOGIN_MAX_ATTEMPTS` за `LOGIN_WINDOW_SECONDS` с IP, блокировка на
  `LOGIN_LOCKOUT_SECONDS` (429);
* **валидация путей**: документ нельзя добавить откуда угодно — только из
  каталога своей сессии, общего каталога документов или каталога данных
  (для админа). Симлинки наружу не обходят проверку, `..` не проходит;
* офлайн-режим по умолчанию: нет запросов к Crossref/Semantic Scholar;
* `multimodal=OFF`, приватность данных: наружу уходит только к вашему Ollama;
* пароли — argon2 (`pwdlib`), refresh-токены в БД только в виде хэша;
* доступ к БД и фронтенду — только с `127.0.0.1`.

Что стоит настроить перед боевым режимом:

```bash
ALLOW_EXTERNAL_IMPORT_PATHS=false   # оставить выключенным
OFFLINE_MODE=true
MULTIMODAL=false
LOG_LEVEL=INFO                     # WARNING в проде, если логов много
```

Если нужен импорт файлов из произвольных мест (например, с сетевого диска) —
`ALLOW_EXTERNAL_IMPORT_PATHS=true`, но файлы всё равно не выйдут за пределы
каталога данных. Приложение предупредит об этом в логах при старте.

## 10. Боевой режим (GPU)

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

prod-оверрайд добавляет: GPU passthrough для Ollama (NVIDIA, все карты),
`OLLAMA_KEEP_ALIVE=24h`, лимиты ресурсов, ротацию логов, `restart: always`.

Перед боевым запуском: смените `LLM_MODEL` на модель по объёму VRAM,
сгенерируйте `SECRET_KEY`, сделайте бэкап.

## 11. Ограничения

* Один процесс backend: реестр фоновых задач и «аренды» сессий живут в памяти,
  после рестарта незавершённые задачи теряются (их можно поставить заново),
  окно rate-limit обнуляется. Несколько реплик backend не поддерживаются —
  платформа по ТЗ локальная и однопользовательская по контуру.
* SQLite + WAL: рассчитан на один процесс записи, не на высокую конкуренцию.
* Модель эмбеддингов качается из HuggingFace при первом старте. Для полностью
  оффлайн-контура нужен `make warm-embedding` или предзагрузка в том.