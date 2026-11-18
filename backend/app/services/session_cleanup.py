"""Уборка артефактов сессии: файлы на диске и коллекция чанков.

Один код зовут два сценария: purge архива по TTL (`workers/reaper.py`) и явное
удаление сессии владельцем (`api/sessions.py`).

Почему нельзя удалять «все пути документов сессии». Исследователь вправе
добавить в сессию файл из общей библиотеки (`documents_dir` — это
`session_import_roots`, см. `core/safety.py`): такой документ лежит в
каталоге сессии, а его файл — в каталоге глобальной базы. Если purge сессии
удалит и его, файл глобальной базы исчезнет с диска, а запись в реестре и
индекс PaperQA останутся — глобальный документ превратится в битую ссылку.

Поэтому удаляются только файлы внутри каталога сессии (`sessions/<id>/`),
а проверка повторяется непосредственно перед удалением.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from pathlib import Path

import anyio

from app.core.locks import locks
from app.core.safety import session_root
from app.services.pqa_registry import get_registry, session_collection

log = logging.getLogger("boasi.services.session_cleanup")


def owned_paths(session_id: str, paths: Iterable[str]) -> list[Path]:
    """Из путей — только те, что лежат внутри каталога сессии.

    Путь разворачивается (`resolve`), поэтому `..` и симлинки не позволяют
    выйти за каталог сессии.
    """
    try:
        root = session_root(session_id).resolve()
    except OSError:
        return []
    result: list[Path] = []
    for raw in paths:
        if not raw:
            continue
        try:
            candidate = Path(raw).resolve()
        except OSError:  # битые симлинки, недоступные сетевые пути
            continue
        if candidate == root or root in candidate.parents:
            result.append(candidate)
    return result


def remove_files(paths: Sequence[str]) -> int:
    """Удалить файлы; опустевшие каталоги поднимаем вверх по дереву."""
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
            log.warning("session_cleanup: не удалось удалить %s", path)
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


def remove_session_files(session_id: str, paths: Iterable[str]) -> int:
    """Удалить только те файлы, что принадлежат сессии."""
    owned = owned_paths(session_id, paths)
    if not owned:
        return 0
    return remove_files([str(path) for path in owned])


async def clear_session_collection(session_id: str) -> int:
    """Очистить коллекцию чанков сессии и забыть её сервис."""
    collection = session_collection(session_id)
    registry = get_registry()
    # Сначала забываем сервис: иначе persist_state при остановке приложения
    # записал бы обратно только что удалённые чанки.
    registry.drop(collection)
    try:
        return await registry.store.clear(collection)
    except Exception:
        log.exception("session_cleanup: не удалось очистить чанки %s", collection)
        return 0


async def purge_session_artifacts(
    session_id: str,
    paths: Iterable[str] = (),
) -> dict[str, int]:
    """Файлы сессии, её коллекция чанков и сброс блокировки.

    Возвращает, что именно удалено: `files_removed`, `chunks_removed`.
    """
    files_removed = await anyio.to_thread.run_sync(
        remove_session_files, session_id, list(paths))
    chunks_removed = await clear_session_collection(session_id)
    locks.reset_session_lock(session_id)
    log.info("session_cleanup: сессия=%s файлов=%d чанков=%d",
             session_id, files_removed, chunks_removed)
    return {"files_removed": files_removed, "chunks_removed": chunks_removed}


__all__ = [
    "clear_session_collection",
    "owned_paths",
    "purge_session_artifacts",
    "remove_files",
    "remove_session_files",
    "session_root",
]
