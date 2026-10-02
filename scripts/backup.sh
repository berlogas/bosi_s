#!/usr/bin/env bash
# Бэкап данных boasi_s: том boasi_data (SQLite + PQA_HOME + файлы сессий).
#
#   ./scripts/backup.sh              -> backups/boasi-YYYYmmdd-HHMMSS.tar.gz
#   ./scripts/backup.sh out.tar.gz   -> свой путь
#
# Бэкап снимается «на холодную»: том монтируется read-only в одноразовый
# контейнер, поэтому работает и при остановленном стеке, и при запущенном
# (SQLite в WAL — см. консистентность ниже).
set -euo pipefail

VOLUME="${BOASI_DATA_VOLUME:-boasi_data}"
BACKUP_DIR="${BOASI_BACKUP_DIR:-backups}"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="${1:-$BACKUP_DIR/boasi-$STAMP.tar.gz}"

command -v docker >/dev/null 2>&1 || { echo "docker не найден" >&2; exit 1; }
docker volume inspect "$VOLUME" >/dev/null 2>&1 || {
  echo "Том $VOLUME не найден. Запустите стек (make up) или создайте том." >&2
  exit 1
}

mkdir -p "$(dirname "$OUT")"
mkdir -p "$BACKUP_DIR"

# WAL-консистентность: сначала копия БД, затем файлы. Снимок БД делаем
# через sqlite3 .backup, чтобы не поймать половину транзакции.
echo "-> Бэкап тома $VOLUME в $OUT"

if docker ps --format '{{.Names}}' | grep -q '^boasi-backend$'; then
  echo "   стек запущен: делаем консистентный снимок SQLite"
  docker exec boasi-backend python - <<'PY' || true
import shutil, sqlite3, os
src = "/data/boasi.sqlite3"
if os.path.exists(src):
    dst = "/data/.backup-snapshot.sqlite3"
    with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
        s.backup(d)
PY
fi

docker run --rm \
  -v "$VOLUME:/data:ro" \
  -v "$(cd "$(dirname "$OUT")" && pwd):/backup" \
  alpine:3.20 \
  tar -czf "/backup/$(basename "$OUT")" -C /data .

# убираем временный снимок, если он был создан
if docker ps --format '{{.Names}}' | grep -q '^boasi-backend$'; then
  docker exec boasi-backend rm -f /data/.backup-snapshot.sqlite3 || true
fi

SIZE="$(du -h "$OUT" | cut -f1)"
echo "OK: $OUT ($SIZE)"
echo "Восстановление: ./scripts/restore.sh $OUT"