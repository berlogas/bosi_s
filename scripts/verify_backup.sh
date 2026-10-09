#!/usr/bin/env bash
# Проверка бэкапа БЕЗ последствий: архив распаковывается во временное место,
# проверяется целостность SQLite и наличие файлов, временное место удаляется.
#
#   ./scripts/verify_backup.sh backups/boasi-20261002-120000.tar.gz
#   make backup-verify ARCHIVE=backups/boasi-20261002-120000.tar.gz
#
# Смысл: «бэкап снят» ничего не значит, пока из него не восстанавливались.
# Этот скрипт — дешёвая замена ручному «развернуть и посмотреть».
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck source=scripts/lib_backup.sh
. scripts/lib_backup.sh

ARCHIVE="${1:-${ARCHIVE:-}}"
[ -n "$ARCHIVE" ] || die "Укажите архив: make backup-verify ARCHIVE=backups/....tar.gz"
[ -f "$ARCHIVE" ] || die "Файл не найден: $ARCHIVE"

detect_mode
# Распаковываем во временный каталог рядом с системным: боевые данные не
# трогаем ни при каких обстоятельствах.
CHECK_DIR="$(mktemp -d)"
cleanup() { rm -rf "$CHECK_DIR"; }
trap cleanup EXIT

# ------------------------------------------------------- 1. контрольная сумма
log "контрольная сумма"
verify_sha256 "$(cd "$(dirname "$ARCHIVE")" && pwd)" "$(basename "$ARCHIVE")" \
  || die "sha256 не совпал — архив битый"

# ------------------------------------------------------------ 2. распаковка
log "распаковка во временный каталог"
tar -xzf "$ARCHIVE" -C "$CHECK_DIR" || die "архив не распаковывается"

# снимок кладём на место БД — так же, как это делает restore.sh
rm -f "$CHECK_DIR/boasi.sqlite3-wal" "$CHECK_DIR/boasi.sqlite3-shm"
if [ -f "$CHECK_DIR/.backup-snapshot.sqlite3" ]; then
  mv "$CHECK_DIR/.backup-snapshot.sqlite3" "$CHECK_DIR/boasi.sqlite3"
fi
rm -f "$CHECK_DIR/.backup-snapshot.sqlite3"

# --------------------------------------------------------- 3. проверки
FAIL=0
DB="$CHECK_DIR/boasi.sqlite3"
if [ ! -f "$DB" ]; then
  echo "   [FAIL] boasi.sqlite3 отсутствует — в архиве нет снимка базы"
  FAIL=1
else
  DB_SIZE="$(wc -c < "$DB" | tr -d ' ')"
  echo "   [ok] boasi.sqlite3: $DB_SIZE байт"
fi

if [ "$FAIL" = "0" ]; then
  RESULT="$(sqlite_integrity "$DB")"
  case "$RESULT" in
    ok) echo "   [ok] integrity_check: ok" ;;
    "")  echo "   [FAIL] integrity_check выполнить не удалось"; FAIL=1 ;;
    *)   echo "   [FAIL] SQLite повреждён: $RESULT"; FAIL=1 ;;
  esac

  PY="$(path_for_native "$(pick_python)")"
  INFO="$("$PY" - "$(path_for_native "$DB")" <<'PY' 2>/dev/null || true
import sqlite3, sys
con = sqlite3.connect("file:" + sys.argv[1].replace("\\", "/") + "?mode=ro", uri=True)
tables = [r[0] for r in con.execute(
    "SELECT name FROM sqlite_master WHERE type = ?", ("table",))]
if "alembic_version" in tables:
    row = con.execute("SELECT version_num FROM alembic_version LIMIT 1").fetchone()
    print("REV " + (row[0] if row else "?"))
else:
    print("REV none")
total = 0
for t in ("users", "research_sessions", "documents", "projects", "messages"):
    try:
        n = con.execute("SELECT count(*) FROM " + t).fetchone()[0]
    except Exception:
        n = -1
    total += max(n, 0)
    print(t + "=" + str(n))
print("TOTAL=" + str(total))
PY
)"
  printf '%s\n' "$INFO" | grep -q '^REV ' \
    && echo "   [i] ревизия схемы: $(printf '%s' "$INFO" | grep '^REV ' | head -1 | cut -d' ' -f2)"
  echo "   [i] строк по основным таблицам: $(printf '%s' "$INFO" | grep '^TOTAL=' | cut -d= -f2)"
fi

for dir in sessions documents pqa; do
  if [ -d "$CHECK_DIR/$dir" ]; then
    echo "   [ok] /$dir: $(find "$CHECK_DIR/$dir" -type f | wc -l | tr -d ' ') файлов"
  else
    echo "   [i] /$dir нет (нормально, если каталог не использовался)"
  fi
done

echo
if [ "$FAIL" = "1" ]; then
  die "бэкап НЕ пригоден для восстановления"
fi
ok "бэкап пригоден для восстановления (временные файлы удалены)"
echo "Восстановление:  ./scripts/restore.sh $ARCHIVE"