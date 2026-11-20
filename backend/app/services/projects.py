"""Сервис работы с разделами статей: планы, версии, перевод и сборка.

Связывает RAG-контекст и LLM-генерацию через SectionAgent:

    план -> генерация агентом -> проверка цитат -> версия в БД

Планы разделов (`section_plans`) и их версии (`section_versions`) —
единственный источник истины о тексте статьи.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.db.models import (
    Document,
    DocumentLink,
    GenerationKind,
    Project,
    ResearchSession,
    SectionKind,
    SectionPlan,
    SectionStatus,
    SectionVersion,
    User,
    VersionStatus,
    new_id,
)
from app.services.generation import normalize_sections, progress
from app.services.history import HistoryService
from app.services.pqa_registry import ServiceRegistry, get_registry
from app.services.project_sections import project_sections
from app.services.section_agent import SectionAgent, SectionTranslator

log = logging.getLogger("boasi.services.projects")

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


class ProjectService:
    def __init__(self, registry: ServiceRegistry | None = None) -> None:
        self.registry = registry or get_registry()

    def set_section_plans(
        self,
        db: Session,
        project: Project,
        sections: list[dict[str, Any]] | None = None,
    ) -> list[SectionPlan]:
        """Создать или обновить план разделов по списку разделов проекта.

        Вызывается при создании проекта (стартовый план) и когда пользователь
        явно меняет состав разделов. Существующие планы не удаляются: их
        версии и история должны сохраняться.
        """
        plans: list[SectionPlan] = []
        for item in normalize_sections(sections):
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            plan = next(
                (p for p in project.section_plans
                 if p.name.lower() == name.lower()),
                None,
            )
            word_target = int(item.get("word_target") or 500)
            if plan is None:
                plan = SectionPlan(
                    id=new_id(),
                    project_id=project.id,
                    name=name,
                    kind=SectionKind.standard,
                    language=project.language,
                    status=SectionStatus.pending,
                )
                db.add(plan)
                project.section_plans.append(plan)
            plan.order = int(item.get("order") or (len(plans) + 1))
            plan.required = bool(item.get("required", True))
            plan.word_target = word_target
            plan.word_min = max(100, word_target // 2)
            plan.word_max = word_target * 4
            plan.notes = str(item.get("notes") or "")
            plan.depends_on = list(item.get("depends_on") or [])
            plans.append(plan)
        db.commit()
        return plans

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
        """Сохранить правку раздела как версию плана (SectionPlan + SectionVersion).

        Правка обновляет текущую версию на месте, если та черновик, иначе
        создаёт новую версию с родителем.

        `citation_map` и `source` — для генерации: ссылок в тексте без
        карты источников выгрузка не соберёт список литературы.
        """
        # План должен покрывать все разделы проекта, иначе раздел,
        # который ещё не правили, исчезнет из прогресса и выгрузки.
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
        """Генерация раздела через SectionAgent.

        `kind` — вид генерации: обычный раздел, обзор литературы, сверка
        с данными, обсуждение, пробелы, отчёт, разбор черновика. Вид влияет
        на промпт (его собирает агент) и на тип плана раздела.
        """
        if session.status.value not in {"active", "paused"}:
            from app.core.errors import ConflictError
            raise ConflictError("Сессия архивирована — генерация недоступна")

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

        GET не пишет в базу: если планов ещё нет, возвращается пустой
        манускрипт с предупреждением.
        """
        plans = project.section_plans

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
    "ProjectService",
    "find_project",
    "linked_documents",
]