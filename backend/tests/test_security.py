"""Пароли, JWT, RBAC."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import HTTPException

from app.db.models import Role


def test_password_hash_and_verify() -> None:
    from app.core.security import hash_password, verify_password

    hashed = hash_password("correct-horse-battery")
    assert hashed != "correct-horse-battery"
    assert verify_password("correct-horse-battery", hashed) is True
    assert verify_password("wrong-password", hashed) is False


def test_broken_hash_does_not_crash() -> None:
    from app.core.security import verify_password

    assert verify_password("anything", "not-a-real-hash") is False


def test_short_password_rejected() -> None:
    from app.core.security import hash_password

    with pytest.raises(ValueError):
        hash_password("short")


def test_access_token_roundtrip(admin_user) -> None:
    from app.core.security import create_access_token, decode_token

    payload = decode_token(create_access_token(admin_user))
    assert payload["sub"] == admin_user.id
    assert payload["role"] == "admin"
    assert payload["type"] == "access"


def test_refresh_token_rejected_as_access(admin_user) -> None:
    from app.core.security import create_access_token, decode_token

    token = create_access_token(admin_user, extra={"type": "refresh"})
    with pytest.raises(HTTPException) as exc:
        decode_token(token, expected_type="access")
    assert exc.value.status_code == 401


def test_expired_token_rejected(admin_user) -> None:
    from app.config import get_settings
    from app.core.security import decode_token

    settings = get_settings()
    expired = jwt.encode(
        {"sub": admin_user.id, "role": "admin", "type": "access",
         "exp": datetime.now(UTC) - timedelta(minutes=1)},
        settings.secret_key, algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(HTTPException) as exc:
        decode_token(expired)
    assert exc.value.status_code == 401


def test_token_signed_with_another_key_rejected(admin_user) -> None:
    from app.core.security import decode_token

    forged = jwt.encode({"sub": admin_user.id, "role": "admin", "type": "access",
                         "exp": datetime.now(UTC) + timedelta(hours=1)},
                        "wrong-key", algorithm="HS256")
    with pytest.raises(HTTPException):
        decode_token(forged)


def test_require_role_blocks_researcher(researcher_user) -> None:
    from app.core.security import require_admin, require_researcher

    guard = require_admin
    with pytest.raises(HTTPException) as exc:
        guard(researcher_user)
    assert exc.value.status_code == 403
    assert require_researcher(researcher_user).role is Role.researcher


def test_require_role_passes_admin(admin_user) -> None:
    from app.core.security import require_admin

    assert require_admin(admin_user).role is Role.admin


def test_refresh_token_hash_is_not_reversible() -> None:
    from app.core.security import hash_token

    assert hash_token("abc") == hash_token("abc")
    assert hash_token("abc") != "abc"
    assert len(hash_token("abc")) == 64


def test_refresh_token_creation() -> None:
    from app.core.security import create_refresh_token, hash_token

    token, expires = create_refresh_token(admin_user_stub())  # type: ignore[arg-type]
    assert len(token) > 40
    assert expires > datetime.now(UTC)
    assert len(hash_token(token)) == 64


def admin_user_stub():
    from app.db.models import User

    return User(id="u1", username="u", hashed_password="x", role=Role.admin)
