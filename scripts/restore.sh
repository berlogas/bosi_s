#!/usr/bin/env bash
# Восстановление данных boasi_s из архива, снятого scripts/backup.sh.
#
#   ./scripts/restore.sh backups/boasi-20261002-120000.tar.gz
#
# ВНИМАНИЕ: текущие данные тома заменяются полностью. Стек должен быть
# остановлен — иначе SQLite продолжит писать в удалённые файлы.
set -euo pipefail

ARCHIVE="${1:-}"
VOLUME="${BOASI_DATA_VOLUME:-boasi_data}"

if [ -z "$ARCHIVE" ]; then
  echo "Использование: $0 <backup.tar.gz>" >&2
  exit 1
fi
[ -f "$ARCHIVE" ] || { echo "Файл не найден: $ARCHIVE" >&2; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "docker не найден" >&2; exit 1; }

if docker ps --format '{{.Names}}' | grep -qE '^boasi-backend$'; then
  echo "Остановите стек перед восстановлением: make down" >&2
  exit 1
fi

echo "-> Восстановление $ARCHIVE в том $VOLUME"

docker volume inspect "$VOLUME" >/dev/null 2>&1 || {
  echo "Том $VOLUME не найден" >&2
  exit 1
}

# чистим содержимое тома, затем распаковываем архив
docker run --rm \
  -v "$VOLUME:/data" \
  alpine:3.20 sh -c 'rm -rf /data/* /data/.[!.]* 2>/dev/null || true'

docker run --rm \
  -v "$VOLUME:/data" \
  -v "$(cd "$(dirname "$ARCHIVE")" && pwd):/backup:ro" \
  alpine:3.20 \
  tar -xzf "/backup/$(basename "$ARCHIVE")" -C /data

echo "-> проверка целостности SQLite"
docker run --rm -v "$VOLUME:/data:ro" alpine:3.20 sh -c '
  if [ -f /data/boasi.sqlite3 ]; then
    ls -la /data/boasi.sqlite3
    echo "размер БД: $(stat -c %s /data/boasi.sqlite3) байт"
  else
    echo "ВНИМАНИЕ: boasi.sqlite3 не найден в архиве" >&2
    exit 1
  fi'

echo "OK. Запустите стек: make up"