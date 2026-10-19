#!/usr/bin/env bash
# Замер времени ответа на один вопрос по глобальной базе.
#
# Нужен, чтобы сравнивать прогоны на разных настройках таймаута и не
# полагаться на глазок: разброс от зависающих сетевых вызовов (25 с против
# 205 с на одном и том же вопросе) перекрывает эффект любой настройки, если
# смотреть на один прогон.
#
# Запуск:
#   ./scripts/bench_query.sh 4
#   QUERY="что такое биомасса?" ./scripts/bench_query.sh 3
#
# Печатает по прогону время, статус и число источников, в конце — сводку:
# минимум, медиана, худший и долю ответов дольше 60 с.
#
# Обмен с python идёт через stdin/stdout, а не через файлы: пути, которые
# выдаёт mktemp в Git Bash, Windows-python не видит (он получает
# «/tmp/tmp.XXXX», которого для него не существует), и молча разбирал не тот
# файл — замер выглядел правдоподобно и был выдуманным.

set -u

# Отчёт на русском, а локаль консоли на Windows по умолчанию cp1251: печать
# упала бы UnicodeEncodeError посреди замера и потеряла бы ровно то, ради чего
# скрипт написан.
export PYTHONIOENCODING=utf-8

BASE="${TOO:-http://127.0.0.1:8000}"
USER="${USER:-ctd_admin}"
PASS="${PASS:-ctd-admin-pass-123}"
RUNS="${1:-4}"
QUERY="${QUERY:-что такое CTD-зонд?}"
POLLS="${POLLS:-70}"   # сколько раз опросить задачу по 5 с

ask() { python -c "$1"; }

token=$(curl -s -m 30 -X POST "$BASE/api/auth/login" \
  -H "Content-Type: application/json" \
  --data-binary "{\"username\":\"$USER\",\"password\":\"$PASS\"}" \
  | ask "import json,sys;print(json.load(sys.stdin)['tokens']['access_token'])" 2>/dev/null)

if [ -z "$token" ]; then
  echo "не удалось войти: проверьте USER/PASS" >&2
  exit 1
fi

times=""
unfinished=0

for run in $(seq 1 "$RUNS"); do
  # Тело запроса уходит на stdin curl, а не аргументом: Git Bash ломает
  # кириллицу в аргументах, тело приходит битым, и сервер отвечает 400 —
  # тихо, без следа в скрипте.
  payload=$(printf '{"query":%s,"no_cache":true}' \
    "$(printf '%s' "$QUERY" | python -c "import json,sys;print(json.dumps(sys.stdin.read(),ensure_ascii=False))")")

  tid=$(printf '%s' "$payload" \
    | curl -s -m 60 -X POST "$BASE/api/chat/quick-query" \
        -H "Authorization: Bearer $token" \
        -H "Content-Type: application/json; charset=utf-8" \
        --data-binary @- \
    | ask "import json,sys;print(json.load(sys.stdin).get('task_id',''))" 2>/dev/null)

  if [ -z "$tid" ]; then
    echo "прогон $run: задача не создана"
    continue
  fi

  status=running
  body=""
  for _ in $(seq 1 "$POLLS"); do
    body=$(curl -s -m 20 "$BASE/api/tasks/$tid" -H "Authorization: Bearer $token")
    status=$(printf '%s' "$body" \
      | ask "import json,sys;print(json.load(sys.stdin).get('status','?'))" 2>/dev/null || echo '?')
    [ "$status" != "running" ] && break
    sleep 5
  done

  line=$(printf '%s' "$body" | ask "
import json, sys
task = json.load(sys.stdin)
result = task.get('result') or {}
seconds = task.get('seconds')
print(f\"{task.get('status')} {seconds if seconds is not None else 0} {len(result.get('sources') or [])}\")
" 2>/dev/null || echo "? 0 0")

  read -r st secs sources <<< "$line"
  if [ "$st" = "running" ]; then
    unfinished=$((unfinished + 1))
    echo "прогон $run: не завершён за $((POLLS * 5)) с"
  else
    times="$times $secs"
    echo "прогон $run: $st, ${secs} с, источников $sources"
  fi
done

printf '%s\n' $times | ask "
import statistics, sys
values = [float(v) for v in sys.stdin.read().split()]
if not values:
    print('нет завершённых прогонов')
    raise SystemExit(0)
print()
print(f'завершено: {len(values)}, не завершено: $unfinished')
print(f'минимум: {min(values):.1f} с, медиана: {statistics.median(values):.1f} с, худший: {max(values):.1f} с')
print(f'дольше 60 с: {sum(1 for v in values if v > 60)} из {len(values)}')
"