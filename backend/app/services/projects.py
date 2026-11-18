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
from pathlib import Path
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
    SectionKind,
    SectionPlan,
    SectionStatus,
    SectionVersion,
    User,
    VersionStatus,
    new_id,
)
from app.services import analyses
from app.services.generation import (
    GenerationResult,
    build_citation_map,
    build_prompt,
    citations_required,
    normalize_sections,
    progress,
    validate_citations,
)
from app.services.history import HistoryService
from app.services.journal_styles import style_prompt
from app.services.pqa_registry import ServiceRegistry, get_registry
from app.services.project_sections import project_sections
from app.services.rag_service import RagFusionService
from app.services.section_agent import SectionAgent, SectionTranslator

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


def _plan_kind(kind: GenerationKind) -> SectionKind:
    """Вид генерации → тип плана раздела.

    У плана свой набор типов (SectionKind), у генерации — свой
    (GenerationKind). Обзор литературы и обсуждение — те же понятия,
    сверка с данными — это раздел про данные, остальное — обычный раздел.
    """
    if kind is GenerationKind.literature_review:
        return SectionKind.literature_review
    if kind is GenerationKind.discussion:
        return SectionKind.discussion
    if kind is GenerationKind.data_comparison:
        return SectionKind.data
    return SectionKind.standard


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
    # Язык генерации (ru | en). Если не передан — берётся из project.language.
    language: str | None = None
    # Вид генерации; по умолчанию обычный раздел.
    kind: GenerationKind = GenerationKind.section


class ProjectService:
    def __init__(self, registry: ServiceRegistry | None = None) -> None:
        self.registry = registry or get_registry()

    # ------------------------------------------------------------------ генерация (старая API, для совместимости)
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

        # Язык разрешаем один раз, здесь. Дальше он участвует и в промпте,
        # и в ключе кэша; если оставить в кэше «как просили» (None), а в
        # версии «как вышло» ('ru'), то кэш не срабатывал никогда: тот же
        # вопрос и тот же раздел давали новый ответ вместо прошлого.
        request.language = request.language or project.language
        self._question = request.question
        self._language = request.language

        # План разделов — источник истины: перед генерацией приводим его
        # в соответствие со старой моделью, иначе в плане окажется один
        # раздел вместо всех.
        self.ensure_section_plans(db, project)

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

        # Методы и собственные результаты ссылкой не обязаны: там описывается
        # работа авторов, а не факты о других публикациях.
        check = validate_citations(
            text, len(sources),
            require_any=citations_required(request.section or ""))
        citation_map = build_citation_map(text, sources)

        analysis_payload = None
        if kind is GenerationKind.draft_analysis:
            # Детерминированный разбор считаем сами, модель лишь комментирует.
            analysis_payload = analyses.analyze_draft(
                project_sections(project)).to_dict()

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
        language = request.language or project.language
        self._language = language
        notes = request.notes or self._section_notes(project, request.section)

        # Документ-правила оформления журнала добавляем как дополнительные указания
        # автору — это приоритетнее общего стиля журнала (target_journal),
        # так как это конкретные требования конкретного журнала.
        style_guide = self._style_guide_text(project, db)
        if style_guide:
            notes = (notes + "\n\n" if notes else "") + (
                f"ТРЕБОВАНИЯ ЖУРНАЛА (документ «Правила оформления»):\n{style_guide}"
            )

        # Стиль журнала достаётся из поля проекта: пользователь выбрал его
        # один раз при создании, и дальше он действует во всех видах генерации
        # — от обычного раздела до обсуждения. Шаблон подбирается под раздел:
        # у группы журналов их несколько, и для «Methods» нужен свой.
        style = style_prompt(project.target_journal, request.section)
        require_citations = citations_required(request.section or "")

        if request.kind is GenerationKind.literature_review:
            return analyses.literature_review_prompt(
                request.question or request.section, sources,
                word_target=request.word_target or 1200, style=style,
                language=language)

        if request.kind is GenerationKind.data_comparison:
            summaries = self._data_summaries(project, db, request.data_document_ids)
            return analyses.data_comparison_prompt(
                request.question or request.section, summaries, sources,
                word_target=request.word_target or 800, style=style,
                language=language)

        if request.kind is GenerationKind.discussion:
            # Обсуждение строится на уже написанном: без разделов Results и
            # Methods модели нечего сопоставлять с литературой.
            summaries = self._data_summaries(project, db, request.data_document_ids)
            written = analyses.written_sections(project_sections(project))
            return analyses.discussion_prompt(
                request.question or request.section or "Обсуждение результатов",
                written, summaries, sources,
                word_target=request.word_target or 900, style=style,
                language=language)

        if request.kind is GenerationKind.gap_analysis:
            return analyses.gap_analysis_prompt(
                request.question or request.section,
                analyses.coverage_line(sources), sources, style=style,
                language=language)

        if request.kind is GenerationKind.report:
            template = request.template_md or analyses.DEFAULT_REPORT_TEMPLATE
            return analyses.report_prompt(template, sources,
                                          question=request.question,
                                          style=style,
                                          language=language)

        if request.kind is GenerationKind.draft_analysis:
            # Сначала детерминированный разбор, модель добавляет комментарий.
            sections = project_sections(project)
            analysis = analyses.analyze_draft(sections)
            base = build_prompt(
                request.section or "Обзор черновика", request.question, sources,
                language=language, notes=notes, word_target=request.word_target,
                style=style, require_citations=require_citations)
            commentary = (
                "На основе разбора выше напиши краткий комментарий: что исправить "
                "в первую очередь и почему. Ссылайся на источники [n]."
            )
            return (f"{analyses.render_gaps(analysis)}\n\n{commentary}\n\n{base}")

        return build_prompt(
            request.section, request.question, sources, language=language,
            notes=notes, word_target=request.word_target, style=style,
            require_citations=require_citations,
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
        for item in project_sections(project):
            if item["name"].lower() == section.lower():
                return item.get("notes") or None
        return None

    def _style_guide_text(self, project: Project, db: Session) -> str | None:
        """Текст документа «Правила оформления» журнала, привязанного к проекту.

        Читаем файл с диска по пути, сохранённому в модели Document.
        Если документа нет или файл исчез — возвращаем None (не блокируем
        генерацию).
        """
        if not project.style_guide_document_id:
            return None
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

    # ------------------------------------------------------------------ версии (старая система)
    _question: str = ""
    _language: str = ""

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
            seconds=generation.seconds,
            stats={"citations_ok": generation.ok,
                   "sources": len(generation.sources),
                   "seconds": round(generation.seconds, 2)},
            created_by=user.id,
        )
        db.add(version)
        self._write_into_plan(project, generation)
        # Та же правка — в новую модель: она источник истины (прогресс,
        # выгрузка и интерфейс читают её), старый JSON — зеркало.
        self.apply_manual_section_text(
            db, project, generation.section, generation.content_md,
            citation_map=generation.citation_map, source="generate",
        )
        version.stats = {**(version.stats or {}), "question": self._question,
                          "language": self._language}
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
        """Последняя версия этого раздела с тем же вопросом (хранится в stats).

        Ключ кэша — раздел + вопрос + язык + вид генерации. Вид обязателен:
        у разных видов разный промпт, и ответ «обсуждения» нельзя отдавать
        как «раздел».
        """
        stmt = (
            select(ProjectVersion)
            .where(ProjectVersion.project_id == project_id,
                   ProjectVersion.section_name == request.section)
            .order_by(ProjectVersion.created_at.desc())
            .limit(1)
        )
        for version in db.scalars(stmt):
            stats = version.stats or {}
            if (stats.get("question") == request.question
                    and stats.get("language") == request.language
                    and version.kind == request.kind):
                return version
        return None

    # ------------------------------------------------------------------ SectionPlan / SectionVersion (новая система)
    def get_or_create_section_plan(
        self,
        db: Session,
        project: Project,
        section_name: str,
        *,
        kind: SectionKind = SectionKind.standard,
        order: int | None = None,
        word_target: int | None = None,
        notes: str = "",
        language: str | None = None,
        required: bool = True,
        depends_on: list[str] | None = None,
    ) -> SectionPlan:
        """Получить или создать план раздела."""
        # Поиск существующего
        for plan in project.section_plans:
            if plan.name.lower() == section_name.lower():
                return plan

        # Определение порядка
        if order is None:
            order = len(project.section_plans) + 1

        plan = SectionPlan(
            id=new_id(),
            project_id=project.id,
            name=section_name,
            kind=kind,
            order=order,
            required=required,
            word_target=word_target or 500,
            word_min=max(100, (word_target or 500) // 2),
            word_max=(word_target or 500) * 4,
            notes=notes,
            language=language or project.language,
            depends_on=depends_on or [],
            status=SectionStatus.pending,
        )
        db.add(plan)
        db.commit()
        return plan

    def sync_project_sections_to_plans(self, db: Session, project: Project) -> list[SectionPlan]:
        """Синхронизировать старый JSON project.sections в новые SectionPlan.

        Перенос односторонний: старая модель — зеркало, новая — источник
        истины. Поэтому у раздела, у которого уже есть текущая версия,
        текст не трогаем: правки и генерации живут в новой модели, и
        затирать их старым JSON нельзя.

        Скрипт идемпотентен: повторный запуск ничего не меняет и не плодит
        версии.
        """
        plans = []
        for idx, section in enumerate(normalize_sections(project.sections)):
            plan = self.get_or_create_section_plan(
                db, project, section["name"],
                kind=SectionKind.standard,
                order=section.get("order", idx + 1),
                word_target=section.get("word_target", 500),
                notes=section.get("notes", ""),
                required=section.get("required", True),
                language=section.get("language", project.language),
            )
            # Текст переносим только если у плана ещё нет версии.
            content = section.get("content_md", "")
            if content.strip() and not plan.current_version_id:
                version = SectionVersion(
                    id=new_id(),
                    section_plan_id=plan.id,
                    project_id=project.id,
                    content_md=content,
                    language=plan.language,
                    word_count=len(content.split()),
                    citation_map=[],
                    generation_params={"source": "migration"},
                    quality_report={},
                    # Текст из старой модели — написанный и законченный,
                    # поэтому версия одобрена (манускрипт берёт одобренные).
                    status=VersionStatus.approved,
                )
                db.add(version)
                db.flush()
                plan.current_version_id = version.id
                plan.status = SectionStatus.approved
            plans.append(plan)
        db.commit()
        return plans

    def ensure_section_plans(self, db: Session, project: Project) -> None:
        """Дополнить план разделов недостающими разделами старой модели.

        Планы — источник истины, но проект мог получить их раньше, чем
        переехал на новую модель: тогда в плане один раздел, а в старой
        модели — все. Синхронизация дополняет план разделами и не трогает
        тексты: они живут в версиях.
        """
        legacy_count = len(normalize_sections(project.sections))
        if len(project.section_plans or []) >= legacy_count:
            return
        self.sync_project_sections_to_plans(db, project)
        db.refresh(project)

    def apply_manual_section_text(
        self,
        db: Session,
        project: Project,
        section_name: str,
        content_md: str,
        *,
        citation_map: list[dict[str, Any]] | None = None,
        source: str = "manual",
    ) -> SectionVersion | None:
        """Сохранить правку раздела в новую модель (SectionPlan + SectionVersion).

        Новая модель — источник истины; старая (`project.sections`) — её
        зеркало. Правка обновляет текущую версию на месте, если та черновик,
        иначе создаёт новую версию с родителем.

        `citation_map` и `source` — для генерации: ссылок в тексте без
        карты источников выгрузка не соберёт список литературы.
        """
        # План должен покрывать все разделы проекта, иначе раздел,
        # который ещё не правили, исчезнет из прогресса и выгрузки.
        self.ensure_section_plans(db, project)
        plan: SectionPlan | None = None
        for candidate in project.section_plans:
            if candidate.name.lower() == section_name.lower():
                plan = candidate
                break
        if plan is None:
            plan = self.get_or_create_section_plan(db, project, section_name)

        version = (
            db.get(SectionVersion, plan.current_version_id)
            if plan.current_version_id
            else None
        )
        word_count = len((content_md or "").split())

        if version is not None and version.status == VersionStatus.draft:
            version.content_md = content_md
            version.word_count = word_count
        else:
            version = SectionVersion(
                section_plan_id=plan.id,
                project_id=project.id,
                session_id=project.session_id,
                content_md=content_md,
                language=plan.language,
                word_count=word_count,
                citation_map=list(citation_map or []),
                generation_params={"source": source},
                quality_report={},
                status=VersionStatus.draft,
                parent_version_id=plan.current_version_id,
            )
            db.add(version)
            # id присваивается на вставке — до flush он ещё None, и плану
            # не на что было бы сослаться как на текущую версию.
            db.flush()

        plan.current_version_id = version.id
        plan.status = SectionStatus.review

        # Зеркалим в старую модель: её читают прогресс проекта и выгрузка.
        # Раздел мог появиться только в новой модели — тогда добавляем его.
        #
        # Словари копируем: JSON-колонка отслеживает изменение по значению,
        # и правка «на месте» не была бы замечена — текст не сохранился бы.
        sections: list[dict[str, Any]] = []
        found = False
        for raw in project.sections or []:
            item = dict(raw)
            if item.get("name", "").lower() == section_name.lower():
                item["content_md"] = content_md
                found = True
            sections.append(item)
        if not found:
            sections.append({
                "name": plan.name,
                "required": plan.required,
                "order": plan.order,
                "word_target": plan.word_target,
                "notes": plan.notes,
                "content_md": content_md,
            })
        project.sections = sections

        db.flush()
        return version

    async def generate_section_v2(
        self,
        db: Session,
        *,
        project: Project,
        session: ResearchSession,
        user: User,
        section_name: str,
        question: str,
        notes: str | None = None,
        word_target: int | None = None,
        use_cache: bool = True,
        kind: GenerationKind = GenerationKind.section,
    ) -> SectionVersion:
        """Новая генерация раздела через SectionAgent.

        `kind` — вид генерации: обычный раздел, обзор литературы, сверка
        с данными, обсуждение, пробелы, отчёт, разбор черновика. Вид влияет
        на промпт (его собирает агент) и на тип плана раздела.
        """
        if session.status.value not in {"active", "paused"}:
            from app.core.errors import ConflictError
            raise ConflictError("Сессия архивирована — генерация недоступна")

        # План разделов — источник истины: сначала дополняем его
        # недостающими разделами старой модели.
        self.ensure_section_plans(db, project)

        # Получаем или создаем план раздела
        plan = self.get_or_create_section_plan(
            db, project, section_name,
            kind=_plan_kind(kind),
            word_target=word_target,
            notes=notes,
        )

        # Особый вид уточняет тип раздела: «обсуждение» — это discussion.
        if kind is not GenerationKind.section:
            plan.kind = _plan_kind(kind)

        # Запускаем агента (передаём проект для динамических порогов качества)
        agent = SectionAgent(registry=self.registry, project=project)
        version = await agent.generate(
            db=db,
            section_plan=plan,
            project=project,
            session=session,
            user=user,
            question=question,
            notes=notes,
            word_target=word_target,
            use_cache=use_cache,
            kind=kind,
        )
        return version

    async def translate_section(
        self,
        db: Session,
        *,
        project: Project,
        section_plan_id: str,
        target_language: str,
        user: User,
        version_id: str | None = None,
    ) -> SectionVersion:
        """Перевести раздел на целевой язык."""
        translator = SectionTranslator(registry=self.registry)

        # Определяем версию для перевода
        if version_id:
            version = db.get(SectionVersion, version_id)
        else:
            plan = db.get(SectionPlan, section_plan_id)
            if not plan or not plan.current_version_id:
                raise ValueError("Нет версии для перевода")
            version = db.get(SectionVersion, plan.current_version_id)

        if not version:
            raise ValueError("Версия не найдена")

        return await translator.translate(
            db=db,
            version=version,
            target_language=target_language,
            project=project,
            user=user,
        )

    def get_section_history(self, db: Session, section_plan_id: str):
        """Получить историю версий раздела (дерево)."""
        history = HistoryService(db)
        return history.get_version_tree(section_plan_id)

    def diff_section_versions(
        self,
        db: Session,
        from_version_id: str,
        to_version_id: str,
    ):
        """Сравнить две версии раздела."""
        history = HistoryService(db)
        return history.diff_versions(from_version_id, to_version_id)

    def rollback_section(
        self,
        db: Session,
        section_plan_id: str,
        version_id: str,
        user: User,
    ) -> SectionVersion:
        """Откатить раздел к указанной версии."""
        history = HistoryService(db)
        return history.rollback(section_plan_id, version_id, user)

    def approve_section_version(
        self,
        db: Session,
        section_plan_id: str,
        version_id: str,
        user: User,
    ) -> SectionVersion:
        """Одобрить версию раздела."""
        history = HistoryService(db)
        return history.approve_version(section_plan_id, version_id, user)

    # ------------------------------------------------------------------ Batch operations
    async def regenerate_outdated_sections(
        self,
        db: Session,
        *,
        project: Project,
        session: ResearchSession,
        user: User,
        force: bool = False,
    ) -> dict[str, Any]:
        """Перегенерировать все разделы, у которых устарели источники или нет контента.

        Раздел считается устаревшим, если:
        - нет контента (пустой)
        - force=True
        - у раздела есть depends_on и зависимости обновились

        Возвращает отчёт о перегенерации.
        """
        if session.status.value not in {"active", "paused"}:
            from app.core.errors import ConflictError
            raise ConflictError("Сессия архивирована — генерация недоступна")

        # Синхронизируем планы если нужно
        plans = project.section_plans
        if not plans:
            self.sync_project_sections_to_plans(db, project)
            db.refresh(project)
            plans = project.section_plans

        agent = SectionAgent(registry=self.registry, project=project)
        results = {
            "total": len(plans),
            "regenerated": [],
            "skipped": [],
            "failed": [],
        }

        for plan in plans:
            # Проверяем нужно ли перегенерировать
            current_version = plan.current_version_id
            needs_regen = force or not current_version

            # Если есть зависимые разделы, проверяем их версии
            if not needs_regen:
                for dep_id in plan.depends_on:
                    dep_plan = db.get(SectionPlan, dep_id)
                    if dep_plan and dep_plan.current_version_id != current_version:
                        needs_regen = True
                        break

            if not needs_regen:
                results["skipped"].append({"section": plan.name, "reason": "up to date"})
                continue

            try:
                # Генерируем вопрос на основе названия раздела и заметок
                question = f"Напиши раздел '{plan.name}' научной статьи."
                if plan.notes:
                    question += f" Указания: {plan.notes}"

                version = await agent.generate(
                    db=db,
                    section_plan=plan,
                    project=project,
                    session=session,
                    user=user,
                    question=question,
                    notes=plan.notes,
                    word_target=plan.word_target,
                    use_cache=False,  # принудительно перегенерируем
                )
                results["regenerated"].append({
                    "section": plan.name,
                    "version_id": version.id,
                    "word_count": version.word_count,
                })
            except Exception as e:
                log.exception(f"Batch regen failed for section {plan.name}")
                results["failed"].append({"section": plan.name, "error": str(e)})

        return results

    def _compile_manuscript_legacy(
        self, project: Project, language: str | None = None,
    ) -> dict[str, Any]:
        """Манускрипт из старой модели — для проектов без планов.

        Истории версий у такой статьи нет, поэтому разделы берутся как есть,
        а список литературы остаётся пустым.
        """
        sections_output: list[dict[str, Any]] = []
        warnings: list[str] = []
        total_words = 0
        for item in project_sections(project):
            content = item.get("content_md") or ""
            if not content.strip():
                warnings.append(f"Раздел '{item['name']}': нет текста")
                continue
            words = len(content.split())
            sections_output.append({
                "name": item["name"],
                "kind": "standard",
                "content": content,
                "word_count": words,
            })
            total_words += words
        return {
            "full_text": "\n\n".join(s["content"] for s in sections_output),
            "sections": sections_output,
            "bibliography": [],
            "stats": {
                "total_words": total_words,
                "sections_count": len(sections_output),
                "sources_count": 0,
                "language": language or project.language,
            },
            "warnings": warnings,
        }

    def compile_manuscript(
        self,
        db: Session,
        project: Project,
        *,
        language: str | None = None,
        include_unapproved: bool = False,
    ) -> dict[str, Any]:
        """Собрать полный манускрипт из одобренных версий разделов.

        Возвращает:
        - full_text: объединённый markdown
        - bibliography: единый список литературы без дублей
        - stats: общее количество слов, разделов, источников
        - warnings: разделы без контента или не одобренные

        GET не пишет в базу: если планов ещё нет (проект до перехода),
        манускрипт собирается из старой модели. Перенос делает явный
        POST /section-plans/sync или скрипт миграции.
        """
        plans = project.section_plans
        if not plans:
            return self._compile_manuscript_legacy(project, language)

        target_lang = language or project.language
        sections_output = []
        all_citations = {}  # index -> citation_info
        warnings = []
        total_words = 0

        for plan in sorted(plans, key=lambda p: p.order):
            if not plan.current_version_id:
                warnings.append(f"Раздел '{plan.name}': нет версии")
                continue

            version = db.get(SectionVersion, plan.current_version_id)
            if not version:
                warnings.append(f"Раздел '{plan.name}': версия не найдена")
                continue

            if version.status != VersionStatus.approved and not include_unapproved:
                warnings.append(f"Раздел '{plan.name}': не одобрен (статус {version.status.value})")
                if not include_unapproved:
                    continue

            # Используем версию на целевом языке если есть, иначе оригинал
            content = version.content_md
            if target_lang != version.language:
                # Ищем перевод
                for v in plan.versions:
                    if v.language == target_lang and v.parent_version_id == version.id:
                        content = v.content_md
                        break
                else:
                    warnings.append(f"Раздел '{plan.name}': нет перевода на {target_lang}, используется {version.language}")

            sections_output.append({
                "name": plan.name,
                "kind": plan.kind.value,
                "content": content,
                "word_count": len(content.split()),
            })
            total_words += len(content.split())

            # Собираем цитаты (пересчитываем индексы для единого списка)
            for cite in version.citation_map:
                idx = cite.get("index")
                if idx and idx not in all_citations:
                    all_citations[idx] = cite

        # Пересчитываем индексы цитаций в тексте для единого списка
        # (упрощённо: оставляем как есть, bibliography будет по порядку появления)
        bibliography = []
        for idx in sorted(all_citations.keys()):
            cite = all_citations[idx]
            bibliography.append({
                "index": idx,
                "title": cite.get("title"),
                "citation": cite.get("citation"),
                "dockey": cite.get("dockey"),
            })

        full_text = "\n\n".join(s["content"] for s in sections_output)

        return {
            "full_text": full_text,
            "sections": sections_output,
            "bibliography": bibliography,
            "stats": {
                "total_words": total_words,
                "sections_count": len(sections_output),
                "sources_count": len(bibliography),
                "language": target_lang,
            },
            "warnings": warnings,
        }

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
        # Прогресс считаем по новой модели: она — источник истины.
        return progress(project_sections(project))


__all__ = [
    "NO_MATERIAL_TEXT",
    "GenerationRequest",
    "ProjectDocRole",
    "ProjectService",
    "ProjectStatus",
    "find_project",
    "linked_documents",
]