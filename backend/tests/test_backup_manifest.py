"""Манифест бэкапа: состав, ревизия схемы, объём, работа без БД."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR / "scripts") not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR / "scripts"))

from backup_manifest import MANIFEST_VERSION, build_manifest  # noqa: E402


def _patch(monkeypatch, engine, settings) -> None:
    """build_manifest берёт настройки и движок по месту вызова — подменяем их."""
    import app.config
    import app.db.session

    monkeypatch.setattr(app.config, "get_settings", lambda: settings)
    monkeypatch.setattr(app.db.session, "get_engine", lambda *a, **k: engine)


def test_manifest_reports_counts_and_dirs(db_engine, db, tmp_path, monkeypatch) -> None:
    from app.config import Settings
    from app.core.security import hash_password
    from app.db.repositories.users import create_user

    create_user(db, username="bcp-user", password="backup-pass-123",
                hashed_password=hash_password("backup-pass-123"))

    settings = Settings(
        data_dir=tmp_path,
        database_url=str(db_engine.url),   # БД та, что создала фикстура
        environment="test",
        secret_key="test-secret-key-0123456789",
        _env_file=None,  # type: ignore[call-arg]
    )
    settings.ensure_dirs()
    (settings.sessions_dir / "s-1" / "files").mkdir(parents=True, exist_ok=True)
    (settings.sessions_dir / "s-1" / "files" / "a.pdf").write_bytes(b"x" * 32)
    _patch(monkeypatch, db_engine, settings)

    manifest = build_manifest()

    assert manifest["manifest_version"] == MANIFEST_VERSION
    assert manifest["app_version"]
    assert manifest["tables"]["users"] == 1
    assert manifest["totals"]["rows"] >= 1
    assert manifest["dirs"]["sessions"]["files"] == 1
    assert manifest["dirs"]["sessions"]["bytes"] == 32
    assert manifest["database"]["exists"] is True
    assert manifest["models"]["embedding"]


def test_manifest_is_json_serialisable(db_engine, tmp_path, monkeypatch) -> None:
    from app.config import Settings

    settings = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{(tmp_path / 'boasi.sqlite3').as_posix()}",
        environment="test",
        secret_key="test-secret-key-0123456789",
        _env_file=None,  # type: ignore[call-arg]
    )
    settings.ensure_dirs()
    _patch(monkeypatch, db_engine, settings)

    manifest = build_manifest()
    dumped = json.loads(json.dumps(manifest, ensure_ascii=False))

    assert dumped["data_dir"] == str(tmp_path)


def test_manifest_survives_missing_database(tmp_path, monkeypatch) -> None:
    """Свежий том без миграций: манифест собирается, а не падает."""
    from sqlalchemy import create_engine

    from app.config import Settings

    missing = tmp_path / "nope" / "boasi.sqlite3"
    settings = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{missing.as_posix()}",
        environment="test",
        secret_key="test-secret-key-0123456789",
        _env_file=None,  # type: ignore[call-arg]
    )
    settings.ensure_dirs()
    engine = create_engine(f"sqlite:///{missing.as_posix()}", future=True)
    try:
        _patch(monkeypatch, engine, settings)
        manifest = build_manifest()
    finally:
        engine.dispose()

    assert manifest["tables"] == {}
    assert manifest["database"]["exists"] is False
    assert manifest["alembic_revision"] is None


def test_manifest_writes_output_file(db_engine, tmp_path, monkeypatch) -> None:
    import backup_manifest

    from app.config import Settings

    settings = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{(tmp_path / 'boasi.sqlite3').as_posix()}",
        environment="test",
        secret_key="test-secret-key-0123456789",
        _env_file=None,  # type: ignore[call-arg]
    )
    settings.ensure_dirs()
    _patch(monkeypatch, db_engine, settings)

    target = tmp_path / "boasi-manifest.json"
    monkeypatch.setattr(sys, "argv", ["backup_manifest.py", "--output", str(target)])
    assert backup_manifest.main() == 0

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["manifest_version"] == MANIFEST_VERSION


# ------------------------------------------------------- путь к файлу БД
@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("sqlite:////data/boasi.sqlite3", "/data/boasi.sqlite3"),
        ("sqlite:////app/data/boasi.sqlite3", "/app/data/boasi.sqlite3"),
    ],
)
def test_resolved_db_path_posix(tmp_path, url: str, expected: str) -> None:
    from app.config import Settings

    settings = Settings(data_dir=tmp_path, database_url=url,
                        secret_key="test-secret-key-0123456789", _env_file=None)  # type: ignore[call-arg]
    # путь сверяем в posix-виде: на Windows str(Path('/data/x')) даёт backslash
    assert settings.resolved_db_path.as_posix() == expected


def test_resolved_db_path_ignores_non_sqlite(tmp_path) -> None:
    from app.config import Settings

    settings = Settings(data_dir=tmp_path, database_url="postgresql://host/boasi",
                        secret_key="test-secret-key-0123456789", _env_file=None)  # type: ignore[call-arg]
    assert settings.resolved_db_path is None


def test_resolved_db_path_from_data_dir(tmp_path) -> None:
    from app.config import Settings

    settings = Settings(
        data_dir=tmp_path,
        database_url=None,  # DATABASE_URL из окружения тестов иначе подставится
        secret_key="test-secret-key-0123456789",
        _env_file=None,  # type: ignore[call-arg]
    )
    assert settings.resolved_db_path == tmp_path / "boasi.sqlite3"