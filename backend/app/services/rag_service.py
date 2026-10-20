"""Оркестратор RAG-fusion (Фаза 6).

Связывает три слоя, которые иначе не видят друг друга:
  * реестр `documents` — категории, теги, привязка к проектам;
  * коллекции PaperQA — глобальная база и коллекция сессии;
  * генерация — ровно один вызов `aquery(PQASession)` на объединённый контекст.

Поток запроса:
    параллельно aget_evidence(глобальная, сессия)
      -> DocumentCatalog
      -> merge + приоритетный rerank (rag_fusion)
      -> top-k
      -> один aquery(PQASession)
      -> ответ + источники 📚/📁

Модуль разбит на  focused-модули:
  * `rag_trivial` — болтовня и вопросы о помощнике
  * `rag_citations` — перенумерация и починка цитат
  * `rag_retrieval` — сбор кандидатов из коллекций
  * `rag_generation` — генерация ответа и пост-обработка

Все публичные символы переэкспортируются здесь для обратной совместимости.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import SearchMode
from app.services.answer_cache import AnswerCache, get_answer_cache, index_stamp
from app.services.paperqa_service import ServiceRegistry, get_registry
from app.services.pqa_profile import build_pqa_settings, settings_fingerprint
from app.services.rag_citations import (
    REFUSAL_TEXT,
    apply_refusal,
    localize_headers,
    renumber_citations,
    strip_question_header,
    strip_references_block,
)
from app.services.rag_fusion import DocumentCatalog
from app.services.rag_generation import AnswerGenerator, FusionResult
from app.services.rag_retrieval import EvidenceRetriever
from app.services.rag_trivial import (
    ASSISTANT_NAME,
    IDENTITY_QUERIES,
    TRIVIAL_QUERIES,
    is_identity_query,
    is_refusal,
    is_trivial_query,
    trivial_prompt,
)

log = logging.getLogger("boasi.services.rag")

# ---------------------------------------------------------------------------
# Переэкспорт для обратной совместимости (тесты и другие модули импортируют
# из rag_service).
# ---------------------------------------------------------------------------
__all__ = [
    "ASSISTANT_NAME",
    "IDENTITY_QUERIES",
    "REFUSAL_TEXT",
    "TRIVIAL_QUERIES",
    "AnswerGenerator",
    "EvidenceRetriever",
    "FusionResult",
    "RagFusionService",
    "apply_refusal",
    "is_identity_query",
    "is_refusal",
    "is_trivial_query",
    "localize_headers",
    "renumber_citations",
    "strip_question_header",
    "strip_references_block",
    "trivial_prompt",
]


# ---------------------------------------------------------------------------
# Алиасы для тестов, которые импортируют приватные функции
# ---------------------------------------------------------------------------
def _is_refusal(text: str) -> bool:
    """Алиас для `is_refusal` из `rag_trivial` (обратная совместимость)."""
    return is_refusal(text)


def _renumber_citations(text: str, used: list[int]) -> str:
    """Алиас для `renumber_citations` из `rag_citations` (обратная совместимость)."""
    return renumber_citations(text, used)


def _strip_references_block(text: str) -> str:
    """Алиас для `strip_references_block` из `rag_citations` (обратная совместимость)."""
    return strip_references_block(text)


class RagFusionService:
    """Оркестратор RAG-fusion: связывает retrieval, generation и citations.

    Делегирует работу специализированным модулям:
      * `EvidenceRetriever` — сбор кандидатов из коллекций
      * `AnswerGenerator` — генерация ответа и пост-обработка
    """

    def __init__(
        self,
        registry: ServiceRegistry | None = None,
        cache: AnswerCache | None = None,
        app: Any | None = None,
    ) -> None:
        self.registry = registry or get_registry()
        self.cache = cache or get_answer_cache()
        self._app = app or get_settings()
        # Отпечаток настроек входит в ключ кэша: правка промпта или смена модели
        # обязана делать старые ответы недействительными, иначе пользователь
        # продолжает получать ответ по прежним правилам.
        self._config_stamp = settings_fingerprint(build_pqa_settings(self._app))
        self._retriever = EvidenceRetriever(self.registry, self._app)
        self._generator = AnswerGenerator(self.registry, self.cache, self._app)

    # ------------------------------------------------------------- каталог
    @staticmethod
    def load_catalog(
        db: Session, session_id: str | None,
        config: str | None = None,
    ) -> tuple[DocumentCatalog, str]:
        """Собрать метаданные документов (сессии + глобальные) и отпечаток индекса."""
        catalog = EvidenceRetriever._load_catalog(db, session_id)
        from app.db.models import Document, DocumentStatus
        rows = list(db.scalars(__import__('sqlalchemy').select(Document).where(
            Document.status != DocumentStatus.error,
            Document.session_id.is_(None) if session_id is None
            else (Document.session_id == session_id) | Document.session_id.is_(None),
        )))
        chunks = sum(row.chunks_count or 0 for row in rows)
        stamp = index_stamp(session_id, len(rows), chunks, config)
        return catalog, stamp

    # ------------------------------------------------------------- поиск
    async def retrieve(
        self,
        db: Session,
        *,
        query: str,
        session_id: str | None = None,
        mode: SearchMode = SearchMode.hybrid,
        k: int = 10,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Только источники, без генерации."""
        return await self._retriever.retrieve(
            db, query=query, session_id=session_id, mode=mode, k=k)

    # ------------------------------------------------------------- ответ
    async def answer(
        self,
        db: Session,
        *,
        query: str,
        session_id: str | None = None,
        mode: SearchMode = SearchMode.hybrid,
        k: int = 10,
        max_sources: int = 5,
        use_cache: bool = True,
        on_stage: Any = None,
    ) -> FusionResult:
        """Полный цикл: слияние коллекций -> rerank -> генерация."""
        catalog, stamp = self.load_catalog(db, session_id, self._config_stamp)
        return await self._generator.answer(
            db,
            query=query,
            session_id=session_id,
            mode=mode,
            k=k,
            max_sources=max_sources,
            use_cache=use_cache,
            on_stage=on_stage,
            catalog=catalog,
            stamp=stamp,
        )

    # ------------------------------------------------------------- уточнения
    async def suggest_queries(self, query: str, *, limit: int = 4) -> list[str]:
        """3–5 уточняющих вопросов по теме запроса (через LLM, при отказе — [])."""
        return await self._generator.suggest_queries(query, limit=limit)
