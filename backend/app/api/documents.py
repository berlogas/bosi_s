"""Глобальная база знаний (Фаза 4, админский доступ).

Один `Docs` на всю платформу + реестр в таблице `documents` (`session_id=NULL`,
`visibility=global`). Все обращения аудируются, потому что это данные,
разделяемые всеми исследователями.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import anyio
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.api.serializers import document_from_ref, document_from_row
from app.core.errors import NotFoundError
from app.core.security import require_admin
from app.db.models import (
    Document,
    DocumentCategory,
    DocumentStatus,
    DocumentVisibility,
    User,
)
from app.db.repositories import documents as docs_repo
from app.db.repositories.users import audit
from app.db.session import get_db
from app.schemas.api import (
    DocumentBatchResultOut,
    DocumentOut,
    DocumentPatch,
    FileFailureOut,
)
from app.services.paperqa_service import PaperQA2Service, get_registry
from app.services.types import DocStatus

log = logging.getLogger("boasi.api.documents")

router = APIRouter(prefix="/api/admin/documents", tags=["admin-documents"],
                   dependencies=[Depends(require_admin)])

GLOBAL_CATEGORY = DocumentCategory.global_knowledge


def _meta(request: Request) -> dict[str, str | None]:
    return {"ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent")}


def _service() -> PaperQA2Service:
    return get_registry().global_service()


def _register(db: Session, user: User, ref: Any, tags: list[str],
              source: str) -> Document:
    return docs_repo.upsert_document(
        db,
        dockey=ref.dockey,
        docname=ref.docname or "",
        title=ref.title or ref.docname,
        filename=os.path.basename(ref.path) if ref.path else (ref.docname or ""),
        path=ref.path,
        url=ref.url,
        size_bytes=ref.size_bytes or 0,
        pages=ref.pages,
        chunk_count=ref.chunk_count,
        citation=ref.citation,
        content_hash=ref.content_hash,
        category=GLOBAL_CATEGORY,
        visibility=DocumentVisibility.global_,
        session_id=None,
        owner_user_id=user.id,
        added_by=user.id,
        tags=tags,
        source=source,
        status=DocumentStatus.ready if ref.status is DocStatus.READY else DocumentStatus.error,
    )


# --------------------------------------------------------------------------- чтение
@router.get("", response_model=list[DocumentOut])
def list_global_documents(db: Session = Depends(get_db),
                          category: DocumentCategory | None = None
                          ) -> list[DocumentOut]:
    return [document_from_row(d) for d in
            docs_repo.list_documents(db, session_id=None, category=category)]


@router.get("/stats")
def global_stats(db: Session = Depends(get_db)) -> dict[str, Any]:
    return docs_repo.documents_summary(db, None)


# --------------------------------------------------------------------------- запись
@router.post("/upload", response_model=DocumentBatchResultOut)
async def upload(files: list[UploadFile] = File(...), tags: str = Form(""),
                 request: Request = None,
                 admin: User = Depends(require_admin),
                 db: Session = Depends(get_db)) -> DocumentBatchResultOut:
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    result = await _service().add_uploads(files)
    stored = [document_from_row(_register(db, admin, ref, tag_list, "upload"))
              for ref in result.added]
    audit(db, action="admin.documents.upload", actor=admin, target_type="collection",
          target_id="global", **(_meta(request) if request else {}),
          files=len(files), added=len(result.added), failed=len(result.failed))
    return DocumentBatchResultOut(
        added=stored,
        duplicates=[document_from_ref(ref) for ref in result.duplicates],
        failed=[FileFailureOut(name=name, error=error) for name, error in result.failed],
        total=result.total,
    )


@router.post("/bulk", response_model=DocumentBatchResultOut)
async def bulk_add(payload: dict[str, Any], request: Request,
                   admin: User = Depends(require_admin),
                   db: Session = Depends(get_db)) -> DocumentBatchResultOut:
    """Массовое добавление: `{"paths": [...], "tags": [...]}` (лимит 200 файлов)."""
    paths = payload.get("paths") or []
    if not isinstance(paths, list) or not paths:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Ожидается список `paths`")
    limit = 200
    if len(paths) > limit:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"За один раз не больше {limit} файлов")
    missing = [p for p in paths
               if not await anyio.to_thread.run_sync(Path(str(p)).exists)]
    if missing:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"Не найдено файлов: {len(missing)}")

    tag_list = [str(t).strip() for t in (payload.get("tags") or []) if str(t).strip()]
    result = await _service().add_files([str(p) for p in paths])
    stored = [document_from_row(_register(db, admin, ref, tag_list, "bulk"))
              for ref in result.added]
    audit(db, action="admin.documents.bulk", actor=admin, target_type="collection",
          target_id="global", **_meta(request),
          requested=len(paths), added=len(result.added))
    return DocumentBatchResultOut(
        added=stored,
        duplicates=[document_from_ref(ref) for ref in result.duplicates],
        failed=[FileFailureOut(name=name, error=error) for name, error in result.failed],
        total=result.total,
    )


@router.post("/path", response_model=DocumentOut)
async def add_path(payload: dict[str, Any], request: Request,
                   admin: User = Depends(require_admin),
                   db: Session = Depends(get_db)) -> DocumentOut:
    raw_path = str(payload.get("path") or "").strip()
    if not raw_path:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Не указан путь")
    path = Path(raw_path)
    is_file = await anyio.to_thread.run_sync(lambda: path.exists() and path.is_file())
    if not is_file:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Файл не найден: {path.name}")
    ref = await _service().add_file(path)
    if ref is None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Документ уже в базе (дедуп по содержимому)")
    document = _register(db, admin, ref, [], "path")
    audit(db, action="admin.documents.add", actor=admin, target_type="document",
          target_id=document.id, **_meta(request), filename=document.filename)
    return document_from_row(document)


@router.patch("/{document_id}", response_model=DocumentOut)
def update_document(document_id: str, payload: DocumentPatch, request: Request,
                    admin: User = Depends(require_admin),
                    db: Session = Depends(get_db)) -> DocumentOut:
    document = docs_repo.update_document(
        db, document_id, title=payload.title, tags=payload.tags,
        category=DocumentCategory(payload.category) if payload.category else None)
    audit(db, action="admin.documents.update", actor=admin, target_type="document",
          target_id=document_id, **_meta(request))
    return document_from_row(document)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: str, request: Request,
                          admin: User = Depends(require_admin),
                          db: Session = Depends(get_db)) -> None:
    document = docs_repo.get_document(db, document_id)
    if document.session_id is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Это документ сессии, а не глобальной базы")
    if document.dockey:
        await _service().delete_document(dockey=document.dockey)
    docs_repo.delete_document_row(db, document_id)
    audit(db, action="admin.documents.delete", actor=admin, target_type="document",
          target_id=document_id, **_meta(request), filename=document.filename)


@router.delete("", response_model=DocumentBatchResultOut)
async def clear_all(request: Request, admin: User = Depends(require_admin),
                    db: Session = Depends(get_db)) -> DocumentBatchResultOut:
    """Полная очистка глобальной базы (индекс + реестр)."""
    removed = 0
    for document in docs_repo.list_documents(db, session_id=None):
        docs_repo.delete_document_row(db, document.id)
        removed += 1
    await _service().clear_documents()
    audit(db, action="admin.documents.clear", actor=admin, target_type="collection",
          target_id="global", **_meta(request), removed=removed)
    return DocumentBatchResultOut(total=removed)


# --------------------------------------------------------------------------- индекс
@router.post("/reindex")
async def reindex(request: Request, admin: User = Depends(require_admin)) -> dict[str, Any]:
    result = await _service().rebuild_index()
    audit_db = None
    try:
        from app.db.session import get_session_factory

        with get_session_factory()() as db:
            audit_db = audit(db, action="admin.documents.reindex", actor=admin,
                             target_type="collection", target_id="global",
                             **_meta(request), **result)
    except Exception:  # аудит не должен ронять операцию
        log.exception("reindex: не удалось записать аудит")
    return {**result, "audited": audit_db is not None}


@router.post("/persist")
async def persist(request: Request, admin: User = Depends(require_admin)) -> dict[str, int]:
    saved = await _service().persist_state()
    return {"persisted": saved}


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, db: Session = Depends(get_db)) -> DocumentOut:
    document = docs_repo.get_document(db, document_id)
    if document.session_id is not None:
        raise NotFoundError("Документ не найден в глобальной базе")
    return document_from_row(document)