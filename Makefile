# boasi_s — команды разработки
PY ?= .venv/Scripts/python.exe
PYTHON ?= .venv/Scripts/python      # Linux/macOS
BACKEND := backend

.PHONY: help venv install test test-integration lint warm-embedding run migrate models up down logs backup

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

venv: ## создать venv на Python 3.11
	py -3.11 -m venv .venv

install: ## установить зависимости
	$(PY) -m pip install -r $(BACKEND)/requirements.txt

test: ## тесты backend (без сети)
	cd $(BACKEND) && ../$(PY) -m pytest -q

test-integration: ## интеграционные тесты с живым Ollama (медленные, минуты)
	cd $(BACKEND) && ../$(PY) -m pytest -m integration -q

lint: ## статическая проверка (ruff)
	$(PY) -m ruff check $(BACKEND)/app $(BACKEND)/tests

warm-embedding: ## заранее скачать модель эмбеддингов в HF_HOME (для оффлайн-запуска)
	$(PY) -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('st-multi-qa-MiniLM-L6-cos-v1'); print('ok')"

run: ## запустить backend локально
	cd $(BACKEND) && ../$(PY) -m uvicorn app.main:app --reload --port 8000

migrate: ## применить миграции
	cd $(BACKEND) && ../$(PY) -m alembic upgrade head

migrate-autogen: ## создать миграцию: make migrate-autogen m="описание"
	cd $(BACKEND) && ../$(PY) -m alembic revision --autogenerate -m "$(m)"

models: ## скачать модели Ollama для локальной разработки
	ollama pull qwen2.5:3b
	ollama pull nomic-embed-text

up: ## поднять весь стек в Docker
	docker compose up -d --build
	@echo "API: http://127.0.0.1:8000/api/health | UI: http://127.0.0.1:8501"

down: ## остановить стек
	docker compose down

logs: ## логи сервисов
	docker compose logs -f --tail=100

backup: ## бэкап БД и PQA_HOME
	@mkdir -p backups
	tar -czf backups/boasi-$$(date +%Y%m%d-%H%M%S).tar.gz data/ || true
	@echo "backup -> backups/"
