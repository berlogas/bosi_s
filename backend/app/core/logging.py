"""Настройка структурного логирования."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": self._message(record),
        }
        for key in ("request_id", "user_id", "session_id", "action", "duration_ms"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _message(record: logging.LogRecord) -> str:
        """Текст записи.

        `record.getMessage()` подставляет аргументы через `%` и падает, если
        аргумент один, а в сообщении несколько `%d` (так пишут некоторые
        сторонние библиотеки). Запись не должна ронять логирование целиком —
        поэтому при ошибке подстановки отдаём исходный шаблон.
        """
        try:
            return record.getMessage()
        except (TypeError, ValueError):
            return str(record.msg)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "LiteLLM", "litellm", "watchfiles", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
