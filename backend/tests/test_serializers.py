"""Сериализация сервисных DTO и ORM в схемы API."""

from __future__ import annotations

from app.api.serializers import (
    batch_from_result,
    document_from_ref,
    document_from_row,
)
from app.db.models import DocumentCategory, DocumentVisibility
from app.db.repositories import documents as docs_repo
from app.services.types import DocStatus, DocumentBatchResult, DocumentRef


def _ref(**overrides) -> DocumentRef:
    data = {
        "dockey": "dockey-1",
        "docname": "biomass",
        "title": "Биомасса",
        "citation": "Биомасса (загружено пользователем)",
        "path": "/data/sessions/abc/uploads/biomass.md",
        "size_bytes": 2048,
        "pages": 2,
        "chunk_count": 3,
        "category": DocumentCategory.project_data,
        "status": DocStatus.READY,
        "content_hash": "hash",
    }
    data.update(overrides)
    return DocumentRef(**data)


def test_document_from_ref_maps_enum_to_string() -> None:
    out = document_from_ref(_ref())

    assert out.category == "project_data"
    assert out.status == "ready"
    assert out.chunk_count == 3
    assert out.size_bytes == 2048
    assert out.path.endswith("biomass.md")
    assert out.id is None  # сервисный DTO не знает про БД


def test_document_from_ref_tolerates_minimal_ref() -> None:
    out = document_from_ref(DocumentRef(dockey="x", docname="x"))

    assert out.dockey == "x"
    assert out.category is None
    assert out.size_bytes == 0
    assert out.tags == []
    assert out.chunk_count == 0


def test_document_from_ref_with_error_status() -> None:
    out = document_from_ref(_ref(status=DocStatus.ERROR, error="битый файл"))
    assert out.status == "error"
    assert out.error == "битый файл"


def test_document_from_row_uses_chunks_count(db, admin_user) -> None:
    row = docs_repo.upsert_document(
        db, dockey="dockey-1", docname="biomass", title="Биомасса",
        filename="biomass.md", path="/data/biomass.md", size_bytes=100,
        chunk_count=7, category=DocumentCategory.project_draft,
        visibility=DocumentVisibility.session, session_id=None,
        owner_user_id=admin_user.id, added_by=admin_user.id,
        tags=[" море ", "Баренцево"])

    out = document_from_row(row)

    assert out.id == row.id
    assert out.chunk_count == 7          # ORM называет поле chunks_count
    assert out.tags == ["море", "Баренцево"]
    assert out.category == "project_draft"
    assert out.visibility == "session"
    assert out.status == "ready"
    assert out.created_at is not None


def test_batch_result_keeps_partial_success() -> None:
    result = DocumentBatchResult(
        added=[_ref()],
        duplicates=[DocumentRef(dockey="d2", docname="d2")],
        failed=[("плохой.pdf", "DocumentProcessingError: тип файла")],
    )

    out = batch_from_result(result)

    assert out.total == 3
    assert len(out.added) == 1
    assert out.added[0].dockey == "dockey-1"
    assert out.duplicates[0].dockey == "d2"
    assert out.failed[0].name == "плохой.pdf"
    assert "DocumentProcessingError" in out.failed[0].error


def test_empty_batch_result() -> None:
    out = batch_from_result(DocumentBatchResult())
    assert out.added == [] and out.total == 0