"""Документы внутри исследовательской сессии (Фаза 5).

Индекс PaperQA (`document_chunks`) и реестр (`documents`) — разные вещи:
сервис знает только про чанки, этот модуль держит метаданные (категория, теги,
цитата, размер), проверяет лимиты ТЗ и синхронизирует удаление.

Маршруты:
  GET    /api/sessions/{id}/documents              — реестр документов сессии
  POST   /api/sessions/{id}/documents/upload       — загрузка файлов (multipart)
  POST   /api/sessions/{id}/documents/path         — добавление файла с диска
  PATCH  /api/sessions/{id}/documents/{doc_id}     — категория, теги, название
  DELETE /api/sessions/{id}/documents/{doc_id}     — удалить из индекса и реестра
  POST   /api/sessions/{id}/documents/links        — связать документ (cites/…)
  GET    /api/sessions/{id}/documents/links        — связи сессии
  DELETE /api/sessions/{id}/documents/links/{link_id}
  POST   /api/sessions/{id}/documents/restore      — пересобрать индекс из БД
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import anyio
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.api.serializers import (
    document_from_ref,
    document_from_row,
    link_out,
)
from app.core.security import get_current_user, require_researcher
from app.db.models import (
    Document,
    DocumentCategory,
    DocumentStatus,
    DocumentVisibility,
    ProjectDocRole,
    RelationType,
    ResearchSession,
    User,
)
from app.db.repositories import documents as docs_repo
from app.db.repositories.sessions import ensure_writable
from app.db.repositories.users import audit, get_owned_session, touch_session
from app.db.session import get_db
from app.schemas.api import (
    DocumentBatchResultOut,
    DocumentLinkIn,
    DocumentLinkOut,
    DocumentOut,
    DocumentPatch,
    FileFailureOut,
)
from app.services.paperqa_service import get_registry
from app.services.types import DocStatus, DocumentRef

log = logging.getLogger("boasi.api.session_documents")

router = APIRouter(prefix="/api/sessions", tags=["session-documents"],
                   dependencies=[Depends(require_researcher)])


def _meta(request: Request) -> dict[str, str | None]:
    return {"ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent")}


def _service(session_id: str) -> Any:
    return get_registry().session_service(session_id)


async def _register(db: Session, session: ResearchSession, user: User,
                    ref: DocumentRef,
                    category: DocumentCategory, tags: list[str] | None,
                    source: str | None) -> Document:
    """Зеркалим `DocumentRef` в таблицу `documents`."""
    return docs_repo.upsert_document(
        db,
        dockey=ref.dockey,
        docname=ref.docname or "",
        title=ref.title or ref.docname,
        filename=os.path.basename(ref.path) if ref.path else (ref.docname or ""),
        path=ref.path,
        url=ref.url,
        mime=None,
        size_bytes=ref.size_bytes or 0,
        pages=ref.pages,
        chunk_count=ref.chunk_count,
        citation=ref.citation,
        content_hash=ref.content_hash,
        category=category,
        visibility=DocumentVisibility.session,
        session_id=session.id,
        owner_user_id=session.user_id,
        added_by=user.id,
        tags=tags,
        source=source,
        status=DocumentStatus.ready if ref.status is DocStatus.READY else DocumentStatus.error,
    )


# --------------------------------------------------------------------------- чтение
@router.get("/{session_id}/documents", response_model=list[DocumentOut])
def list_session_documents(session_id: str, user: User = Depends(get_current_user),
                           db: Session = Depends(get_db),
                           category: DocumentCategory | None = None
                           ) -> list[Document]:
    session = get_owned_session(db, session_id, user)
    touch_session(db, session)
    return docs_repo.list_documents(db, session_id=session.id, category=category)


# --------------------------------------------------------------------------- запись
@router.post("/{session_id}/documents/upload", response_model=DocumentBatchResultOut)
async def upload_documents(
    session_id: str,
    files: list[UploadFile] = File(...),
    category: DocumentCategory = Form(DocumentCategory.temp_literature),
    tags: str = Form(""),
    request: Request = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentBatchResultOut:
    session = get_owned_session(db, session_id, user)
    ensure_writable(session)

    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    total_bytes = sum(getattr(f, "size", 0) or 0 for f in files)
    docs_repo.check_document_limits(db, session.id,
                                    incoming_count=len(files),
                                    incoming_bytes=total_bytes)

    # сервис читает UploadFile сам, поэтому передаём их как есть
    result = await _service(session.id).add_uploads(
        files, category=category.value, session_id=session.id)

    registered = 0
    stored: list[DocumentOut] = []
    for ref in result.added:
        document = await _register(db, session, user, ref, category, tag_list, source="upload")
        stored.append(document_from_row(document))
        registered += 1

    touch_session(db, session, action_type="documents.upload",
                  action_label=f"Загружено документов: {registered}",
                  snapshot={"tab": "documents"})
    audit(db, action="session.documents.upload", actor=user, target_type="session",
          target_id=session.id, **(_meta(request) if request else {}),
          files=len(files), added=registered, failed=len(result.failed))
    # ответ строим по реестру — в нём есть теги и категория, которых нет в DocumentRef
    return DocumentBatchResultOut(
        added=stored,
        duplicates=[document_from_ref(ref) for ref in result.duplicates],
        failed=[FileFailureOut(name=name, error=error)
                for name, error in result.failed],
        total=result.total,
    )


@router.post("/{session_id}/documents/path", response_model=DocumentOut)
async def add_document_path(
    session_id: str,
    payload: dict[str, Any],
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentOut:
    """Добавление файла с диска: `{"path": ..., "category": ..., "tags": [...]}`."""
    session = get_owned_session(db, session_id, user)
    ensure_writable(session)

    raw_path = str(payload.get("path") or "").strip()
    if not raw_path:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Не указан путь к файлу")
    path = Path(raw_path)
    is_file = await anyio.to_thread.run_sync(lambda: path.exists() and path.is_file())
    if not is_file:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Файл не найден: {path.name}")

    category = _parse_category(payload.get("category"))
    tags = _parse_tags(payload.get("tags"))

    size = await anyio.to_thread.run_sync(lambda: path.stat().st_size)
    docs_repo.check_document_limits(db, session.id, incoming_count=1,
                                    incoming_bytes=size)
    ref = await _service(session.id).add_file(path, category=category.value,
                                              session_id=session.id)
    if ref is None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Документ уже есть в индексе (дедуп по содержимому)")
    document = await _register(db, session, user, ref, category, tags, source="path")
    touch_session(db, session, action_type="documents.add",
                  action_label=f"Добавлен документ: {ref.title or ref.docname}",
                  snapshot={"tab": "documents"})
    return document_from_row(document)


@router.patch("/{session_id}/documents/{document_id}", response_model=DocumentOut)
def update_document(session_id: str, document_id: str, payload: DocumentPatch,
                    user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)) -> DocumentOut:
    session = get_owned_session(db, session_id, user)
    ensure_writable(session)

    document = docs_repo.get_document(db, document_id)
    if document.session_id != session.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Документ не найден в сессии")

    updated = docs_repo.update_document(
        db, document_id, title=payload.title,
        category=_parse_category(payload.category) if payload.category else None,
        tags=payload.tags,
    )
    touch_session(db, session, action_type="documents.update",
                  action_label=f"Обновлён документ: {updated.title}")
    return document_from_row(updated)


@router.delete("/{session_id}/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(session_id: str, document_id: str,
                          user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)) -> None:
    session = get_owned_session(db, session_id, user)
    ensure_writable(session)

    document = docs_repo.get_document(db, document_id)
    if document.session_id != session.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Документ не найден в сессии")

    dockey = document.dockey
    if dockey:
        await _service(session.id).delete_document(dockey=dockey)
    docs_repo.delete_document_row(db, document_id)
    touch_session(db, session, action_type="documents.delete",
                  action_label=f"Удалён документ: {document.title}",
                  snapshot={"tab": "documents"})


@router.post("/{session_id}/documents/restore", response_model=dict)
async def restore_index(session_id: str, user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)) -> dict[str, int]:
    """Пересобрать `Docs` сессии из БД (после рестарта контейнера)."""
    session = get_owned_session(db, session_id, user)
    restored = await _service(session.id).restore_state(force=True)
    touch_session(db, session, action_type="documents.restore",
                  action_label="Индекс восстановлен из БД")
    return {"restored": restored}


# --------------------------------------------------------------------------- связи
@router.post("/{session_id}/documents/{document_id}/links",
             response_model=DocumentLinkOut, status_code=status.HTTP_201_CREATED)
def create_link(session_id: str, document_id: str, payload: DocumentLinkIn,
                user: User = Depends(get_current_user),
                db: Session = Depends(get_db)) -> DocumentLinkOut:
    """Связать документ с проектом или с другим документом (cites/supports/…)."""
    session = get_owned_session(db, session_id, user)
    ensure_writable(session)

    document = docs_repo.get_document(db, document_id)
    if document.session_id != session.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Документ не найден в сессии")

    link = docs_repo.link_document(
        db,
        document_id=document_id,
        session_id=session.id,
        project_id=payload.project_id,
        target_document_id=payload.target_document_id,
        role=_parse_role(payload.role),
        relation=_parse_relation(payload.relation),
        note=payload.note,
    )
    touch_session(db, session, action_type="documents.link",
                  action_label=f"Связь: {payload.relation}")
    return link_out(link)


@router.get("/{session_id}/documents/links", response_model=list[DocumentLinkOut])
def list_links(session_id: str, user: User = Depends(get_current_user),
               db: Session = Depends(get_db)) -> list[DocumentLinkOut]:
    session = get_owned_session(db, session_id, user)
    return [link_out(link) for link in docs_repo.list_links(db, session_id=session.id)]


@router.delete("/{session_id}/documents/links/{link_id}",
               status_code=status.HTTP_204_NO_CONTENT)
def delete_link(session_id: str, link_id: str, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)) -> None:
    session = get_owned_session(db, session_id, user)
    ensure_writable(session)
    if not docs_repo.unlink_document(db, link_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Связь не найдена")


# --------------------------------------------------------------------------- хелперы
def _parse_category(value: Any, default: DocumentCategory = DocumentCategory.temp_literature
                    ) -> DocumentCategory:
    """Категория из запроса; пустое значение -> категория по умолчанию."""
    if isinstance(value, DocumentCategory):
        return value
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    try:
        return DocumentCategory(str(value).strip())
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Неизвестная категория: {value}. Допустимо: "
            + ", ".join(c.value for c in DocumentCategory),
        ) from exc


def _parse_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [t.strip() for t in value.split(",") if t.strip()]
    return [str(t).strip() for t in value if str(t).strip()]


def _parse_role(value: str | None) -> ProjectDocRole | None:

    if value is None:
        return None
    try:
        return ProjectDocRole(value)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Неизвестная роль документа: {value}") from exc


def _parse_relation(value: str | None) -> RelationType:

    try:
        return RelationType(value or "cites")
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Неизвестный тип связи: {value}") from exc