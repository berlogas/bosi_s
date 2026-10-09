"""Reaper: жизненный цикл сессий по TTL (Фаза 5) и уборка журнала аудита.

Четыре операции за проход:
  1. архивирование сессий, у которых истёк TTL (`expires_at < now`);
  2. purge архивов старше retention-политики (`archive_retention_days`):
     запись помечается `purged_at`, файлы сессии и её чанки удаляются;
  3. подчистка протухших refresh-токенов;
  4. ретрация `audit_log` (раз в `AUDIT_PRUNE_INTERVAL_HOURS`) и VACUUM,
     если после удаления освободилось место.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

import anyio
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.locks import locks
from app.db.models import RefreshToken, utcnow
from app.db.repositories.sessions import purge_expired_archives
from app.db.repositories.users import expire_due_sessions
from app.db.repositories.users import prune_audit as prune_audit_repo
from app.db.session import get_session_factory
from app.services.paperqa_service import get_registry, session_collection

log = logging.getLogger("boasi.workers.reaper")

# Монотонное время последней ретрации аудита: живёт в памяти процесса,
# чтобы не делать лишний запрос к БД каждые 5 минут.
_last_audit_prune = 0.0


def remove_files(paths: list[str]) -> int:
    """Удалить файлы сессии; опустевшие каталоги поднимаем вверх по дереву."""
    removed = 0
    dirs: set[Path] = set()
    for raw in paths:
        path = Path(raw)
        try:
            if path.is_file():
                path.unlink()
                removed += 1
                dirs.add(path.parent)
        except OSError:
            log.warning("reaper: не удалось удалить %s", path)
    for directory in sorted(dirs, key=lambda p: len(p.parts), reverse=True):
        current = directory
        for _ in range(3):  # files -> <session_id> -> sessions
            try:
                next(current.iterdir())
                break  # каталог не пуст — выше не идём
            except StopIteration:
                try:
                    current.rmdir()
                except OSError:
                    break
                current = current.parent
            except OSError:
                break
    return removed


async def purge_sessions(retention_days: int | None = None) -> dict[str, Any]:
    """Пометить старые архивы purged, удалить их файлы и чанки."""
    factory = get_session_factory()
    with factory() as db:
        purged = purge_expired_archives(db, retention_days=retention_days)

    if not purged:
        return {"purged": 0, "files_removed": 0, "chunks_removed": 0}

    removed_files = await anyio.to_thread.run_sync(
        remove_files, [p for item in purged for p in item["paths"]])

    chunks_removed = 0
    for item in purged:
        collection = session_collection(item["session_id"])
        try:
            chunks_removed += await get_registry().get(collection).store.clear(collection)
        except Exception:
            log.exception("reaper: не удалось очистить чанки %s", collection)
        locks.reset_session_lock(item["session_id"])

    log.info("reaper: purged=%d файлов=%d чанков=%d",
             len(purged), removed_files, chunks_removed)
    return {"purged": len(purged), "files_removed": removed_files,
            "chunks_removed": chunks_removed}


def archive_expired() -> list[str]:
    factory = get_session_factory()
    with factory() as db:
        return expire_due_sessions(db)


def purge_expired_refresh_tokens() -> int:
    factory = get_session_factory()
    with factory() as db:
        from sqlalchemy import delete

        result = db.execute(
            delete(RefreshToken).where(
                RefreshToken.expires_at < utcnow() - timedelta(days=7)))
        db.commit()
        return int(result.rowcount or 0)


def vacuum_audit(db: Session) -> bool:
    """Сжать БД после удаления старых записей аудита.

    SQLite не отдаёт удалённое место файлу, пока не сработает VACUUM.
    Он блокирует запись на время выполнения, поэтому делается редко
    (раз в сутки) и в отдельном соединении с AUTOCOMMIT: внутри
    транзакции VACUUM не выполняется в принципе.
    """
    if not get_settings().is_sqlite:
        return False
    try:
        with db.get_bind().connect().execution_option(
                isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text("VACUUM"))
    except Exception:  # файл может быть занят — не повод ронять reaper
        log.warning("reaper: VACUUM не выполнен", exc_info=True)
        return False
    return True


async def prune_audit_if_due(force: bool = False) -> dict[str, Any]:
    """Ретрация журнала аудита по расписанию (раз в `AUDIT_PRUNE_INTERVAL_HOURS`)."""
    global _last_audit_prune

    settings = get_settings()
    interval = max(1, settings.audit_prune_interval_hours) * 3600
    now = time.monotonic()
    if not force and now - _last_audit_prune < interval:
        return {"skipped": True}

    _last_audit_prune = now
    factory = get_session_factory()
    with factory() as db:
        result = prune_audit_repo(db)
        if result["needs_vacuum"] and settings.audit_vacuum:
            result["vacuumed"] = await anyio.to_thread.run_sync(
                vacuum_audit, db)

    if result["removed_total"]:
        log.info(
            "reaper: аудит — удалено по сроку=%d по объёму=%d, осталось=%d, vacuum=%s",
            result["removed_by_age"], result["removed_overflow"],
            result["total"], result.get("vacuumed", False),
        )
    return result


async def reaper_once() -> dict[str, Any]:
    """Один проход reaper'а (без сна — удобно для тестов и ручного запуска)."""
    archived = await anyio.to_thread.run_sync(archive_expired)
    if archived:
        log.info("reaper: архивировано по TTL сессий=%d", len(archived))
    purged = await purge_sessions()
    tokens = await anyio.to_thread.run_sync(purge_expired_refresh_tokens)
    audit_result = await prune_audit_if_due()
    return {"archived": len(archived), **purged, "refresh_tokens": tokens,
            "audit": audit_result}


async def reaper_loop(interval_seconds: float | None = None) -> None:
    """Цикл с интервалом из конфигурации (по умолчанию 5 минут)."""
    settings = get_settings()
    interval = interval_seconds or settings.heartbeat_interval_minutes * 60
    log.info("Reaper: интервал=%s c, retention=%s дней",
             interval, settings.archive_retention_days)
    while True:
        try:
            await reaper_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Reaper: ошибка в итерации")
        await asyncio.sleep(interval)