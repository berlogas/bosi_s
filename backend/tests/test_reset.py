"""Сброс состояния: уровни, защита кэша моделей, dry-run, prod-запрет, API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.config import Settings
from app.core.errors import ForbiddenError
from app.db.models import AuditLog, DocumentChunk, Message, RefreshToken, ResearchSession, User
from app.db.repositories.messages import save_exchange
from app.db.repositories.users import (
    create_research_session,
    create_user,
    get_user_by_username,
    save_refresh_token,
)
from app.services.reset import (
    CONFIRM_PHRASES,
    plan_reset,
    run_reset,
    tables_for,
    wipe_paths,
)


@pytest.fixture
def tmp_settings(tmp_path: Path) -> Settings:
    """Настройки на отдельном каталоге: сброс не должен трогать боевые данные."""
    settings = Settings(
        data_dir=tmp_path / "data",
        environment="dev",
        secret_key="test-secret-key-0123456789",
        _env_file=None,  # type: ignore[call-arg]
    )
    settings.ensure_dirs()
    return settings


def _seed(db, settings: Settings) -> dict:
    """Пользователь + сессия + сообщения + refresh-токен + файлы на диске."""
    from app.core.security import hash_password

    user = create_user(db, username="reset-admin", password="reset-pass-123",
                       role="admin", hashed_password=hash_password("reset-pass-123"))
    session = create_research_session(db, user, "Рабочая сессия")
    save_exchange(db, user=user, question="вопрос", answer="ответ",
                  session_id=session.id)
    save_refresh_token(db, user.id, "hash-of-token",
                       datetime.now(UTC) + timedelta(days=30))
    db.add(DocumentChunk(collection="global", dockey="d1", docname="doc",
                         chunk_count=1, doc_blob=b"x", texts_blob=b"y"))
    db.commit()

    (settings.sessions_dir / session.id / "files").mkdir(parents=True, exist_ok=True)
    (settings.sessions_dir / session.id / "files" / "paper.pdf").write_bytes(b"x" * 64)
    (settings.documents_dir / "incoming").mkdir(parents=True, exist_ok=True)
    (settings.documents_dir / "incoming" / "note.txt").write_text("черновик")
    (settings.resolved_pqa_home / "answers" / "ab").mkdir(parents=True, exist_ok=True)
    (settings.resolved_pqa_home / "answers" / "ab" / "c.json").write_text("{}")
    # Кэш моделей: внутри data_dir, но сброс данных его не должен трогать.
    (settings.resolved_hf_home / "hub").mkdir(parents=True, exist_ok=True)
    (settings.resolved_hf_home / "hub" / "model.bin").write_bytes(b"w" * 128)
    return {"user_id": user.id, "session_id": session.id}


def _count(db, model) -> int:
    return int(db.execute(select(func.count()).select_from(model)).scalar_one())


# --------------------------------------------------------------------- уровни
def test_scope_data_keeps_users_and_audit(db, tmp_settings) -> None:
    seeded = _seed(db, tmp_settings)

    result = run_reset("data", dry_run=False, db=db, settings=tmp_settings)

    assert _count(db, User) == 1
    assert _count(db, ResearchSession) == 0
    assert _count(db, Message) == 0
    assert _count(db, RefreshToken) == 1
    assert result.deleted_tables["research_sessions"] == 1
    assert _count(db, DocumentChunk) == 0
    # Файлы удалены, каталоги пересозданы пустыми
    assert not (tmp_settings.sessions_dir / seeded["session_id"]).exists()
    assert list(tmp_settings.documents_dir.iterdir()) == []
    assert tmp_settings.sessions_dir.exists()
    # Запись о сбросе остаётся в аудите
    assert _count(db, AuditLog) >= 1


def test_scope_users_also_drops_refresh_tokens(db, tmp_settings) -> None:
    _seed(db, tmp_settings)

    result = run_reset("users", dry_run=False, db=db, settings=tmp_settings)

    assert _count(db, User) == 1, "scope=users сохраняет учётные записи"
    assert _count(db, RefreshToken) == 0, "все входы должны быть сброшены"
    assert result.deleted_tables.get("refresh_tokens") == 1


def test_scope_all_empties_everything_but_leaves_trace(db, tmp_settings) -> None:
    _seed(db, tmp_settings)

    run_reset("all", dry_run=False, db=db, settings=tmp_settings)

    assert _count(db, User) == 0
    assert _count(db, RefreshToken) == 0
    # Аудит очищен, но запись о самом сбросе должна остаться
    entries = list(db.scalars(select(AuditLog)))
    assert len(entries) == 1
    assert entries[0].action == "admin.reset"
    assert entries[0].target_id == "all"


def test_unknown_scope_rejected(tmp_settings) -> None:
    with pytest.raises(ValueError, match="Неизвестный scope"):
        plan_reset("nope", settings=tmp_settings)


def test_tables_order_respects_dependencies() -> None:
    data = tables_for("data")
    assert data.index("messages") < data.index("research_sessions")
    assert data.index("projects") < data.index("research_sessions")
    assert tables_for("users") == (*data, "refresh_tokens")
    assert tables_for("all") == (*tables_for("users"), "audit_log", "users")


# --------------------------------------------------------------------- dry-run
def test_dry_run_changes_nothing(db, tmp_settings) -> None:
    seeded = _seed(db, tmp_settings)

    result = run_reset("data", dry_run=True, db=db, settings=tmp_settings)

    assert result.dry_run is True
    assert result.deleted_tables == {}
    assert _count(db, User) == 1
    assert (tmp_settings.sessions_dir / seeded["session_id"] / "files"
            / "paper.pdf").exists()


def test_plan_reports_rows_files_and_kept_paths(db, tmp_settings) -> None:
    _seed(db, tmp_settings)

    plan = plan_reset("data", db=db, settings=tmp_settings)

    assert plan.allowed is True
    assert plan.tables["research_sessions"] == 1
    assert plan.tables["messages"] == 2
    assert plan.files == 3
    assert plan.total_bytes > 0
    assert str(tmp_settings.resolved_hf_home) in plan.kept_paths
    assert {Path(p.path).name for p in plan.paths} == {"sessions", "documents", "pqa"}


# ------------------------------------------------------- кэш моделей не трогаем
def test_model_cache_survives_data_reset(db, tmp_settings) -> None:
    targets, kept = wipe_paths(tmp_settings)
    assert str(tmp_settings.resolved_hf_home) in kept
    assert tmp_settings.resolved_hf_home not in targets
    model = tmp_settings.resolved_hf_home / "hub" / "model.bin"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(b"w" * 128)

    run_reset("data", dry_run=False, db=db, settings=tmp_settings)

    assert model.exists(), "сброс данных обязан сохранить модель эмбеддингов"


def test_include_models_removes_cache(db, tmp_settings) -> None:
    model = tmp_settings.resolved_hf_home / "hub" / "model.bin"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(b"w" * 128)

    result = run_reset("data", dry_run=False, include_models=True, db=db,
                       settings=tmp_settings)

    assert not model.exists()
    assert result.plan.kept_paths == []


# ----------------------------------------------------------------------- prod
def test_prod_reset_requires_explicit_flag(tmp_settings) -> None:
    tmp_settings.environment = "prod"
    tmp_settings.allow_destructive_reset = False

    plan = plan_reset("all", settings=tmp_settings)
    assert plan.allowed is False
    assert "ALLOW_DESTRUCTIVE_RESET" in (plan.blocked_reason or "")
    with pytest.raises(ForbiddenError):
        run_reset("all", dry_run=False, settings=tmp_settings)


def test_prod_reset_allowed_with_flag(tmp_settings) -> None:
    tmp_settings.environment = "prod"
    tmp_settings.allow_destructive_reset = True

    assert plan_reset("data", settings=tmp_settings).allowed is True


# ------------------------------------------------------------------- файлы сброса
def test_run_reset_opens_own_session_when_db_not_given(db_engine, db, tmp_settings,
                                                        monkeypatch) -> None:
    """Путь CLI: сессия открывается внутри `run_reset` и закрывается там же."""
    from sqlalchemy.orm import sessionmaker

    from app.services import reset as reset_module

    factory = sessionmaker(bind=db_engine, expire_on_commit=False, future=True)
    monkeypatch.setattr(reset_module, "get_session_factory", lambda: factory)
    _seed(db, tmp_settings)

    result = run_reset("data", dry_run=False, settings=tmp_settings)

    assert result.deleted_tables["research_sessions"] == 1
    assert _count(db, User) == 1
def test_skeleton_dirs_recreated(db, tmp_settings) -> None:
    run_reset("data", dry_run=False, db=db, settings=tmp_settings)

    assert tmp_settings.sessions_dir.is_dir()
    assert tmp_settings.documents_dir.is_dir()
    assert tmp_settings.resolved_pqa_home.is_dir()


def test_scope_all_is_confirmed_by_phrase() -> None:
    assert set(CONFIRM_PHRASES) == {"data", "users", "all"}
    assert len(set(CONFIRM_PHRASES.values())) == 3, "фразы должны различаться"


# ------------------------------------------------------------------------- API
async def test_reset_preview_requires_admin(client, researcher_user) -> None:
    from tests.conftest import login_headers

    headers = await login_headers(client, "ivanov", "researcher-pass-123")
    response = await client.get("/api/admin/reset/preview", headers=headers)
    assert response.status_code == 403


async def test_reset_preview_reports_plan(client, admin_user, tmp_settings,
                                          monkeypatch) -> None:
    from app.services import reset as reset_module
    from tests.conftest import login_headers

    monkeypatch.setattr(reset_module, "get_settings", lambda: tmp_settings)
    headers = await login_headers(client, "admin", "admin-pass-123")

    response = await client.get("/api/admin/reset/preview?scope=data", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scope"] == "data"
    assert "research_sessions" in body["tables"]
    assert body["confirmation"] == CONFIRM_PHRASES["data"]


async def test_reset_rejects_wrong_confirmation(client, admin_user, tmp_settings,
                                               monkeypatch) -> None:
    from app.services import reset as reset_module
    from tests.conftest import login_headers

    monkeypatch.setattr(reset_module, "get_settings", lambda: tmp_settings)
    headers = await login_headers(client, "admin", "admin-pass-123")

    response = await client.post("/api/admin/reset",
                                 json={"scope": "data", "confirm": "точно нет"},
                                 headers=headers)

    assert response.status_code == 409
    assert CONFIRM_PHRASES["data"] in response.json()["detail"]


async def test_reset_executes_with_confirmation(client, admin_user, tmp_settings,
                                                monkeypatch) -> None:
    from app.services import reset as reset_module
    from tests.conftest import login_headers

    monkeypatch.setattr(reset_module, "get_settings", lambda: tmp_settings)
    headers = await login_headers(client, "admin", "admin-pass-123")
    created = await client.post("/api/sessions", json={"title": "Сессия для сброса"},
                                headers=headers)
    assert created.status_code == 201, created.text
    sessions_path = tmp_settings.sessions_dir / "some-session"
    sessions_path.mkdir(parents=True, exist_ok=True)

    response = await client.post(
        "/api/admin/reset",
        json={"scope": "data", "confirm": CONFIRM_PHRASES["data"]},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dry_run"] is False
    assert body["deleted_tables"]["research_sessions"] == 1
    assert not sessions_path.exists()
    # Сброс записан в аудит
    audit = await client.get("/api/admin/audit?action=admin.reset", headers=headers)
    assert audit.status_code == 200
    assert audit.json()[0]["action"] == "admin.reset"


async def test_reset_blocked_in_prod_via_api(client, admin_user, tmp_settings,
                                             monkeypatch) -> None:
    from app.services import reset as reset_module
    from tests.conftest import login_headers

    tmp_settings.environment = "prod"
    monkeypatch.setattr(reset_module, "get_settings", lambda: tmp_settings)
    headers = await login_headers(client, "admin", "admin-pass-123")

    response = await client.post(
        "/api/admin/reset",
        json={"scope": "all", "confirm": CONFIRM_PHRASES["all"]},
        headers=headers,
    )

    assert response.status_code == 403


# ------------------------------------------------------------- учётные записи
def test_admin_created_user_can_still_login_after_users_reset(db, tmp_settings) -> None:
    _seed(db, tmp_settings)

    run_reset("users", dry_run=False, db=db, settings=tmp_settings)

    assert get_user_by_username(db, "reset-admin") is not None