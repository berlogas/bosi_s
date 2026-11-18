"""Операции с индексом PaperQA2: переиндексация, статус."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, status

from app.api.admin import _client_meta
from app.core.security import require_admin
from app.db.session import get_db
from app.schemas.api import CitationReportOut, ReindexRequest, ReindexResultOut
from app.services.pqa_registry import get_registry

router = APIRouter(prefix="/api/pqa", tags=["pqa"], dependencies=[Depends(require_admin)])


@router.post("/reindex", response_model=ReindexResultOut, status_code=status.HTTP_200_OK)
async def reindex_index(
    payload: ReindexRequest,
    request: Request,
    db=Depends(get_db),
) -> dict[str, Any]:
    """Полная переиндексация коллекции.

    Перечитывает документы из хранилища, пересчитывает эмбеддинги
    (если ``drop_embeddings=True``) и сохраняет результат обратно.
    Требует прав администратора.
    """
    registry = get_registry()
    service = registry.global_service()
    result = await service.rebuild_index(drop_embeddings=payload.drop_embeddings)
    return {
        "documents": result["documents"],
        "chunks": result["chunks"],
        "seconds": result["seconds"],
        "collection": service.collection,
        "meta": {"source": "api", **_client_meta(request)},
    }


@router.get("/citation-report", response_model=CitationReportOut | None,
            status_code=status.HTTP_200_OK)
async def citation_report() -> CitationReportOut | None:
    """Отчёт о цитировании последнего ответа чата.

    Возвращает CitationReport из последнего ответа /api/chat/query
    (или /api/chat/stream): какие маркеры починили, какие удалили,
    предупреждения о сломанных ссылках. Требует прав администратора.
    """
    registry = get_registry()
    report = registry.get_citation_report()
    if report is None:
        return None
    return CitationReportOut(**report)
