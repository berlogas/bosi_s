"""Безопасность файловых путей (Фаза 9, hardening).

ТЗ требует: «валидация путей (нет выхода за пределы каталога сессии)».
Эндпоинты добавления документа принимают путь на диске, и без проверки
исследователь мог указать что угодно — вплоть до файлов за пределами платформы.

Правила:
  * путь разворачивается в абсолютный (`resolve`), поэтому `..` и симлинки
    не обходят проверку;
  * результат обязан находиться внутри одного из разрешённых корней;
  * для сессии это её собственный каталог + общий каталог документов;
  * для глобальной базы (админ) — каталог данных, либо любой путь, если
    администратор явно разрешил это флагом `ALLOW_EXTERNAL_IMPORT_PATHS`.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from pathlib import Path

from app.config import get_settings
from app.core.errors import ForbiddenError, NotFoundError

log = logging.getLogger("boasi.core.safety")


def session_import_roots(session_id: str) -> list[Path]:
    """Корни, из которых исследователь может импортировать документ сессии."""
    settings = get_settings()
    return [settings.sessions_dir / session_id,
            settings.documents_dir]


def session_root(session_id: str) -> Path:
    """Каталог сессии: `data/sessions/<id>`.

    Свои файлы сессии лежат здесь; всё, что вне каталога, — чужие (например,
    файл общей библиотеки, добавленный в сессию по пути). Удалять при purge
    можно только то, что внутри каталога (см. `services/session_cleanup.py`).
    """
    return get_settings().sessions_dir / session_id


def global_import_roots() -> list[Path]:
    settings = get_settings()
    roots: list[Path] = [settings.documents_dir]
    if settings.allow_external_import_paths:
        # админ сознательно разрешил импорт откуда угодно
        roots.append(settings.data_dir)
    return roots


def _within(path: Path, roots: Sequence[Path]) -> Path | None:
    for root in roots:
        try:
            resolved_root = root.resolve()
        except OSError:
            continue
        if path == resolved_root or resolved_root in path.parents:
            return resolved_root
    return None


def resolve_import_path(raw: str | Path, roots: Iterable[Path], *,
                        must_exist: bool = True) -> Path:
    """Проверить путь и вернуть абсолютный, либо бросить `ForbiddenError`."""
    text = str(raw or "").strip()
    if not text:
        raise ForbiddenError("Путь к файлу не указан")

    # Сначала пробуем прямое разрешение (как было раньше)
    candidate = Path(text).expanduser()
    try:
        resolved = candidate.resolve()
    except OSError as exc:  # битые_symlinks, сетевые пути
        raise ForbiddenError(f"Не удалось разобрать путь: {text}") from exc

    # Проверяем, разрешено ли это путь внутри корней
    allowed = _within(resolved, list(roots))
    if allowed is not None:
        # Путь разрешен внутри одного из корней — возвращаем разрешенный путь
        if must_exist:
            if not resolved.exists():
                raise NotFoundError(f"Файл не найден: {resolved.name}")
            if not resolved.is_file():
                raise ForbiddenError(f"Это не файл: {resolved.name}")
        return resolved

    # Если прямое разрешение не сработало (путь, скорее всего, относительный),
    # пробуем разрешить относительно каждого из корней
    for root in roots:
        root_resolved = root.resolve()
        # Пытаемся добавить путь как относительный к этому корню
        try:
            test_path = root_resolved / text
            test_resolved = test_path.resolve()
            if _within(test_resolved, [root]):
                # Путь разрешен внутри этого корня
                if must_exist:
                    if not test_resolved.exists():
                        raise NotFoundError(f"Файл не найден: {test_resolved.name}")
                    if not test_resolved.is_file():
                        raise ForbiddenError(f"Это не файл: {test_resolved.name}")
                return test_resolved
        except OSError:
            continue

    # Если ни один корень не подошёл, возвращаем ошибку
    raise ForbiddenError(
        f"Путь вне разрешённых каталогов: {text}. "
        f"Разрешено: {', '.join(str(r) for r in roots)}",
        meta={"path": text},
    )


def validate_session_import(session_id: str, raw: str | Path,
                            *, must_exist: bool = True) -> Path:
    """Основная проверка для документов сессии."""
    settings = get_settings()
    if settings.allow_external_import_paths:
        roots = [*session_import_roots(session_id), settings.data_dir]
    else:
        roots = session_import_roots(session_id)
    path = resolve_import_path(raw, roots, must_exist=must_exist)
    log.info("validate_session_import: %s -> %s", raw, path)
    return path


def validate_global_import(raw: str | Path, *, must_exist: bool = True) -> Path:
    """Проверка для глобальной базы знаний (админ)."""
    return resolve_import_path(raw, global_import_roots(), must_exist=must_exist)


def ensure_within(path: Path, root: Path) -> Path:
    """Проверка, что путь не выходит за каталог (используется при purge)."""
    resolved = path.resolve()
    root_resolved = root.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ForbiddenError(f"Файл вне каталога {root_resolved}")
    return resolved


def is_within(path: Path, roots: Sequence[Path]) -> bool:
    """Проверить, что путь лежит внутри одного из корней (безопасная проверка перед удалением)."""
    return _within(path, roots) is not None
