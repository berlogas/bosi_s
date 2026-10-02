#!/usr/bin/env bash
# Единый запуск boasi_s (Фаза 10).
#
#   ./scripts/start.sh              — запустить всё (ручной режим)
#   ./scripts/start.sh docker       — через Docker Compose
#   ./scripts/start.sh stop         — остановить
#   ./scripts/start.sh status       — состояние компонентов
#   ./scripts/start.sh logs backend — хвост логов
#
# Скрипт самодостаточный: не требует `make` (на этой машине его нет).
# Понимает и Git Bash, и Linux/macOS.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

RUN_DIR="$ROOT/.run"
LOG_DIR="$ROOT/logs"
mkdir -p "$RUN_DIR" "$LOG_DIR"

# ------------------------------------------------------------------ конфигурация
API_PORT="${API_PORT:-8000}"
UI_PORT="${UI_PORT:-80}"
OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"

# Python: Windows и Linux различаются путём к интерпретатору
pick_python() {
  if [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
    printf '%s' "$ROOT/.venv/Scripts/python.exe"
  elif [ -x "$ROOT/.venv/bin/python" ]; then
    printf '%s' "$ROOT/.venv/bin/python"
  else
    printf '%s' "python"
  fi
}
PY="$(pick_python)"

if [ -t 1 ]; then
  RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; BLU=$'\033[34m'; DIM=$'\033[2m'; OFF=$'\033[0m'
else
  RED=""; GRN=""; YEL=""; BLU=""; DIM=""; OFF=""
fi

step() { printf '%s==>%s %s\n' "$BLU" "$OFF" "$1"; }
ok()   { printf '  %s✓%s %s\n' "$GRN" "$OFF" "$1"; }
warn() { printf '  %s!%s %s\n' "$YEL" "$OFF" "$1"; }
fail() { printf '  %s✗%s %s\n' "$RED" "$OFF" "$1"; }
die()  { fail "$1"; exit 1; }

# ------------------------------------------------------------------ утилиты
pid_of() {
  # ВАЖНО: нельзя писать `local name="$1" file="$RUN_DIR/$name.pid"` одной
  # строкой — bash раскрывает все слова до присваиваний, `$name` считается
  # неприсвоенной, и `set -u` молча завершает скрипт (ошибка уходит в stderr,
  # который мы часто перенаправляем в /dev/null).
  local name="$1"
  local file="$RUN_DIR/$name.pid"
  [ -f "$file" ] || return 1
  local pid; pid="$(cat "$file" 2>/dev/null)"
  [ -n "$pid" ] || return 1
  # жив ли процесс
  if kill -0 "$pid" 2>/dev/null; then printf '%s' "$pid"; else return 1; fi
}

port_busy() {
  local port="$1"
  if command -v netstat >/dev/null 2>&1; then
    netstat -ano 2>/dev/null | grep -q ":$port .*LISTENING"
  else
    (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null && exec 3<&- && return 0
  fi
}

wait_http() {
  local url="$1" tries="${2:-60}" i=0
  while [ "$i" -lt "$tries" ]; do
    if curl -sf -m 3 -o /dev/null "$url" 2>/dev/null; then return 0; fi
    i=$((i+1)); sleep 1
  done
  return 1
}

# ------------------------------------------------------------------ префlight
preflight() {
  step "Проверки окружения"

  if [ ! -x "$PY" ] && ! command -v "$PY" >/dev/null 2>&1; then
    die "Python не найден. Создайте окружение: python -m venv .venv"
  fi
  ok "Python: $PY"

  if ! "$PY" -c "import fastapi, uvicorn" >/dev/null 2>&1; then
    warn "Зависимости backend не установлены"
    printf '     установить: %s -m pip install -r backend/requirements.lock\n' "$PY"
  else
    ok "Зависимости backend на месте"
  fi

  if [ ! -f .env ]; then
    warn "Файл .env отсутствует — копирую из .env.example"
    cp .env.example .env
    fail "В .env обязательно задать SECRET_KEY. Сгенерируйте:"
    printf '     python -c "import secrets; print(secrets.token_urlsafe(48))"\n'
    printf '     и вставьте в строку SECRET_KEY=, затем запустите снова.\n'
    exit 1
  fi

  if ! grep -qE '^SECRET_KEY=.+' .env; then
    die "SECRET_KEY пустой в .env — приложение не стартует."
  fi
  if grep -qi 'change-me' .env; then
    die "SECRET_KEY остался шаблонным. Сгенерируйте новый:"
    printf '     python -c "import secrets; print(secrets.token_urlsafe(48))"\n'
  fi
  ok "SECRET_KEY задан"

  # Ollama: предупреждаем, но не блокируем — backend поднимется и без неё
  if curl -sf -m 3 -o /dev/null "$OLLAMA_URL/api/tags" 2>/dev/null; then
    local models
    models="$(curl -sf -m 5 "$OLLAMA_URL/api/tags" 2>/dev/null \
      | "$PY" -c 'import sys,json
try:
    print(", ".join(m["name"] for m in json.load(sys.stdin).get("models", [])) or "-")
except Exception:
    print("-")' 2>/dev/null)"
    ok "Ollama доступна, модели: ${models:--}"
    if [ "$models" = "-" ] || [ -z "$models" ]; then
      warn "Моделей нет: ответы работать не будут. Скачать: ./scripts/start.sh models"
    fi
  else
    warn "Ollama недоступна на $OLLAMA_URL — ответы не будут работать."
    printf '     запустите: ollama serve\n'
  fi
}

# ------------------------------------------------------------------ режимы
start_manual() {
  preflight

  # ---- backend
  if pid_of backend >/dev/null 2>&1; then
    ok "Backend уже запущен (pid $(pid_of backend))"
  else
    if port_busy "$API_PORT"; then
      die "Порт $API_PORT занят. Остановите то, что его слушает."
    fi
    step "Запуск backend на порту $API_PORT"
    (
      cd backend
      nohup "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" \
        > "$LOG_DIR/backend.log" 2>&1 &
      echo $! > "$RUN_DIR/backend.pid"
    )
    if wait_http "http://127.0.0.1:$API_PORT/api/health" 90; then
      ok "Backend поднялся (pid $(pid_of backend))"
    else
      fail "Backend не поднялся за 90 с. Хвост лога:"
      tail -n 20 "$LOG_DIR/backend.log" 2>/dev/null | sed 's/^/     /'
      exit 1
    fi
  fi

  # ---- frontend
  if pid_of frontend >/dev/null 2>&1; then
    ok "Frontend уже запущен (pid $(pid_of frontend))"
  else
    # Порт 80 может быть занят другим приложением (IIS, Skype, nginx).
    # Тогда не отказываем, а переходим на 8501 и говорим об этом.
    if port_busy "$UI_PORT"; then
      if [ "$UI_PORT" = "80" ] && ! port_busy 8501; then
        warn "Порт 80 занят другим приложением — интерфейс будет на 8501"
        UI_PORT=8501
      else
        die "Порт $UI_PORT занят."
      fi
    fi
    step "Запуск интерфейса на порту $UI_PORT"
    (
      cd frontend
      API_URL="http://127.0.0.1:$API_PORT" \
      nohup "$PY" -m streamlit run app.py \
        --server.address 127.0.0.1 --server.port "$UI_PORT" \
        --server.headless true --browser.gatherUsageStats false \
        > "$LOG_DIR/frontend.log" 2>&1 &
      echo $! > "$RUN_DIR/frontend.pid"
    )
    if wait_http "http://127.0.0.1:$UI_PORT/_stcore/health" 60; then
      ok "Интерфейс поднялся (pid $(pid_of frontend))"
    else
      fail "Интерфейс не поднялся за 60 с. Хвост лога:"
      tail -n 20 "$LOG_DIR/frontend.log" 2>/dev/null | sed 's/^/     /'
      exit 1
    fi
  fi

  print_urls
}

start_docker() {
  step "Запуск через Docker Compose"
  command -v docker >/dev/null 2>&1 || die "docker не найден в PATH"
  docker compose version >/dev/null 2>&1 || die "нет docker compose v2"
  [ -f .env ] || { cp .env.example .env; warn "создан .env из шаблона"; }
  if grep -qi 'change-me' .env; then
    die "SECRET_KEY шаблонный — замените в .env перед запуском в Docker"
  fi
  step "Модели Ollama (если ещё не скачаны)"
  ./scripts/pull_models.sh || warn "загрузка моделей не удалась — проверьте вручную"
  step "Подъём стека"
  docker compose up -d --build || die "docker compose up не удался"
  if wait_http "http://127.0.0.1:$API_PORT/api/health" 180; then
    ok "Backend отвечает"
  else
    warn "Backend пока не отвечает — смотрите: docker compose logs backend"
  fi
  print_urls
  printf '  %sЛоги:%s docker compose logs -f backend\n' "$DIM" "$OFF"
}

print_urls() {
  echo
  printf '%s  Платформа запущена%s\n' "$GRN" "$OFF"
  printf '  Интерфейс:  http://127.0.0.1:%s\n' "$UI_PORT"
  printf '  API:        http://127.0.0.1:%s/api/docs\n' "$API_PORT"
  printf '  Здоровье:   http://127.0.0.1:%s/api/health\n' "$API_PORT"
  echo
  printf '  %sЛоги:%s      ./scripts/start.sh logs backend\n' "$DIM" "$OFF"
  printf '  %sСостояние:%s  ./scripts/start.sh status\n' "$DIM" "$OFF"
  printf '  %sОстановить:%s ./scripts/start.sh stop\n' "$DIM" "$OFF"
  echo
  print_login_hint
}

# Подсказка по первому входу. Раньше печаталась безусловно и говорила
# «учётной записи нет», даже когда админ давно существовал. Теперь смотрим
# в БД и показываем реальное состояние.
print_login_hint() {
  local admins
  admins="$(list_admins)"

  if [ -n "$admins" ]; then
    printf '  Вход готов: %s\n' "$admins"
    printf '  %sЗабыли пароль:%s ./scripts/start.sh password <логин>\n' "$DIM" "$OFF"
  else
    echo
    printf '  Учётных записей нет — создайте администратора:\n'
    printf '    ./scripts/start.sh admin <логин>\n'
    printf '  %sWindows:%s scripts\\start.bat admin <логин>\n' "$DIM" "$OFF"
  fi
}

# Активные администраторы из БД. Пустая строка — записей нет либо БД ещё
# не создана (первый запуск); это не повод для ошибки.
list_admins() {
  (
    cd backend 2>/dev/null || return 0
    "$PY" -c 'import sys
sys.path.insert(0, ".")
try:
    from app.db.models import Role, User
    from app.db.session import get_session_factory
    with get_session_factory()() as db:
        names = [u.username for u in db.query(User)
            .filter(User.role == Role.admin, User.is_active.is_(True))
            .order_by(User.created_at)]
    print(", ".join(names))
except Exception:
    print("")'
 2>/dev/null
  )
}

stop_all() {
  step "Остановка"
  for name in frontend backend; do
    if pid="$(pid_of "$name")"; then
      kill "$pid" 2>/dev/null
      sleep 1
      kill -9 "$pid" 2>/dev/null
      rm -f "$RUN_DIR/$name.pid"
      ok "$name остановлен (pid $pid)"
    else
      warn "$name не запущен через скрипт"
    fi
  done
  ok "Готово"
}

status_all() {
  printf '%s  Состояние boasi_s%s\n\n' "$BLU" "$OFF"

  if curl -sf -m 3 -o /dev/null "$OLLAMA_URL/api/tags" 2>/dev/null; then
    printf '  %s✓%s Ollama      %s\n' "$GRN" "$OFF" "$OLLAMA_URL"
  else
    printf '  %s✗%s Ollama      не отвечает (%s)\n' "$RED" "$OFF" "$OLLAMA_URL"
  fi

  if curl -sf -m 3 -o /dev/null "http://127.0.0.1:$API_PORT/api/health" 2>/dev/null; then
    local health
    health="$(curl -sf -m 5 "http://127.0.0.1:$API_PORT/api/health" 2>/dev/null \
      | "$PY" -c 'import sys, json
# Без f-string со вложенными кавычками: в Python 3.11 обратный слэш внутри
# f-выражения — синтаксическая ошибка.
try:
    d = json.load(sys.stdin)
    print("status=" + str(d.get("status"))
          + ", БД=" + str(d.get("database"))
          + ", модель=" + str(d.get("llm_model")))
except Exception as exc:
    print("ответ получен, разобрать не удалось: " + type(exc).__name__)' \
      2>/dev/null || printf '%s' "ответил, подробности недоступны")"
    printf '  %s✓%s Backend     %s\n' "$GRN" "$OFF" "$health"
  else
    printf '  %s✗%s Backend     не отвечает (порт %s)\n' "$RED" "$OFF" "$API_PORT"
  fi

  if curl -sf -m 3 -o /dev/null "http://127.0.0.1:$UI_PORT/_stcore/health" 2>/dev/null; then
    printf '  %s✓%s Frontend    http://127.0.0.1:%s\n' "$GRN" "$OFF" "$UI_PORT"
  else
    printf '  %s✗%s Frontend    не отвечает (порт %s)\n' "$RED" "$OFF" "$UI_PORT"
  fi

  echo
  if pid_of backend >/dev/null 2>&1; then
    printf '  PID: backend=%s frontend=%s\n' "$(pid_of backend)" "$(pid_of frontend || echo -)"
  fi
}

pull_models() {
  step "Загрузка моделей Ollama"
  if curl -sf -m 3 -o /dev/null "$OLLAMA_URL/api/tags" 2>/dev/null; then
    model="$(grep -E '^LLM_MODEL=' .env 2>/dev/null | cut -d= -f2-)"
    model="${model##*/}"
    [ -n "$model" ] || model="qwen2.5:3b"
    ok "Тяну $model (это может занять несколько минут)"
    ollama pull "$model" || die "ollama pull не удался"
  else
    die "Ollama не запущена. Сначала: ollama serve"
  fi
}

# Последние ошибки интерфейса — то, что пользователю нужно приложить к
# сообщению об ошибке.
show_errors() {
  file="$LOG_DIR/frontend.log"
  [ -f "$file" ] || { echo "Лог интерфейса ещё не создан: $file"; return 0; }
  printf '  %sОшибки интерфейса (%s)%s

' "$DIM" "$file" "$OFF"
  grep -A 12 -E "ERROR|Traceback" "$file" | tail -60 || echo "  ошибок не зафиксировано"
}

show_logs() {
  which="${1:-backend}"
  file="$LOG_DIR/$which.log"
  [ -f "$file" ] || die "Лог $which не найден ($file)"
  printf '%s  %s (Ctrl+C — выход)%s\n\n' "$DIM" "$file" "$OFF"
  tail -f "$file"
}

create_admin() {
  "$PY" backend/scripts/create_admin.py "$@"
}

# ------------------------------------------------------------------ точка входа
case "${1:-start}" in
  start|"")      start_manual ;;
  docker)        start_docker ;;
  stop)          stop_all ;;
  restart)       stop_all; echo; start_manual ;;
  status)        status_all ;;
  logs)          show_logs "${2:-backend}" ;;
  errors)        show_errors ;;
  models)        pull_models ;;
  admin)         shift; create_admin "$@" ;;
  users)         "$PY" backend/scripts/reset_password.py --list ;;
  password)      shift
                 if [ -z "${1:-}" ]; then
                   die "Укажите логин: ./scripts/start.sh password <login>"
                 fi
                 "$PY" backend/scripts/reset_password.py "$@" ;;
  test)          cd backend && "$PY" -m pytest -q ;;
  help|-h|--help)
    cat << 'USAGE'
Запуск boasi_s:

  ./scripts/start.sh              запустить всё (ручной режим)
  ./scripts/start.sh docker       запустить через Docker Compose
  ./scripts/start.sh stop         остановить backend и интерфейс
  ./scripts/start.sh restart      перезапустить
  ./scripts/start.sh status       состояние компонентов
  ./scripts/start.sh logs backend хвост логов (frontend)
  ./scripts/start.sh errors       ошибки интерфейса с трассировками
  ./scripts/start.sh models       скачать модели Ollama
  ./scripts/start.sh admin <login> создать администратора
  ./scripts/start.sh users        список пользователей
  ./scripts/start.sh password <login> [новый-пароль]  сброс пароля
  ./scripts/start.sh test         прогнать тесты

Переменные окружения:
  API_PORT=8000  UI_PORT=80  OLLAMA_URL=http://127.0.0.1:11434
USAGE
    ;;
  *) die "Неизвестная команда: $1 (./scripts/start.sh help)" ;;
esac