# boasi_s backend — CPU-образ (dev и prod)
# ВАЖНО: внутри контейнера torch ставится CPU-сборки — эмбеддинги дешёвые,
# а генерацию LLM берёт на себя Ollama (в prod — на GPU).
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/data/hf \
    PQA_HOME=/data/pqa \
    TORCH_HOME=/data/torch

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.lock ./

RUN pip install --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple \
        -r requirements.lock

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY tests ./tests

RUN useradd -m -u 1000 boasi && mkdir -p /data && chown -R boasi:boasi /app /data
USER boasi

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["sh", "-c", "alembic upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"]