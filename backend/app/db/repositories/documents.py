"""Репозиторий документов: реестр поверх индекса PaperQA.

`PaperQA2Service` пишет чанки в `document_chunks` (ключ — collection+dockey) и
ничего не знает про SQLAlchemy. Здесь ведётся «реестр» документов с
метаданными, категориями, тегами и связями, а также проверяются лимиты ТЗ:
≤50 документов и ≤500 МБ на сессию.

Связи между документами (cites/supports/contradicts/uses) и привязка к проекту
живут в `document_links`: у документа два FK на `documents.id` (сам документ и
целевой документ), поэтому в relationship обязательно указывается
`foreign_keys`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.errors import ConflictError, NotFoundError
from app.db.models import (
    Document,
    DocumentCategory,
    DocumentLink,
    DocumentStatus,
    DocumentVisibility,
    Project,
    ProjectDocRole,
    RelationType,
    ResearchSession,
    utcnow,
)


# --------------------------------------------------------------------------- поиск
def get_document(db: Session, document_id: str) -> Document:
    doc = db.get(Document, document_id)
    if doc is None:
        raise NotFoundError("Документ не найден")
    return doc


def find_document(db: Session, *, session_id: str | None, dockey: str) -> Document | None:
    """Поиск по dockey внутри коллекции (`session_id=None` — глобальная база)."""
    stmt = select(Document).where(Document.dockey == dockey)
    stmt = (stmt.where(Document.session_id == session_id) if session_id
            else stmt.where(Document.session_id.is_(None)))
    return db.scalar(stmt)


def list_documents(
    db: Session,
    *,
    session_id: str | None,
    category: DocumentCategory | None = None,
) -> list[Document]:
    stmt = select(Document)
    stmt = (stmt.where(Document.session_id == session_id) if session_id
            else stmt.where(Document.session_id.is_(None)))
    if category is not None:
        stmt = stmt.where(Document.category == category)
    return list(db.scalars(stmt.order_by(Document.created_at)))


def count_documents(db: Session, session_id: str) -> int:
    return int(db.scalar(
        select(func.count()).select_from(Document)
        .where(Document.session_id == session_id))) or 0


def storage_bytes(db: Session, session_id: str) -> int:
    total = db.scalar(
        select(func.coalesce(func.sum(Document.size_bytes), 0))
        .where(Document.session_id == session_id))
    return int(total or 0)


# --------------------------------------------------------------------------- лимиты
def check_document_limits(
    db: Session,
    session_id: str,
    *,
    incoming_count: int = 1,
    incoming_bytes: int = 0,
) -> None:
    """Проверить лимиты ТЗ до индексации. Бросает `ConflictError` (HTTP 409)."""
    settings = get_settings()
    current = count_documents(db, session_id)
    if current + incoming_count > settings.max_documents_per_session:
        raise ConflictError(
            f"Лимит документов на сессию — {settings.max_documents_per_session} "
            f"(сейчас {current})",
            meta={"limit": settings.max_documents_per_session, "current": current,
                  "resource": "documents"},
        )
    used = storage_bytes(db, session_id)
    limit_bytes = settings.max_session_storage_mb * 1024 * 1024
    if used + max(0, incoming_bytes) > limit_bytes:
        raise ConflictError(
            f"Лимит хранилища сессии — {settings.max_session_storage_mb} МБ "
            f"(сейчас {used // (1024 * 1024)} МБ)",
            meta={"limit": settings.max_session_storage_mb, "current": used,
                  "resource": "storage"},
        )


def count_projects(db: Session, session_id: str) -> int:
    return int(db.scalar(
        select(func.count()).select_from(Project)
        .where(Project.session_id == session_id))) or 0


def check_project_limit(db: Session, session_id: str) -> None:
    settings = get_settings()
    current = count_projects(db, session_id)
    if current >= settings.max_projects_per_session:
        raise ConflictError(
            f"Лимит проектов на сессию — {settings.max_projects_per_session}",
            meta={"limit": settings.max_projects_per_session, "current": current,
                  "resource": "projects"},
        )


# --------------------------------------------------------------------------- запись
def _clean_tags(tags: Sequence[str] | None) -> list[str]:
    """Нормализация тегов: обрезаем пробелы, убираем пустые, сохраняем порядок."""
    if not tags:
        return []
    cleaned: list[str] = []
    for tag in tags:
        value = str(tag).strip()
        if value and value not in cleaned:
            cleaned.append(value)
    return cleaned


def upsert_document(
    db: Session,
    *,
    dockey: str,
    docname: str,
    title: str | None = None,
    filename: str | None = None,
    path: str | None = None,
    url: str | None = None,
    mime: str | None = None,
    size_bytes: int = 0,
    pages: int | None = None,
    chunk_count: int = 0,
    citation: str | None = None,
    content_hash: str | None = None,
    category: DocumentCategory = DocumentCategory.temp_literature,
    visibility: DocumentVisibility = DocumentVisibility.session,
    session_id: str | None = None,
    owner_user_id: str,
    added_by: str,
    tags: Sequence[str] | None = None,
    source: str | None = None,
    status: DocumentStatus = DocumentStatus.ready,
) -> Document:
    """Создать или обновить запись реестра (идемпотентно по dockey)."""
    doc = find_document(db, session_id=session_id, dockey=dockey)
    if doc is None:
        doc = Document(
            session_id=session_id,
            owner_user_id=owner_user_id,
            added_by=added_by,
            dockey=dockey,
        )
        db.add(doc)
    doc.docname = docname
    doc.title = title or doc.title or docname
    doc.filename = filename or doc.filename or docname
    doc.path = path or doc.path or ""
    doc.url = url
    doc.mime = mime
    doc.size_bytes = int(size_bytes or 0)
    doc.pages = pages
    doc.chunks_count = int(chunk_count or 0)
    doc.citation = citation
    doc.content_hash = content_hash
    doc.category = category
    doc.visibility = visibility
    doc.status = status
    if tags is not None:
        doc.tags = _clean_tags(tags)
    doc.source = source
    doc.indexed_at = utcnow()
    db.commit()
    db.refresh(doc)
    return doc


def update_document(
    db: Session,
    document_id: str,
    *,
    title: str | None = None,
    category: DocumentCategory | None = None,
    tags: Sequence[str] | None = None,
) -> Document:
    doc = get_document(db, document_id)
    if title is not None:
        doc.title = title
    if category is not None:
        doc.category = category
    if tags is not None:
        doc.tags = _clean_tags(tags)
    db.commit()
    db.refresh(doc)
    return doc


def delete_document_row(db: Session, document_id: str) -> bool:
    doc = db.get(Document, document_id)
    if doc is None:
        return False
    db.delete(doc)
    db.commit()
    return True


def mark_error(db: Session, document_id: str, error: str) -> Document:
    doc = get_document(db, document_id)
    doc.status = DocumentStatus.error
    doc.error = error[:2000]
    db.commit()
    return doc


# --------------------------------------------------------------------------- связи
def link_document(
    db: Session,
    *,
    document_id: str,
    session_id: str | None = None,
    project_id: str | None = None,
    target_document_id: str | None = None,
    role: ProjectDocRole | None = None,
    relation: RelationType = RelationType.cites,
    note: str | None = None,
) -> DocumentLink:
    """Создать/обновить связь документа (с проектом и/или с другим документом)."""
    get_document(db, document_id)
    stmt = select(DocumentLink).where(DocumentLink.document_id == document_id)
    stmt = (stmt.where(DocumentLink.project_id == project_id) if project_id
            else stmt.where(DocumentLink.project_id.is_(None)))
    stmt = (stmt.where(DocumentLink.target_document_id == target_document_id)
            if target_document_id else stmt.where(DocumentLink.target_document_id.is_(None)))
    link = db.scalar(stmt)
    if link is None:
        link = DocumentLink(
            document_id=document_id,
            project_id=project_id,
            target_document_id=target_document_id,
            session_id=session_id,
        )
        db.add(link)
    link.role = role
    link.relation = relation
    link.note = note
    db.commit()
    db.refresh(link)
    return link


def unlink_document(db: Session, link_id: str) -> bool:
    link = db.get(DocumentLink, link_id)
    if link is None:
        return False
    db.delete(link)
    db.commit()
    return True


def list_links(
    db: Session,
    *,
    session_id: str | None = None,
    document_id: str | None = None,
) -> list[DocumentLink]:
    stmt = select(DocumentLink)
    if session_id is not None:
        stmt = stmt.where(DocumentLink.session_id == session_id)
    if document_id is not None:
        stmt = stmt.where(DocumentLink.document_id == document_id)
    return list(db.scalars(stmt.order_by(DocumentLink.created_at)))


# --------------------------------------------------------------------------- сводка
def documents_summary(db: Session, session_id: str | None) -> dict[str, Any]:
    """Количество документов по категориям — для дашборда сессии."""
    scope = (Document.session_id == session_id) if session_id else Document.session_id.is_(None)
    rows = db.execute(
        select(Document.category, func.count()).where(scope).group_by(Document.category)
    ).all()
    by_category: dict[str, int] = {}
    for category, count in rows:
        by_category[getattr(category, "value", str(category))] = int(count)
    return {
        "total": sum(by_category.values()),
        "storage_bytes": storage_bytes(db, session_id) if session_id else 0,
        "by_category": by_category,
    }


def session_document_paths(db: Session, session_id: str) -> list[str]:
    """Пути файлов сессии — нужны reaper'у при purge (удаляем с диска)."""
    return [d.path for d in db.scalars(
        select(Document).where(Document.session_id == session_id)) if d.path]


def owned_session_or_none(db: Session, session_id: str) -> ResearchSession | None:
    return db.get(ResearchSession, session_id)
