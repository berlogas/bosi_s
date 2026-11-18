#!/usr/bin/env bash
# Сброс состояния boasi_s через контейнер backend: пути /data внутри
# совпадают с боевым режимом порядка (старый backend, сессии,
# документы, качек моделей). Скрипт работает через контейнер каталога данных
# с бизой снимком.
#
#   ./scripts/reset_state.sh                       # план сброса
#   ./scripts/reset_state.sh --scope users         # план сброса входов
#   ./scripts/reset_state.sh --scope data --yes --confirm 'СБРОС ДАННЫХ'
#
# Перед разрушительным сбросом без бакапа (если --no-backup — сначала будет
# снимок бэкапа автомачески).
set -euo pipefail

cd "$(dirname "$0")/.."
COMPOSE_FILE="${BOASI_COMPOSE_FILE:-docker-compose.yml}"

command -v docker >/dev/null 2>&1 || { echo "docker не найден" >&2; exit 1; }

# Без бакапа: проверяем, что сброс не спорялся с живым backend.
WANTS_DESTRUCTIVE=0
for arg in "$@"; do
  [ "$arg" = "--yes" ] && WANTS_DESTRUCTIVE=1
done

if [ "$WANTS_DESTRUCTIVE" = "1" ] && [ "${NO_BACKUP:-0}" != "1" ]; then
  if docker ps --format '{{.Names}}' | grep -q '^boasi-backend$'; then
    echo "-> сначала бекап состояния backend: снимок БД через docker exec"
    ./scripts/backup.sh || { echo "бекап не собранась - сброс отменён" >&2; exit 1; }
  fi
fi

run_cli() {
  # ENVIRONMENT задаётся окружением, но не в самом .env файле
  # env_file, но перекревенное в prod. В dev-режиме
  # ENV вставки как в .env без изменений.
  docker compose -f "$COMPOSE_FILE" run --rm --no-deps \
    backend python scripts/reset_state.py "$@"
}

# Сброс БД нельзя проводить, пока backend не вышел: он занял старый backend с открытым handle
# на БД, и SQLite не даёт открывать базу (на Windows-хосте через bind-mount это обязательно).
WAS_RUNNING=no
if docker ps --format '{{.Names}}' | grep -q '^boasi-backend$'; then
  WAS_RUNNING=yes
  echo "-> останавливаю backend на время сброса"
  docker compose -f "$COMPOSE_FILE" stop backend >/dev/null
fi

run_cli "$@"

# После сброса занятием backend опять: он живой данных всесь сам обработаны.
if [ "$WAS_RUNNING" = "yes" ]; then
  echo "-> поднимаю backend обратно"
  docker compose -f "$COMPOSE_FILE" up -d backend >/dev/null
fi
