"""API: health, auth, refresh-ротация, аудит, обработка ошибок."""

from __future__ import annotations

import app.db.session as session_module

# Фикстура `client` перенесена в tests/conftest.py — используется всеми API-тестами.


async def _login(client, username: str, password: str) -> dict:
    response = await client.post("/api/auth/login",
                                 json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


async def test_health_ok(client) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["llm_model"] == "ollama/qwen2.5:3b"
    assert body["embedding_model"] == "st-multi-qa-MiniLM-L6-cos-v1"
    assert "reachable" in body["ollama"]
    assert "secret" not in response.text.lower()


async def test_login_and_me(client, admin_user) -> None:
    data = await _login(client, "admin", "admin-pass-123")
    assert data["user"]["role"] == "admin"
    assert data["tokens"]["token_type"] == "bearer"
    assert data["tokens"]["expires_in"] > 0

    me = await client.get("/api/auth/me",
                          headers={"Authorization": f"Bearer {data['tokens']['access_token']}"})
    assert me.status_code == 200
    assert me.json()["username"] == "admin"


async def test_login_wrong_password(client, admin_user) -> None:
    response = await client.post("/api/auth/login",
                                 json={"username": "admin", "password": "wrong-pass-123"})
    assert response.status_code == 403
    assert response.json()["detail"] == "Неверный логин или пароль"


async def test_login_unknown_user(client, admin_user) -> None:
    response = await client.post("/api/auth/login",
                                 json={"username": "ghost", "password": "whatever-123"})
    assert response.status_code == 403


async def test_me_requires_token(client, admin_user) -> None:
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_me_rejects_garbage_token(client, admin_user) -> None:
    response = await client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-token"})
    assert response.status_code == 401


async def test_inactive_user_cannot_login(client, admin_user) -> None:
    from app.db.repositories.users import get_user

    with session_module.get_session_factory()() as db:
        user = get_user(db, admin_user.id)
        user.is_active = False
        db.commit()

    response = await client.post("/api/auth/login",
                                 json={"username": "admin", "password": "admin-pass-123"})
    assert response.status_code == 403


async def test_refresh_rotates_token(client, admin_user) -> None:
    data = await _login(client, "admin", "admin-pass-123")
    first = data["tokens"]["refresh_token"]

    response = await client.post("/api/auth/refresh", json={"refresh_token": first})
    assert response.status_code == 200
    second = response.json()["refresh_token"]
    assert second != first

    reuse = await client.post("/api/auth/refresh", json={"refresh_token": first})
    assert reuse.status_code == 404


async def test_logout_revokes_token(client, admin_user) -> None:
    data = await _login(client, "admin", "admin-pass-123")
    refresh = data["tokens"]["refresh_token"]

    assert (await client.post("/api/auth/logout",
                              json={"refresh_token": refresh})).status_code == 204
    assert (await client.post("/api/auth/refresh",
                              json={"refresh_token": refresh})).status_code == 404


async def test_refresh_token_not_stored_in_plaintext(client, admin_user) -> None:
    from sqlalchemy import select

    from app.db.models import RefreshToken

    data = await _login(client, "admin", "admin-pass-123")
    with session_module.get_session_factory()() as db:
        tokens = list(db.scalars(select(RefreshToken)))
        assert tokens
        assert all(t.token_hash != data["tokens"]["refresh_token"] for t in tokens)


async def test_validation_error_shape(client, admin_user) -> None:
    response = await client.post("/api/auth/login", json={"username": "a", "password": "short"})
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


async def test_login_writes_audit_record(client, admin_user) -> None:
    from sqlalchemy import select

    from app.db.models import AuditLog

    await _login(client, "admin", "admin-pass-123")
    with session_module.get_session_factory()() as db:
        entries = list(db.scalars(select(AuditLog)))
    assert any(e.action == "auth.login" and e.ok and e.actor_username == "admin" for e in entries)


async def test_failed_login_writes_failed_audit(client, admin_user) -> None:
    from sqlalchemy import select

    from app.db.models import AuditLog

    await client.post("/api/auth/login",
                      json={"username": "admin", "password": "wrong-pass-123"})
    with session_module.get_session_factory()() as db:
        entries = list(db.scalars(select(AuditLog).where(AuditLog.ok.is_(False))))
    assert entries and entries[0].action == "auth.login"


async def test_locks_endpoint(client) -> None:
    response = await client.get("/api/health/locks")
    assert response.status_code == 200
    assert "global_index" in response.json()