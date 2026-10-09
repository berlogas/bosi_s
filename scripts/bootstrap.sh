#!/usr/bin/env bash
# Первичная установка boasi_s на новом сервере. Идемпотентно: повторный
# запуск на развёрнутом сервере ничего не ломает, только дописывает недостающее.
#
#   ./scripts/bootstrap.sh                              # полный цикл, пароль спросит
#   ADMIN_USERNAME=admin ADMIN_PASSWORD=... ./scripts/bootstrap.sh   # без ввода
#
# Шаги: .env и SECRET_KEY -> том данных -> модели -> стек -> здоровье -> админ.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
ENV_FILE="${ROOT}/.env"
DATA_VOLUME="${BOASI_DATA_VOLUME:-boasi_data}"
API_URL="${BOASI_API_URL:-http://127.0.0.1:8000}"
ADMIN_USERNAME="${ADMIN_USERNAME:-admin}"
PYTHON_BIN="$(command -v python3 || command -v python || true)"

log()  { printf '\033[36m->\033[0m %s\n' "$*"; }
warn() { printf '\033[33m!!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31mxx\033[0m %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "docker не найден (нужен Docker 24+ / Compose v2)"
docker compose version >/dev/null 2>&1 || die "docker compose v2 не найден"

# ---------------------------------------------------------------- 1. .env + ключ
if [ ! -f "$ENV_FILE" ]; then
  [ -f "${ROOT}/.env.example" ] || die "нет .env.example - скопируйте его в .env вручную"
  log "создаю .env из .env.example"
  cp "${ROOT}/.env.example" "$ENV_FILE"
else
  log ".env уже есть - не трогаю"
fi

# SECRET_KEY генерируется только если там шаблон: перезаписывать ключ на
# работающем сервере нельзя - это отозвало бы все выданные JWT.
CURRENT_KEY="$(grep -E '^SECRET_KEY=' "$ENV_FILE" | cut -d= -f2- || true)"
if printf '%s' "$CURRENT_KEY" | grep -qi 'change-me'; then
  [ -n "$PYTHON_BIN" ] || die "нужен python для генерации SECRET_KEY"
  NEW_KEY="$("$PYTHON_BIN" -c 'import secrets; print(secrets.token_urlsafe(48))')"
  log "генерирую SECRET_KEY"
  # Переносимо: sed -i на BSD/macOS требует аргумент, поэтому правим через python.
  "$PYTHON_BIN" - "$ENV_FILE" "$NEW_KEY" <<'PY'
import io, sys
path, key = sys.argv[1], sys.argv[2]
lines = io.open(path, encoding="utf-8").read().splitlines()
out = ["SECRET_KEY=" + key if line.startswith("SECRET_KEY=") else line for line in lines]
io.open(path, "w", encoding="utf-8", newline="\n").write("\n".join(out) + "\n")
PY
  warn "SECRET_KEY сгенерирован. Сохраните .env в секретном хранилище: при его"
  warn "потере все выданные токены перестанут проверяться, потребуется новый вход."
else
  log "SECRET_KEY уже задан - оставляю как есть"
fi

# --------------------------------------------------------------------- 2. тома
log "создаю том данных ${DATA_VOLUME}"
docker volume inspect "$DATA_VOLUME" >/dev/null 2>&1 || docker volume create "$DATA_VOLUME" >/dev/null

if docker run --rm -v "${DATA_VOLUME}:/data:ro" alpine:3.20 \
     test -f /data/.install-state.json >/dev/null 2>&1; then
  log "том уже развёрнут (есть .install-state.json) - данные НЕ сбрасываются"
else
  log "первичная установка: том пуст"
fi

# --------------------------------------------------------------------- 3. модели
log "поднимаю ollama и скачиваю модели (может занять минуты)"
docker compose up -d ollama
./scripts/pull_models.sh

# ----------------------------------------------------------------------- 4. стек
log "собираю и поднимаю backend + frontend"
docker compose up -d --build

# -------------------------------------------------------------------- 5. здоровье
log "жду готовности backend"
READY=0
for _ in $(seq 1 60); do
  if curl -fsS "${API_URL}/api/health" >/dev/null 2>&1; then READY=1; break; fi
  sleep 5
done
[ "$READY" -eq 1 ] || die "backend не стал здоров за 5 минут: docker compose logs -f backend"
curl -fsS "${API_URL}/api/health" || true
echo

# --------------------------------------------------------------------- 6. админ
ADMIN_OK=no
if curl -fsS -X POST "${API_URL}/api/auth/login" -H 'Content-Type: application/json' \
     -d "{\"username\":\"${ADMIN_USERNAME}\",\"password\":\"${ADMIN_PASSWORD:-}\"}" \
     >/dev/null 2>&1; then
  ADMIN_OK=yes
fi

if [ "$ADMIN_OK" = "yes" ]; then
  log "администратор «${ADMIN_USERNAME}» уже существует - пропускаю"
elif [ -n "$PYTHON_BIN" ]; then
  if [ -n "${ADMIN_PASSWORD:-}" ]; then
    log "создаю администратора «${ADMIN_USERNAME}»"
    (cd backend && "$PYTHON_BIN" scripts/create_admin.py "$ADMIN_USERNAME" \
        --password "$ADMIN_PASSWORD" </dev/null)
  else
    warn "нужен первый администратор (регистрации в UI нет)"
    (cd backend && "$PYTHON_BIN" scripts/create_admin.py "$ADMIN_USERNAME" </dev/null)
  fi
else
  die "python не найден - создайте администратора вручную: make create-admin"
fi

# ---------------------------------------------------------- 7. маркер установки
STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
docker run --rm -v "${DATA_VOLUME}:/data" alpine:3.20 sh -c \
  "printf '{\"installed_at\":\"${STAMP}\",\"admin\":\"${ADMIN_USERNAME}\",\"tool\":\"bootstrap.sh\"}' > /data/.install-state.json"

warn "DATA_DIR=/data содержит ещё и кэш моделей (HF_HOME, TORCH_HOME)."
warn "Обычный сброс данных их не трогает: make reset-plan"
warn "Полная очистка тома (включая модели): make reset-all"

echo
log "Готово. Интерфейс: http://127.0.0.1  ·  API: ${API_URL}/api/health"