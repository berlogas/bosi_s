"""Блокировки: сессионные (write) и глобальный индекс (RW)."""

from __future__ import annotations

import asyncio

import pytest

from app.core.locks import LockRegistry


async def test_session_lock_is_exclusive() -> None:
    registry = LockRegistry()
    order: list[str] = []

    async def worker(name: str, delay: float) -> None:
        async with registry.session_lock("s1"):
            order.append(f"{name}:start")
            await asyncio.sleep(delay)
            order.append(f"{name}:end")

    await asyncio.gather(worker("A", 0.05), worker("B", 0.01))
    assert order in (
        ["A:start", "A:end", "B:start", "B:end"],
        ["B:start", "B:end", "A:start", "A:end"],
    )
    assert "A:start" != "B:start" or order.index("A:start") == 0


async def test_different_sessions_do_not_block_each_other() -> None:
    registry = LockRegistry()
    started = asyncio.Event()

    async def hold() -> None:
        async with registry.session_lock("s1"):
            started.set()
            await asyncio.sleep(0.1)

    task = asyncio.create_task(hold())
    await started.wait()
    async with registry.session_lock("s2"):  # не блокируется
        pass
    await task


async def test_rwlock_allows_parallel_readers() -> None:
    registry = LockRegistry()
    inside = 0
    max_inside = 0

    async def reader() -> None:
        nonlocal inside, max_inside
        async with registry.global_index.read():
            inside += 1
            max_inside = max(max_inside, inside)
            await asyncio.sleep(0.05)
            inside -= 1

    await asyncio.gather(reader(), reader(), reader())
    assert max_inside == 3


async def test_rwlock_writer_excludes_readers() -> None:
    registry = LockRegistry()
    events: list[str] = []

    async def writer() -> None:
        async with registry.global_index.write():
            events.append("write:start")
            await asyncio.sleep(0.05)
            events.append("write:end")

    async def reader() -> None:
        await asyncio.sleep(0.01)
        async with registry.global_index.read():
            events.append("read")

    await asyncio.gather(writer(), reader())
    assert events.index("write:end") < events.index("read")


async def test_write_excludes_other_writer() -> None:
    registry = LockRegistry()
    order: list[str] = []

    async def worker(name: str) -> None:
        async with registry.global_index.write():
            order.append(f"{name}:start")
            await asyncio.sleep(0.02)
            order.append(f"{name}:end")

    await asyncio.gather(worker("A"), worker("B"))
    assert len(order) == 4
    # участки не пересекаются
    assert order[1].endswith(":end") and order[2].endswith(":start")


async def test_lock_released_after_exception() -> None:
    registry = LockRegistry()
    with pytest.raises(RuntimeError):
        async with registry.session_lock("s1"):
            msg = "boom"
            raise RuntimeError(msg)
    async with registry.session_lock("s1"):  # не должен висеть
        pass


def test_registry_stats_shape() -> None:
    registry = LockRegistry()
    stats = registry.stats()
    assert "locks" in stats and "global_index" in stats