"""DTO (pydantic) — контракт API. Стабильный интерфейс для всех фаз."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.db.models import ResearchSession, Role, SearchMode, SessionStatus


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
    username: str | None = Field(default=None, min_length=2, max_length=64)
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
    owner_username: str = ""
    owner_full_name: str | None = None
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

    @model_validator(mode="before")
    @classmethod
    def _fill_owner(cls, data: Any) -> Any:
        """Владелец берётся из связи `session.user`.

        Исследователю он не нужен (его собственные сессии), но администратор
        получает общий список, и без подписи карточки неотличимы друг от друга.
        Связь подгружается в списке сессий (selectinload), поэтому здесь только
        чтение уже загруженного объекта — без дополнительных запросов.
        """
        if isinstance(data, ResearchSession):
            owner = data.user
            if owner is None:
                data.owner_username = ""
                data.owner_full_name = None
            else:
                data.owner_username = owner.username
                data.owner_full_name = owner.full_name
        return data


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


class GlobalDocumentOut(BaseModel):
    """Документ глобальной базы для чтения обычным исследователем.

    Отдельная схема вместо `DocumentOut` намеренно: админский ответ несёт
    `path` (путь на диске), `error` и служебный `content_hash`, которые
    читателю списка знаний не нужны, а показывать пути файлов на сервере
    исследователю — незачем. Набор полей — ровно то, что показывает таблица.
    """

    id: str | None = None
    dockey: str
    title: str | None = None
    filename: str | None = None
    citation: str | None = None
    category: str | None = None
    status: str | None = None
    size_bytes: int = 0
    chunk_count: int = 0
    tags: list[str] = Field(default_factory=list)
    source: str | None = None
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


class SectionVersionOut(BaseModel):
    """Версия раздела — полная сериализация для интерфейса.

    `content_md` — сам текст раздела. Без него в ответе интерфейс не может
    показать сохранённый текст после перезагрузки страницы: он знает только
    метаданные версии.
    """

    id: str
    section_plan_id: str
    project_id: str
    session_id: str | None = None
    content_md: str = ""
    language: str = "ru"
    source_language: str | None = None
    word_count: int = 0
    citation_map: list[dict[str, Any]] = Field(default_factory=list)
    generation_params: dict[str, Any] = Field(default_factory=dict)
    seconds: float | None = None
    cost_usd: float | None = None
    token_counts: dict[str, Any] = Field(default_factory=dict)
    quality_report: dict[str, Any] = Field(default_factory=dict)
    status: str
    parent_version_id: str | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, version: Any) -> "SectionVersionOut":
        """Собрать DTO из ORM-объекта SectionVersion."""
        return cls(
            id=version.id,
            section_plan_id=version.section_plan_id,
            project_id=version.project_id,
            session_id=version.session_id,
            content_md=version.content_md or "",
            language=version.language,
            source_language=version.source_language,
            word_count=version.word_count or 0,
            citation_map=list(version.citation_map or []),
            generation_params=dict(version.generation_params or {}),
            seconds=version.seconds,
            cost_usd=version.cost_usd,
            token_counts=dict(version.token_counts or {}),
            quality_report=dict(version.quality_report or {}),
            status=getattr(version.status, "value", str(version.status)),
            parent_version_id=version.parent_version_id,
            created_by=version.created_by,
            created_at=version.created_at,
            updated_at=version.updated_at,
        )


class SectionPlanOut(BaseModel):
    """План раздела — вместе с текущей версией и её текстом."""

    id: str
    project_id: str
    name: str
    kind: str
    order: int
    required: bool = True
    word_target: int = 500
    word_min: int = 0
    word_max: int = 0
    notes: str = ""
    language: str = "ru"
    depends_on: list[str] = Field(default_factory=list)
    status: str
    current_version_id: str | None = None
    current_version: SectionVersionOut | None = None
    created_at: datetime
    updated_at: datetime


class VersionNodeOut(BaseModel):
    """Узел дерева версий: сама версия и её потомки."""

    version: SectionVersionOut
    children: list["VersionNodeOut"] = Field(default_factory=list)


class VersionTreeOut(BaseModel):
    """Дерево версий раздела + плоский список всех версий."""

    section_plan_id: str
    section_name: str
    roots: list[VersionNodeOut] = Field(default_factory=list)
    all_versions: list[SectionVersionOut] = Field(default_factory=list)


class ProjectOut(ORMModel):
    id: str
    session_id: str
    title: str
    target_journal: str | None = None
    style_guide_document_id: str | None = None
    language: str = "ru"
    status: str
    sections: list[dict[str, Any]] = Field(default_factory=list)
    order: int = 0
    created_at: datetime
    updated_at: datetime


class JournalTemplateOut(BaseModel):
    """Шаблон промпта группы: под какие разделы он подходит."""

    label: str
    sections: list[str]


class JournalStyleOut(BaseModel):
    """Группа журналов с общим способом изложения — для селектора в UI."""

    key: str
    title: str
    summary: str
    journals: list[str]
    # Русское описание стиля из `meta.toml` — то, что читает интерфейс.
    description: str
    description_lines: list[str]
    # Строки «TONE: ...», «TARGET AUDIENCE: ...» из самого промпта: английник,
    # на котором модель работает. Показывается как запасной вариант, если
    # русского описания в группе не написано.
    highlights: list[str]
    templates: list[JournalTemplateOut]


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    target_journal: str | None = Field(default=None, max_length=255)
    language: str = Field(default="ru", max_length=10)
    status: str = "planning"
    sections: list[dict[str, Any]] | None = None


class ProjectPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    target_journal: str | None = Field(default=None, max_length=255)
    language: str | None = Field(default=None, max_length=10)
    style_guide_document_id: str | None = Field(default=None)
    status: str | None = None
    sections: list[dict[str, Any]] | None = None
    order: int | None = Field(default=None, ge=0)


class ProjectDocBind(BaseModel):
    document_id: str
    role: str = "reference"  # reference | data | draft
    note: str | None = Field(default=None, max_length=2000)


class ProjectStyleGuideRequest(BaseModel):
    """Привязать/отвязать документ «Правила оформления» журнала к проекту как стиль оформления."""

    document_id: str | None = Field(
        default=None,
        description="ID документа «Правила оформления». None — отвязать текущий стиль.",
    )


class GenerateRequest(BaseModel):
    section: str = Field(default="", max_length=255)
    question: str = Field(default="", max_length=2000)
    kind: str = "section"
    word_target: int | None = Field(default=None, ge=0, le=20000)
    notes: str | None = Field(default=None, max_length=2000)
    no_cache: bool = False


class ExportFormat(str, Enum):
    """Формат выгрузки статьи."""

    markdown = "markdown"
    docx = "docx"
    zip = "zip"


# --------------------------------------------------------------------- сброс
class ResetRequest(BaseModel):
    """Запрос на сброс состояния.

    `confirm` — фраза из `ResetPlanOut.confirmation`: защита от случайного
    нажатия кнопки в админке (принцип как в Grafana/Datadog).
    """

    scope: Literal["data", "users", "all"] = "data"
    confirm: str = ""
    include_models: bool = False


class PathTargetOut(BaseModel):
    path: str
    files: int
    bytes: int


class ResetPlanOut(BaseModel):
    scope: str
    tables: dict[str, int]
    rows: int
    paths: list[PathTargetOut]
    files: int
    total_bytes: int
    kept_paths: list[str]
    includes_models: bool
    allowed: bool
    blocked_reason: str | None = None
    confirmation: str


class ResetResultOut(BaseModel):
    scope: str
    dry_run: bool
    deleted_tables: dict[str, int]
    deleted_rows: int
    deleted_paths: list[str]
    freed_bytes: int
    kept_paths: list[str]
    includes_models: bool


class BackupEntryOut(BaseModel):
    name: str
    bytes: int
    human_size: str
    created_at: str | None = None
    has_sha256: bool
    has_manifest: bool


class BackupPlanOut(BaseModel):
    data_dir: str
    backup_dir: str
    files: int
    source_bytes: int
    source_human: str
    estimated_bytes: int
    estimated_human: str
    free_bytes: int | None = None
    free_human: str | None = None
    existing: int
    keep: int
    db_exists: bool
    # Предупреждение для показа в окне подтверждения: сколько займёт копия
    # и сколько старых копий исчезнет по ротации. Фразы подтверждения нет:
    # операция ничего не разрушает.
    warning: str | None = None


class BackupListOut(BaseModel):
    backups: list[BackupEntryOut]
    plan: BackupPlanOut


class BackupCreateRequest(BaseModel):
    """Создание копии.

    Фразы подтверждения нет: операция неразрушающая, её
    план показывается в UI до кнопки. `keep` — сколько копий остать
    (None — взять из BACKUP_KEEP).
    """

    keep: int | None = Field(default=None, ge=0, le=500)


# --------------------------------------------------------------------------- inbox
class InboxFileOut(ORMModel):
    """Строка журнала: что с файлом и — если не сложилось — почему."""

    id: str
    rel_path: str
    abs_path: str
    size_bytes: int
    sha256: str | None = None
    status: str
    stage: str
    reason_code: str | None = None
    reason_text: str | None = None
    attempts: int
    document_id: str | None = None
    final_path: str | None = None
    created_at: datetime
    updated_at: datetime


class InboxRunOut(ORMModel):
    """Прогон сканирования inbox со счётчиками."""

    id: str
    trigger: str
    status: str
    inbox_dir: str
    scanned: int
    indexed: int
    archived: int
    rejected: int
    replaced: int
    failed: int
    error: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    files: list[InboxFileOut] = Field(default_factory=list)


class InboxStatusOut(BaseModel):
    """Текущее состояние папки-приёмника — для включения кнопки в UI."""

    inbox_dir: str
    exists: bool
    files: int
    usable_files: int
    unsupported_files: int
    bytes: int
    busy: bool




class InboxScanResultOut(BaseModel):
    run: InboxRunOut
    inbox_dir: str

class ReindexRequest(BaseModel):
    """Параметры переиндексации."""

    drop_embeddings: bool = Field(default=True,
                                  description="Пересчитать эмбеддинги заново")


class ReindexResultOut(BaseModel):
    """Результат переиндексации коллекции PaperQA2."""

    documents: int
    chunks: int
    seconds: float
    collection: str
    meta: dict[str, Any] = Field(default_factory=dict)


class CitationReportOut(BaseModel):
    """Отчёт о цитировании последнего ответа чата (из CitationReport)."""

    ok: bool = False
    changed: bool = False
    repaired: list[str] = Field(default_factory=list)
    dropped: list[str] = Field(default_factory=list)
    reflowed: list[str] = Field(default_factory=list)
    cited: list[int] = Field(default_factory=list)
    dangling: list[int] = Field(default_factory=list)
    uncited: bool = False
    warnings: list[str] = Field(default_factory=list)
