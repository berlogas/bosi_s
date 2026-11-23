"""Обёртка для обратной совместимости.

Импортирует функции работы с БД из :mod:`app.db.session` под старыми
именами, которые используются в ``app.main`` и других модулях.
"""

from __future__ import annotations

from app.db.session import dispose_engine, get_db, init_db


async def create_db_and_tables() -> None:
    init_db()


async def close_db_connection() -> None:
    dispose_engine()


get_session = get_db

__all__ = ["close_db_connection", "create_db_and_tables", "get_session"]
