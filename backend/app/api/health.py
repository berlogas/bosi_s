"""Проверка живости системы: БД, конфигурация, доступность Ollama."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter
from sqlalchemy import text

from app import __version__
from app.config import get_settings
from app.core.locks import locks
from app.schemas.api import HealthResponse

router = APIRouter(prefix="/api", tags=["system"])


async def _check_ollama(settings) -> dict[str, Any]:  # noqa: ANN001
    url = f"{settings.ollama_base_url.rstrip('/')}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(url)
        response.raise_for_status()
        models = [m.get("name") for m in response.json().get("models", [])]
        # "ollama/qwen2.5:3b" -> "qwen2.5:3b" (ollama-тег является частью имени)
        wanted = settings.llm_model.split("/")[-1]
        return {
            "reachable": True,
            "models": models,
            "llm_model_present": any(m == wanted or m.startswith(f"{wanted}:") for m in models),
            "wanted_model": wanted,
        }
    except Exception as exc:
        return {"reachable": False, "error": f"{type(exc).__name__}: {exc}"}


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    database = "ok"
    try:
        from app.db.session import get_session_factory

        with get_session_factory()() as db:
            db.execute(text("SELECT 1"))
    except Exception as exc:
        database = f"error: {type(exc).__name__}: {exc}"

    ollama = await _check_ollama(settings)
    status = "ok" if database == "ok" else "degraded"
    return HealthResponse(
        status=status,
        app=settings.app_name,
        environment=settings.environment,
        version=__version__,
        database=database,
        llm_model=settings.llm_model,
        embedding_model=settings.embedding_model,
        ollama=ollama,
    )


@router.get("/health/locks")
async def locks_state() -> dict[str, Any]:
    return locks.stats()
