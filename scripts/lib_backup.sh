#!/usr/bin/env bash
# Общая часть для backup.sh / restore.sh / verify_backup.sh.
#
# Главное, что здесь решается: платформа бывает развёрнута двумя способами,
# и данные лежат в разных местах:
#
#   local  — backend запущен из репозитория (scripts/start.sh), DATA_DIR=./data.
#            Это режим по умолчанию на машине разработки. Ни Docker, ни тома.
#   docker — backend в контейнере, данные в томе boasi_data (/data).
#
# Прежние версии скриптов умели только docker и падали с «Том boasi_data не
# найден», хотя данные лежат рядом, в ./data. Теперь режим определяется сам
# (или задаётся явно: BOASI_MODE=local|docker).

# shellcheck shell=bash

BOASI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ------------------------------------------------------------------ вывод
if [ -t 1 ]; then
  RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; BLU=$'\033[36m'; OFF=$'\033[0m'
else
  RED=""; GRN=""; YEL=""; BLU=""; OFF=""
fi

log()  { printf '%s->%s %s\n' "$BLU" "$OFF" "$*"; }
ok()   { printf '%s ok %s %s\n' "$GRN" "$OFF" "$*"; }
warn() { printf '%s!!%s %s\n' "$YEL" "$OFF" "$*" >&2; }
die()  { printf '%sxx%s %s\n' "$RED" "$OFF" "$*" >&2; exit 1; }

# Git Bash (MSYS) отдаёт пути в виде /c/Users/... — docker.exe их не понимает,
# а автоконвертация не срабатывает, когда в аргументе есть ':' (как в
# "-v /c/x/backups:/backup"). Конвертируем явно и отключаем автоконвертацию.
export MSYS_NO_PATHCONV=1
host_path() {
  if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else printf '%s' "$1"; fi
}

# ------------------------------------------------------------------ python
# Windows и Linux различаются путём к интерпретатору в venv.
pick_python() {
  if [ -x "$BOASI_ROOT/.venv/Scripts/python.exe" ]; then
    printf '%s' "$BOASI_ROOT/.venv/Scripts/python.exe"
  elif [ -x "$BOASI_ROOT/.venv/bin/python" ]; then
    printf '%s' "$BOASI_ROOT/.venv/bin/python"
  else
    printf 'python'
  fi
}

# ------------------------------------------------------------------ .env
# Достаём значение параметра из .env. Пустая строка в .env означает
# «не задано» (так же трактует app/config.py), поэтому пустое -> дефолт.
env_value() {
  local key="$1" default="${2:-}"
  local raw
  [ -f "$BOASI_ROOT/.env" ] || { printf '%s' "$default"; return; }
  raw="$(grep -E "^${key}=" "$BOASI_ROOT/.env" 2>/dev/null | head -1 | cut -d= -f2- || true)"
  raw="$(printf '%s' "$raw" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' \
        -e 's/^"//' -e 's/"$//')"
  if [ -z "$raw" ]; then printf '%s' "$default"; else printf '%s' "$raw"; fi
}

# DATA_DIR из .env относительный — разрешаем от корня репозитория (как это
# делает app.config._abs_path), иначе путь «теряется» при смене CWD.
resolve_data_dir() {
  local raw dir
  raw="$(env_value DATA_DIR "./data")"
  case "$raw" in
    /*|[A-Za-z]:[\\/]*) dir="$raw" ;;
    *) dir="$BOASI_ROOT/${raw#./}" ;;
  esac
  # нормализация ./ и ../ без python
  dir="$(printf '%s' "$dir" | sed -e 's|/\./|/|g' -e 's|/\.\./|/|g')"
  printf '%s' "$dir"
}

# ------------------------------------------------------------------ режим
# BOASI_MODE=local|docker — принудительный выбор; иначе определяем сами.
#
# данными есть — работаем локально. И наоборот.
detect_mode() {
  local volume data_dir docker_ok=0
  volume="${BOASI_DATA_VOLUME:-boasi_data}"
  data_dir="$(resolve_data_dir)"

  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    docker_ok=1
  fi

  local requested="${BOASI_MODE:-auto}"
  case "$requested" in
    local|docker)
      MODE="$requested"
      ;;
    auto)
      if [ "$docker_ok" = "1" ] && docker volume inspect "$volume" >/dev/null 2>&1; then
        MODE="docker"
      elif [ -d "$data_dir" ]; then
        MODE="local"
      elif [ "$docker_ok" = "1" ]; then
        MODE="docker"
      else
        MODE="local"
      fi
      ;;
    *)
      die "BOASI_MODE должен быть local или docker, а не «${requested}»"
      ;;
  esac

  if [ "$MODE" = "local" ]; then
    DATA_PATH="$data_dir"
  else
    DATA_PATH="$volume"
  fi
}

# Что описывает источник данных — для сообщений и проверок.
describe_source() {
  if [ "$MODE" = "local" ]; then
    printf 'локальный каталог %s' "$DATA_PATH"
  else
    printf 'том Docker %s' "$DATA_PATH"
  fi
}

# Есть ли в источнике хоть какие-то данные.
source_exists() {
  if [ "$MODE" = "local" ]; then
    [ -d "$DATA_PATH" ]
  else
    command -v docker >/dev/null 2>&1 && docker volume inspect "$DATA_PATH" >/dev/null 2>&1
  fi
}

source_has_files() {
  if [ "$MODE" = "local" ]; then
    [ -n "$(ls -A "$DATA_PATH" 2>/dev/null || true)" ]
  else
    command -v docker >/dev/null 2>&1 \
      && [ -n "$(docker run --rm -v "$DATA_PATH:/data:ro" alpine:3.20 \
               sh -c 'ls -A /data 2>/dev/null' 2>/dev/null)" ]
  fi
}

# Путь к БД внутри источника (для локального режима — на хосте).
db_file_local() {
  printf '%s/boasi.sqlite3' "$DATA_PATH"
}

# Путь для передачи В ПРОГРАММУ (python/cygpath), а не для bash.
# Под Git Bash это /n/Development/..., который нативный python.exe не открывает.
# Такое происходит со всеми путями репозитория: сам $BOASI_ROOT уже в виде /n/...
path_for_native() {
  host_path "$1"
}

# ------------------------------------------------------- согласованный снимок
# sqlite .backup даёт самодостаточный файл; «файл + -wal как есть» может не
# восстановиться, потому что они читаются в разные моменты.
# Результат: путь к файлу-снимку.
make_db_snapshot() {
  local dest="$1" src="$2" py
  py="$(pick_python)"
  # python — нативная программа Windows, пути MSYS ему не подходят
  "$py" - "$(path_for_native "$src")" "$(path_for_native "$dest")" <<'PY'
import sqlite3, sys, os
src, dst = sys.argv[1], sys.argv[2]
if not os.path.exists(src):
    print("НЕТ БД: " + src, file=sys.stderr)
    raise SystemExit(3)
with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
    s.backup(d)
PY
}

# --------------------------------------------------------- проверка архива
verify_sha256() {
  local dir="$1" name="$2"
  local sha_file="$dir/$name.sha256"
  local cr
  cr="$(printf '\015')"
  [ -f "$sha_file" ] || { warn "нет $name.sha256 — целостность не гарантируется"; return 0; }
  if command -v sha256sum >/dev/null 2>&1; then
    (cd "$dir" && tr -d "$cr" < "$name.sha256" | sha256sum -c -) || return 1
  elif command -v shasum >/dev/null 2>&1; then
    (cd "$dir" && tr -d "$cr" < "$name.sha256" | shasum -a 256 -c -) || return 1
  else
    warn "нет sha256sum/shasum — проверка пропущена"
  fi
  return 0
}

write_sha256() {
  local dir="$1" name="$2" cr
  cr="$(printf '\015')"
  if command -v sha256sum >/dev/null 2>&1; then
    (cd "$dir" && sha256sum "$name" | tr -d "$cr" > "$name.sha256")
  elif command -v shasum >/dev/null 2>&1; then
    (cd "$dir" && shasum -a 256 "$name" | tr -d "$cr" > "$name.sha256")
  else
    warn "нет sha256sum/shasum — контрольная сумма не записана"
  fi
}

# --------------------------------------------------------- целостность SQLite
# Печатает результат PRAGMA integrity_check. Пустой вывод = не удалось проверить.
sqlite_integrity() {
  local db="$1" py
  py="$(pick_python)"
  "$py" - "$(path_for_native "$db")" <<'PY' 2>/dev/null || true
import sqlite3, sys
try:
    con = sqlite3.connect("file:" + sys.argv[1].replace("\\", "/") + "?mode=ro", uri=True)
    print(con.execute("PRAGMA integrity_check").fetchone()[0])
except Exception:
    pass
PY
}