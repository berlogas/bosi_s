"""Модели данных boasi_s.

Схема зафиксирована в Фазе 1 и покрывает требования ТЗ:
пользователи (RBAC), глобальная база знаний, исследовательские сессии
с 90-дневным TTL, документы с категориями, проекты статей, связи между
документами, история чата и аудит активности.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import DateTime as _DateTime


class UTCDateTime(TypeDecorator):
    """Время в UTC.

    SQLite не хранит часовой пояс, поэтому DateTime(timezone=True) возвращает
    naive-значения — сравнения с datetime.now(UTC) в коде падают.
    Этот тип гарантирует tz-aware UTC на входе и на выходе.
    """

    impl = _DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: ANN001, ANN201
        if value is None:
            return None
        if value.tzinfo is None:
            return value
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value, dialect):  # noqa: ANN001, ANN201
        if value is None:
            return None
        return value if value.tzinfo else value.replace(tzinfo=UTC)


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------- enums
class Role(str, enum.Enum):
    admin = "admin"
    researcher = "researcher"


class SessionStatus(str, enum.Enum):
    active = "active"
    paused = "paused"
    archived = "archived"


class DocumentCategory(str, enum.Enum):
    project_draft = "project_draft"
    project_data = "project_data"
    temp_literature = "temp_literature"
    notes = "notes"
    supplementary = "supplementary"
    global_knowledge = "global_knowledge"  # документ глобальной базы знаний


class DocumentVisibility(str, enum.Enum):
    global_ = "global"
    session = "session"


class DocumentStatus(str, enum.Enum):
    pending = "pending"
    parsing = "parsing"
    ready = "ready"
    error = "error"


class ProjectStatus(str, enum.Enum):
    planning = "planning"
    drafting = "drafting"
    reviewing = "reviewing"
    done = "done"


class ProjectDocRole(str, enum.Enum):
    reference = "reference"
    data = "data"
    draft = "draft"


class RelationType(str, enum.Enum):
    cites = "cites"
    supports = "supports"
    contradicts = "contradicts"
    uses = "uses"


class SearchMode(str, enum.Enum):
    hybrid = "hybrid"
    project_focus = "project_focus"
    session_only = "session_only"
    global_only = "global_only"


# --------------------------------------------------------------------------- users
class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False), default=Role.researcher)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow,
                                                onupdate=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    sessions: Mapped[list[ResearchSession]] = relationship(back_populates="user")


class RefreshToken(Base):
    """Refresh-токены хранятся только в виде хэша."""

    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


# --------------------------------------------------------------------------- sessions
class ResearchSession(Base):
    """Личное рабочее пространство исследователя. Не закрывается при выходе."""

    __tablename__ = "research_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus, native_enum=False), default=SessionStatus.active
    )
    active_project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # точка возврата
    last_action_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_action_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_action_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    resume_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    state_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # жизненный цикл
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow,
                                                onupdate=utcnow)
    last_activity_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow,
                                                       index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    purged_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")
    documents: Mapped[list[Document]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    projects: Mapped[list[Project]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_research_sessions_user_status", "user_id", "status"),)


# --------------------------------------------------------------------------- documents
class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    # Глобальная база: session_id = NULL + visibility = global
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("research_sessions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                                index=True)
    added_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))

    category: Mapped[DocumentCategory] = mapped_column(
        Enum(DocumentCategory, native_enum=False), default=DocumentCategory.notes
    )
    visibility: Mapped[DocumentVisibility] = mapped_column(
        Enum(DocumentVisibility, native_enum=False), default=DocumentVisibility.session
    )
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, native_enum=False), default=DocumentStatus.pending
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    title: Mapped[str] = mapped_column(String(512))
    filename: Mapped[str] = mapped_column(String(512))
    path: Mapped[str] = mapped_column(String(1024))
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    mime: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)

    # связь с paper-qa
    dockey: Mapped[str | None] = mapped_column(String(64), index=True)
    docname: Mapped[str | None] = mapped_column(String(255), index=True)
    citation: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunks_count: Mapped[int] = mapped_column(Integer, default=0)
    indexed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow,
                                                onupdate=utcnow)

    session: Mapped[ResearchSession | None] = relationship(back_populates="documents")
    links: Mapped[list[DocumentLink]] = relationship(
        back_populates="document",
        # у DocumentLink два FK на documents.id (документ и целевой документ)
        foreign_keys="DocumentLink.document_id",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_documents_session_category", "session_id", "category"),
        Index("ix_documents_visibility_status", "visibility", "status"),
    )


# --------------------------------------------------------------------------- projects
class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("research_sessions.id", ondelete="CASCADE"),
                                             index=True)
    title: Mapped[str] = mapped_column(String(512))
    target_journal: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, native_enum=False), default=ProjectStatus.planning
    )
    sections: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow,
                                                onupdate=utcnow)

    session: Mapped[ResearchSession] = relationship(back_populates="projects")
    versions: Mapped[list[ProjectVersion]] = relationship(
        back_populates="project", cascade="all, delete-orphan",
        order_by="ProjectVersion.created_at")


class GenerationKind(str, enum.Enum):
    """Что именно было сгенерировано — попадает в версию черновика."""

    section = "section"
    literature_review = "literature_review"
    discussion = "discussion"
    data_comparison = "data_comparison"
    gap_analysis = "gap_analysis"
    draft_analysis = "draft_analysis"
    report = "report"


class ProjectVersion(Base):
    """Снапшот черновика на каждую генерацию (Фаза 7: версионирование).

    Хранит не только текст, но и карту цитат: по ней видно, из каких
    источников взялся каждый фрагмент и не «отъехали» ли цитаты при правке.
    """

    __tablename__ = "project_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("research_sessions.id", ondelete="CASCADE"), nullable=True, index=True)
    section_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    kind: Mapped[GenerationKind] = mapped_column(
        Enum(GenerationKind, native_enum=False), default=GenerationKind.section)
    content_md: Mapped[str] = mapped_column(Text, default="")
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    citation_map: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow,
                                                 index=True)

    project: Mapped[Project] = relationship("Project", back_populates="versions")

    __table_args__ = (
        Index("ix_project_versions_project_created", "project_id", "created_at"),
    )


class DocumentLink(Base):
    """Связи между документами и проектом: роль + отношение (cites/supports/...)."""

    __tablename__ = "document_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"),
                                              index=True)
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("research_sessions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    target_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=True
    )
    role: Mapped[ProjectDocRole | None] = mapped_column(
        Enum(ProjectDocRole, native_enum=False), nullable=True
    )
    relation: Mapped[RelationType] = mapped_column(
        Enum(RelationType, native_enum=False), default=RelationType.cites
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    document: Mapped[Document] = relationship(
        back_populates="links",
        # у DocumentLink два FK на documents.id (документ и целевой документ)
        foreign_keys="DocumentLink.document_id",
    )

    __table_args__ = (UniqueConstraint("document_id", "project_id", "target_document_id",
                                       name="uq_document_link"),)


# --------------------------------------------------------------------------- chat
class Message(Base):
    """История чата. session_id = NULL -> свободное общение (quick chat)."""

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("research_sessions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant | system
    content: Mapped[str] = mapped_column(Text)
    mode: Mapped[SearchMode | None] = mapped_column(Enum(SearchMode, native_enum=False),
                                                   nullable=True)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # Отчёты проверок ответа: {"citations": …, "grounding": …, "refusal": …}
    # (см. app/services/citation_guard.py и grounding.py)
    checks: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True,
                                                          default=dict)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    token_counts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow,
                                                index=True)

    __table_args__ = (Index("ix_messages_session_created", "session_id", "created_at"),)


# --------------------------------------------------------------------------- audit
class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    actor_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow,
                                                index=True)

# ------------------------------------------------------- chunks (PaperQA-состояние)
class DocumentChunk(Base):
    """Персистентные чанки PaperQA: `Doc` + `Text[]` с эмбеддингами.

    Ключ — (collection, dockey). `collection` = "global" либо "session:<id>":
    внутри `Docs` один экземпляр на глобальную базу и один на сессию.
    """

    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("collection", "dockey", name="uq_document_chunks_collection_dockey"),
        Index("ix_document_chunks_collection", "collection"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    collection: Mapped[str] = mapped_column(String(64))
    dockey: Mapped[str] = mapped_column(String(64))
    docname: Mapped[str] = mapped_column(String(255))
    citation: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    settings_md5: Mapped[str | None] = mapped_column(String(64), nullable=True)
    doc_blob: Mapped[bytes] = mapped_column(LargeBinary)
    texts_blob: Mapped[bytes] = mapped_column(LargeBinary)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow,
                                                  onupdate=utcnow, index=True)


# --------------------------------------------------------------------- inbox
class InboxRunStatus(str, enum.Enum):
    """Состояние прогона сканирования inbox.

    `running`, который остался в БД после рестарта процесса, означает обрыв:
    такой прогон помечается `failed`, а его файлы получают причину
    (см. `services/inbox.py: reconcile_interrupted`).
    """

    running = "running"
    done = "done"
    failed = "failed"


class InboxFileStatus(str, enum.Enum):
    """Конечный автомат одного файла прогона.

    discovered -> parsed -> indexed -> archived   (успех)
    discovered -> rejected                       (битый/неподдерживаемый → /data/rejected)
    discovered -> failed                         (ошибка индексации, файл остаётся в inbox)
    """

    discovered = "discovered"
    parsed = "parsed"
    indexed = "indexed"
    archived = "archived"
    rejected = "rejected"
    failed = "failed"


class InboxRun(Base):
    """Журнал прогонов: что сканировали, чем закончилось, счётчики."""

    __tablename__ = "inbox_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    trigger: Mapped[str] = mapped_column(String(32), default="manual")
    status: Mapped[InboxRunStatus] = mapped_column(
        Enum(InboxRunStatus, native_enum=False), default=InboxRunStatus.running,
        index=True,
    )
    inbox_dir: Mapped[str] = mapped_column(String(1024))

    scanned: Mapped[int] = mapped_column(Integer, default=0)
    indexed: Mapped[int] = mapped_column(Integer, default=0)
    archived: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    replaced: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow,
                                                 index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    files: Mapped[list[InboxFile]] = relationship(
        back_populates="run", cascade="all, delete-orphan",
    )


class InboxFile(Base):
    """По строке на каждый файл прогона: состояние, причина, куда попал.

    `rel_path` — ключ идемпотентности внутри прогона, `sha256` — содержимое:
    вместе они дают «тот же путь, другое содержимое» = замена документа.
    """

    __tablename__ = "inbox_files"
    __table_args__ = (
        Index("ix_inbox_files_run_status", "run_id", "status"),
        UniqueConstraint("run_id", "rel_path", name="uq_inbox_files_run_rel_path"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("inbox_runs.id", ondelete="CASCADE"), index=True,
    )
    rel_path: Mapped[str] = mapped_column(String(1024))
    abs_path: Mapped[str] = mapped_column(String(1024))
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)

    status: Mapped[InboxFileStatus] = mapped_column(
        Enum(InboxFileStatus, native_enum=False), default=InboxFileStatus.discovered,
    )
    # Шаг, на котором остановился: discovered/parsed/indexed/archived.
    stage: Mapped[str] = mapped_column(String(32), default="discovered")
    # Машиночитаемый код (unsupported_extension, too_large, parse_error,
    # disk_error, replaced, interrupted) + текст для UI.
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    reason_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=1)

    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True,
    )
    final_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow,
                                                  onupdate=utcnow)

    run: Mapped[InboxRun] = relationship(back_populates="files")
