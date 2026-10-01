"""Конфигурация: значения из .env, дефолты, вычисляемые пути, лимиты ТЗ."""

from __future__ import annotations

from pathlib import Path


def test_resolved_paths_are_absolute(tmp_path: Path) -> None:
    settings = type("S", (), {})
    from app.config import Settings

    s = Settings(data_dir=tmp_path / "data")  # type: ignore[call-arg]
    assert s.data_dir.is_absolute()
    assert s.sessions_dir.name == "sessions"
    assert s.documents_dir.name == "documents"
    assert s.resolved_pqa_home.name == "pqa"
    assert s.resolved_db_url.startswith("sqlite:///")
    assert settings is not None


def test_relative_data_dir_resolved_from_project_root() -> None:
    from app.config import PROJECT_ROOT, Settings

    s = Settings(data_dir="./data")  # type: ignore[call-arg]
    assert s.data_dir == PROJECT_ROOT / "data"


def test_model_is_single_config_value() -> None:
    """Модель меняется только конфигом — в коде констант производительности нет."""
    from app.config import Settings

    dev = Settings()  # type: ignore[call-arg]
    prod = Settings(llm_model="ollama/qwen2.5:14b")  # type: ignore[call-arg]
    assert dev.llm_model == "ollama/qwen2.5:3b"
    assert prod.resolved_summary_llm == "ollama/qwen2.5:14b"
    assert dev.summary_llm_model is None  # summary == llm по умолчанию


def test_limits_match_spec() -> None:
    from app.config import Settings

    s = Settings()  # type: ignore[call-arg]
    assert s.session_ttl_days == 90
    assert s.heartbeat_interval_minutes == 5
    assert s.max_sessions_per_user == 10
    assert s.max_documents_per_session == 50
    assert s.max_session_storage_mb == 500
    assert s.max_projects_per_session == 5
    assert s.offline_mode is True
    assert s.multimodal is False
    assert s.llm_timeout_seconds >= 1800  # иначе lmi ретраит по 60 с


def test_public_summary_hides_secrets() -> None:
    from app.config import Settings

    s = Settings(secret_key="super-secret")  # type: ignore[call-arg]
    summary = s.public_summary()
    assert "super-secret" not in str(summary)
    assert summary["llm_model"] == "ollama/qwen2.5:3b"
