"""Heartbeat-воркер: продлевает TTL только у реально открытых сессий.

Почему не «все активные сессии»: такой heartbeat продлевал бы TTL бесконечно и
сценарий ТЗ «100 дней без работы → архив» никогда бы не сработал. Поэтому воркер
работает по арендам (`app.core.leases`), которые выставляет эндпоинт
`POST /api/sessions/{id}/heartbeat`, когда клиент держит сессию открытой.

Побочный эффект: после рестарта процесса аренды пусты, поэтому «мёртвые» сессии
не воскресают.
"""

from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.core.leases import leases
from app.db.models import SessionStatus
from app.db.repositories.sessions import WRITABLE_STATUSES
from app.db.repositories.users import touch_session
from app.db.session import get_session_factory

log = logging.getLogger("boasi.workers.heartbeat")


async def heartbeat_once() -> int:
    """Один проход: продлить TTL сессий с живой арендой. Возвращает их число."""
    live = leases.live()
    if not live:
        return 0
    touched = 0
    factory = get_session_factory()
    with factory() as db:
        from sqlalchemy import select

        from app.db.models import ResearchSession

        for session in db.scalars(
            select(ResearchSession).where(ResearchSession.id.in_(live))
        ):
            if session.purged_at is not None or session.status not in WRITABLE_STATUSES:
                leases.drop(session.id)
                continue
            touch_session(db, session, action_type="session.heartbeat",
                          action_label="Сессия открыта")
            touched += 1
    log.debug("heartbeat: живых сессий=%d, продлено=%d", len(live), touched)
    return touched


async def heartbeat_loop(interval_seconds: float | None = None) -> None:
    """Цикл с интервалом из конфигурации (по умолчанию 5 минут)."""
    settings = get_settings()
    interval = interval_seconds or settings.heartbeat_interval_minutes * 60
    log.info("Heartbeat: интервал=%s c", interval)
    while True:
        try:
            await heartbeat_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Heartbeat: ошибка в итерации")
        await asyncio.sleep(interval)


__all__ = ["SessionStatus", "heartbeat_loop", "heartbeat_once"]