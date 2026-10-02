"""Сервис генерации разделов статей (Фаза 7).

Связывает RAG-контекст (Фаза 6) с LLM-генерацией и контрактом цитат:

    fusion -> источники с номерами -> промпт с жёсткими правилами -> LLM
           -> validate_citations() -> снапшот версии в БД

Генерация сперва пробует без LLM: если раздел уже написан и буфер совпал,
возвращаем версию из БД (кэш генераций). Это же даёт «защиту от повторных
вопросов» для дорогих генераций.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, UpstreamError
from app.db.models import (
    Document,
    DocumentLink,
    GenerationKind,
    Project,
    ProjectDocRole,
    ProjectStatus,
    ProjectVersion,
    ResearchSession,
    SearchMode,
    User,
    new_id,
)
from app.services import analyses
from app.services.generation import (
    GenerationResult,
    build_citation_map,
    build_prompt,
    normalize_sections,
    progress,
    validate_citations,
)
from app.services.paperqa_service import ServiceRegistry, get_registry
from app.services.rag_service import RagFusionService

log = logging.getLogger("boasi.services.projects")

NO_MATERIAL_TEXT = (
    "Недостаточно материала: в контексте проекта не найдено релевантных "
    "источников для этого раздела. Добавьте литературу или данные в сессию."
)


def find_project(db: Session, project_id: str, session_id: str | None = None) -> Project:
    project = db.get(Project, project_id)
    if project is None or (session_id and project.session_id != session_id):
        raise NotFoundError("Проект не найден")
    return project


def linked_documents(db: Session, project_id: str) -> list[tuple[Document, str | None]]:
    """Документы проекта с их ролью (reference / data / draft)."""
    rows = db.execute(
        select(Document, DocumentLink.role)
        .join(DocumentLink, DocumentLink.document_id == Document.id)
        .where(DocumentLink.project_id == project_id)
        .order_by(Document.created_at)
    ).all()
    return [(doc, getattr(role, "value", role)) for doc, role in rows]


@dataclass
class GenerationRequest:
    section: str
    question: str
    word_target: int | None = None
    notes: str | None = None
    use_cache: bool = True
    # Для отчёта по шаблону (kind=report)
    template_md: str | None = None
    # Ограничить сверку конкретными документами с ролью data
    data_document_ids: list[str] | None = None
    # Вид генерации; по умолчанию обычный раздел.
    kind: GenerationKind = GenerationKind.section


class ProjectService:
    def __init__(self, registry: ServiceRegistry | None = None) -> None:
        self.registry = registry or get_registry()

    # ------------------------------------------------------------------ генерация
    async def generate_section(
        self,
        db: Session,
        *,
        project: Project,
        session: ResearchSession,
        user: User,
        request: GenerationRequest,
        kind: GenerationKind = GenerationKind.section,
    ) -> GenerationResult:
        """Сгенерировать раздел по контексту проекта и сессии.

        Промпт собираем сами (`build_prompt`), а не отдаём вопрос PaperQA:
        у PaperQA своя нумерация источников, а контракт ТЗ требует, чтобы
        каждая ссылка `[n]` разрешалась в наш список.
        """
        if session.status.value not in {"active", "paused"}:
            from app.core.errors import ConflictError

            raise ConflictError("Сессия архивирована — генерация недоступна")

        # Вид генерации — часть состояния запроса: от него зависят промпт,
        # режим подбора контекста и то, попадёт ли разбор в результат.
        request.kind = kind

        # кэш генераций: тот же раздел + тот же вопрос -> отдаём прошлую версию
        if request.use_cache:
            cached = self._find_cached(db, project.id, request)
            if cached is not None:
                log.info("generate: раздел %r взят из версии %s",
                         request.section, cached.id[:8])
                return GenerationResult(
                    section=request.section,
                    content_md=cached.content_md,
                    sources=[s for s in cached.citation_map or []],
                    citation_map=list(cached.citation_map or []),
                    citation_check=validate_citations(cached.content_md,
                                                      len(cached.citation_map or [])),
                    from_cache=True,
                    answer=None,
                )

        fusion = RagFusionService(self.registry)
        mode = SearchMode.project_focus if project.status in {
            ProjectStatus.drafting, ProjectStatus.reviewing} else SearchMode.hybrid
        sources, _retrieval_stats = await fusion.retrieve(
            db, query=request.question, session_id=session.id, mode=mode, k=15)

        if not sources:
            generation = GenerationResult(
                section=request.section,
                content_md=NO_MATERIAL_TEXT,
                sources=[], citation_map=[],
                citation_check=validate_citations(NO_MATERIAL_TEXT, 0),
                extra_warnings=["В контексте нет релевантных источников"],
            )
            self._save_version(db, project=project, session=session, user=user,
                               generation=generation, kind=kind)
            return generation

        prompt = self._build_prompt(project, request, sources, db)
        text, seconds = await self._complete(prompt, session.id)

        check = validate_citations(text, len(sources))
        citation_map = build_citation_map(text, sources)

        self._question = request.question
        analysis_payload = None
        if kind is GenerationKind.draft_analysis:
            # Детерминированный разбор считаем сами, модель лишь комментирует.
            analysis_payload = analyses.analyze_draft(
                normalize_sections(project.sections)).to_dict()

        generation = GenerationResult(
            section=request.section,
            content_md=text,
            sources=sources,
            citation_check=check,
            citation_map=citation_map,
            seconds=seconds,
            analysis=analysis_payload,
        )
        self._save_version(db, project=project, session=session, user=user,
                           generation=generation, kind=kind)
        return generation

    # ------------------------------------------------------------------ промпты
    def _build_prompt(self, project: Project, request: GenerationRequest,
                      sources: list[dict[str, Any]], db: Session) -> str:
        """Промпт под вид генерации: у каждого своя постановка вопроса."""
        language = self.registry.app.answer_language
        notes = request.notes or self._section_notes(project, request.section)

        if request.kind is GenerationKind.literature_review:
            return analyses.literature_review_prompt(
                request.question or request.section, sources,
                word_target=request.word_target or 1200)

        if request.kind is GenerationKind.data_comparison:
            summaries = self._data_summaries(project, db, request.data_document_ids)
            return analyses.data_comparison_prompt(
                request.question or request.section, summaries, sources,
                word_target=request.word_target or 800)

        if request.kind is GenerationKind.gap_analysis:
            return analyses.gap_analysis_prompt(
                request.question or request.section,
                analyses.coverage_line(sources), sources)

        if request.kind is GenerationKind.report:
            template = request.template_md or analyses.DEFAULT_REPORT_TEMPLATE
            return analyses.report_prompt(template, sources,
                                          question=request.question)

        if request.kind is GenerationKind.draft_analysis:
            # Сначала детерминированный разбор, модель добавляет комментарий.
            sections = normalize_sections(project.sections)
            analysis = analyses.analyze_draft(sections)
            base = build_prompt(
                request.section or "Обзор черновика", request.question, sources,
                language=language, notes=notes, word_target=request.word_target)
            commentary = (
                "На основе разбора выше напиши краткий комментарий: что исправить "
                "в первую очередь и почему. Ссылайся на источники [n]."
            )
            return (f"{analyses.render_gaps(analysis)}\n\n{commentary}\n\n{base}")

        return build_prompt(
            request.section, request.question, sources, language=language,
            notes=notes, word_target=request.word_target,
        )

    def _data_summaries(self, project: Project, db: Session,
                        only_ids: list[str] | None = None) -> list[Any]:
        """Сводки по документам с ролью data, привязанным к проекту."""
        from app.services.data_extract import summarize_documents

        documents = [doc for doc, role in linked_documents(db, project.id)
                     if role == ProjectDocRole.data.value]
        if only_ids:
            wanted = set(only_ids)
            documents = [doc for doc in documents if doc.id in wanted]
        return summarize_documents(documents)

    @staticmethod
    def _section_notes(project: Project, section: str) -> str | None:
        """Указания автора к разделу из плана проекта."""
        for item in normalize_sections(project.sections):
            if item["name"].lower() == section.lower():
                return item.get("notes") or None
        return None

    async def _complete(self, prompt: str, session_id: str | None
                        ) -> tuple[str, float]:
        """Один вызов LLM с нашим промптом через слой сервисов.

        Идём через `PaperQA2Service.complete`, а не строим модель сами:
        так генерация использует ровно ту же (в т.ч. подменённую в тестах)
        модель, что и поиск по контексту.
        """
        import time

        service = (self.registry.session_service(session_id) if session_id
                   else self.registry.global_service())
        started = time.perf_counter()
        try:
            text = await service.complete(prompt, name="section")
        except Exception as exc:
            log.exception("generate: LLM не ответил")
            raise UpstreamError(
                f"Генерация не удалась: {type(exc).__name__}: {exc}") from exc
        return text, time.perf_counter() - started

    # ------------------------------------------------------------------ версии
    _question: str = ""

    def _save_version(self, db: Session, *, project: Project,
                      session: ResearchSession, user: User,
                      generation: GenerationResult,
                      kind: GenerationKind) -> ProjectVersion:
        version = ProjectVersion(
            id=new_id(),
            project_id=project.id,
            session_id=session.id,
            section_name=generation.section,
            kind=kind,
            content_md=generation.content_md,
            word_count=generation.word_count,
            citation_map=generation.citation_map,
            stats={"citations_ok": generation.ok,
                   "sources": len(generation.sources),
                   "seconds": round(generation.seconds, 2)},
            created_by=user.id,
        )
        db.add(version)
        self._write_into_plan(project, generation)
        version.stats = {**(version.stats or {}), "question": self._question}
        db.commit()
        return version

    @staticmethod
    def _write_into_plan(project: Project, generation: GenerationResult) -> None:
        """Записать текст в раздел плана (создаём раздел, если его нет)."""
        sections = normalize_sections(project.sections)
        for section in sections:
            if section["name"].lower() == generation.section.lower():
                section["content_md"] = generation.content_md
                break
        else:
            sections.append({
                "name": generation.section,
                "required": True,
                "order": len(sections) + 1,
                "word_target": len(generation.content_md.split()),
                "notes": "",
                "content_md": generation.content_md,
            })
        project.sections = sections

    def _find_cached(self, db: Session, project_id: str,
                     request: GenerationRequest) -> ProjectVersion | None:
        """Последняя версия этого раздела с тем же вопросом (хранится в stats)."""
        stmt = (
            select(ProjectVersion)
            .where(ProjectVersion.project_id == project_id,
                   ProjectVersion.section_name == request.section)
            .order_by(ProjectVersion.created_at.desc())
            .limit(1)
        )
        for version in db.scalars(stmt):
            if (version.stats or {}).get("question") == request.question:
                return version
        return None

    # ------------------------------------------------------------------ данные
    @staticmethod
    def data_summary(documents: Sequence[Document]) -> list[dict[str, Any]]:
        """Сводка по документам с ролью data — для сопоставления с литературой."""
        summary: list[dict[str, Any]] = []
        for document in documents:
            if document.mime and "csv" not in document.mime and \
                    not str(document.filename or "").lower().endswith((".csv", ".tsv")):
                continue
            summary.append({
                "id": document.id,
                "title": document.title,
                "filename": document.filename,
                "rows": document.pages,
                "bytes": document.size_bytes,
                "citation": document.citation,
            })
        return summary

    @staticmethod
    def plan_progress(project: Project) -> dict[str, Any]:
        return progress(normalize_sections(project.sections))


__all__ = [
    "NO_MATERIAL_TEXT",
    "GenerationRequest",
    "ProjectDocRole",
    "ProjectService",
    "ProjectStatus",
    "find_project",
    "linked_documents",
]