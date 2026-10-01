"""Точка входа boasi_s backend."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import auth, health
from app.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import setup_logging
from app.db.session import dispose_engine, init_db
from app.services.paperqa_service import get_registry, reset_registry

logger = logging.getLogger("boasi")


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN201
    settings = get_settings()
    setup_logging(settings.log_level)
    settings.ensure_dirs()
    init_db()
    logger.info("boasi_s backend started", extra=settings.public_summary())

    # Восстанавливаем состояние PaperQA из БД (глобальная коллекция + сессии).
    # Ошибка восстановления не должна ронять старт: платформа остаётся рабочей,
    # просто индекс пуст и его можно пересобрать (Фаза 4: реиндексация).
    registry = get_registry()
    app.state.registry = registry
    try:
        restored = await registry.global_service().restore_state()
        logger.info("PaperQA: восстановлено документов=%d", restored)
    except Exception:
        logger.exception("PaperQA: не удалось восстановить состояние глобальной базы")

    yield
    try:
        await registry.persist_global()
    except Exception:
        logger.exception("PaperQA: не удалось сохранить состояние")
    dispose_engine()
    logger.info("boasi_s backend stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="boasi_s API",
        version=__version__,
        description="Локальная научная RAG-платформа на PaperQA2",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    # Приватность: API слушает только локально, CORS — только для локального Streamlit
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    return app


def _reset_state() -> None:  # pragma: no cover - только для тестов
    reset_registry()


app = create_app()
