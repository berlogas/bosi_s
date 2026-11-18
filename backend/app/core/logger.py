"""Обёртка для обратной совместимости.

Экспортирует стандартный ``logging.Logger`` под именем ``logger``,
коим пользуется ``app.main``.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("boasi_s")

__all__ = ["logger"]
