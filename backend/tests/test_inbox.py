"""Массовая загрузка файлов из inbox: скан, журнал, перенос в библиотеку.

Тесты идут без сети и без LLM (см. `conftest.py`): индексация настоящая,
но на коротких текстовых файлах.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.db.models import Document, InboxFile, InboxFileStatus, InboxRunStatus
from app.services.inbox import (
    REASON_REPLACED,
    REASON_TOO_LARGE,
    REASON_UNSUPPORTED,
    InboxService,
)


@pytest.fixture
def inbox_app(service_app, tmp_path):
    """Настройки с отдельными каталогами inbox/library/rejected."""
    app = service_app.model_copy(update={
        "data_dir": tmp_path / "data",
        "inbox_dir": tmp_path / "inbox",
        "library_dir": tmp_path / "data" / "documents" / "library",
        "rejected_dir": tmp_path / "data" / "rejected",
    })
    app.ensure_dirs()
    return app


@pytest.fixture
def inbox_service(inbox_app):
    return InboxService(inbox_app)


def _put(inbox: Path, name: str, text: str = "Привет, это тестовый документ.") -> Path:
    path = inbox / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _files(db) -> list[InboxFile]:
    return list(db.scalars(select(InboxFile).order_by(InboxFile.rel_path)))


# --------------------------------------------------------------------------- скан
async def test_scan_archives_file_into_library(db, inbox_service, inbox_app, service, admin_user):
    _put(inbox_service.inbox_dir, "doc.txt")

    run = await inbox_service.scan(db, service, admin_user)

    assert run.status == InboxRunStatus.done
    assert (run.scanned, run.indexed, run.archived, run.rejected, run.failed) == (1, 1, 1, 0, 0)
    row = _files(db)[0]
    assert row.status == InboxFileStatus.archived
    # файл ушёл из inbox и лежит в постоянной библиотеке
    assert not (inbox_service.inbox_dir / "doc.txt").exists()
    assert row.final_path and Path(row.final_path).exists()
    assert Path(row.final_path).is_relative_to(inbox_service.library_dir)


async def test_scan_indexes_before_moving(db, inbox_service, service, admin_user):
    """Индексация идёт по файлу в inbox — перенос только после успеха."""
    _put(inbox_service.inbox_dir, "a.txt")
    _put(inbox_service.inbox_dir, "b.txt")

    seen: list[Path] = []
    original = service.add_file

    async def spy(path, *args, **kwargs):
        seen.append(Path(path))
        # на момент индексации оба файла ещё лежат во входной папке
        assert (inbox_service.inbox_dir / "a.txt").exists()
        assert (inbox_service.inbox_dir / "b.txt").exists()
        return await original(path, *args, **kwargs)

    service.add_file = spy  # type: ignore[method-assign]
    await inbox_service.scan(db, service, admin_user)

    assert len(seen) == 2


async def test_document_path_points_to_library(db, inbox_service, service, admin_user):
    _put(inbox_service.inbox_dir, "doc.txt")

    await inbox_service.scan(db, service, admin_user)

    document = db.scalar(select(Document).where(Document.filename == "doc.txt"))
    assert document is not None
    assert Path(document.path).exists()
    assert Path(document.path).is_relative_to(inbox_service.library_dir)


# --------------------------------------------------------------------------- брак
async def test_unsupported_extension_goes_to_rejected(db, inbox_service, service, admin_user):
    _put(inbox_service.inbox_dir, "photo.png")

    run = await inbox_service.scan(db, service, admin_user)

    assert run.rejected == 1
    row = _files(db)[0]
    assert row.reason_code == REASON_UNSUPPORTED
    assert row.status == InboxFileStatus.rejected
    # inbox чист, брак — в rejected, причина сохранена в журнале
    assert list(inbox_service.inbox_dir.iterdir()) == []
    rejected = list(inbox_service.rejected_dir.rglob("photo.png"))
    assert len(rejected) == 1


async def test_oversized_file_goes_to_rejected(db, inbox_service, inbox_app, service, admin_user):
    inbox_app.upload_max_mb = 0
    inbox_app.allowed_extensions = [".txt"]
    _put(inbox_service.inbox_dir, "big.txt")

    run = await inbox_service.scan(db, service, admin_user)

    assert run.rejected == 1
    assert _files(db)[0].reason_code == REASON_TOO_LARGE


async def test_broken_file_stays_in_inbox(db, inbox_service, service, admin_user):
    """Не удалось проиндексировать — файл остаётся во входной папке."""
    broken = inbox_service.inbox_dir / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 broken")

    run = await inbox_service.scan(db, service, admin_user)

    assert run.failed == 1
    row = _files(db)[0]
    assert row.status == InboxFileStatus.failed
    assert row.reason_code == "parse_error"
    assert broken.exists()


# --------------------------------------------------------------------------- замена
async def test_same_filename_replaces_previous_document(db, inbox_service, service, admin_user):
    _put(inbox_service.inbox_dir, "report.txt", "Первая версия отчёта.")
    await inbox_service.scan(db, service, admin_user)
    first = db.scalar(select(Document).where(Document.filename == "report.txt"))

    _put(inbox_service.inbox_dir, "report.txt", "Вторая, исправленная версия отчёта.")
    run = await inbox_service.scan(db, service, admin_user)

    assert run.replaced == 1
    documents = list(db.scalars(select(Document).where(Document.filename == "report.txt")))
    assert len(documents) == 1
    assert documents[0].id != first.id
    # прежний документ удалён вместе со ссылкой из журнала
    # журнал ссылается на НОВЫЙ документ (прежний удалён)
    assert _files(db)[-1].document_id == documents[0].id
    assert Path(documents[0].path).exists()
    assert _files(db)[-1].reason_code == REASON_REPLACED


# --------------------------------------------------------------------------- журнал
def test_peek_reports_only_usable_files(db, inbox_service):
    _put(inbox_service.inbox_dir, "good.txt")
    _put(inbox_service.inbox_dir, "bad.png")

    status = inbox_service.peek(db)

    assert status["files"] == 2
    assert status["usable_files"] == 1
    assert status["unsupported_files"] == 1
    assert status["busy"] is False


def test_peek_reports_busy_while_run_open(db, inbox_service, admin_user):
    inbox_service.start_run(db, admin_user)

    assert inbox_service.peek(db)["busy"] is True


def test_interrupted_run_is_closed_with_reason(db, inbox_service, admin_user):
    """Прогон, оставшийся `running` (обрыв процесса), закрывается с причиной."""
    run = inbox_service.start_run(db, admin_user)
    db.add(InboxFile(run_id=run.id, rel_path="a.txt", abs_path="/x/a.txt",
                     status=InboxFileStatus.indexed, stage="indexed"))
    db.commit()

    closed = inbox_service.reconcile_interrupted(db)

    assert closed == 1
    db.refresh(run)
    row = _files(db)[0]
    assert run.status == InboxRunStatus.failed
    assert row.status == InboxFileStatus.failed
    assert row.reason_code == "interrupted"
    assert "перезапущен" in row.reason_text


def test_partial_files_are_removed_on_reconcile(db, inbox_service):
    """Незавершённый файл `*.inbox-partial` убирается при сверке."""
    stale = inbox_service.library_dir / "2026-10" / "doc.txt.inbox-partial"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("half", encoding="utf-8")

    inbox_service.reconcile_interrupted(db)

    assert not stale.exists()


async def test_run_history_is_ordered_newest_first(db, inbox_service, service, admin_user):
    _put(inbox_service.inbox_dir, "first.txt")
    await inbox_service.scan(db, service, admin_user)
    await inbox_service.scan(db, service, admin_user)

    runs = inbox_service.runs(db)
    assert len(runs) == 2
    assert runs[0].started_at >= runs[1].started_at


def test_clear_rejected_removes_files(inbox_service, db):
    (inbox_service.rejected_dir / "2026-10-09").mkdir(parents=True)
    (inbox_service.rejected_dir / "2026-10-09" / "photo.png").write_bytes(b"x")

    removed = inbox_service.clear_rejected(db)

    assert removed == 1
    assert not any(inbox_service.rejected_dir.rglob("*.png"))


# --------------------------------------------------------------------------- API
@pytest.fixture
async def admin(client, admin_user):
    from tests.conftest import login_headers

    return await login_headers(client, "admin", "admin-pass-123")


@pytest.fixture
async def researcher(client, researcher_user):
    from tests.conftest import login_headers

    return await login_headers(client, "ivanov", "researcher-pass-123")


@pytest.fixture
def inbox_settings(inbox_app, monkeypatch):
    """Эндпоинты создают `InboxService()` из глобальных настроек — подменяем."""
    import app.services.inbox as inbox_module

    monkeypatch.setattr(inbox_module, "get_settings", lambda: inbox_app)
    return inbox_app


async def test_api_scan_and_status(client, admin, inbox_settings, stub_registry):
    _put(inbox_settings.resolved_inbox_dir, "api.txt")

    status = (await client.get("/api/admin/inbox/status", headers=admin)).json()
    assert status["usable_files"] == 1

    response = await client.post("/api/admin/inbox/scan", headers=admin)
    assert response.status_code == 200, response.text
    run = response.json()["run"]
    assert run["archived"] == 1

    runs = (await client.get("/api/admin/inbox/runs", headers=admin)).json()
    assert len(runs) == 1
    assert len(runs[0]["files"]) == 1


async def test_api_scan_without_inbox_returns_404(client, admin, tmp_path, monkeypatch):
    import app.services.inbox as inbox_module
    from app.config import get_settings

    missing = get_settings().model_copy(update={"inbox_dir": tmp_path / "нет-такой"})
    monkeypatch.setattr(inbox_module, "get_settings", lambda: missing)

    response = await client.post("/api/admin/inbox/scan", headers=admin)

    # папки нет — понятная ошибка, а не 500
    assert response.status_code == 404
    assert "INBOX_DIR" in response.json()["detail"]


async def test_api_researcher_cannot_scan(client, researcher, inbox_settings):
    response = await client.post("/api/admin/inbox/scan", headers=researcher)
    assert response.status_code == 403