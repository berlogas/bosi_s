"""DTO (pydantic) — контракт API. Стабильный интерфейс для всех фаз."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import Role, SessionStatus


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- health
class HealthResponse(BaseModel):
    status: str
    app: str
    environment: str
    version: str
    database: str
    llm_model: str
    embedding_model: str
    ollama: dict[str, Any]


# --------------------------------------------------------------------------- auth
class LoginRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=8, max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(ORMModel):
    id: str
    username: str
    email: str | None = None
    full_name: str | None = None
    role: Role
    is_active: bool
    last_login_at: datetime | None = None


class LoginResponse(BaseModel):
    user: UserOut
    tokens: TokenPair


# --------------------------------------------------------------------------- sessions
class SessionOut(ORMModel):
    id: str
    user_id: str
    title: str
    status: SessionStatus
    active_project_id: str | None = None
    last_action_type: str | None = None
    last_action_label: str | None = None
    last_action_at: datetime | None = None
    resume_note: str | None = None
    state_snapshot: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    last_activity_at: datetime
    expires_at: datetime
    archived_at: datetime | None = None


class SessionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class SessionPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    status: SessionStatus | None = None
    resume_note: str | None = Field(default=None, max_length=4000)
    state_snapshot: dict[str, Any] | None = None