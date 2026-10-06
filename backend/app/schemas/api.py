"""DTO (pydantic) — контракт API. Стабильный интерфейс для всех фаз."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.db.models import Role, SearchMode, SessionStatus


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


class UserWithPasswordOut(UserOut):
    pass


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=8, max_length=256)
    role: Role = Role.researcher
    email: str | EmailStr | None = None
    full_name: str | None = Field(default=None, max_length=255)


class UserUpdateRequest(BaseModel):
    password: str | None = Field(default=None, min_length=8, max_length=256)
    role: Role | None = None
    email: str | EmailStr | None = None
    full_name: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None


class LoginResponse(BaseModel):
    user: UserOut
    tokens: TokenPair


# --------------------------------------------------------------------------- audit
class AuditLogOut(ORMModel):
    id: str
    actor_user_id: str | None
    actor_username: str | None
    action: str
    target_type: str | None
    target_id: str | None
    ip: str | None
    user_agent: str | None
    ok: bool
    meta: dict[str, Any] | None
    # Имя поля совпадает с моделью (created_at). Раньше здесь было `ts`, и при
    # from_attributes сериализация падала: «AuditLog has no attribute 'ts'» —
    # вкладка «Аудит» отдавала 500.
    created_at: datetime


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
    purged_at: datetime | None = None


class SessionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class SessionPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    resume_note: str | None = Field(default=None, max_length=4000)
    active_project_id: str | None = None
    state_snapshot: dict[str, Any] | None = None


class SessionStateUpdate(BaseModel):
    """Автосохранение точки возврата (активный проект, вкладка, позиция чата)."""

    snapshot: dict[str, Any] = Field(default_factory=dict)
    resume_note: str | None = Field(default=None, max_length=4000)
    action_type: str | None = Field(default=None, max_length=64)
    action_label: str | None = Field(default=None, max_length=512)
    force: bool = False


class SessionSummaryOut(BaseModel):
    documents: int
    documents_by_category: dict[str, int] = Field(default_factory=dict)
    storage_bytes: int
    storage_limit_bytes: int
    documents_limit: int
    projects: int
    projects_limit: int
    messages: int
    links: int
    read_only: bool


class SessionDetailOut(SessionOut):
    summary: SessionSummaryOut
    days_left: int
    writable: bool


class SessionResumeOut(BaseModel):
    """Ответ `POST /sessions/{id}/resume`: точка возврата + состояние индекса."""

    session: SessionOut
    summary: SessionSummaryOut
    state: dict[str, Any] = Field(default_factory=dict)
    restored_documents: int = 0
    days_left: int = 0
    last_exchange: list[str] | None = None  # [вопрос, ответ] — последний диалог


# --------------------------------------------------------------------------- documents
class DocumentOut(BaseModel):
    id: str | None = None
    dockey: str
    docname: str | None = None
    title: str | None = None
    filename: str | None = None
    citation: str | None = None
    path: str | None = None
    url: str | None = None
    mime: str | None = None
    category: str | None = None
    visibility: str | None = None
    status: str | None = None
    error: str | None = None
    size_bytes: int = 0
    pages: int | None = None
    chunk_count: int = 0
    tags: list[str] = Field(default_factory=list)
    source: str | None = None
    content_hash: str | None = None
    session_id: str | None = None
    created_at: datetime | None = None


class DocumentPatch(BaseModel):
    title: str | None = Field(default=None, max_length=512)
    category: str | None = None
    tags: list[str] | None = None


class FileFailureOut(BaseModel):
    name: str
    error: str


class DocumentBatchResultOut(BaseModel):
    added: list[DocumentOut] = Field(default_factory=list)
    duplicates: list[DocumentOut] = Field(default_factory=list)
    failed: list[FileFailureOut] = Field(default_factory=list)
    total: int = 0


class DocumentLinkOut(ORMModel):
    id: str
    document_id: str
    project_id: str | None = None
    session_id: str | None = None
    target_document_id: str | None = None
    role: str | None = None
    relation: str
    note: str | None = None
    created_at: datetime


class DocumentLinkIn(BaseModel):
    project_id: str | None = None
    target_document_id: str | None = None
    role: str | None = None
    relation: str = "cites"
    note: str | None = Field(default=None, max_length=2000)


# --------------------------------------------------------------------------- chat
class MessageOut(BaseModel):
    id: str
    session_id: str | None = None
    role: str
    content: str
    mode: str | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)
    # Отчёты проверок ответа: {"citations": …, "grounding": …}
    checks: dict[str, Any] = Field(default_factory=dict)
    duration_seconds: float | None = None
    created_at: datetime


class MessagePage(BaseModel):
    messages: list[MessageOut] = Field(default_factory=list)
    total: int = 0
    offset: int = 0


class ChatQueryRequest(BaseModel):
    session_id: str
    query: str = Field(min_length=1, max_length=2000)
    mode: SearchMode = SearchMode.hybrid
    max_sources: int | None = Field(default=5, ge=1, le=20)
    k: int | None = Field(default=10, ge=1, le=50)
    no_cache: bool = False


class SourceOut(BaseModel):
    """Источник ответа: 📚 глобальная база или 📁 документ сессии."""

    index: int
    marker: str
    source_scope: str
    dockey: str
    docname: str = ""
    title: str | None = None
    citation: str = ""
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    page: str | None = None
    score: float = 0.0
    raw_score: float = 0.0
    priority: float = 0.0
    dedup_penalty: float = 0.0
    projects: list[str] = Field(default_factory=list)
    text: str = ""


class ChatQueryResponse(BaseModel):
    answer: str
    sources: list[dict[str, Any]] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    mode: SearchMode
    query: str
    from_cache: bool = False
    stats: dict[str, Any] = Field(default_factory=dict)
    base_empty: bool = False


class QuickQueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    max_sources: int | None = Field(default=5, ge=1, le=20)
    k: int | None = Field(default=10, ge=1, le=50)
    no_cache: bool = False


class QuickQueryResponse(BaseModel):
    answer: str
    sources: list[dict[str, Any]] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    query: str
    from_cache: bool = False
    stats: dict[str, Any] = Field(default_factory=dict)
    # Ответ получен без опоры на базу (база пуста или ничего не нашлось).
    # Фронтенд покажет пояснение, чтобы «пустой» ответ был понятен.
    base_empty: bool = False


class SuggestionsResponse(BaseModel):
    suggestions: list[str] = Field(default_factory=list)
    query: str = ""

# --------------------------------------------------------------------------- projects
class ProjectSectionOut(BaseModel):
    name: str
    required: bool = True
    order: int = 0
    word_target: int = 500
    notes: str = ""
    content_md: str = ""
    words: int = 0
    written: bool = False


class ProjectSectionUpdate(BaseModel):
    content_md: str | None = None
    notes: str | None = Field(default=None, max_length=2000)
    word_target: int | None = Field(default=None, ge=0, le=20000)
    required: bool | None = None


class ProjectOut(ORMModel):
    id: str
    session_id: str
    title: str
    target_journal: str | None = None
    status: str
    sections: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    target_journal: str | None = Field(default=None, max_length=255)
    status: str = "planning"
    sections: list[dict[str, Any]] | None = None


class ProjectPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    target_journal: str | None = Field(default=None, max_length=255)
    status: str | None = None
    sections: list[dict[str, Any]] | None = None


class ProjectDocBind(BaseModel):
    document_id: str
    role: str = "reference"  # reference | data | draft
    note: str | None = Field(default=None, max_length=2000)


class GenerateRequest(BaseModel):
    section: str = Field(default="", max_length=255)
    question: str = Field(default="", max_length=2000)
    kind: str = "section"
    word_target: int | None = Field(default=None, ge=0, le=20000)
    notes: str | None = Field(default=None, max_length=2000)
    no_cache: bool = False
    template_md: str | None = Field(default=None, max_length=20000)
    data_document_ids: list[str] | None = None


class GenerateResultOut(BaseModel):
    project_id: str
    section: str
    content_md: str
    word_count: int
    sources: list[dict[str, Any]] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    citations_ok: bool = True
    citation_check: dict[str, Any] | None = None
    citations: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    seconds: float = 0.0
    from_cache: bool = False
    analysis: dict[str, Any] | None = None


class ProjectVersionOut(BaseModel):
    id: str
    project_id: str
    section_name: str | None = None
    kind: str
    content_md: str
    word_count: int
    citation_map: list[dict[str, Any]] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ExportFormat(str, Enum):
    """Формат выгрузки статьи."""

    markdown = "markdown"
    docx = "docx"
    zip = "zip"
