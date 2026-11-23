"""Бэкап из админки: план, создание копии, ротация, защита от рекурсии.

Проверяем в том числе то, что ломается легче всего: каталог бэкапов внутри
каталога данных (копия попала бы сама в себя) и приоритет оператора в оценке
размера (одна скобка — и оценка улетает в терабайты).
"""

from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from app.services import backup as backup_service


@pytest.fixture
def env(tmp_path: Path, db_engine, db, monkeypatch):
    """Настройки на отдельном каталоге: тесты не трогают боевые данные."""
    from app.config import Settings
    from app.core.security import hash_password
    from app.db.repositories.users import create_user

    data_dir = tmp_path / "data"
    backups = tmp_path / "backups"
    settings = Settings(
        data_dir=data_dir,
        backup_dir=backups,
        database_url=str(db_engine.url),
        environment="test",
        secret_key="test-secret-key-0123456789",
        _env_file=None,  # type: ignore[call-arg]
    )
    settings.ensure_dirs()
    backups.mkdir(parents=True, exist_ok=True)

    create_user(db, username="bcp", password="backup-pass-123",
                hashed_password=hash_password("backup-pass-123"))
    (settings.sessions_dir / "s1" / "files").mkdir(parents=True, exist_ok=True)
    (settings.sessions_dir / "s1" / "files" / "a.pdf").write_bytes(b"x" * 512)

    import app.db.session
    monkeypatch.setattr(app.db.session, "get_engine", lambda *a, **k: db_engine)
    return settings


# ------------------------------------------------------------------ план
def test_plan_reports_sources(env) -> None:
    plan = backup_service.plan_backup(env)

    assert plan.data_dir == str(env.data_dir)
    assert plan.backup_dir == str(env.resolved_backup_dir)
    assert plan.db_exists is True
    assert plan.files >= 2            # файл сессии + БД
    assert "warning" in plan.as_dict(), "план должен предупреждать о последствиях"


def test_estimate_is_sane(env) -> None:
    """Оценка объёма обязана быть правдоподобной, а не «умноженной на мегабайт».

    Регрессия: `... + 1 << 20` без скобок сдвигает всё выражение на 20 бит,
    и оценка 2 МБ превращается в 1.4 ТБ — копия отказалась бы создаваться.
    """
    plan = backup_service.plan_backup(env)

    assert plan.estimated_bytes < plan.source_bytes * 4 + (16 << 20)
    assert plan.estimated_bytes > 0


def test_plan_without_database(tmp_path) -> None:
    from app.config import Settings

    settings = Settings(
        data_dir=tmp_path / "empty",
        backup_dir=tmp_path / "bk",
        database_url=f"sqlite:///{(tmp_path / 'empty' / 'no.sqlite3').as_posix()}",
        secret_key="test-secret-key-0123456789",
        _env_file=None,  # type: ignore[call-arg]
    )
    settings.ensure_dirs()

    plan = backup_service.plan_backup(settings)

    assert plan.db_exists is False
    assert plan.files == 0


# --------------------------------------------------------------- создание
def test_backup_contains_snapshot_and_manifest(env) -> None:
    result = backup_service.run_backup(settings=env, keep=0)

    archive = Path(result.entry.path)
    assert archive.exists()
    assert archive.with_name(archive.name + ".sha256").exists()
    assert result.deleted_old == []

    with tarfile.open(archive, "r:gz") as tar:
        names = tar.getnames()
    assert ".backup-snapshot.sqlite3" in names
    assert "boasi-manifest.json" in names
    # живой БД в архив не попадает — вместо неё снимок
    assert "boasi.sqlite3" not in names


def test_backup_manifest_has_counts(env) -> None:
    result = backup_service.run_backup(settings=env, keep=0)

    assert result.manifest["source"] == "admin-ui"
    assert result.manifest["db_snapshot"] is True
    assert result.manifest["tables"]["users"] == 1
    assert result.manifest["models"]["embedding"]


def test_backup_is_restorable_by_script(env, tmp_path) -> None:
    """Совместимость с scripts/verify_backup.sh: снимок на месте и БД читается."""
    import sqlite3

    backup_service.run_backup(settings=env, keep=0)
    archive = next(Path(env.resolved_backup_dir).glob("boasi-*.tar.gz"))

    extract = tmp_path / "extract"
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(extract)
    snapshot = extract / ".backup-snapshot.sqlite3"
    assert snapshot.exists()

    con = sqlite3.connect(snapshot)
    try:
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert con.execute("SELECT count(*) FROM users").fetchone()[0] == 1
    finally:
        con.close()


def test_backup_dir_inside_data_dir_is_excluded(env, monkeypatch) -> None:
    """Если BACKUP_DIR уткнулся внутрь DATA_DIR, копия не должна брать себя."""
    from app.config import Settings

    nested = env.data_dir / "backups"
    nested.mkdir(parents=True, exist_ok=True)
    (nested / "boasi-old.tar.gz").write_bytes(b"x" * 2048)

    settings = Settings(
        data_dir=env.data_dir,
        backup_dir=nested,
        database_url=str(env.resolved_db_url),
        secret_key="test-secret-key-0123456789",
        _env_file=None,  # type: ignore[call-arg]
    )

    files, total = backup_service._iter_data_files(settings)
    names = {p.name for p in files}

    assert "boasi-old.tar.gz" not in names
    assert all("backups" not in p.parts for p in files)
    assert total > 0


def test_no_partial_file_left_behind(env, monkeypatch) -> None:
    """Прерванный бэкап не должен оставить «полноценный» архив."""
    import app.services.backup as svc

    def boom(*_args, **_kwargs):
        raise OSError("Нет места")

    monkeypatch.setattr(svc.tarfile, "open", boom)

    with pytest.raises(OSError):
        svc.run_backup(settings=env, keep=0)

    leftovers = list(Path(env.resolved_backup_dir).glob("*.partial"))
    assert leftovers == []


# ---------------------------------------------------------------- ротация
def test_rotation_keeps_n_newest(env) -> None:
    for _ in range(3):
        backup_service.run_backup(settings=env, keep=2)

    archives = backup_service.list_backups(env)   # уже отсортированы: новые сверху
    assert len(archives) <= 2
    # sha256 удаляется вместе с архивом
    for entry in archives:
        assert entry.has_sha256 is True


def test_rotation_disabled_with_zero(env) -> None:
    for _ in range(3):
        backup_service.run_backup(settings=env, keep=0)
    assert len(backup_service.list_backups(env)) >= 3


def test_rotation_never_deletes_the_new_one(env) -> None:
    result = backup_service.run_backup(settings=env, keep=1)

    assert Path(result.entry.path).exists(), "свежая копия не должна удаляться ротацией"


# ---------------------------------------------------------------- удаление
def test_delete_backup(env) -> None:
    result = backup_service.run_backup(settings=env, keep=0)

    assert backup_service.delete_backup(result.entry.name, settings=env) is True
    assert not Path(result.entry.path).exists()
    assert backup_service.delete_backup(result.entry.name, settings=env) is False


@pytest.mark.parametrize("name", [
    "../../etc/passwd",
    "boasi-../../x.tar.gz",
    "/abs/path.tar.gz",
    "not-a-boasi-archive.tar.gz",
    "boasi-x.tar.gz.bak",
])
def test_delete_rejects_bad_names(env, name: str) -> None:
    with pytest.raises(ValueError):
        backup_service.delete_backup(name, settings=env)



async def _wait_backup_task(task_id: str, wait_seconds: float = 10.0):
    """Дождаться фоновой задачи создания копии."""
    import asyncio

    from app.services.tasks import tasks

    deadline = asyncio.get_running_loop().time() + wait_seconds
    while asyncio.get_running_loop().time() < deadline:
        task = tasks.get(task_id)
        if task is not None and task.finished:
            assert task.status.value == "done", task.error
            return task
        await asyncio.sleep(0.01)
    raise AssertionError(f"задача {task_id} не завершилась за {wait_seconds} с")

# -------------------------------------------------------------------- API
async def test_backup_list_endpoint(client, admin_user, env, monkeypatch) -> None:
    import app.services.backup as svc
    from tests.conftest import login_headers
    monkeypatch.setattr(svc, "plan_backup", lambda *a, **k: svc.plan_backup(env))
    monkeypatch.setattr(svc, "get_settings", lambda: env)

    headers = await login_headers(client, "admin", "admin-pass-123")
    response = await client.get("/api/admin/backup", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["backups"] == []
    assert "warning" in body["plan"]


async def test_backup_create_needs_no_confirmation_phrase(client, admin_user,
                                                            env, monkeypatch) -> None:
    """Бэкап неразрушающий — фраза не требуется, достаточно кнопки."""
    import app.api.admin as admin_api
    import app.services.backup as svc
    from tests.conftest import login_headers

    monkeypatch.setattr(admin_api, "plan_backup", lambda *a, **k: svc.plan_backup(env))
    monkeypatch.setattr(svc, "get_settings", lambda: env)
    headers = await login_headers(client, "admin", "admin-pass-123")

    response = await client.post("/api/admin/backup", json={}, headers=headers)

    assert response.status_code == 200, response.text
    body = (await _wait_backup_task(response.json()["task_id"])).result
    assert body["entry"]["has_manifest"] is True


async def test_backup_create_works(client, admin_user, env, monkeypatch) -> None:
    import app.api.admin as admin_api
    import app.services.backup as svc
    from tests.conftest import login_headers

    monkeypatch.setattr(admin_api, "plan_backup", lambda *a, **k: svc.plan_backup(env))
    monkeypatch.setattr(svc, "get_settings", lambda: env)
    headers = await login_headers(client, "admin", "admin-pass-123")

    response = await client.post("/api/admin/backup",
                                 json={"keep": 5}, headers=headers)

    assert response.status_code == 200, response.text
    body = (await _wait_backup_task(response.json()["task_id"])).result
    assert body["entry"]["has_manifest"] is True
    assert body["entry"]["has_sha256"] is True
    assert "restore.sh" in body["restore_hint"]

    # копия видна в списке и записана в аудит
    listing = await client.get("/api/admin/backup", headers=headers)
    assert any(item["name"] == body["entry"]["name"]
               for item in listing.json()["backups"])

    audit = await client.get("/api/admin/audit?action=admin.backup", headers=headers)
    assert audit.json()[0]["action"] == "admin.backup.create"


async def test_backup_create_refused_without_database(client, admin_user,
                                                      tmp_path, monkeypatch) -> None:
    """Пустая платформа: копия без базы бесполезна — отказываем."""
    import app.api.admin as admin_api
    import app.services.backup as svc
    from app.config import Settings
    from tests.conftest import login_headers

    settings = Settings(
        data_dir=tmp_path / "empty",
        backup_dir=tmp_path / "bk",
        database_url=f"sqlite:///{(tmp_path / 'empty' / 'no.sqlite3').as_posix()}",
        secret_key="test-secret-key-0123456789",
        _env_file=None,  # type: ignore[call-arg]
    )
    settings.ensure_dirs()
    monkeypatch.setattr(admin_api, "plan_backup", lambda *a, **k: svc.plan_backup(settings))
    headers = await login_headers(client, "admin", "admin-pass-123")

    response = await client.post("/api/admin/backup",
                                 json={}, headers=headers)

    assert response.status_code == 409


async def test_backup_requires_admin(client, researcher_user) -> None:
    from tests.conftest import login_headers

    headers = await login_headers(client, "ivanov", "researcher-pass-123")

    assert (await client.get("/api/admin/backup", headers=headers)).status_code == 403
    assert (await client.post("/api/admin/backup", json={},
                              headers=headers)).status_code == 403



def test_two_backups_in_one_second_do_not_collide(env) -> None:
    """Двойной клик по кнопке не должен перетереть свежую копию."""
    first = backup_service.run_backup(settings=env, keep=0)
    second = backup_service.run_backup(settings=env, keep=0)

    assert first.entry.name != second.entry.name
    assert Path(first.entry.path).exists()
    assert Path(second.entry.path).exists()

async def test_backup_task_reports_progress(client, admin_user, env,
                                            monkeypatch) -> None:
    """Админка видит этапы создания копии, а не тихое ожидание."""
    import app.api.admin as admin_api
    import app.services.backup as svc
    from tests.conftest import login_headers

    monkeypatch.setattr(admin_api, "plan_backup", lambda *a, **k: svc.plan_backup(env))
    monkeypatch.setattr(svc, "get_settings", lambda: env)
    headers = await login_headers(client, "admin", "admin-pass-123")

    steps: list[tuple[int, str]] = []
    original_run = svc.run_backup

    def spy_run(*args, **kwargs):
        inner = kwargs.pop("on_progress", None)

        def report(percent: int, step: str) -> None:
            steps.append((percent, step))
            if inner is not None:
                inner(percent, step)

        return original_run(*args, **kwargs, on_progress=report)

    monkeypatch.setattr(svc, "run_backup", spy_run)

    response = await client.post("/api/admin/backup", json={}, headers=headers)
    assert response.status_code == 200, response.text
    task = await _wait_backup_task(response.json()["task_id"])

    assert steps[0][1] == "подготовка"
    assert steps[-1] == (100, "готово")
    assert any("архивирование" in step for _, step in steps)
    assert task.progress == 100

async def test_backup_does_not_block_api(client, admin_user, env,
                                         monkeypatch) -> None:
    """Пока копия пишется, API продолжает отвечать (иначе UI теряет backend)."""
    import asyncio
    import time

    import app.api.admin as admin_api
    import app.services.backup as svc
    from tests.conftest import login_headers

    monkeypatch.setattr(admin_api, "plan_backup", lambda *a, **k: svc.plan_backup(env))
    monkeypatch.setattr(svc, "get_settings", lambda: env)
    headers = await login_headers(client, "admin", "admin-pass-123")

    loop = asyncio.get_running_loop()
    started = loop.create_future()
    original_run = svc.run_backup

    def slow_run(*args, **kwargs):
        on_progress = kwargs.get("on_progress")
        if on_progress is not None:
            on_progress(40, "архивирование файлов")
        loop.call_soon_threadsafe(started.set_result, True)
        time.sleep(0.6)  # синхронная работа в потоке, не в event loop
        if on_progress is not None:
            on_progress(100, "готово")
        return original_run(*args, **kwargs)

    monkeypatch.setattr(svc, "run_backup", slow_run)

    response = await client.post("/api/admin/backup", json={}, headers=headers)
    assert response.status_code == 200, response.text
    await asyncio.wait_for(started, timeout=2)

    began = loop.time()
    listing = await client.get("/api/admin/backup", headers=headers)
    elapsed = loop.time() - began
    assert listing.status_code == 200
    assert elapsed < 0.4, f"API отвечал {elapsed:.2f} с — event loop заблокирован"

    task = await _wait_backup_task(response.json()["task_id"])
    assert task.progress == 100
    assert task.result["entry"]["name"]

