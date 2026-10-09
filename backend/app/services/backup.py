"""Резервное копирование из админки: снимок БД + архив + манифест.

Скрипты `scripts/backup.sh` делают то же самое, но снаружи. Здесь — то же
самое внутри процесса backend, чтобы копию можно было снять из UI.

Почему это работает и в Docker, и на Windows:

* backend в обоих случаях знает, где лежат данные (`settings.data_dir`):
  в контейнере это том `/data`, локально — каталог `data/`;
* архив собирается модулем `tarfile` из стандартной библиотеки — никаких
  внешних `tar`/`docker`, одинаковое поведение везде;
* копии складываются в `settings.resolved_backup_dir`, который намеренно
  вынесен **за пределы** каталога данных: иначе архивы попадали бы сами в
  себя и раздували том без предела.

Восстановление из UI намеренно не делаем: оно требует остановки платформы,
поэтому остаётся скриптом (`./scripts/restore.sh`).
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import shutil
import sqlite3
import tarfile
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from app.config import Settings, get_settings

log = logging.getLogger("boasi.backup")

# Имя файла-снимка внутри архива (restore.sh кладёт его на место boasi.sqlite3).
SNAPSHOT_NAME = ".backup-snapshot.sqlite3"
MANIFEST_NAME = "boasi-manifest.json"
# Фразы подтверждения у бэкапа НЕТ намеренно.
# Сброс удаляет данные — там фраза обязательна. Создание копии
# ничего не разрушает: худшее, что случится от
# случайного нажатия, — потратится место на диске (объём
# показан в модальном окне). Здесь достаточно обычного
# подтверждения кнопками «Создать / Отмена».

# Файлы БД не архивируются «как есть»: вместо них кладётся снимок.
DB_FILE_NAMES = ("boasi.sqlite3", "boasi.sqlite3-wal", "boasi.sqlite3-shm")


def _now_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def _unique_archive(backup_dir: Path, stamp: str) -> Path:
    """Имя архива, которого ещё нет.

    Две копии в одну секунду (двойной клик, повтор по таймауту) иначе получили
    бы одно имя и молча перетёрли друг друга — потерялась бы и только что
    снятая копия, и место на диске освободилось бы незаметно.
    """
    candidate = backup_dir / f"boasi-{stamp}.tar.gz"
    if not candidate.exists():
        return candidate
    for suffix in range(2, 100):
        candidate = backup_dir / f"boasi-{stamp}-{suffix}.tar.gz"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Не удалось подобрать свободное имя копии в {backup_dir}")


def _human_bytes(size: float) -> str:
    value = float(size)
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if value < 1024 or unit == "ТБ":
            return f"{value:.1f} {unit}" if unit != "Б" else f"{int(value)} Б"
        value /= 1024
    return f"{value:.1f} ТБ"


@dataclass(frozen=True)
class BackupEntry:
    """Один архив в каталоге бэкапов."""

    name: str
    path: str
    bytes: int
    created_at: str | None
    human_size: str
    has_sha256: bool
    has_manifest: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "bytes": self.bytes,
            "human_size": self.human_size,
            "created_at": self.created_at,
            "has_sha256": self.has_sha256,
            "has_manifest": self.has_manifest,
        }


@dataclass(frozen=True)
class BackupPlan:
    """Что будет снято и сколько это примерно займёт."""

    data_dir: str
    backup_dir: str
    files: int
    source_bytes: int
    estimated_bytes: int
    free_bytes: int | None
    existing: int
    keep: int
    db_exists: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "data_dir": self.data_dir,
            "backup_dir": self.backup_dir,
            "files": self.files,
            "source_bytes": self.source_bytes,
            "source_human": _human_bytes(self.source_bytes),
            "estimated_bytes": self.estimated_bytes,
            "estimated_human": _human_bytes(self.estimated_bytes),
            "free_bytes": self.free_bytes,
            "free_human": _human_bytes(self.free_bytes) if self.free_bytes else None,
            "existing": self.existing,
            "keep": self.keep,
            "db_exists": self.db_exists,
            # вместо фразы — предупреждение: сколько займёт
            # места и сколько старых копий исчезцится по ротации.
            "warning": (
                f"Копия займёт около "
                f"{_human_bytes(self.estimated_bytes)}; более старых "
                f"копий будет удалено: "
                f"{max(self.existing - self.keep, 0)}"
                if self.keep else
                f"Копия займёт около "
                f"{_human_bytes(self.estimated_bytes)} (ротация отключена)"
            ),
        }


@dataclass(frozen=True)
class BackupResult:
    """Итог создания копии."""

    entry: BackupEntry
    manifest: dict[str, Any] = field(default_factory=dict)
    deleted_old: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "entry": self.entry.as_dict(),
            "deleted_old": self.deleted_old,
            "restore_hint": (
                "Восстановление — только скриптом, платформу нужно сначала "
                "остановить: ./scripts/restore.sh <архив>"
            ),
        }


# ------------------------------------------------------------------ инвентарь
def _list_archive_paths(backup_dir: Path) -> list[Path]:
    if not backup_dir.exists():
        return []
    return sorted(
        (p for p in backup_dir.glob("boasi-*.tar.gz") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def list_backups(settings: Settings | None = None) -> list[BackupEntry]:
    """Все архивы в каталоге бэкапов, новые сверху."""
    settings = settings or get_settings()
    entries: list[BackupEntry] = []
    for path in _list_archive_paths(settings.resolved_backup_dir):
        stat = path.stat()
        created = datetime.fromtimestamp(stat.st_mtime, UTC).isoformat()
        entries.append(BackupEntry(
            name=path.name,
            path=str(path),
            bytes=stat.st_size,
            created_at=created,
            human_size=_human_bytes(stat.st_size),
            has_sha256=path.with_name(path.name + ".sha256").exists(),
            has_manifest=_archive_has(path, MANIFEST_NAME),
        ))
    return entries


def _archive_has(archive: Path, member: str) -> bool:
    """Есть ли в архиве файл с таким именем (обрыв после первого совпадения)."""
    try:
        with tarfile.open(archive, "r:gz") as tar:
            for item in tar:
                if Path(item.name).name == member:
                    return True
    except (tarfile.TarError, OSError):
        return False
    return False


# ---------------------------------------------------------------------- план
def _iter_data_files(settings: Settings) -> tuple[list[Path], int]:
    """Файлы каталога данных, которые попадут в архив, и их суммарный размер."""
    data_dir = settings.data_dir
    backup_dir = settings.resolved_backup_dir
    files: list[Path] = []
    total = 0
    if not data_dir.exists():
        return files, 0
    for root, dirs, names in os.walk(data_dir, onerror=lambda _e: None):
        root_path = Path(root)
        # каталог бэкапов внутрь data_dir архивировать нельзя — иначе копия
        # попадёт сама в себя; исключаем поддерево целиком
        dirs[:] = [
            d for d in dirs
            if not (root_path == data_dir and (root_path / d) == backup_dir)
        ]
        for name in names:
            if root_path == data_dir and name in DB_FILE_NAMES:
                continue          # вместо них идёт снимок
            if name == SNAPSHOT_NAME and root_path == data_dir:
                continue          # возможный остаток прошлого прогона
            path = root_path / name
            try:
                files.append(path)
                total += path.stat().st_size
            except OSError:
                continue
    return files, total


def plan_backup(settings: Settings | None = None) -> BackupPlan:
    """Посчитать объём и проверить, есть ли место. Ничего не меняет."""
    settings = settings or get_settings()
    files, source_bytes = _iter_data_files(settings)

    db_path = settings.resolved_db_path
    db_exists = bool(db_path and db_path.exists())
    if db_exists:
        source_bytes += db_path.stat().st_size

    # Грубая оценка: tar.gz жмёт текст и json лучше, но не в разы — закладываем
    # половину объёма, плюс запас на БД и служебные файлы.
    # ВНИМАНИЕ: скобки обязательны. Без них `+ 1 << 20` — это сдвиг всего
    # выражения на 20 бит (умножение на мегабайт), и оценка улетает в терабайты.
    estimated = (
        int(source_bytes * 0.5)
        + (db_path.stat().st_size if db_exists else 0)
        + (1 << 20)          # запас на манифест и служебные файлы
    )

    free_bytes: int | None
    try:
        usage = shutil.disk_usage(settings.resolved_backup_dir.parent
                                  if not settings.resolved_backup_dir.exists()
                                  else settings.resolved_backup_dir)
        free_bytes = usage.free
    except OSError:
        free_bytes = None

    return BackupPlan(
        data_dir=str(settings.data_dir),
        backup_dir=str(settings.resolved_backup_dir),
        files=len(files) + (1 if db_exists else 0),
        source_bytes=source_bytes,
        estimated_bytes=estimated,
        free_bytes=free_bytes,
        existing=len(_list_archive_paths(settings.resolved_backup_dir)),
        keep=settings.backup_keep,
        db_exists=db_exists,
    )


# ------------------------------------------------------------------- снимок БД
def _snapshot_db(settings: Settings, dest: Path) -> bool:
    """Согласованный снимок SQLite. False — базы нет (тоже не ошибка).

    Соединения закрываем явно: `with sqlite3.connect(...)` только коммитит
    транзакцию, но не закрывает соединение, и на Windows файл снимка остаётся
    занятым — временный каталог потом не удаляется (PermissionError).
    """
    db_path = settings.resolved_db_path
    if not db_path or not db_path.exists():
        log.info("БД не найдена (%s) — архив будет без неё", db_path)
        return False
    src_con = dst_con = None
    try:
        src_con = sqlite3.connect(str(db_path))
        dst_con = sqlite3.connect(str(dest))
        src_con.backup(dst_con)
    except sqlite3.Error as exc:
        # База может быть залочена активным процессом — это не повод
        # отказывать в бэкапе файлов, но молчать об этом нельзя.
        log.warning("Снимок БД не удался: %s", exc)
        return False
    finally:
        for con in (src_con, dst_con):
            if con is not None:
                with contextlib.suppress(sqlite3.Error):  # pragma: no cover
                    con.close()
    return True


# --------------------------------------------------------------------- манифест
def _build_manifest(settings: Settings, snapshot_taken: bool, files: int) -> dict[str, Any]:
    """Манифест: что снято. Тот же формат, что у scripts/backup_manifest.py."""
    manifest: dict[str, Any] = {
        "manifest_version": 2,
        "created_at": datetime.now(UTC).isoformat(),
        "source": "admin-ui",
        "data_dir": str(settings.data_dir),
        "backup_dir": str(settings.resolved_backup_dir),
        "files": files,
        "db_snapshot": snapshot_taken,
        "models": {
            "llm": settings.llm_model,
            "summary_llm": settings.resolved_summary_llm,
            "embedding": settings.embedding_model,
        },
    }
    db_path = settings.resolved_db_path
    if db_path and db_path.exists():
        manifest["database"] = {"file": str(db_path), "bytes": db_path.stat().st_size}

    # Ревизия схемы и счётчики строк читаем из самой базы.
    try:
        from sqlalchemy import func, inspect, select
        from sqlalchemy.orm import Session

        from app.db.models import Base
        from app.db.session import get_engine

        engine = get_engine()
        db = Session(engine)
        try:
            tables = Base.metadata.tables
            present = inspect(engine).has_table
            manifest["tables"] = {
                name: int(db.execute(select(func.count()).select_from(table)).scalar_one())
                for name, table in tables.items() if present(name)
            }
            if present("alembic_version"):
                from sqlalchemy import text

                row = db.execute(
                    text("SELECT version_num FROM alembic_version LIMIT 1")).first()
                manifest["alembic_revision"] = str(row[0]) if row else None
        finally:
            db.close()
    except Exception as exc:  # манифест — справочный, падать из-за него нельзя
        log.info("манифест без данных о таблицах: %s", exc)
        manifest.setdefault("warnings", []).append(f"таблицы: {exc}")
    return manifest


# -------------------------------------------------------------------- создание
def run_backup(
    *,
    keep: int | None = None,
    settings: Settings | None = None,
    actor: Any = None,
) -> BackupResult:
    """Снять копию. Возвращает созданный архив и что было удалено по ротации."""
    import json

    settings = settings or get_settings()
    backup_dir = settings.resolved_backup_dir
    backup_dir.mkdir(parents=True, exist_ok=True)
    keep = settings.backup_keep if keep is None else keep

    stamp = _now_stamp()
    archive = _unique_archive(backup_dir, stamp)
    name = archive.name
    files, _source_bytes = _iter_data_files(settings)

    log.warning("Бэкап стартует: %s -> %s", settings.data_dir, archive)

    partial = backup_dir / (name + ".partial")
    with tempfile.TemporaryDirectory(prefix="boasi-backup-") as tmpdir:
        tmp = Path(tmpdir)

        # 1. снимок БД
        snapshot = tmp / SNAPSHOT_NAME
        snapshot_taken = _snapshot_db(settings, snapshot)

        # 2. манифест
        manifest = _build_manifest(settings, snapshot_taken, len(files))
        (tmp / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        # 3. архив: сначала пишем во временный файл и только потом переносим
        #    на место — иначе прерванный бэкап остался бы «полноценным».
        try:
            with tarfile.open(partial, "w:gz", compresslevel=6) as tar:
                tar.add(tmp / MANIFEST_NAME, arcname=MANIFEST_NAME)
                if snapshot_taken:
                    tar.add(snapshot, arcname=SNAPSHOT_NAME)
                for path in files:
                    try:
                        tar.add(path, arcname=str(path.relative_to(settings.data_dir)))
                    except (OSError, ValueError) as exc:
                        # один недоступный файл не должен срывать весь бэкап
                        log.warning("пропущен файл %s: %s", path, exc)
            if snapshot_taken and not _archive_has(partial, SNAPSHOT_NAME):
                raise RuntimeError("в архив не попал снимок БД")
            partial.replace(archive)
        except Exception:
            partial.unlink(missing_ok=True)
            raise

    # 4. контрольная сумма
    _write_sha256(archive)

    # 5. ротация
    deleted = _prune(backup_dir, keep=keep, protect=archive)

    entry = list_backups(settings)[0] if list_backups(settings) else BackupEntry(
        name=name, path=str(archive), bytes=archive.stat().st_size,
        created_at=datetime.now(UTC).isoformat(),
        human_size=_human_bytes(archive.stat().st_size),
        has_sha256=True, has_manifest=True)

    log.warning("Бэкап готов: %s (%s)", archive.name, entry.human_size)
    return BackupResult(entry=entry, manifest=manifest, deleted_old=deleted)


def _write_sha256(archive: Path) -> None:
    digest = hashlib.sha256()
    with archive.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    archive.with_name(archive.name + ".sha256").write_text(
        f"{digest.hexdigest()}  {archive.name}\n", encoding="utf-8")


def _prune(backup_dir: Path, *, keep: int, protect: Path) -> list[str]:
    """Оставить `keep` свежих копий. protect никогда не удаляется."""
    if keep <= 0:
        return []
    archives = _list_archive_paths(backup_dir)
    removed: list[str] = []
    for old in archives[keep:]:
        if old == protect:
            continue
        try:
            old.unlink()
            old.with_name(old.name + ".sha256").unlink(missing_ok=True)
            removed.append(old.name)
        except OSError as exc:
            log.warning("не удалось удалить старый бэкап %s: %s", old.name, exc)
    return removed


# ---------------------------------------------------------------------- удаление
def delete_backup(name: str, *, settings: Settings | None = None) -> bool:
    """Удалить один архив. Имя проверяется — никаких путей извне."""
    settings = settings or get_settings()
    if not name.startswith("boasi-") or not name.endswith(".tar.gz") \
            or "/" in name or "\\" in name or ".." in name:
        raise ValueError(f"Недопустимое имя архива: {name!r}")
    path = settings.resolved_backup_dir / name
    if not path.exists():
        return False
    path.unlink()
    path.with_name(name + ".sha256").unlink(missing_ok=True)
    log.warning("Бэкап удалён администратором: %s", name)
    return True


BackupMode = Literal["manual"]


__all__ = [
    "BackupEntry",
    "BackupPlan",
    "BackupResult",
    "delete_backup",
    "list_backups",
    "plan_backup",
    "run_backup",
]