"""Кэш ответов: защита от повторных вопросов и перезапросов после рестарта.

Ключ — хэш от (режим, нормализованный вопрос, отпечаток индекса). Отпечаток
меняется при добавлении/удалении документов, поэтому устаревший ответ после
изменения коллекции не подставляется.

Хранилище — JSON в `PQA_HOME/answers` (тот же том, что и остальные данные),
плюс оперативный слой в памяти процесса.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anyio

from app.config import get_settings

log = logging.getLogger("boasi.services.answer_cache")

_NORMALIZE_RE = re.compile(r"\s+")


def normalize_query(text: str) -> str:
    """Регистр и пробелы не должны создавать новый ключ."""
    return _NORMALIZE_RE.sub(" ", (text or "").strip().lower())


def index_stamp(session_id: str | None, doc_count: int, chunk_count: int) -> str:
    return f"{session_id or '-'}:{doc_count}:{chunk_count}"


def make_key(*, session_id: str | None, mode: str, query: str, stamp: str) -> str:
    raw = "|".join((session_id or "-", mode, normalize_query(query), stamp))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class CachedAnswer:
    answer: str
    sources: list[dict[str, Any]] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    seconds: float = 0.0
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"answer": self.answer, "sources": self.sources,
                "citations": self.citations, "seconds": self.seconds,
                "created_at": self.created_at}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CachedAnswer:
        return cls(answer=str(raw.get("answer", "")),
                   sources=list(raw.get("sources") or []),
                   citations=list(raw.get("citations") or []),
                   seconds=float(raw.get("seconds") or 0.0),
                   created_at=float(raw.get("created_at") or 0.0))


class AnswerCache:
    def __init__(self, root: Path | None = None, ttl_seconds: float | None = None
                 ) -> None:
        settings = get_settings()
        self.root = root or (settings.resolved_pqa_home / "answers")
        self.ttl = ttl_seconds if ttl_seconds is not None else 24 * 3600
        self._memory: dict[str, CachedAnswer] = {}

    # ------------------------------------------------------------------ пути
    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    # ------------------------------------------------------------------ запись
    def _write(self, key: str, payload: CachedAnswer) -> None:
        self._memory[key] = payload
        path = self._path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload.to_dict(), ensure_ascii=False),
                            encoding="utf-8")
        except OSError as exc:
            log.warning("answer_cache: не удалось записать %s: %s", key[:12], exc)

    async def put(self, key: str, payload: CachedAnswer) -> None:
        payload.created_at = time.time()
        await anyio.to_thread.run_sync(self._write, key, payload)

    # ------------------------------------------------------------------ чтение
    def _read(self, key: str) -> CachedAnswer | None:
        payload = self._memory.get(key)
        if payload is not None:
            return payload if time.time() - payload.created_at <= self.ttl else None
        path = self._path(key)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        payload = CachedAnswer.from_dict(raw)
        if time.time() - payload.created_at > self.ttl:
            return None
        self._memory[key] = payload
        return payload

    async def get(self, key: str) -> CachedAnswer | None:
        return await anyio.to_thread.run_sync(self._read, key)

    async def get_or_none(self, *, session_id: str | None, mode: str, query: str,
                          stamp: str) -> CachedAnswer | None:
        return await self.get(make_key(session_id=session_id, mode=mode,
                                      query=query, stamp=stamp))

    async def put_answer(self, *, session_id: str | None, mode: str, query: str,
                         stamp: str, payload: CachedAnswer) -> str:
        key = make_key(session_id=session_id, mode=mode, query=query, stamp=stamp)
        await self.put(key, payload)
        return key

    def invalidate_session(self, session_id: str) -> int:
        """Сбросить оперативный слой сессии (файлы трогаем лениво)."""
        return len(self._memory)

    def clear(self) -> None:
        self._memory.clear()


_cache: AnswerCache | None = None


def get_answer_cache() -> AnswerCache:
    global _cache
    if _cache is None:
        _cache = AnswerCache()
    return _cache


def reset_answer_cache() -> None:
    global _cache
    _cache = None