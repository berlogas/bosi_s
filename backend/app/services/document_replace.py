"""Замена прежней версии документа при загрузке файла с тем же именем.

Дедуп в PaperQA идёт по `dockey` — MD5 **содержимого**. Поэтому изменённый
файл получает другой dockey и попадает в коллекцию вторым документом: старая
версия остаётся в индексе, и в выдаче поиска встречаются обе.

Пользователь ожидает другого: «я загрузил обновлённый отчёт — старый должен
исчезнуть». Поэтому перед добавлением файла прежняя запись с тем же именем
удаляется (из индекса и из реестра), а новая занимает её место.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy.orm import Session

from app.db.repositories import documents as docs_repo

log = logging.getLogger("boasi.services.document_replace")


async def drop_replaced_documents(
    db: Session,
    service: Any,
    *,
    session_id: str | None,
    names: Iterable[str],
) -> list[str]:
    """Убрать прежние версии документов с теми же именами.

    `session_id=None` — глобальная база. Возвращает имена удалённых файлов.
    """
    wanted = {name for name in names if name}
    if not wanted:
        return []

    removed: list[str] = []
    for document in docs_repo.list_documents(db, session_id=session_id):
        if (document.filename or "") not in wanted:
            continue
        if document.dockey:
            try:
                await service.delete_document(dockey=document.dockey)
            except Exception:
                # Документ мог остаться только в реестре — удаляем и его.
                log.exception("drop_replaced_documents: не удалён из индекса %s",
                              document.dockey[:12])
        docs_repo.delete_document_row(db, document.id)
        removed.append(document.filename or "")
    if removed:
        log.info("drop_replaced_documents: заменено документов=%d: %s",
                 len(removed), ", ".join(removed))
    return removed


def documents_with_names(db: Session, *, session_id: str | None,
                          names: Sequence[str]) -> list[str]:
    """Имена файлов, которые уже есть в коллекции."""
    wanted = {name for name in names if name}
    if not wanted:
        return []
    return [document.filename or "" for document
            in docs_repo.list_documents(db, session_id=session_id)
            if (document.filename or "") in wanted]
