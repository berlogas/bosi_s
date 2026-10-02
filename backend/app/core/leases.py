"""Кратковременные «аренды» активных сессий — для корректного TTL.

TTL сессии (90 дней) продлевается только реальной активностью пользователя.
Если бы фоновый heartbeat продлевал TTL *всем* активным сессиям, они никогда
не истекали бы и сценарий ТЗ «100 дней без работы → архив» не выполнялся.

Поэтому:
  * клиент, у которого сессия открыта в UI, шлёт ``POST /sessions/{id}/heartbeat``;
  * эндпоинт ставит аренду на ``heartbeat_interval_minutes * 2``;
  * фоновый воркер продлевает TTL только сессиям с живой арендой.

Брошенные сессии аренды не имеют и спокойно доходят до ``expires_at``.
Аренды живут в памяти процесса: после рестарта они пусты, что безопасно —
до первого heartbeat сессия не продлевается.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class LeaseRegistry:
    """Набор session_id, которые прямо сейчас считаются «открытыми»."""

    _expires_at: dict[str, float] = field(default_factory=dict)

    def touch(self, session_id: str, ttl_seconds: float) -> None:
        """Продлить аренду сессии на ``ttl_seconds`` (монотонное время).

        ``ttl_seconds=0`` означает «пометить как истёкшую» — удобно в тестах
        и при явном снятии аренды.
        """
        self._expires_at[session_id] = time.monotonic() + max(0.0, float(ttl_seconds))

    def drop(self, session_id: str) -> None:
        self._expires_at.pop(session_id, None)

    def is_live(self, session_id: str) -> bool:
        return self._expires_at.get(session_id, 0.0) > time.monotonic()

    def live(self) -> list[str]:
        """Живые аренды; истёкшие попутно вычищаются."""
        now = time.monotonic()
        for key in [k for k, v in self._expires_at.items() if v <= now]:
            self._expires_at.pop(key, None)
        return sorted(self._expires_at)

    def clear(self) -> None:
        self._expires_at.clear()

    def stats(self) -> dict[str, int]:
        return {"live": len(self.live())}


leases = LeaseRegistry()
