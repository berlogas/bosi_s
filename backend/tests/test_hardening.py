"""Фаза 9 — hardening: пути, rate-limit, метрики, проверка конфигурации.

Это те требования ТЗ, которые защищают данные исследователя:
путь не должен выводить за пределы каталога сессии, перебор пароля должен
упираться в блокировку, а слабый SECRET_KEY — не проходить молча.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.errors import ForbiddenError
from app.core.safety import (
    ensure_within,
    resolve_import_path,
    session_import_roots,
    validate_global_import,
    validate_session_import,
)


# --------------------------------------------------------------------------- пути
@pytest.fixture
def session_tree(service_app, tmp_path, monkeypatch) -> Path:
    """Дерево каталогов сессии внутри тестового data_dir."""
    data = tmp_path / "hardening-data"
    service_app.data_dir = data
    service_app.ensure_dirs()

    session_id = "sess-123"
    files = session_id and data / "sessions" / session_id / "uploads"
    files.mkdir(parents=True, exist_ok=True)
    good = files / "paper.md"
    good.write_text("# Paper\n\nChl-a 1.85.\n", encoding="utf-8")

    shared = data / "documents"
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "shared.csv").write_text("a,b\n1,2\n", encoding="utf-8")

    monkeypatch.setattr("app.core.safety.get_settings", lambda: service_app)
    return data


def test_path_inside_session_is_allowed(session_tree) -> None:
    target = session_tree / "sessions" / "sess-123" / "uploads" / "paper.md"
    assert validate_session_import("sess-123", str(target)) == target.resolve()


def test_shared_documents_dir_is_allowed(session_tree) -> None:
    target = session_tree / "documents" / "shared.csv"
    assert validate_session_import("sess-123", str(target)).name == "shared.csv"


def test_path_outside_session_is_rejected(session_tree) -> None:
    secret = Path("C:/Windows/System32/drivers/etc/hosts")
    with pytest.raises(ForbiddenError) as exc:
        validate_session_import("sess-123", str(secret))
    assert "вне разрешённых каталогов" in str(exc.value)


def test_parent_traversal_is_rejected(session_tree) -> None:
    """`..` не должен выводить за пределы каталога сессии."""
    escape = session_tree / "sessions" / "sess-123" / "uploads" / ".." / ".." \
        / ".." / "etc" / "passwd"
    with pytest.raises(ForbiddenError):
        validate_session_import("sess-123", str(escape))


def test_other_session_directory_is_rejected(session_tree) -> None:
    """Документы чужой сессии недоступны — это и есть изоляция сессий."""
    foreign = session_tree / "sessions" / "other" / "uploads" / "secret.md"
    foreign.parent.mkdir(parents=True, exist_ok=True)
    foreign.write_text("чужое", encoding="utf-8")

    with pytest.raises(ForbiddenError):
        validate_session_import("sess-123", str(foreign))


def test_symlink_escape_is_rejected(session_tree) -> None:
    """Симлинк наружу не обходит проверку (проверяем ПОСЛЕ resolve)."""
    link = session_tree / "sessions" / "sess-123" / "uploads" / "leak.md"
    target = session_tree.parent / "outside.md"
    target.write_text("вне", encoding="utf-8")
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("симлинки недоступны на этой платформе")

    with pytest.raises(ForbiddenError):
        validate_session_import("sess-123", str(link))


def test_missing_file_is_not_found(session_tree) -> None:
    """Путь разрешён, файла нет: это 404 (NotFoundError), а не 403."""
    from app.core.errors import NotFoundError

    missing = session_tree / "sessions" / "sess-123" / "uploads" / "nope.md"
    with pytest.raises(NotFoundError) as exc:
        validate_session_import("sess-123", str(missing))
    assert "не найден" in str(exc.value)
    assert exc.value.status_code == 404


def test_directory_is_not_a_file(session_tree) -> None:
    directory = session_tree / "sessions" / "sess-123" / "uploads"
    with pytest.raises(ForbiddenError) as exc:
        validate_session_import("sess-123", str(directory))
    assert "не файл" in str(exc.value)


def test_empty_path_is_rejected(session_tree) -> None:
    with pytest.raises(ForbiddenError):
        validate_session_import("sess-123", "   ")


def test_external_paths_blocked_by_default(session_tree) -> None:
    outside = session_tree.parent / "elsewhere.md"
    outside.write_text("x", encoding="utf-8")
    with pytest.raises(ForbiddenError):
        validate_global_import(str(outside))


def test_external_paths_allowed_when_configured(session_tree,
                                                service_app) -> None:
    """С флагом админ может импортировать из любого места каталога данных."""
    service_app.allow_external_import_paths = True
    inside_data = session_tree / "other_area.md"
    inside_data.write_text("x", encoding="utf-8")

    assert validate_global_import(str(inside_data)).exists()


def test_flag_does_not_open_files_outside_data_dir(session_tree,
                                                   service_app) -> None:
    """Даже с флагом файлы за пределами data_dir остаются недоступны."""
    service_app.allow_external_import_paths = True
    outside = session_tree.parent / "elsewhere.md"
    outside.write_text("x", encoding="utf-8")

    with pytest.raises(ForbiddenError):
        validate_global_import(str(outside))


def test_session_roots_are_scoped(session_tree) -> None:
    roots = session_import_roots("sess-123")
    assert any(str(r).endswith("sess-123") for r in roots)


def test_resolve_import_path_returns_absolute(session_tree) -> None:
    target = session_tree / "documents" / "shared.csv"
    assert resolve_import_path(str(target), session_import_roots("sess-123")).is_absolute()


def test_must_exist_can_be_relaxed(session_tree) -> None:
    future = session_tree / "documents" / "later.csv"
    assert resolve_import_path(str(future), [session_tree / "documents"],
                               must_exist=False).name == "later.csv"


def test_ensure_within_rejects_escape(session_tree) -> None:
    outside = session_tree.parent / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    with pytest.raises(ForbiddenError):
        ensure_within(outside, session_tree / "documents")


# --------------------------------------------------------------------------- rate-limit
def test_login_limiter_blocks_after_threshold(monkeypatch) -> None:
    from app.config import get_settings
    from app.core.rate_limit import SlidingWindowLimiter

    settings = get_settings()
    monkeypatch.setattr(settings, "login_max_attempts", 3, raising=False)
    limiter = SlidingWindowLimiter()

    for _ in range(3):
        assert limiter.is_blocked("ivanov", "1.2.3.4") is False
        limiter.record_failure("ivanov", "1.2.3.4")

    assert limiter.is_blocked("ivanov", "1.2.3.4") is True


def test_login_limiter_is_per_login_and_ip(monkeypatch) -> None:
    from app.config import get_settings
    from app.core.rate_limit import SlidingWindowLimiter

    settings = get_settings()
    monkeypatch.setattr(settings, "login_max_attempts", 2, raising=False)
    limiter = SlidingWindowLimiter()

    limiter.record_failure("ivanov", "1.2.3.4")
    limiter.record_failure("ivanov", "1.2.3.4")

    assert limiter.is_blocked("ivanov", "1.2.3.4") is True
    assert limiter.is_blocked("ivanov", "5.6.7.8") is False, "другой IP не блокируется"
    assert limiter.is_blocked("petrov", "1.2.3.4") is False, "другой логин не блокируется"


def test_login_limiter_reset_on_success(monkeypatch) -> None:
    from app.config import get_settings
    from app.core.rate_limit import SlidingWindowLimiter

    settings = get_settings()
    monkeypatch.setattr(settings, "login_max_attempts", 3, raising=False)
    limiter = SlidingWindowLimiter()

    limiter.record_failure("ivanov", "1.2.3.4")
    limiter.record_failure("ivanov", "1.2.3.4")
    limiter.reset("ivanov", "1.2.3.4")

    assert limiter.remaining("ivanov", "1.2.3.4") == 3


def test_login_limiter_window_expires(monkeypatch) -> None:
    import app.core.rate_limit as rate_limit
    from app.config import get_settings
    from app.core.rate_limit import SlidingWindowLimiter

    settings = get_settings()
    monkeypatch.setattr(settings, "login_max_attempts", 2, raising=False)
    monkeypatch.setattr(settings, "login_window_seconds", 0, raising=False)
    limiter = SlidingWindowLimiter()

    limiter.record_failure("ivanov", "1.2.3.4")
    limiter.record_failure("ivanov", "1.2.3.4")

    # окно истекло -> попытки вытеснены, блокировки нет
    assert limiter.is_blocked("ivanov", "1.2.3.4") is False
    assert limiter.stats() == {"tracked_keys": 0}
    assert isinstance(rate_limit.login_limiter.stats(), dict)


# --------------------------------------------------------------------------- SECRET_KEY
def test_short_secret_key_is_rejected() -> None:
    from app.config import Settings

    settings = Settings(secret_key="short")
    with pytest.raises(RuntimeError) as exc:
        settings.validate_runtime()
    assert "SECRET_KEY" in str(exc.value)


def test_placeholder_secret_key_is_rejected() -> None:
    from app.config import Settings

    settings = Settings(secret_key="change-me-please-generate-48-bytes-x")
    with pytest.raises(RuntimeError) as exc:
        settings.validate_runtime()
    assert "шаблонным" in str(exc.value)


def test_good_secret_key_passes() -> None:
    from app.config import Settings

    settings = Settings(secret_key="x" * 48)
    assert settings.validate_runtime() == []


def test_prod_issues_are_warned() -> None:
    from app.config import Settings

    settings = Settings(secret_key="y" * 48, environment="prod", debug=True,
                        multimodal=True, offline_mode=False)
    warnings = settings.validate_runtime()

    assert any("DEBUG" in w for w in warnings)
    assert any("MULTIMODAL" in w for w in warnings)
    assert any("OFFLINE_MODE" in w for w in warnings)


def test_external_import_flag_is_warned() -> None:
    from app.config import Settings

    settings = Settings(secret_key="z" * 48, allow_external_import_paths=True)
    assert any("ALLOW_EXTERNAL_IMPORT_PATHS" in w
               for w in settings.validate_runtime())


# --------------------------------------------------------------------------- метрики
async def test_metrics_renders_prometheus_text(client) -> None:
    response = await client.get("/api/metrics")

    assert response.status_code == 200
    body = response.text
    assert "boasi_uptime_seconds" in body
    assert "# TYPE boasi_sessions gauge" in body
    assert "boasi_documents_total" in body
    assert "boasi_tasks_active" in body


async def test_metrics_json(client, researcher_user) -> None:
    response = await client.get("/api/metrics.json")

    body = response.json()
    assert body["tasks_active"] >= 0
    assert "documents" in body and "chunks" in body


async def test_health_reports_configuration(client) -> None:
    body = (await client.get("/api/health")).json()

    assert body["status"] in {"ok", "degraded"}
    assert body["database"] == "ok"
    assert "reachable" in body["ollama"]