#!/usr/bin/env bash
# Бэкап данных boasi_s.
#
#   ./scripts/backup.sh                    -> backups/boasi-YYYYmmdd-HHMMSS.tar.gz
#   ./scripts/backup.sh out.tar.gz         -> свой путь
#   CONFIG_BACKUP=1 ./scripts/backup.sh    -> ещё и .env (SECRET_KEY) отдельным файлом
#   MODELS_BACKUP=1 ./scripts/backup.sh    -> ещё и модели Ollama (много гигабайт)
#   KEEP_BACKUPS=14 ./scripts/backup.sh    -> оставить 14 последних архивов
#   BOASI_MODE=local|docker ./scripts/backup.sh   -> принудительный выбор режима
#
# Режим (каталог ./data или том Docker boasi_data) определяется автоматически —
# см. scripts/lib_backup.sh. Локальный режим не требует Docker вообще.
#
# Что попадает в архив:
#   .backup-snapshot.sqlite3 — согласованный снимок БД (sqlite .backup, а НЕ
#       «файл + -wal как есть»: снятые в разные моменты они могут не
#       согласоваться). Внутри архива лежит под служебным именем; restore.sh
#       кладёт его на место boasi.sqlite3, поэтому архив самодостаточен;
#   sessions/, documents/, pqa/ — файлы сессий, документов, кэш ответов;
#   hf/, torch/ — кэш моделей эмбеддингов, если он есть;
#   boasi-manifest.json — что снято: ревизия схемы, строки, объём.
#
# Живая boasi.sqlite3 вместе с -wal/-shm в архив НЕ попадает.
# Рядом пишется boasi-<stamp>.tar.gz.sha256: restore.sh проверяет его ДО
# очистки данных, чтобы битый архив не съел рабочее состояние.
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck source=scripts/lib_backup.sh
. scripts/lib_backup.sh

BACKUP_DIR="${BOASI_BACKUP_DIR:-backups}"
KEEP_BACKUPS="${KEEP_BACKUPS:-0}"          # 0 = хранить всё
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="${1:-$BACKUP_DIR/boasi-$STAMP.tar.gz}"
OUT_DIR="$(cd "$(dirname "$OUT")" 2>/dev/null && pwd || dirname "$OUT")"
OUT_NAME="$(basename "$OUT")"
ALPINE="alpine:3.20"
SNAPSHOT_REL="./.backup-snapshot.sqlite3"

detect_mode
log "источник данных: $(describe_source)"

if [ "$MODE" = "docker" ]; then
  source_exists || {
    echo "Том $DATA_PATH не найден. Запустите стек (make up) или создайте том:" >&2
    echo "  docker volume create $DATA_PATH" >&2
    echo "Либо укажите локальный каталог: BOASI_MODE=local ./scripts/backup.sh" >&2
    exit 1
  }
fi
[ -d "$OUT_DIR" ] || mkdir -p "$OUT_DIR"
mkdir -p "$BACKUP_DIR"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# ------------------------------------------- 1. согласованный снимок SQLite
log "снимок SQLite"
snapshot_ok=0
if [ "$MODE" = "local" ]; then
  if make_db_snapshot "$TMP/boasi.sqlite3" "$(db_file_local)"; then
    snapshot_ok=1
  else
    warn "не удалось снять снимок (нет БД?) — продолжу без него"
  fi
else
  STACK_UP=0
  if docker ps --format '{{.Names}}' | grep -q '^boasi-backend$'; then STACK_UP=1; fi
  BACKEND_IMAGE="$(docker compose images -q backend 2>/dev/null | head -1 || true)"
  if [ "$STACK_UP" = "1" ]; then
    # ВАЖНО: -i обязателен, иначе stdin (код на stdin) не доедет до python.
    if docker exec -i boasi-backend python - /data/.backup-snapshot.sqlite3 <<'PY'
import sqlite3, sys
src, dst = "/data/boasi.sqlite3", sys.argv[1]
try:
    with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
        s.backup(d)
except Exception as exc:
    print(f"snapshot failed: {exc}", file=sys.stderr)
    raise SystemExit(1)
PY
    then snapshot_ok=1; else die "не удалось снять снимок БД"; fi
  elif [ -n "$BACKEND_IMAGE" ]; then
    if docker run --rm -i -v "$DATA_PATH:/data" "$BACKEND_IMAGE" \
         python - /data/.backup-snapshot.sqlite3 <<'PY'
import sqlite3, sys
src, dst = "/data/boasi.sqlite3", sys.argv[1]
try:
    with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
        s.backup(d)
except Exception as exc:
    print(f"snapshot failed: {exc}", file=sys.stderr)
    raise SystemExit(1)
PY
    then snapshot_ok=1; fi
  fi
fi

if [ "$snapshot_ok" = "1" ]; then
  ok "снимок готов, он и попадёт в архив (живая БД исключается)"
else
  warn "снимка БД не будет: архив получится без базы данных"
fi

# ------------------------------------------------------ 2. манифест архива
if [ "$MODE" = "local" ]; then
  # пути к backend/ и к данным — нативные: python.exe не понимает /n/...
  if DATA_DIR="$(path_for_native "$(resolve_data_dir)")" \
     "$(path_for_native "$(pick_python)")" \
     "$(path_for_native "$BOASI_ROOT/backend/scripts/backup_manifest.py")" \
     > "$TMP/boasi-manifest.json" 2>/dev/null; then
    :
  else
    warn "манифест собрать не удалось — архив будет без него"
    rm -f "$TMP/boasi-manifest.json"
  fi
else
  if [ "$STACK_UP" = "1" ]; then
    MANIFEST_CMD=(docker exec boasi-backend python scripts/backup_manifest.py)
  elif [ -n "$BACKEND_IMAGE" ]; then
    MANIFEST_CMD=(docker run --rm -v "$DATA_PATH:/data:ro" -e DATA_DIR=/data \
      "$BACKEND_IMAGE" python scripts/backup_manifest.py)
  else
    MANIFEST_CMD=()
  fi
  if [ "${#MANIFEST_CMD[@]}" -gt 0 ]; then
    if ! "${MANIFEST_CMD[@]}" > "$TMP/boasi-manifest.json" 2>/dev/null; then
      warn "манифест собрать не удалось — архив будет без него"
      rm -f "$TMP/boasi-manifest.json"
    fi
  else
    warn "образ backend не собран — манифест не собрать (только каталоги)"
  fi
fi
[ -f "$TMP/boasi-manifest.json" ] && log "манифест: ревизия схемы, строки, объём"

# -------------------------------------------------------------- 3. сборка
# Каталог с данными копируется целиком, но без файлов БД: вместо них
# подставляется снимок из шага 1. Копия идёт во временный каталог, чтобы
# архив был собран из одного состояния, а не «появился на полпути».
log "сборка архива -> $OUT"
STAGE="$TMP/stage"
mkdir -p "$STAGE"

if [ "$MODE" = "local" ]; then
  # копируем содержимое DATA_DIR без файлов БД
  ( cd "$DATA_PATH" && tar -cf - \
      --exclude=./boasi.sqlite3 \
      --exclude=./boasi.sqlite3-wal \
      --exclude=./boasi.sqlite3-shm \
      --exclude=./.backup-snapshot.sqlite3 \
      . ) | ( cd "$STAGE" && tar -xf - )
  if [ "$snapshot_ok" = "1" ]; then
    cp "$TMP/boasi.sqlite3" "$STAGE/.backup-snapshot.sqlite3"
  fi
else
  docker run --rm -v "$DATA_PATH:/data:ro" "$ALPINE" sh -c \
    "cd /data && tar -cf - \
       --exclude=./boasi.sqlite3 \
       --exclude=./boasi.sqlite3-wal \
       --exclude=./boasi.sqlite3-shm \
       . " \
    | ( cd "$STAGE" && tar -xf - )
  if [ "$snapshot_ok" = "1" ]; then
    docker run --rm -v "$DATA_PATH:/data:ro" -v "$(host_path "$TMP"):/tmp:ro" \
      "$ALPINE" sh -c "cp /data/.backup-snapshot.sqlite3 /tmp/boasi.sqlite3" \
      && cp "$TMP/boasi.sqlite3" "$STAGE/.backup-snapshot.sqlite3"
  fi
fi

if [ -f "$TMP/boasi-manifest.json" ]; then
  cp "$TMP/boasi-manifest.json" "$STAGE/boasi-manifest.json"
fi

log "упаковка"
( cd "$STAGE" && tar -czf "$OUT_DIR/$OUT_NAME" . ) \
  || die "не удалось собрать архив $OUT"
[ -f "$OUT" ] || die "архив не создан: $OUT"

# --------------------------------------------------------- 4. самопроверка
# Снимок внутри есть, живой БД — нет. Если исключения не сработали
# (бывает у нестандартных tar), узнаем сейчас, а не при аварии.
log "самопроверка архива"
LIST="$(tar -tzf "$OUT" 2>/dev/null || true)"
[ -n "$LIST" ] || die "архив не читается — скорее всего, он пустой"
COUNT="$(printf '%s\n' "$LIST" | grep -vc '/$' || true)"
echo "   файлов в архиве: $COUNT"

if [ "$snapshot_ok" != "1" ]; then
  die "архив без базы данных бесполезен: укажите верный DATA_DIR (BOASI_MODE=local) или запустите стек в Docker"
fi
printf '%s\n' "$LIST" | grep -q "$SNAPSHOT_REL" \
  || die "в архиве нет снимка БД — архив непригоден, удалите его"
if printf '%s\n' "$LIST" | grep -q '^\./boasi\.sqlite3$'; then
  warn "в архив попала живая БД вместо снимка: восстановление может быть неконсистентным"
fi

# --------------------------------------------------- 5. контрольная сумма
write_sha256 "$OUT_DIR" "$OUT_NAME"

# --------------------------------------------- 6. конфигурация (по запросу)
if [ "${CONFIG_BACKUP:-0}" = "1" ]; then
  ENV_OUT="$OUT_DIR/boasi-$STAMP.env"
  if [ -f .env ]; then
    cp .env "$ENV_OUT"
    chmod 600 "$ENV_OUT" 2>/dev/null || true
    log "конфигурация (с SECRET_KEY) -> $ENV_OUT — хранить отдельно от данных"
  else
    warn ".env не найден — конфигурация не сохранена"
  fi
fi

# ------------------------------------------------ 7. модели Ollama (по запросу)
if [ "${MODELS_BACKUP:-0}" = "1" ]; then
  MODELS_VOLUME="${BOASI_MODELS_VOLUME:-boasi_ollama_models}"
  MODELS_OUT="boasi-models-$STAMP.tar.gz"
  if command -v docker >/dev/null 2>&1 \
     && docker volume inspect "$MODELS_VOLUME" >/dev/null 2>&1; then
    log "модели Ollama -> $OUT_DIR/$MODELS_OUT (это много гигабайт)"
    docker run --rm \
      -v "$MODELS_VOLUME:/models:ro" \
      -v "$(host_path "$OUT_DIR"):/backup" \
      "$ALPINE" tar -czf "/backup/$MODELS_OUT" -C /models . \
      || warn "модели не сохранились"
  else
    warn "том $MODELS_VOLUME не найден (Docker недоступен?) — модели пропущены"
  fi
fi

# ---------------------------------------------------------------- 8. ротация
if [ "$KEEP_BACKUPS" -gt 0 ] 2>/dev/null; then
  log "ротация: оставляю $KEEP_BACKUPS последних архивов"
  ( cd "$OUT_DIR" \
    && ls -1t boasi-*.tar.gz 2>/dev/null | tail -n "+$((KEEP_BACKUPS + 1))" \
       | while read -r old; do rm -f "$old" "$old.sha256"; echo "   удалён $old"; done ) || true
fi

SIZE="$(du -h "$OUT" | cut -f1)"
cat <<EOF

OK: $OUT ($SIZE)
  источник: $(describe_source)
  рядом: $OUT_NAME.sha256
  внутри: снимок БД, данные каталогов, boasi-manifest.json

Посмотреть состав, не распаковывая:  ./scripts/restore.sh $OUT --list
Проверить архив целиком:  make backup-verify ARCHIVE=$OUT
Восстановление:  ./scripts/stop.sh  (или make down)  &&  ./scripts/restore.sh $OUT
EOF