"""Точка входа boasi_s backend."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import (
    admin,
    auth,
    chat,
    documents,
    health,
    history,
    projects,
    session_documents,
    sessions,
    users,
)
from app.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.leases import leases
from app.core.logging import setup_logging
from app.db.session import dispose_engine, init_db
from app.services.paperqa_service import get_registry, reset_registry
from app.workers.heartbeat import heartbeat_loop
from app.workers.reaper import reaper_loop, reaper_once

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

    # Фоновые задачи: heartbeat (TTL открытых сессий) и reaper (архив/purge).
    # Первый проход reaper'а выполняем сразу — протухшее архивируется без задержки.
    background = [asyncio.create_task(heartbeat_loop(), name="heartbeat"),
                  asyncio.create_task(reaper_loop(), name="reaper")]
    app.state.background = background
    try:
        await reaper_once()
    except Exception:
        logger.exception("Reaper: первоначальный проход не удался")

    try:
        yield
    finally:
        for task in background:
            task.cancel()
        for task in background:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Фоновая задача %s упала при остановке", task.get_name())
        leases.clear()

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
    app.include_router(admin.router)
    app.include_router(sessions.router)
    app.include_router(users.router)
    app.include_router(documents.router)
    app.include_router(session_documents.router)
    app.include_router(chat.router)
    app.include_router(history.router)
    app.include_router(projects.router)
    return app


def _reset_state() -> None:  # pragma: no cover - только для тестов
    reset_registry()


app = create_app()
