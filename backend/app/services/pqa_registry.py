"""Реестр сервисов PaperQA2 по коллекциям.

Один `Docs` на глобальную базу и один `Docs` на сессию. Реестр управляет
их жизненным циклом: ленивое создание, восстановление из хранилища,
сохранение при остановке.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import Settings, get_settings
from app.services.chunk_store import ChunkStore, SqliteChunkStore
from app.services.paperqa_service import PaperQA2Service

log = logging.getLogger("boasi.services.pqa")

GLOBAL_COLLECTION = "global"
SESSION_PREFIX = "session:"


def session_collection(session_id: str) -> str:
    return f"{SESSION_PREFIX}{session_id}"


def collection_kind(collection: str) -> Any:
    from app.services.types import SourceKind
    return SourceKind.SESSION if collection.startswith(SESSION_PREFIX) else SourceKind.GLOBAL


def normalize_collection(collection: str) -> str:
    if not collection or collection == GLOBAL_COLLECTION:
        return GLOBAL_COLLECTION
    return collection if collection.startswith(SESSION_PREFIX) else session_collection(collection)


class ServiceRegistry:
    """Реестр сервисов по коллекциям: один `Docs` на глобальную базу и на сессию."""

    def __init__(self, app: Settings | None = None,
                 store: ChunkStore | None = None) -> None:
        self.app = app or get_settings()
        self.store = store or SqliteChunkStore()
        self._services: dict[str, PaperQA2Service] = {}
        self._meta_lock = asyncio.Lock()

    def get(self, collection: str = GLOBAL_COLLECTION) -> PaperQA2Service:
        key = normalize_collection(collection)
        service = self._services.get(key)
        if service is None:
            service = PaperQA2Service(
                settings=self.app, collection=key, chunk_store=self.store)
            self._services[key] = service
        return service

    def global_service(self) -> PaperQA2Service:
        return self.get(GLOBAL_COLLECTION)

    def session_service(self, session_id: str) -> PaperQA2Service:
        return self.get(session_collection(session_id))

    async def restore_all(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for key, service in list(self._services.items()):
            result[key] = await service.restore_state()
        return result

    async def persist_global(self) -> int:
        """Сохранить состояние всех загруженных коллекций (остановка приложения)."""
        total = 0
        for service in list(self._services.values()):
            total += await service.persist_state()
        return total

    async def close(self) -> None:
        await self.persist_global()
        self._services.clear()


_registry: ServiceRegistry | None = None


def get_registry(app: Settings | None = None) -> ServiceRegistry:
    global _registry
    if _registry is None:
        _registry = ServiceRegistry(app)
    return _registry


def reset_registry() -> None:
    global _registry
    _registry = None


__all__ = [
    "GLOBAL_COLLECTION",
    "SESSION_PREFIX",
    "ServiceRegistry",
    "collection_kind",
    "get_registry",
    "normalize_collection",
    "reset_registry",
    "session_collection",
]
