"""Защита от перебора пароля на `/api/auth/login` (Фаза 9).

Простая скользящая рамка в памяти процесса: считаем **неудачные** попытки по
паре (логин, IP). После `login_max_attempts` за окно — блокировка на
`login_lockout_seconds`.

Почему в памяти, а не в БД: счётчики живут минутами, теряются при рестарте
(и это правильно — после рестарта окно обнуляется), а лишняя таблица и запись
на каждый неудачный запрос не нужны. Для одного инстанса этого достаточно;
при нескольких репликах нужен общий стор — но платформа по ТЗ локальная,
один процесс.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings

log = logging.getLogger("boasi.core.rate_limit")


@dataclass
class SlidingWindowLimiter:
    attempts: dict[str, list[float]] = field(default_factory=dict)

    def _key(self, login: str, ip: str) -> str:
        return f"{login.lower()}@{ip}"

    def _prune(self, key: str, window: float) -> list[float]:
        now = time.monotonic()
        hits = [t for t in self.attempts.get(key, []) if now - t < window]
        if hits:
            self.attempts[key] = hits
        else:
            self.attempts.pop(key, None)
        return hits

    def is_blocked(self, login: str, ip: str) -> bool:
        settings = get_settings()
        hits = self._prune(self._key(login, ip), settings.login_window_seconds)
        return len(hits) >= settings.login_max_attempts

    def record_failure(self, login: str, ip: str) -> int:
        settings = get_settings()
        key = self._key(login, ip)
        hits = self._prune(key, settings.login_window_seconds)
        hits.append(time.monotonic())
        self.attempts[key] = hits
        return len(hits)

    def reset(self, login: str, ip: str) -> None:
        self.attempts.pop(self._key(login, ip), None)

    def remaining(self, login: str, ip: str) -> int:
        settings = get_settings()
        hits = self._prune(self._key(login, ip), settings.login_window_seconds)
        return max(0, settings.login_max_attempts - len(hits))

    def clear(self) -> None:
        self.attempts.clear()

    def stats(self) -> dict[str, int]:
        return {"tracked_keys": len(self.attempts)}


login_limiter = SlidingWindowLimiter()


def client_ip(request: Any) -> str:
    return request.client.host if request.client else "unknown"