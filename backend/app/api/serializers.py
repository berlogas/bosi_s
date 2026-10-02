"""Преобразование доменных объектов в DTO схем API.

Сервисный слой (`DocumentRef`, `DocumentBatchResult`) и ORM (`Document`) не
совпадают по именам полей (`chunk_count` vs `chunks_count`, `status`/`category`
как enum), поэтому конвертация вынесена сюда и покрыта тестами.
"""

from __future__ import annotations

from typing import Any

from app.db.models import Document
from app.schemas.api import (
    DocumentBatchResultOut,
    DocumentLinkOut,
    DocumentOut,
    FileFailureOut,
    ProjectOut,
    SessionDetailOut,
    SessionOut,
    SessionResumeOut,
    SessionSummaryOut,
)
from app.services.types import DocumentBatchResult, DocumentRef


def _enum_value(value: Any) -> str | None:
    if value is None:
        return None
    return getattr(value, "value", value) if not isinstance(value, str) else value


def document_from_ref(ref: DocumentRef) -> DocumentOut:
    """`DocumentRef` (слой PaperQA) -> DTO."""
    return DocumentOut(
        dockey=ref.dockey,
        docname=ref.docname,
        title=ref.title,
        citation=ref.citation,
        path=ref.path,
        url=ref.url,
        category=_enum_value(ref.category),
        status=_enum_value(ref.status),
        error=ref.error,
        size_bytes=ref.size_bytes or 0,
        pages=ref.pages,
        chunk_count=ref.chunk_count,
        content_hash=ref.content_hash,
        session_id=ref.session_id,
        created_at=ref.created_at,
    )


def document_from_row(doc: Document) -> DocumentOut:
    """ORM `Document` -> DTO."""
    return DocumentOut(
        id=doc.id,
        dockey=doc.dockey or "",
        docname=doc.docname,
        title=doc.title,
        filename=doc.filename,
        citation=doc.citation,
        path=doc.path,
        url=doc.url,
        mime=doc.mime,
        category=_enum_value(doc.category),
        visibility=_enum_value(doc.visibility),
        status=_enum_value(doc.status),
        error=doc.error,
        size_bytes=doc.size_bytes or 0,
        pages=doc.pages,
        chunk_count=doc.chunks_count or 0,
        tags=list(doc.tags or []),
        source=doc.source,
        content_hash=doc.content_hash,
        session_id=doc.session_id,
        created_at=doc.created_at,
    )


def batch_from_result(result: DocumentBatchResult) -> DocumentBatchResultOut:
    return DocumentBatchResultOut(
        added=[document_from_ref(ref) for ref in result.added],
        duplicates=[document_from_ref(ref) for ref in result.duplicates],
        failed=[FileFailureOut(name=name, error=error) for name, error in result.failed],
        total=result.total,
    )


def link_out(link: Any) -> DocumentLinkOut:
    return DocumentLinkOut(
        id=link.id,
        document_id=link.document_id,
        project_id=link.project_id,
        session_id=link.session_id,
        target_document_id=link.target_document_id,
        role=_enum_value(link.role),
        relation=_enum_value(link.relation) or "cites",
        note=link.note,
        created_at=link.created_at,
    )


def session_out(session: Any) -> SessionOut:
    return SessionOut.model_validate(session)


def session_detail(session: Any, summary: dict[str, Any], days_left: int,
                   writable: bool) -> SessionDetailOut:
    return SessionDetailOut(
        **session_out(session).model_dump(),
        summary=SessionSummaryOut(**summary),
        days_left=days_left,
        writable=writable,
    )


def session_resume(session: Any, summary: dict[str, Any], state: dict[str, Any],
                   restored_documents: int, days_left: int,
                   last_exchange: list[str] | None = None) -> SessionResumeOut:
    return SessionResumeOut(
        session=session_out(session),
        summary=SessionSummaryOut(**summary),
        state=state,
        restored_documents=restored_documents,
        days_left=days_left,
        last_exchange=last_exchange,
    )

def project_out(project: Any) -> ProjectOut:
    """ORM `Project` -> DTO с нормализованным планом разделов."""
    from app.services.generation import normalize_sections

    sections = normalize_sections(project.sections)
    return ProjectOut(
        id=project.id,
        session_id=project.session_id,
        title=project.title,
        target_journal=project.target_journal,
        status=getattr(project.status, "value", str(project.status)),
        sections=sections,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )
