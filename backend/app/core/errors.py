"""Единые ошибки приложения и их маппинг в HTTP."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger("boasi.errors")


class AppError(Exception):
    """Базовая ошибка предметной области."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "app_error"

    def __init__(self, detail: str, *, meta: dict | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.meta = meta or {}


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"


class ConflictError(AppError):
    """Нарушение лимитов ТЗ (сессии, документы, хранилище)."""

    status_code = status.HTTP_409_CONFLICT
    code = "limit_exceeded"


class UpstreamError(AppError):
    """Ollama недоступен или вернул ошибку."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "upstream_unavailable"


class DocumentProcessingError(AppError):
    status_code = 422
    code = "document_error"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.code, "detail": exc.detail, "meta": exc.meta},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": "validation_error",
                "detail": "Некорректные данные запроса",
                "meta": {"errors": exc.errors()},
            },
        )

    @app.exception_handler(Exception)
    async def _unexpected(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Необработанная ошибка: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "internal_error", "detail": "Внутренняя ошибка сервера"},
        )