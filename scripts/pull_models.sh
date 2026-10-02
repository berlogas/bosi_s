#!/usr/bin/env bash
# Предзагрузка моделей Ollama в том (Фаза 9).
#
#   ./scripts/pull_models.sh              # берёт модели из .env
#   MODELS="qwen2.5:3b" ./scripts/pull_models.sh
#
# Зачем: контур работает оффлайн. Если модель не скачана заранее, платформа
# стартует, но каждый ответ будет падать на «model not found».
set -euo pipefail

ENV_FILE="${ENV_FILE:-.env}"

read_setting() {
  local key="$1" default="${2:-}"
  if [ -f "$ENV_FILE" ]; then
    local value
    value="$(grep -E "^${key}=" "$ENV_FILE" | head -n1 | cut -d= -f2- || true)"
    if [ -n "$value" ]; then
      # у Ollama имена вида ollama/qwen2.5:3b — префикс provider'а не нужен
      printf '%s' "${value##*/}"
      return
    fi
  fi
  printf '%s' "$default"
}

collect() {
  local list=""
  if [ -n "${MODELS:-}" ]; then
    list="$MODELS"
  else
    list="$(read_setting LLM_MODEL qwen2.5:3b) $(read_setting SUMMARY_LLM_MODEL "")"
  fi
  printf '%s' "$list"
}

# Эмбеддинги по умолчанию считаются локально (sentence-transformers), и такой
# модели в Ollama нет — `ollama pull st-...` упал бы. Явно перечисленные
# в MODELS модели тянем всегда.
is_ollama_model() {
  case "$1" in
    st-*|'') return 1 ;;
    *) return 0 ;;
  esac
}

MODELS_TO_PULL=""
for model in $(collect); do
  if is_ollama_model "$model"; then
    MODELS_TO_PULL="${MODELS_TO_PULL:+$MODELS_TO_PULL }$model"
  else
    echo "   пропускаем локальную модель эмбеддингов: $model"
  fi
done

if [ -z "$(printf '%s' "$MODELS_TO_PULL" | tr -d '[:space:]')" ]; then
  echo "Не найдено моделей для загрузки (задайте MODELS или LLM_MODEL в .env)" >&2
  exit 1
fi

echo "-> Тяну модели в том Ollama: $MODELS_TO_PULL"
for model in $MODELS_TO_PULL; do
  [ -z "$model" ] && continue
  echo "   ollama pull $model"
  docker compose exec -T ollama ollama pull "$model"
done

echo "OK. Проверка:"
docker compose exec -T ollama ollama list