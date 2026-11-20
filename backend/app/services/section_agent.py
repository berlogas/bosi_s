"""SectionAgent — итеративный агент генерации разделов (PaperQA2 style).

Реализует цикл: search_evidence -> gather_summaries -> generate_draft -> critique
с повторением до прохождения quality gates или max_iterations.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    new_id,
    GenerationKind,
    Project,
    ProjectDocRole,
    ProjectStatus,
    ProjectLanguagePolicy,
    ResearchSession,
    SectionKind,
    SectionPlan,
    SectionStatus,
    SectionVersion,
    TerminologyGlossary,
    User,
    VersionStatus,
)
from app.services import analyses
from app.services.generation import (
    GenerationResult,
    build_citation_map,
    build_prompt,
    citations_required,
    normalize_sections,
    validate_citations,
)
from app.services.journal_styles import style_prompt
from app.services.paperqa_service import PaperQA2Service
from app.services.pqa_registry import ServiceRegistry, get_registry
from app.services.project_sections import project_sections
from app.services.rag_service import RagFusionService
from app.services.rag_service import SearchMode

log = logging.getLogger("boasi.services.section_agent")


# --------------------------------------------------------------------------- dataclasses
@dataclass
class QualityReport:
    """Отчёт качества версии раздела."""

    citations_ok: bool = True
    dangling_citations: list[int] = field(default_factory=list)
    unused_sources: list[int] = field(default_factory=list)
    grounding_score: float | None = None      # 0-1, LLM-judged
    completeness_score: float | None = None   # 0-1, covers question aspects
    style_compliance: dict[str, bool] = field(default_factory=dict)
    terminology_consistency: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    passed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "citations_ok": self.citations_ok,
            "dangling_citations": self.dangling_citations,
            "unused_sources": self.unused_sources,
            "grounding_score": self.grounding_score,
            "completeness_score": self.completeness_score,
            "style_compliance": self.style_compliance,
            "terminology_consistency": self.terminology_consistency,
            "warnings": self.warnings,
            "passed": self.passed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QualityReport:
        return cls(**data)


@dataclass
class GenerationParams:
    """Полный снапшот параметров генерации для воспроизводимости."""

    question: str
    notes: str | None
    style_guide_text: str | None
    journal_style: str | None
    sources_used: list[dict[str, Any]] = field(default_factory=list)
    retrieval_mode: str = "hybrid"
    evidence_k: int = 15
    max_sources: int = 10
    temperature: float = 0.0
    model: str = ""
    prompt_template_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "notes": self.notes,
            "style_guide_text": self.style_guide_text,
            "journal_style": self.journal_style,
            "sources_used": self.sources_used,
            "retrieval_mode": self.retrieval_mode,
            "evidence_k": self.evidence_k,
            "max_sources": self.max_sources,
            "temperature": self.temperature,
            "model": self.model,
            "prompt_template_version": self.prompt_template_version,
        }


@dataclass
class CritiqueResult:
    """Результат самокритики черновика."""

    quality_report: QualityReport
    feedback: str  # текстовый фидбек для следующей итерации
    needs_revision: bool


# --------------------------------------------------------------------------- SectionAgent
class SectionAgent:
    """Агент генерации одного раздела с итеративным улучшением."""

    def __init__(
        self,
        registry: ServiceRegistry | None = None,
        max_iterations: int = 3,
        quality_thresholds: dict[str, float] | None = None,
        project: Project | None = None,
    ) -> None:
        self.registry = registry or get_registry()
        self.max_iterations = max_iterations
        self.project = project
        
        # Базовые пороги (перекрываются настройками проекта если project передан)
        self._base_quality_thresholds = quality_thresholds or {
            "grounding": 0.7,
            "completeness": 0.7,
            "citations_ok": 1.0,
        }

    def _get_quality_thresholds(self) -> dict[str, float]:
        """Получить пороги качества с учётом настроек проекта."""
        thresholds = dict(self._base_quality_thresholds)
        if self.project and self.project.language_policy:
            policy = self.project.language_policy
            thresholds["grounding"] = policy.quality_grounding_threshold
            thresholds["completeness"] = policy.quality_completeness_threshold
            thresholds["citations_ok"] = 1.0 if policy.quality_citations_required else 0.0
        return thresholds

    def _get_max_iterations(self) -> int:
        """Получить максимум итераций с учётом настроек проекта."""
        if self.project and self.project.language_policy:
            return self.project.language_policy.max_generation_iterations
        return self.max_iterations

    async def generate(
        self,
        db: Session,
        *,
        section_plan: SectionPlan,
        project: Project,
        session: ResearchSession,
        user: User,
        question: str,
        notes: str | None = None,
        word_target: int | None = None,
        use_cache: bool = True,
        kind: GenerationKind = GenerationKind.section,
    ) -> SectionVersion:
        """Сгенерировать раздел с итеративным улучшением.

        `kind` — вид генерации: обычный раздел, обзор литературы, сверка
        с данными, обсуждение, пробелы в литературе, отчёт, разбор
        черновика. Для нестандартных видов промпт собирается отдельно
        (те же постановки, что и в старом пути генерации).
        """
        # Привязываем проект для динамических порогов
        self.project = project
        start_time = time.perf_counter()

        # 1. Подготовка параметров
        language = section_plan.language or project.language
        word_target = word_target or section_plan.word_target

        # Style guide документ
        style_guide_text = self._get_style_guide_text(db, project)
        journal_style = style_prompt(project.target_journal, section_plan.name)

        # 2. Поиск источников (RAG Fusion)
        fusion = RagFusionService(self.registry)
        mode = self._get_search_mode(project)
        sources, _ = await fusion.retrieve(
            db, query=question, session_id=session.id, mode=mode, k=15
        )

        if not sources:
            return self._create_empty_version(
                db, section_plan, project, session, user,
                question, notes, language, style_guide_text, journal_style,
                "Недостаточно материала: в контексте проекта не найдено релевантных источников"
            )

        # 3. Итеративный цикл генерации
        max_iter = self._get_max_iterations()
        quality_thresholds = self._get_quality_thresholds()
        iteration = 0
        current_draft = None
        critique_feedback = ""
        final_generation: GenerationResult | None = None

        while iteration < max_iter:
            iteration += 1
            log.info(f"SectionAgent: iteration {iteration}/{self.max_iterations} for section '{section_plan.name}'")

            # Обновляем заметки с фидбеком от предыдущей итерации
            effective_notes = self._combine_notes(notes, critique_feedback)

            # Генерация черновика
            generation = await self._generate_draft(
                db=db,
                section_plan=section_plan,
                project=project,
                session=session,
                question=question,
                notes=effective_notes,
                sources=sources,
                language=language,
                word_target=word_target,
                style_guide_text=style_guide_text,
                journal_style=journal_style,
                kind=kind,
            )

            # Критика черновика
            critique = await self._critique_draft(
                section_plan=section_plan,
                project=project,
                generation=generation,
                sources=sources,
                question=question,
            )

            current_draft = generation
            final_generation = generation
            critique_feedback = critique.feedback

            if not critique.needs_revision:
                log.info(f"SectionAgent: quality gate passed on iteration {iteration}")
                break

            log.info(f"SectionAgent: revision needed, feedback: {critique.feedback[:100]}...")

        # 4. Финализация версии
        elapsed = time.perf_counter() - start_time
        version = self._save_version(
            db=db,
            section_plan=section_plan,
            project=project,
            session=session,
            user=user,
            generation=final_generation,
            generation_params=GenerationParams(
                question=question,
                notes=notes,
                style_guide_text=style_guide_text,
                journal_style=journal_style,
                sources_used=[{"index": s["index"], "dockey": s.get("dockey"), "title": s.get("title")} for s in sources],
                retrieval_mode=mode.value,
                evidence_k=15,
                max_sources=10,
                temperature=0.0,
                model="",
            ),
            quality_report=critique.quality_report,
            elapsed=elapsed,
        )

        return version

    # ------------------------------------------------------------------ private methods
    def _get_search_mode(self, project: Project) -> SearchMode:
        if project.status in {ProjectStatus.drafting, ProjectStatus.reviewing}:
            return SearchMode.project_focus
        return SearchMode.hybrid

    def _get_style_guide_text(self, db: Session, project: Project) -> str | None:
        if not project.style_guide_document_id:
            return None
        from app.db.models import Document
        from pathlib import Path
        document = db.get(Document, project.style_guide_document_id)
        if document is None:
            return None
        path = Path(document.path)
        if not path.is_file():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def _combine_notes(self, notes: str | None, feedback: str) -> str:
        parts = []
        if notes:
            parts.append(f"Указания автора:\n{notes}")
        if feedback:
            parts.append(f"Фидбек от самокритики (исправь в новой версии):\n{feedback}")
        return "\n\n".join(parts) if parts else ""

    async def _generate_draft(
        self,
        *,
        db: Session,
        section_plan: SectionPlan,
        project: Project,
        session: ResearchSession,
        question: str,
        notes: str | None,
        sources: list[dict[str, Any]],
        language: str,
        word_target: int,
        style_guide_text: str | None,
        journal_style: str | None,
        kind: GenerationKind = GenerationKind.section,
    ) -> GenerationResult:
        """Сгенерировать черновик раздела."""
        # Подготовка промпта: для особых видов — своя постановка.
        prompt = self._kind_prompt(
            db=db,
            section_plan=section_plan,
            project=project,
            question=question,
            notes=notes,
            sources=sources,
            language=language,
            word_target=word_target,
            journal_style=journal_style,
            kind=kind,
        )
        if prompt is None:
            prompt = build_prompt(
                section=section_plan.name,
                question=question,
                sources=sources,
                language=language,
                notes=notes,
                word_target=word_target,
                style=journal_style,
                require_citations=citations_required(section_plan.name),
            )

        # Добавляем style guide если есть
        if style_guide_text:
            prompt = f"{prompt}\n\nТРЕБОВАНИЯ ЖУРНАЛА (документ «Правила оформления»):\n{style_guide_text}"

        # Вызов LLM через PaperQA2Service с учётом стоимости
        service = self.registry.session_service(session.id)
        text, cost_info = await service.complete_with_cost(prompt, name=f"section_{section_plan.name}")

        # Валидация цитат
        check = validate_citations(text, len(sources), require_any=citations_required(section_plan.name))
        citation_map = build_citation_map(text, sources)

        # Сохраняем стоимость в generation для передачи в _save_version
        generation = GenerationResult(
            section=section_plan.name,
            content_md=text,
            sources=sources,
            citation_check=check,
            citation_map=citation_map,
            seconds=0.0,  # будет заполнено снаружи
        )
        generation.cost_info = cost_info
        return generation

    def _kind_prompt(
        self,
        *,
        db: Session,
        section_plan: SectionPlan,
        project: Project,
        question: str,
        notes: str | None,
        sources: list[dict[str, Any]],
        language: str,
        word_target: int,
        journal_style: str | None,
        kind: GenerationKind,
    ) -> str | None:
        """Промпт под вид генерации; None — обычный раздел.

        Постановки те же, что и в старом пути (`ProjectService._build_prompt`),
        чтобы вид из интерфейса и из API давали один и тот же результат.
        """
        style = journal_style
        name = section_plan.name

        if kind is GenerationKind.literature_review:
            return analyses.literature_review_prompt(
                question or name, sources,
                word_target=word_target or 1200, style=style, language=language)

        if kind is GenerationKind.data_comparison:
            summaries = self._data_summaries(db, project)
            return analyses.data_comparison_prompt(
                question or name, summaries, sources,
                word_target=word_target or 800, style=style, language=language)

        if kind is GenerationKind.discussion:
            # Обсуждение строится на уже написанном: без разделов Results и
            # Methods модели нечего сопоставлять с литературой.
            summaries = self._data_summaries(db, project)
            written = analyses.written_sections(project_sections(project))
            return analyses.discussion_prompt(
                question or name or "Обсуждение результатов",
                written, summaries, sources,
                word_target=word_target or 900, style=style, language=language)

        if kind is GenerationKind.gap_analysis:
            return analyses.gap_analysis_prompt(
                question or name, analyses.coverage_line(sources), sources,
                style=style, language=language)

        if kind is GenerationKind.report:
            return analyses.report_prompt(
                analyses.DEFAULT_REPORT_TEMPLATE, sources,
                question=question, style=style, language=language)

        if kind is GenerationKind.draft_analysis:
            # Сначала детерминированный разбор, модель добавляет комментарий.
            analysis = analyses.analyze_draft(project_sections(project))
            base = build_prompt(
                name, question, sources, language=language, notes=notes,
                word_target=word_target, style=style,
                require_citations=citations_required(name))
            commentary = (
                "На основе разбора выше напиши краткий комментарий: что исправить "
                "в первую очередь и почему. Ссылайся на источники [n]."
            )
            return f"{analyses.render_gaps(analysis)}\n\n{commentary}\n\n{base}"

        return None

    def _data_summaries(self, db: Session, project: Project) -> list[Any]:
        """Сводки по документам с ролью data, привязанным к проекту."""
        from sqlalchemy import select

        from app.db.models import Document, DocumentLink
        from app.services.data_extract import summarize_documents

        rows = db.execute(
            select(Document, DocumentLink.role)
            .join(DocumentLink, DocumentLink.document_id == Document.id)
            .where(DocumentLink.project_id == project.id)
            .order_by(Document.created_at)
        ).all()
        documents = [
            doc for doc, role in rows
            if getattr(role, "value", role) == ProjectDocRole.data.value
        ]
        if not documents:
            return []
        return summarize_documents(documents)

    async def _critique_draft(
        self,
        *,
        section_plan: SectionPlan,
        project: Project,
        generation: GenerationResult,
        sources: list[dict[str, Any]],
        question: str,
    ) -> CritiqueResult:
        """Самокритика черновика: проверка качества, grounding, completeness."""
        quality_report = QualityReport()

        # 1. Проверка цитат
        if generation.citation_check:
            quality_report.citations_ok = generation.citation_check.ok
            quality_report.dangling_citations = generation.citation_check.dangling
            quality_report.unused_sources = generation.citation_check.uncited_sources
            quality_report.warnings.extend(generation.citation_check.warnings)

        # 2. Grounding check (LLM-as-judge)
        grounding_score = await self._check_grounding(
            generation.content_md, sources, question
        )
        quality_report.grounding_score = grounding_score

        # 3. Completeness check
        completeness_score = await self._check_completeness(
            generation.content_md, question, section_plan.notes
        )
        quality_report.completeness_score = completeness_score

        # 4. Style compliance (базовая)
        style_compliance = self._check_style_compliance(
            generation.content_md, section_plan
        )
        quality_report.style_compliance = style_compliance

        # 5. Terminology consistency
        terminology = await self._check_terminology(
            generation.content_md, project
        )
        quality_report.terminology_consistency = terminology

        # Оценка прохождения quality gates
        thresholds = self._get_quality_thresholds()
        passed = (
            quality_report.citations_ok and
            (grounding_score or 1.0) >= thresholds["grounding"] and
            (completeness_score or 1.0) >= thresholds["completeness"]
        )
        quality_report.passed = passed

        # Формируем фидбек для следующей итерации
        feedback_parts = []
        if not quality_report.citations_ok:
            feedback_parts.append(f"Проблемы с цитатами: {quality_report.warnings}")
        if grounding_score is not None and grounding_score < thresholds["grounding"]:
            feedback_parts.append(f"Недостаточное обоснование (grounding={grounding_score:.2f}): укрепите утверждения ссылками на источники")
        if completeness_score is not None and completeness_score < thresholds["completeness"]:
            feedback_parts.append(f"Неполнота (completeness={completeness_score:.2f}): охватите все аспекты вопроса и указаний автора")

        feedback = "\n".join(feedback_parts) if feedback_parts else ""
        needs_revision = not passed and feedback != ""

        return CritiqueResult(
            quality_report=quality_report,
            feedback=feedback,
            needs_revision=needs_revision,
        )

    async def _check_grounding(
        self,
        content: str,
        sources: list[dict[str, Any]],
        question: str,
    ) -> float | None:
        """LLM-as-judge: насколько содержание обосновано источниками."""
        if not sources:
            return 0.0

        # Подготовка источников для промпта
        sources_text = "\n\n".join(
            f"[{s['index']}] {s.get('title', '')}: {s.get('text', '')[:500]}"
            for s in sources[:10]
        )

        prompt = f"""Оцените, насколько следующий текст раздела обоснован предоставленными источниками.

ВОПРОС РАЗДЕЛА: {question}

ИСТОЧНИКИ:
{sources_text}

ТЕКСТ РАЗДЕЛА:
{content[:3000]}

Задача: Для каждого утверждения в тексте проверьте, есть ли поддержка в источниках.
Верните JSON:
{{
  "score": 0.0-1.0,
  "issues": ["описание проблемных мест"]
}}

Только JSON, без лишнего текста."""

        try:
            service = self.registry.global_service()
            result = await service.complete(prompt, name="grounding_check")
            import json
            data = json.loads(result)
            return float(data.get("score", 0.0))
        except Exception as e:
            log.warning(f"Grounding check failed: {e}")
            return None

    async def _check_completeness(
        self,
        content: str,
        question: str,
        notes: str | None,
    ) -> float | None:
        """LLM-as-judge: насколько полно охвачен вопрос и указания."""
        prompt = f"""Оцените полноту покрытия вопроса и указаний автором в тексте раздела.

ВОПРОС: {question}
УКАЗАНИЯ АВТОРА: {notes or "нет"}

ТЕКСТ РАЗДЕЛА:
{content[:3000]}

Верните JSON:
{{
  "score": 0.0-1.0,
  "missing_aspects": ["что упущено"]
}}

Только JSON, без лишнего текста."""

        try:
            service = self.registry.global_service()
            result = await service.complete(prompt, name="completeness_check")
            import json
            data = json.loads(result)
            return float(data.get("score", 0.0))
        except Exception as e:
            log.warning(f"Completeness check failed: {e}")
            return None

    def _check_style_compliance(
        self,
        content: str,
        section_plan: SectionPlan,
    ) -> dict[str, bool]:
        """Базовая проверка соответствия стилю."""
        checks = {}
        checks["has_heading"] = content.strip().startswith("#")
        checks["word_count_ok"] = section_plan.word_min <= len(content.split()) <= section_plan.word_max
        checks["has_citations"] = "[" in content and "]" in content
        return checks

    async def _check_terminology(
        self,
        content: str,
        project: Project,
    ) -> dict[str, str]:
        """Проверка согласованности терминологии с глоссарием проекта."""
        if not project.glossary:
            return {}

        # Простая проверка: есть ли термины из глоссария в тексте
        found = {}
        for entry in project.glossary:
            term = entry.term
            if term.lower() in content.lower():
                translations = entry.translations
                project_lang = project.language
                if project_lang in translations:
                    found[term] = translations[project_lang]
        return found

    def _create_empty_version(
        self,
        db: Session,
        section_plan: SectionPlan,
        project: Project,
        session: ResearchSession,
        user: User,
        question: str,
        notes: str | None,
        language: str,
        style_guide_text: str | None,
        journal_style: str | None,
        content: str,
    ) -> SectionVersion:
        """Создать версию с сообщением об отсутствии материалов."""
        version = SectionVersion(
            id=new_id(),
            section_plan_id=section_plan.id,
            project_id=project.id,
            session_id=session.id,
            content_md=content,
            language=language,
            word_count=len(content.split()),
            citation_map=[],
            generation_params=GenerationParams(
                question=question,
                notes=notes,
                style_guide_text=style_guide_text,
                journal_style=journal_style,
            ).to_dict(),
            quality_report=QualityReport(
                citations_ok=True,
                warnings=["Нет источников для генерации"],
                passed=False,
            ).to_dict(),
            status=VersionStatus.draft,
            created_by=user.id,
        )
        db.add(version)
        db.flush()
        section_plan.current_version_id = version.id
        section_plan.status = SectionStatus.pending
        db.commit()
        return version

    def _save_version(
        self,
        db: Session,
        *,
        section_plan: SectionPlan,
        project: Project,
        session: ResearchSession,
        user: User,
        generation: GenerationResult,
        generation_params: GenerationParams,
        quality_report: QualityReport,
        elapsed: float,
    ) -> SectionVersion:
        """Сохранить финальную версию раздела."""
        # Деактивируем предыдущую версию если есть
        if section_plan.current_version_id:
            old_version = db.get(SectionVersion, section_plan.current_version_id)
            if old_version:
                old_version.status = VersionStatus.superseded

        # Извлекаем стоимость из generation если есть
        cost_info = getattr(generation, "cost_info", {}) or {}

        version = SectionVersion(
            id=new_id(),
            section_plan_id=section_plan.id,
            project_id=project.id,
            session_id=session.id,
            content_md=generation.content_md,
            language=section_plan.language or project.language,
            word_count=generation.word_count,
            citation_map=generation.citation_map,
            generation_params=generation_params.to_dict(),
            seconds=elapsed,
            cost_usd=cost_info.get("cost_usd"),
            token_counts={
                "prompt_tokens": cost_info.get("prompt_tokens", 0),
                "completion_tokens": cost_info.get("completion_tokens", 0),
                "cache_read_tokens": cost_info.get("cache_read_tokens", 0),
                "cache_creation_tokens": cost_info.get("cache_creation_tokens", 0),
                "model": cost_info.get("model", ""),
            },
            quality_report=quality_report.to_dict(),
            status=VersionStatus.draft,
            created_by=user.id,
        )
        db.add(version)
        # created_at проставляется при вставке — до flush он ещё None,
        # и план получил бы updated_at = NULL (колонка NOT NULL).
        db.flush()

        # Обновляем план раздела
        section_plan.current_version_id = version.id
        section_plan.status = SectionStatus.review
        section_plan.updated_at = version.created_at

        # Синхронизируем с старым JSON в проекте (для обратной совместимости)
        self._sync_to_project_json(project, section_plan, generation.content_md)

        db.commit()
        return version

    def _sync_to_project_json(
        self,
        project: Project,
        section_plan: SectionPlan,
        content_md: str,
    ) -> None:
        """Синхронизация с Project.sections JSON для обратной совместимости.

        Словари копируем: JSON-колонка отслеживает изменение по значению,
        и правка «на месте» не была бы замечена — текст не сохранился бы.
        """
        sections: list[dict[str, Any]] = []
        found = False
        for raw in project.sections or []:
            item = dict(raw)
            if item.get("name", "").lower() == section_plan.name.lower():
                item["content_md"] = content_md
                found = True
            sections.append(item)
        if not found:
            sections.append({
                "name": section_plan.name,
                "required": section_plan.required,
                "order": section_plan.order,
                "word_target": section_plan.word_target,
                "notes": section_plan.notes,
                "content_md": content_md,
            })
        project.sections = sections
        project.updated_at = section_plan.updated_at or datetime.utcnow()


# --------------------------------------------------------------------------- Translation
class SectionTranslator:
    """Перевод разделов с сохранением цитат, формул, терминологии."""

    def __init__(self, registry: ServiceRegistry | None = None) -> None:
        self.registry = registry or get_registry()

    async def translate(
        self,
        db: Session,
        *,
        version: SectionVersion,
        target_language: str,
        project: Project,
        user: User,
    ) -> SectionVersion:
        """Перевести версию раздела на целевой язык."""
        if version.language == target_language:
            raise ValueError("Язык версии уже совпадает с целевым")

        # Проверка разрешенных языков
        policy = project.language_policy
        if policy and target_language not in (policy.allowed_languages or []):
            raise ValueError(f"Язык {target_language} не разрешен для проекта")

        # Глоссарий проекта
        glossary = {entry.term: entry.translations.get(target_language, entry.term) for entry in project.glossary}

        # Промпт перевода
        prompt = self._build_translation_prompt(
            content=version.content_md,
            source_language=version.language,
            target_language=target_language,
            glossary=glossary,
        )

        service = self.registry.session_service(version.session_id)
        translated_text, cost_info = await service.complete_with_cost(prompt, name="translate_section")

        # Создаем новую версию-перевод
        new_version = SectionVersion(
            id=new_id(),
            section_plan_id=version.section_plan_id,
            project_id=version.project_id,
            session_id=version.session_id,
            content_md=translated_text,
            language=target_language,
            source_language=version.language,
            word_count=len(translated_text.split()),
            citation_map=version.citation_map,  # цитаты сохраняем как есть
            generation_params={
                **version.generation_params,
                "translated_from": version.id,
                "translation_target": target_language,
            },
            seconds=0.0,
            cost_usd=cost_info.get("cost_usd"),
            token_counts={
                "prompt_tokens": cost_info.get("prompt_tokens", 0),
                "completion_tokens": cost_info.get("completion_tokens", 0),
                "cache_read_tokens": cost_info.get("cache_read_tokens", 0),
                "cache_creation_tokens": cost_info.get("cache_creation_tokens", 0),
                "model": cost_info.get("model", ""),
            },
            quality_report=version.quality_report,
            status=VersionStatus.draft,
            parent_version_id=version.id,
            created_by=user.id,
        )
        db.add(new_version)
        db.commit()
        # Перевод становится текущей версией раздела: compile_manuscript берёт
        # material из plan.current_version_id, поэтому без этого переведённый
        # текст до approve не попал бы в сборку.
        plan = self.db.get(SectionPlan, version.section_plan_id)
        if plan is not None:
            plan.current_version_id = new_version.id
            plan.status = SectionStatus.review
            db.commit()
        return new_version

    def _build_translation_prompt(
        self,
        *,
        content: str,
        source_language: str,
        target_language: str,
        glossary: dict[str, str],
    ) -> str:
        lang_names = {"ru": "русский", "en": "английский"}
        src = lang_names.get(source_language, source_language)
        tgt = lang_names.get(target_language, target_language)

        glossary_text = "\n".join(f"- {k} → {v}" for k, v in glossary.items()) if glossary else "нет"

        return f"""Переведите следующий раздел научной статьи с {src} на {tgt}.

СТРОГИЕ ПРАВИЛА:
1. СОХРАНЯЙТЕ БЕЗ ИЗМЕНЕНИЙ: маркеры цитат [1], [2,3], [1-3]; структуру markdown (заголовки, списки, таблицы); 
   математические формулы ($...$, $$...$$); имена собственные (географические названия, приборы, методы, 
   аббревиатуры, химические формулы, генетические символы).
2. ПЕРЕВОДИТЕ: только естественно-языковой текст, сохраняя формальный научный стиль.
3. ТЕРМИНОЛОГИЯ: используйте предоставленный глоссарий; термины, отсутствующие в глоссарии, переводите 
   стандартными для предметной области эквивалентами.
4. НЕТ ТВОРЧЕСКОЙ АДАПТАЦИИ — дословный, но плавный перевод.

ГЛОССАРИЙ:
{glossary_text}

ТЕКСТ ДЛЯ ПЕРЕВОДА:
{content}

ПЕРЕВОД:"""