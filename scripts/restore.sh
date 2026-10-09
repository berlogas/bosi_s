#!/usr/bin/env bash
# Восстановление данных boasi_s из архива, снятого scripts/backup.sh.
#
#   ./scripts/restore.sh backups/boasi-20261002-120000.tar.gz
#   ./scripts/restore.sh backups/boasi-....tar.gz --list     # состав, не трогая данные
#   ./scripts/restore.sh backups/boasi-....tar.gz --force    # не спрашивать
#   ./scripts/restore.sh backups/boasi-....tar.gz --target /path/to/data
#
# ВНИМАНИЕ: текущие данные заменяются полностью. Платформа должна быть
# остановлена — иначе SQLite продолжит писать в удалённые файлы.
#
# Порядок проверок важен: сначала контрольная сумма, потом манифест, и только
# потом — очистка. Битый архив не должен съесть рабочие данные.
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck source=scripts/lib_backup.sh
. scripts/lib_backup.sh

ARCHIVE=""
LIST_ONLY=0
FORCE=0
TARGET=""
ALPINE="alpine:3.20"

usage() {
  sed -n '3,9p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --list|-l)   LIST_ONLY=1 ;;
    --force|-f)  FORCE=1 ;;
    --target)    TARGET="${2:-}"; shift ;;
    -h|--help)   usage 0 ;;
    -*)          die "неизвестный ключ: $1 (--help)" ;;
    *)           ARCHIVE="$1" ;;
  esac
  shift
done

[ -n "$ARCHIVE" ] || usage 1
[ -f "$ARCHIVE" ] || die "Файл не найден: $ARCHIVE"

detect_mode
# Куда восстанавливаем: явно заданный каталог, иначе текущий источник.
if [ -n "$TARGET" ]; then
  case "$TARGET" in
    /*|[A-Za-z]:[\\/]*) RESTORE_PATH="$TARGET" ;;
    *) RESTORE_PATH="$BOASI_ROOT/${TARGET#./}" ;;
  esac
elif [ "$MODE" = "local" ]; then
  RESTORE_PATH="$DATA_PATH"
else
  RESTORE_PATH="$DATA_PATH"     # имя тома; для докера путь неважен
fi

ARCHIVE_DIR="$(cd "$(dirname "$ARCHIVE")" && pwd)"
ARCHIVE_NAME="$(basename "$ARCHIVE")"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mount_archive() { echo "-v $(host_path "$ARCHIVE_DIR"):/backup:ro"; }

# ------------------------------------------------- 1. контрольная сумма
log "проверка контрольной суммы"
verify_sha256 "$ARCHIVE_DIR" "$ARCHIVE_NAME" \
  || die "архив повреждён (sha256 не совпал) — восстановление отменено"

# ------------------------------------------------------- 2. состав архива
log "состав архива"
CONTENTS="$(tar -tzf "$ARCHIVE" 2>/dev/null || true)"
[ -n "$CONTENTS" ] || die "архив не читается (битый gzip?)"
COUNT="$(printf '%s\n' "$CONTENTS" | grep -vc '/$' || true)"
echo "   файлов в архиве: $COUNT"

HAS_DB=0
if printf '%s\n' "$CONTENTS" | grep -q '\.backup-snapshot\.sqlite3$'; then HAS_DB=1; fi

show_manifest() {
  local m
  m="$(tar -xzOf "$ARCHIVE" ./boasi-manifest.json 2>/dev/null || true)"
  [ -n "$m" ] || { echo "   манифеста нет (бэкап снят старой версией скрипта)"; return 0; }
  printf '%s' "$m" | "$(path_for_native "$(pick_python)")" -c '
import json, sys
try:
    m = json.load(sys.stdin)
except Exception:
    print("   манифест не читается, продолжаем")
    raise SystemExit(0)
t = m.get("totals") or {}
print("   снят:             " + str(m.get("created_at", "?")))
print("   версия платформы: " + str(m.get("app_version", "?")))
print("   ревизия схемы:    " + str(m.get("alembic_revision") or "?")
      + " (в коде: " + str(m.get("alembic_head") or "?") + ")")
print("   строк: {}, файлов: {}, байт: {}".format(
      t.get("rows", "?"), t.get("files", "?"), t.get("bytes", "?")))
tables = m.get("tables") or {}
for name in ("users", "research_sessions", "documents", "projects", "messages"):
    if name in tables:
        print("     {:<20} {}".format(name, tables[name]))
if (m.get("alembic_revision") and m.get("alembic_head")
        and m["alembic_revision"] != m["alembic_head"]):
    print("   ВНИМАНИЕ: архив старше кода — после запуска применятся миграции")
for w in m.get("warnings") or []:
    print("   !! " + str(w))
' 2>/dev/null || echo "   (разбор манифеста не удался)"
}

if [ "$LIST_ONLY" = "1" ]; then
  echo
  printf '%s\n' "$CONTENTS" | sed 's|^\./||' | grep -v '/$' | head -50
  [ "$COUNT" -gt 50 ] && echo "   ... и ещё $((COUNT - 50))"
  echo
  echo "Манифест:"
  show_manifest
  exit 0
fi

[ "$HAS_DB" = "1" ] || warn "в архиве нет снимка БД — база данных не восстановится"

# ------------------------------------------- 3. манифест: ревизия и объём
log "манифест архива"
show_manifest
echo

# --------------------------------------------- 4. платформа должна быть остановлена
backend_running() {
  # локальный режим: процесс слушает наш порт
  curl -fsS "http://127.0.0.1:${API_PORT:-8000}/api/health" >/dev/null 2>&1
}

if [ "$MODE" = "docker" ]; then
  if docker ps --format '{{.Names}}' | grep -qE '^boasi-backend$'; then
    die "Остановите стек перед восстановлением: make down"
  fi
else
  # Проверяем работающую платформу только если восстанавливаем В ЕЁ каталог.
  # Восстановление в другой каталог (--target) не трогает запущенный backend.
  if backend_running; then
    if [ "$RESTORE_PATH" = "$DATA_PATH" ]; then
      die "Платформа отвечает на порту ${API_PORT:-8000} и использует этот каталог. Остановите её: ./scripts/start.sh stop"
    fi
    warn "платформа сейчас работает (порт ${API_PORT:-8000}), но восстановляем в ДРУГОЙ каталог — продолжаю"
  fi
fi

if [ "$FORCE" != "1" ]; then
  echo "Данные ($( [ "$MODE" = "local" ] && echo "каталог $RESTORE_PATH" || echo "том $RESTORE_PATH" )) будут удалены полностью."
  printf 'Введите слово ВОССТАНОВИТЬ для подтверждения: '
  read -r ANSWER || true
  [ "$ANSWER" = "ВОССТАНОВИТЬ" ] || die "подтверждение не получено — отменено"
fi

# ------------------------------------------------------ 5. страховка текущих
# Если восстановят не тот архив — предыдущее состояние должно остаться.
SAFETY_DIR="$ARCHIVE_DIR/pre-restore"
mkdir -p "$SAFETY_DIR"
SAFETY="$SAFETY_DIR/pre-restore-$(date +%Y%m%d-%H%M%S).tar.gz"

has_current() {
  if [ "$MODE" = "local" ]; then
    [ -d "$RESTORE_PATH" ] && [ -n "$(ls -A "$RESTORE_PATH" 2>/dev/null || true)" ]
  else
    docker volume inspect "$RESTORE_PATH" >/dev/null 2>&1 \
      && [ -n "$(docker run --rm -v "$RESTORE_PATH:/data:ro" "$ALPINE" \
               sh -c 'ls -A /data 2>/dev/null' 2>/dev/null)" ]
  fi
}

if has_current; then
  log "страховочная копия текущих данных -> $SAFETY"
  if [ "$MODE" = "local" ]; then
    tar -czf "$SAFETY" -C "$(dirname "$RESTORE_PATH")" "$(basename "$RESTORE_PATH")" \
      || warn "страховочную копию сделать не удалось — продолжаю"
  else
    docker run --rm -v "$RESTORE_PATH:/data:ro" -v "$(host_path "$SAFETY_DIR"):/backup" \
      "$ALPINE" tar -czf "/backup/$(basename "$SAFETY")" -C /data . \
      || warn "страховочную копию сделать не удалось — продолжаю"
  fi
fi

# --------------------------------------------------------- 6. восстановление
if [ "$MODE" = "local" ]; then
  log "очищаю каталог $RESTORE_PATH"
  mkdir -p "$RESTORE_PATH"
  # скрытые файлы тоже: .install-state.json важен для bootstrap
  find "$RESTORE_PATH" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true
  log "распаковываю $ARCHIVE_NAME"
  tar -xzf "$ARCHIVE" -C "$RESTORE_PATH"
else
  docker volume inspect "$RESTORE_PATH" >/dev/null 2>&1 \
    || { log "создаю том $RESTORE_PATH"; docker volume create "$RESTORE_PATH" >/dev/null; }
  log "очищаю том $RESTORE_PATH"
  docker run --rm -v "$RESTORE_PATH:/data" "$ALPINE" \
    sh -c 'rm -rf /data/* /data/.[!.]* 2>/dev/null || true'
  log "распаковываю $ARCHIVE_NAME"
  docker run --rm -v "$RESTORE_PATH:/data" $(mount_archive) "$ALPINE" \
    tar -xzf "/backup/$ARCHIVE_NAME" -C /data
fi

# снимок кладём на место живой БД (её в архиве нет) и убираем хвосты WAL
if [ "$MODE" = "local" ]; then
  rm -f "$RESTORE_PATH/boasi.sqlite3-wal" "$RESTORE_PATH/boasi.sqlite3-shm"
  if [ -f "$RESTORE_PATH/.backup-snapshot.sqlite3" ]; then
    mv "$RESTORE_PATH/.backup-snapshot.sqlite3" "$RESTORE_PATH/boasi.sqlite3"
    echo "   БД восстановлена из снимка"
  fi
  rm -f "$RESTORE_PATH/.backup-snapshot.sqlite3"
  # alpine распаковывает от root; в локальном режиме файлы и так наши,
  # но Windows иногда ставит read-only — снимаем флаг на всякий случай
  chmod -R u+rwX "$RESTORE_PATH" 2>/dev/null || true
else
  # Владелец: backend работает как boasi (uid 1000). Без chown платформа
  # поднимется, но не сможет писать в БД.
  docker run --rm -v "$RESTORE_PATH:/data" "$ALPINE" sh -c '
    set -e
    if [ -f /data/.backup-snapshot.sqlite3 ]; then
      rm -f /data/boasi.sqlite3-wal /data/boasi.sqlite3-shm
      mv /data/.backup-snapshot.sqlite3 /data/boasi.sqlite3
      echo "   БД восстановлена из снимка"
    fi
    rm -f /data/.backup-snapshot.sqlite3
  '
  BACKEND_IMAGE="$(docker compose images -q backend 2>/dev/null | head -1 || true)"
  if [ -n "$BACKEND_IMAGE" ]; then
    docker run --rm -u root -v "$RESTORE_PATH:/data" "$BACKEND_IMAGE" \
      chown -R boasi:boasi /data || warn "не удалось выставить владельца boasi"
  else
    warn "образ backend не собран — владельца файлов выставить нечем"
  fi
fi

# ------------------------------------------- 7. проверка целостности (sqlite)
log "проверка целостности SQLite"
if [ "$MODE" = "local" ]; then
  DB="$RESTORE_PATH/boasi.sqlite3"
else
  DB="";  # ниже идём через контейнер
fi

if [ "$MODE" = "local" ]; then
  if [ ! -f "$DB" ]; then
    die "boasi.sqlite3 не восстановился — данных нет, разбирайся с архивом"
  fi
  DB_SIZE="$(wc -c < "$DB" | tr -d ' ')"
  RESULT="$(sqlite_integrity "$DB")"
  case "$RESULT" in
    ok) echo "   integrity_check: ok ($DB_SIZE байт)" ;;
    "") warn "integrity_check не выполнен (python недоступен)" ;;
    *) die "SQLite повреждён: $RESULT" ;;
  esac
else
  DB_SIZE="$(docker run --rm -v "$RESTORE_PATH:/data:ro" "$ALPINE" sh -c \
    'if [ -f /data/boasi.sqlite3 ]; then stat -c %s /data/boasi.sqlite3; else echo 0; fi')"
  if [ "$DB_SIZE" = "0" ]; then
    die "boasi.sqlite3 не восстановился — данных нет, разбирайся с архивом"
  fi
  BACKEND_IMAGE="$(docker compose images -q backend 2>/dev/null | head -1 || true)"
  if [ -n "$BACKEND_IMAGE" ]; then
    RESULT="$(docker run --rm -v "$RESTORE_PATH:/data:ro" "$BACKEND_IMAGE" python -c '
import sqlite3
try:
    con = sqlite3.connect("file:/data/boasi.sqlite3?mode=ro", uri=True)
    print(con.execute("PRAGMA integrity_check").fetchone()[0])
except Exception as exc:
    print("ERROR: " + str(exc))
' 2>/dev/null || echo "SKIP")"
    case "$RESULT" in
      ok) echo "   integrity_check: ok ($DB_SIZE байт)" ;;
      SKIP|"") warn "integrity_check не выполнен (нет образа backend)" ;;
      *) die "SQLite повреждён: $RESULT" ;;
    esac
  else
    warn "образ backend не собран — integrity_check пропущен"
    echo "   размер boasi.sqlite3: $DB_SIZE байт"
  fi
fi

# ---------------------------------------------------------------- итог
if [ "$MODE" = "local" ]; then
  echo
  cat <<EOF
OK: каталог $RESTORE_PATH восстановлен из $ARCHIVE_NAME
  БД: $DB_SIZE байт, каталогов: $(ls -A "$RESTORE_PATH" | grep -vc '/$' || true)

Дальше:
  ./scripts/start.sh          # запустить backend и React
  ./scripts/start.sh status   # дождаться status: ok
EOF
else
  echo
  cat <<EOF
OK: том $RESTORE_PATH восстановлен из $ARCHIVE_NAME
  БД: $DB_SIZE байт

Дальше:
  make up          # миграции (alembic upgrade head) накатятся автоматически
  make health      # ждём status: ok
EOF
fi