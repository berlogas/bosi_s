"""Персистентность чанков PaperQA в SQLite.

Почему так (спайк 03): `pickle.dumps(Docs)` работает (15.8 KiB), но каноничный
и переносимый способ — сохранить `Text` + `Doc` (вместе с эмбеддингами) в БД и
восстановить через `Docs.aadd_texts()`. Проверено: после восстановления
`Context.score` совпадают, эмбеддинги не пересчитываются (`aadd_texts` пропускает
модель, если `texts[0].embedding` уже задан).

Формат хранения — zlib + JSON (не pickle): не зависит от версии Python,
безопаснее и читаемо для отладки.
"""

from __future__ import annotations

import json
import zlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

import anyio
from paperqa import Doc, Text
from sqlalchemy import select

from app.db.models import DocumentChunk, utcnow
from app.db.session import get_session_factory


def _dumps(value: Any) -> bytes:
    return zlib.compress(json.dumps(value, ensure_ascii=False).encode("utf-8"), level=6)


def _loads(blob: bytes) -> Any:
    return json.loads(zlib.decompress(blob).decode("utf-8"))


@dataclass(slots=True)
class StoredDocument:
    """Запись хранилища: метаданные документа + его чанки."""

    dockey: str
    docname: str
    citation: str | None
    chunk_count: int
    settings_md5: str | None
    updated_at: Any = None
    doc: Doc | None = None
    texts: list[Text] | None = None


class ChunkStore(Protocol):
    """Контракт хранилища чанков."""

    async def save(self, collection: str, doc: Doc, texts: list[Text],
                   settings_md5: str | None = None) -> None: ...

    async def delete(self, collection: str, dockey: str) -> bool: ...

    async def clear(self, collection: str) -> int: ...

    async def load(self, collection: str) -> list[StoredDocument]: ...

    async def list_documents(self, collection: str) -> list[StoredDocument]: ...

    async def count_chunks(self, collection: str) -> int: ...


class SqliteChunkStore:
    """Хранилище чанков в той же SQLite, что и остальные данные платформы."""

    def __init__(self, session_factory: Any | None = None) -> None:
        self._factory = session_factory

    def _session(self) -> Any:
        return (self._factory or get_session_factory())()

    async def save(self, collection: str, doc: Doc, texts: list[Text],
                   settings_md5: str | None = None) -> None:
        row = DocumentChunk(
            collection=collection,
            dockey=str(doc.dockey),
            docname=doc.docname,
            citation=doc.citation,
            chunk_count=len(texts),
            settings_md5=settings_md5,
            doc_blob=_dumps(doc.model_dump(mode="json")),
            texts_blob=_dumps([t.model_dump(mode="json") for t in texts]),
            updated_at=utcnow(),
        )

        def _write() -> None:
            with self._session() as db:
                existing = db.scalars(
                    select(DocumentChunk).where(
                        DocumentChunk.collection == collection,
                        DocumentChunk.dockey == str(doc.dockey),
                    )
                ).first()
                if existing is None:
                    db.add(row)
                else:
                    for field in ("docname", "citation", "chunk_count", "settings_md5",
                                  "doc_blob", "texts_blob", "updated_at"):
                        setattr(existing, field, getattr(row, field))
                db.commit()

        await anyio.to_thread.run_sync(_write)

    async def delete(self, collection: str, dockey: str) -> bool:
        def _delete() -> bool:
            with self._session() as db:
                row = db.scalars(
                    select(DocumentChunk).where(
                        DocumentChunk.collection == collection,
                        DocumentChunk.dockey == dockey,
                    )
                ).first()
                if row is None:
                    return False
                db.delete(row)
                db.commit()
                return True

        return await anyio.to_thread.run_sync(_delete)

    async def clear(self, collection: str) -> int:
        def _clear() -> int:
            with self._session() as db:
                rows = list(db.scalars(
                    select(DocumentChunk).where(DocumentChunk.collection == collection)
                ))
                for row in rows:
                    db.delete(row)
                db.commit()
                return len(rows)

        return await anyio.to_thread.run_sync(_clear)

    async def load(self, collection: str) -> list[StoredDocument]:
        return await self.list_documents(collection, with_payload=True)

    async def list_documents(self, collection: str, with_payload: bool = False) \
        -> list[StoredDocument]:
        def _read() -> list[StoredDocument]:
            with self._session() as db:
                rows = list(db.scalars(
                    select(DocumentChunk)
                    .where(DocumentChunk.collection == collection)
                    .order_by(DocumentChunk.docname)
                ))
                result = []
                for row in rows:
                    doc = Doc.model_validate(_loads(row.doc_blob)) if with_payload else None
                    texts = (
                        [Text.model_validate(item) for item in _loads(row.texts_blob)]
                        if with_payload else None
                    )
                    result.append(StoredDocument(
                        dockey=row.dockey, docname=row.docname, citation=row.citation,
                        chunk_count=row.chunk_count, settings_md5=row.settings_md5,
                        updated_at=row.updated_at, doc=doc, texts=texts,
                    ))
                return result

        return await anyio.to_thread.run_sync(_read)

    async def count_chunks(self, collection: str) -> int:
        def _count() -> int:
            with self._session() as db:
                return sum(
                    row.chunk_count for row in db.scalars(
                        select(DocumentChunk).where(DocumentChunk.collection == collection)
                    )
                )

        return await anyio.to_thread.run_sync(_count)


class MemoryChunkStore:
    """Хранилище в памяти — для тестов без БД."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, StoredDocument]] = {}

    async def save(self, collection: str, doc: Doc, texts: list[Text],
                   settings_md5: str | None = None) -> None:
        self._data.setdefault(collection, {})[str(doc.dockey)] = StoredDocument(
            dockey=str(doc.dockey), docname=doc.docname, citation=doc.citation,
            chunk_count=len(texts), settings_md5=settings_md5, updated_at=utcnow(),
            doc=doc.model_copy(deep=True),
            texts=[t.model_copy(deep=True) for t in texts],
        )

    async def delete(self, collection: str, dockey: str) -> bool:
        return self._data.get(collection, {}).pop(dockey, None) is not None

    async def clear(self, collection: str) -> int:
        items = self._data.pop(collection, {})
        return len(items)

    async def load(self, collection: str) -> list[StoredDocument]:
        return list(self._data.get(collection, {}).values())

    async def list_documents(self, collection: str) -> list[StoredDocument]:
        return list(self._data.get(collection, {}).values())

    async def count_chunks(self, collection: str) -> int:
        return sum(d.chunk_count for d in self._data.get(collection, {}).values())


def collections_in(store: ChunkStore) -> Iterable[str]:  # pragma: no cover - утилита
    data = getattr(store, "_data", None)
    return list(data) if isinstance(data, dict) else []