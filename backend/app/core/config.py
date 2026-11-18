"""Обёртка для обратной совместимости.

Экспортирует ``settings`` из :mod:`app.config`` под старым именем,
коим пользуется ``app.main``.
"""

from __future__ import annotations

from app.config import get_settings

settings = get_settings()

__all__ = ["settings"]
