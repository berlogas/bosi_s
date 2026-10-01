"""Блокировки для потокобезопасной работы с индексами PaperQA.

Из ТЗ:
  * Lock на уровне сессии при модификации индекса;
  * Lock на глобальный индекс для админских операций;
  * Read-only операции (query) без блокировок.

Реализация: обычная asyncio.Lock на сессию + RW-lock на глобальный индекс
(множество читателей / один писатель).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


class RWLock:
    """Асинхронный read/write lock: много читателей, один писатель."""

    def __init__(self) -> None:
        self._readers = 0
        self._writer = False
        self._cond = asyncio.Condition()

    @contextlib.asynccontextmanager
    async def read(self) -> AsyncIterator[None]:
        async with self._cond:
            while self._writer:
                await self._cond.wait()
            self._readers += 1
        try:
            yield
        finally:
            async with self._cond:
                self._readers -= 1
                if self._readers == 0:
                    self._cond.notify_all()

    @contextlib.asynccontextmanager
    async def write(self) -> AsyncIterator[None]:
        async with self._cond:
            while self._writer or self._readers:
                await self._cond.wait()
            self._writer = True
        try:
            yield
        finally:
            async with self._cond:
                self._writer = False
                self._cond.notify_all()

    @property
    def stats(self) -> dict[str, Any]:
        return {"readers": self._readers, "writer": self._writer}


class LockRegistry:
    """Именованные asyncio.Lock (по session_id / global) с учётом ожидания."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._waiting: dict[str, int] = defaultdict(int)
        self._global_index = RWLock()

    @contextlib.asynccontextmanager
    async def session_lock(self, session_id: str) -> AsyncIterator[None]:
        lock = self._locks[session_id]
        self._waiting[session_id] += 1
        try:
            async with lock:
                yield
        finally:
            self._waiting[session_id] -= 1

    @property
    def global_index(self) -> RWLock:
        return self._global_index

    def stats(self) -> dict[str, Any]:
        return {
            "locks": {
                key: {"locked": lock.locked(), "waiting": self._waiting[key]}
                for key, lock in self._locks.items()
            },
            "global_index": self._global_index.stats,
        }


locks = LockRegistry()


@dataclass
class AppState:
    """Состояние приложения, которое переживает рестарт через БД (см. Фазы 2/5)."""

    started_at: Any = field(default=None)
    indexes_loaded: int = 0