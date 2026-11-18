#!/usr/bin/env python3
"""Переиндексация всех коллекций (global + сессии) после смены EMBEDDING_MODEL.

Запуск: из каталога backend
    ../.venv/Scripts/python.exe scripts/reindex.py

В Docker (в образ попадает вместе с scripts/):
    docker compose exec backend python scripts/reindex.py

Скрипт безопасен для повторного запуска: эмбеддинги пересчитываются всегда,
поэтому после первой переиндексации новые вызовы просто подтверждают индекс.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.models import ResearchSession  # noqa: E402
from app.db.session import session_scope  # noqa: E402
from app.services.pqa_registry import get_registry  # noqa: E402


async def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    settings = get_settings()
    print(f"Модель эмбеддингов: {settings.embedding_model}")

    registry = get_registry(settings)
    targets: list[tuple[str, object]] = [("global", registry.global_service())]

    with session_scope() as db:
        session_ids = list(db.scalars(select(ResearchSession.id)))
    for session_id in session_ids:
        targets.append((session_id, registry.session_service(session_id)))

    for label, service in targets:
        stored = await service.store.load(service.collection)
        if not stored:
            print(f"  {label}: коллекция пуста, пропуск")
            continue
        result = await service.rebuild_index(drop_embeddings=True)
        print(f"  {label}: документов={result['documents']} "
              f"чанков={result['chunks']} за {result['seconds']}с")

    await registry.persist_global()
    print("Готово. Перезапустите backend.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
