"""Журнал аудита: ретрация по сроку и по объёму, защита важных записей.

Проверяем ровно ту политику, которая описана в `ADMIN_GUIDE.md`: журнал
не должен расти бесконечно, но ответ на вопрос «кто и когда сбросил
систему» должен оставаться всегда.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.db.models import AuditLog, utcnow
from app.db.repositories.users import audit, audit_stats, prune_audit


def _next_index(db) -> int:

    return len(list(db.scalars(select(AuditLog.id)))) + 1


def _entry(db, action: str, days_old: int = 0, minutes: int = 0) -> AuditLog:
    """Запись с управляемым временем: порядок ретрации проверяем по нему."""
    entry = AuditLog(
        id=f"{action}-{days_old}-{minutes}-{_next_index(db)}",
        action=action,
        actor_username="admin",
        ok=True,
        meta={},
    )
    if days_old or minutes:
        entry.created_at = utcnow() - timedelta(days=days_old, minutes=minutes)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def test_prune_removes_old_by_age(db) -> None:
    _entry(db, "session.create", days_old=400)
    _entry(db, "session.create", days_old=100)
    _entry(db, "session.create", days_old=10)

    result = prune_audit(db, retention_days=180, max_rows=0)

    assert result["removed_by_age"] == 1
    assert result["needs_vacuum"] is True
    actions = [row.action for row in db.scalars(select(AuditLog))]
    assert actions == ["session.create", "session.create"]


def test_prune_keeps_newest_when_over_cap(db) -> None:
    for index in range(5):
        _entry(db, f"chat.query.{index}", minutes=index)

    result = prune_audit(db, retention_days=0, max_rows=2)

    assert result["removed_overflow"] == 3
    assert result["total"] == 2
    # minutes=0 — самый свежий, minutes=4 — самый старый
    remaining = sorted(row.action for row in db.scalars(select(AuditLog)))
    assert remaining == ["chat.query.0", "chat.query.1"]


def test_protected_actions_are_never_pruned(db) -> None:
    """«Кто и когда сбросил» должно отвечать на вопрос и через год."""
    _entry(db, "admin.reset", days_old=400)
    _entry(db, "admin.user.delete", days_old=400)
    _entry(db, "session.create", days_old=400)
    _entry(db, "chat.query", days_old=400)

    prune_audit(db, retention_days=180, max_rows=0)

    actions = sorted(row.action for row in db.scalars(select(AuditLog)))
    assert actions == ["admin.reset", "admin.user.delete"]


def test_protected_actions_survive_volume_cap(db) -> None:
    _entry(db, "backup.delete", minutes=0)
    for index in range(1, 5):
        _entry(db, f"chat.query.{index}", minutes=index)

    prune_audit(db, retention_days=0, max_rows=1)

    actions = [row.action for row in db.scalars(select(AuditLog))]
    assert "backup.delete" in actions
    assert len(actions) == 1


def test_protection_matches_by_prefix(db) -> None:
    """`reset.` закрывает `reset.execute` и `reset.preview`."""
    _entry(db, "admin.reset", days_old=400)
    _entry(db, "session.create", days_old=400)

    prune_audit(db, retention_days=180, max_rows=0, protected=["admin.reset"])

    assert [row.action for row in db.scalars(select(AuditLog))] == ["admin.reset"]


def test_nothing_to_prune_reports_no_vacuum(db) -> None:
    _entry(db, "session.create")

    result = prune_audit(db, retention_days=180, max_rows=0)

    assert result["removed_total"] == 0
    assert result["needs_vacuum"] is False


def test_audit_stats_reports_total_and_bounds(db) -> None:
    _entry(db, "session.create", days_old=5)

    stats = audit_stats(db)

    assert stats["total"] == 1
    assert stats["oldest_at"] is not None
    assert stats["newest_at"] >= stats["oldest_at"]


def test_audit_writes_and_prunes_together(db, admin_user) -> None:
    """Реальная запись журнала стареет и выселяется — вместе с остальными."""
    entry = audit(db, action="admin.user.update", actor=admin_user,
                  username="ivanov.i")
    entry.created_at = utcnow() - timedelta(days=365)
    db.commit()

    prune_audit(db, retention_days=180, max_rows=0)

    assert audit_stats(db)["total"] == 0

# ------------------------------------------------------------------ reaper и API
async def test_reaper_prunes_audit_on_due(monkeypatch) -> None:
    """Reaper вызывает ретрацию и только раз в сутки, а не каждый проход."""
    from app.workers import reaper as reaper_module

    monkeypatch.setattr(reaper_module, "prune_audit_repo",
                        lambda db: {"removed_by_age": 3, "removed_overflow": 0,
                                    "removed_total": 3, "total": 10,
                                    "needs_vacuum": False})
    monkeypatch.setattr(reaper_module, "_last_audit_prune", 0.0)

    first = await reaper_module.prune_audit_if_due(force=True)
    second = await reaper_module.prune_audit_if_due()

    assert first["removed_total"] == 3
    assert second == {"skipped": True}


async def test_vacuum_runs_after_prune(monkeypatch) -> None:
    """Удалённые строки должны вернуть место файлу — вызывается VACUUM."""
    from app.workers import reaper as reaper_module

    monkeypatch.setattr(reaper_module, "prune_audit_repo",
                        lambda db: {"removed_by_age": 0, "removed_overflow": 5,
                                    "removed_total": 5, "total": 5,
                                    "needs_vacuum": True})
    monkeypatch.setattr(reaper_module, "vacuum_audit", lambda db: True)
    monkeypatch.setattr(reaper_module, "_last_audit_prune", 0.0)

    result = await reaper_module.prune_audit_if_due(force=True)

    assert result["vacuumed"] is True


async def test_api_audit_stats_and_export(client, admin_user, db) -> None:
    from tests.conftest import login_headers

    admin = await login_headers(client, "admin", "admin-pass-123")
    audit(db, action="admin.user.create", username="ivanov")

    stats = (await client.get("/api/admin/audit/stats", headers=admin)).json()
    assert stats["total"] >= 1
    assert stats["newest_at"] is not None

    response = await client.get("/api/admin/audit/export", headers=admin)

    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "attachment" in response.headers["content-disposition"]
    body = response.content.decode("utf-8-sig")
    assert "admin.user.create" in body
    assert "action" in body.splitlines()[0]
