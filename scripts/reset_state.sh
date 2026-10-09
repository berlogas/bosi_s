#!/usr/bin/env bash
# Сброс состояния boasi_s через контейнер backend: пути /data внутри
# контейнера совпадают с боевыми, поэтому чистится именно то, что в бою.
#
#   ./scripts/reset_state.sh                       # план сброса данных
#   ./scripts/reset_state.sh --scope users         # план сброса входов
#   ./scripts/reset_state.sh --scope data --yes --confirm 'СБРОС ДАННЫХ'
#
# По умолчанию ничего не удаляется: печатается план (таблицы, строки,
# каталоги, байты). Реальное удаление требует --yes и точной фразы.
set -euo pipefail

cd "$(dirname "$0")/.."
COMPOSE_FILE="${BOASI_COMPOSE_FILE:-docker-compose.yml}"

command -v docker >/dev/null 2>&1 || { echo "docker не найден" >&2; exit 1; }

# Бэкап перед разрушающей операцией: без --no-backup снимаем том целиком.
WANTS_DESTRUCTIVE=0
for arg in "$@"; do
  [ "$arg" = "--yes" ] && WANTS_DESTRUCTIVE=1
done

if [ "$WANTS_DESTRUCTIVE" = "1" ] && [ "${NO_BACKUP:-0}" != "1" ]; then
  if docker ps --format '{{.Names}}' | grep -q '^boasi-backend$'; then
    echo "-> сброс при работающем backend: сначала снимаю бэкап"
    ./scripts/backup.sh || { echo "бэкап не удался - сброс отменён" >&2; exit 1; }
  fi
fi

run_cli() {
  # ENVIRONMENT намеренно не переопределяем: он приходит из .env через
  # env_file, иначе сброс в prod незаметно прошёл бы как в dev.
  docker compose -f "$COMPOSE_FILE" run --rm --no-deps \
    backend python scripts/reset_state.py "$@"
}

run_cli "$@"