#!/usr/bin/env python3
"""Манифест бэкапа: что именно снято, на какой ревизии схемы и сколько данных.

Запускается внутри контейнера backend (том смонтирован в /data) и печатает
JSON в stdout — его подкладывает `scripts/backup.sh` в архив как
`boasi-manifest.json`. На восстановлении по нему видно, соответствует ли
архив текущему коду и не пустой ли он на самом деле.

    docker exec boasi-backend python scripts/backup_manifest.py
    python scripts/backup_manifest.py --output /backup/manifest.json

Скрипт ничего не пишет в БД и не меняет файлы: работает на read-only томе.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

MANIFEST_NAME = "boasi-manifest.json"
MANIFEST_VERSION = 2


def _app_version() -> str:
    try:
        from app import __version__

        return __version__
    except Exception:  # pragma: no cover - версия не критична
        return "unknown"


def _alembic_revision(db: Any) -> str | None:
    """Ревизия схемы в самой базе (что записано в alembic_version)."""
    from sqlalchemy import inspect, text

    try:
        if not inspect(db.get_bind()).has_table("alembic_version"):
            return None
        row = db.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).first()
        return str(row[0]) if row else None
    except Exception:
        return None


def _alembic_head() -> str | None:
    """Текущая голова миграций из кода — с ней сравнивают ревизию архива."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        return ScriptDirectory.from_config(cfg).get_current_head()
    except Exception:
        return None


def _row_counts(db: Any) -> dict[str, int]:
    from sqlalchemy import func, inspect, select

    from app.db.models import Base

    counts: dict[str, int] = {}
    try:
        present = inspect(db.get_bind())
    except Exception:  # pragma: no cover - нет подключения к БД
        return counts
    for name, table in Base.metadata.tables.items():
        if not present.has_table(name):
            continue
        try:
            counts[name] = int(db.execute(select(func.count()).select_from(table)).scalar_one())
        except Exception:  # pragma: no cover - битая таблица не должна ломать бэкап
            counts[name] = -1
    return counts


def _dir_stats(path: Path) -> dict[str, Any]:
    files = 0
    total = 0
    for root, _dirs, names in os.walk(path, onerror=lambda _e: None):
        for name in names:
            files += 1
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return {"path": str(path), "exists": True, "files": files, "bytes": total}


def _dir_stat(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False, "files": 0, "bytes": 0}
    return _dir_stats(path)


def build_manifest() -> dict[str, Any]:
    """Собрать манифест текущего состояния тома данных."""
    from app.config import get_settings
    from app.db.session import get_engine

    settings = None
    settings_error: str | None = None
    try:
        settings = get_settings()
    except Exception as exc:  # каталоги могут быть на read-only томе
        settings_error = f"{type(exc).__name__}: {exc}"
        from app.config import Settings

        settings = Settings()

    db = None
    db_error: str | None = None
    try:
        db = get_engine()  # type: ignore[assignment]
    except Exception as exc:
        db_error = f"{type(exc).__name__}: {exc}"

    rows: dict[str, int] = {}
    revision: str | None = None
    if db is not None:
        from sqlalchemy.orm import Session

        session = Session(db)
        try:
            rows = _row_counts(session)
            revision = _alembic_revision(session)
        finally:
            session.close()

    db_file = settings.resolved_db_path
    db_exists = bool(db_file and db_file.exists())
    db_bytes = db_file.stat().st_size if db_exists else 0
    manifest: dict[str, Any] = {
        "manifest_version": MANIFEST_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "app_version": _app_version(),
        "alembic_revision": revision,
        "alembic_head": _alembic_head(),
        "data_dir": str(settings.data_dir),
        "database": {
            "file": str(db_file) if db_file else None,
            "exists": db_exists,
            "bytes": db_bytes,
        },
        "dirs": {
            "sessions": _dir_stat(settings.sessions_dir),
            "documents": _dir_stat(settings.documents_dir),
            "pqa": _dir_stat(settings.resolved_pqa_home),
            "hf_cache": _dir_stat(settings.resolved_hf_home),
            "torch_cache": _dir_stat(settings.resolved_torch_home),
        },
        "tables": rows,
        "totals": {
            "rows": sum(v for v in rows.values() if v > 0),
            "files": 0,
            "bytes": db_bytes,
        },
        "models": {
            "llm": settings.llm_model,
            "summary_llm": settings.resolved_summary_llm,
            "embedding": settings.embedding_model,
        },
    }
    for key in ("sessions", "documents", "pqa"):
        entry = manifest["dirs"][key]
        manifest["totals"]["files"] += entry["files"]
        manifest["totals"]["bytes"] += entry["bytes"]

    if settings_error:
        manifest["warnings"] = [f"настройки: {settings_error}"]
    if db_error:
        manifest.setdefault("warnings", []).append(f"БД: {db_error}")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Манифест бэкапа boasi_s (JSON)")
    parser.add_argument("--output", help="куда записать (по умолчанию — stdout)")
    parser.add_argument("--compact", action="store_true", help="одна строка без отступов")
    args = parser.parse_args()

    manifest = build_manifest()
    text = json.dumps(
        manifest,
        ensure_ascii=False,
        indent=None if args.compact else 2,
        separators=(",", ":") if args.compact else None,
    )
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(f"OK: {args.output}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())