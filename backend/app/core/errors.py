"""Единые ошибки приложения и их маппинг в HTTP."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("boasi.errors")

# Человеческие тексты для кодов, которые Starlette иначе отдаёт по-английски.
_STATUS_TEXT_RU: dict[int, str] = {
    400: "Некорректный запрос",
    401: "Требуется вход",
    403: "Доступ запрещён",
    404: "Не найдено",
    405: "Метод не поддерживается",
    409: "Конфликт состояния",
    415: "Неподдерживаемый тип данных",
    422: "Некорректные данные запроса",
    429: "Слишком много запросов",
    500: "Внутренняя ошибка сервера",
    503: "Сервис временно недоступен",
}

# Стандартные фразы Starlette: если detail совпадает с одной из них,
# значит это не наш текст, а служебный — переводим.
_STD_PHRASES: dict[int, tuple[str, ...]] = {
    400: ("Bad Request",),
    401: ("Unauthorized",),
    403: ("Forbidden",),
    404: ("Not Found",),
    405: ("Method Not Allowed",),
    409: ("Conflict",),
    415: ("Unsupported Media Type",),
    422: ("Unprocessable Entity", "Validation Error"),
    429: ("Too Many Requests",),
    500: ("Internal Server Error",),
    503: ("Service Unavailable",),
}


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


class TooManyRequestsError(AppError):
    """Превышен лимит попыток (rate-limit логина)."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"


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

    @app.exception_handler(StarletteHTTPException)
    async def _http(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """Русские тексты вместо стандартных HTTP-причин.

        Starlette отвечает на неизвестный маршрут `{"detail": "Not Found"}`,
        и эта строка дословно всплывала в интерфейсе. Приложение
        русскоязычное, поэтому известные коды переводятся, а неизвестный
        `detail` (наш собственный текст ошибки) сохраняется как есть.
        """
        detail = exc.detail
        if not isinstance(detail, str) or detail in _STD_PHRASES.get(exc.status_code, ()):
            detail = _STATUS_TEXT_RU.get(exc.status_code, "Ошибка запроса")
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": f"http_{exc.status_code}", "detail": detail},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _unexpected(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Необработанная ошибка: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "internal_error", "detail": "Внутренняя ошибка сервера"},
        )