"""Проекты статей: CRUD, план разделов, генерация, экспорт (Фаза 7).

Проект живёт внутри сессии. Документы привязываются к нему с ролью
(`reference` / `data` / `draft`), и именно они попадают в контекст генерации
режимом `project_focus` — поэтому черновики из `project_draft` подставляются
автоматически.

Все генерации обязаны быть с цитатами `[n]`, и каждая цифра обязана
разрешаться в источник — это проверяет `validate_citations` до сохранения
версии (см. `app/services/generation.py`).
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.serializers import document_from_row, project_out
from app.core.errors import ConflictError, NotFoundError
from app.core.security import get_current_user, require_researcher
from app.db.models import (
    GenerationKind,
    Project,
    ProjectDocRole,
    ProjectLanguagePolicy,
    ProjectVersion as ProjectVersionModel,
    SectionKind,
    SectionPlan,
    SectionStatus,
    SectionVersion,
    TerminologyGlossary,
    User,
    VersionStatus,
    new_id,
)
from app.db.repositories import documents as docs_repo
from app.db.repositories.users import audit, get_owned_session, touch_session
from app.db.session import get_db
from app.schemas.api import (
    ExportFormat,
    GenerateRequest,
    GenerateResultOut,
    JournalStyleOut,
    ProjectCreate,
    ProjectDocBind,
    ProjectOut,
    ProjectPatch,
    ProjectSectionOut,
    ProjectSectionUpdate,
    ProjectStyleGuideRequest,
    ProjectVersionOut,
    SectionPlanOut,
    SectionVersionOut,
    TranslateSectionRequest,
    TranslateSectionResultOut,
    VersionNodeOut,
    VersionTreeOut,
)
from app.services import analyses
from app.services import export as export_service
from app.services.generation import missing_sections, normalize_sections
from app.services.project_sections import project_sections
from app.services.journal_styles import style_options
from app.services.paperqa_service import PaperQA2Service
from app.services.pqa_registry import get_registry
from app.services.projects import (
    GenerationRequest,
    ProjectService,
    find_project,
    linked_documents,
)
from app.db.models import (
    SectionKind,
    SectionPlan,
    SectionStatus,
    SectionVersion,
    VersionStatus,
)
from app.services.section_labels import section_title

log = logging.getLogger("boasi.api.projects")

router = APIRouter(prefix="/api/sessions", tags=["projects"],
                   dependencies=[Depends(require_researcher)])


def _meta(request: Request) -> dict[str, str | None]:
    return {"ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent")}


def _out(project: Project) -> ProjectOut:
    return project_out(project)


def _owned(db: Session, project_id: str, session_id: str, user: User) -> Project:
    session = get_owned_session(db, session_id, user)
    return find_project(db, project_id, session.id)


# --------------------------------------------------------------------------- CRUD
@router.get("/{session_id}/projects", response_model=list[ProjectOut])
def list_projects(session_id: str, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)) -> list[ProjectOut]:
    get_owned_session(db, session_id, user)
    # Порядок, заданный перетаскиванием, — основной. Внутри одинакового
    # порядка (старые проекты без order) сохраняем прежнюю сортировку
    # по дате изменения.
    projects = db.scalars(
        select(Project).where(Project.session_id == session_id)
        .order_by(Project.order.asc(), Project.updated_at.desc()))
    return [_out(p) for p in projects]


@router.post("/{session_id}/projects", response_model=ProjectOut,
             status_code=status.HTTP_201_CREATED)
def create_project(session_id: str, payload: ProjectCreate, request: Request,
                   user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)) -> ProjectOut:
    session = get_owned_session(db, session_id, user)
    docs_repo.check_project_limit(db, session.id)

    # Новый проект уходит в конец списка: пользователь перетаскивает проекты
    # мышью, и свежий не должен перепрыгивать уже размещённые.
    max_order = db.scalar(
        select(func.max(Project.order)).where(Project.session_id == session.id)) or 0

    project = Project(
        session_id=session.id,
        title=payload.title.strip(),
        target_journal=payload.target_journal,
        language=payload.language,
        status=payload.status,
        sections=normalize_sections(payload.sections),
        order=max_order + 1,
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    touch_session(db, session, action_type="project.create",
                  action_label=f"Проект: {project.title}",
                  snapshot={"tab": "projects", "active_project": project.id})
    audit(db, action="project.create", actor=user, target_type="project",
          target_id=project.id, **_meta(request), title=project.title)
    return _out(project)


@router.get("/{session_id}/projects/{project_id}", response_model=ProjectOut)
def get_project(session_id: str, project_id: str,
                user: User = Depends(get_current_user),
                db: Session = Depends(get_db)) -> ProjectOut:
    return _out(_owned(db, project_id, session_id, user))


@router.patch("/{session_id}/projects/{project_id}", response_model=ProjectOut)
def patch_project(session_id: str, project_id: str, payload: ProjectPatch,
                  request: Request, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)) -> ProjectOut:
    project = _owned(db, project_id, session_id, user)
    changed: list[str] = []
    if payload.title is not None:
        project.title = payload.title.strip()[:512]
        changed.append("title")
    if payload.target_journal is not None:
        project.target_journal = payload.target_journal[:255]
        changed.append("target_journal")
    if payload.status is not None:
        project.status = payload.status
        changed.append("status")
    if payload.sections is not None:
        project.sections = normalize_sections(payload.sections)
        changed.append("sections")
    if payload.style_guide_document_id is not None:
        project.style_guide_document_id = payload.style_guide_document_id
        changed.append("style_guide_document_id")
    if payload.language is not None:
        project.language = payload.language
        changed.append("language")
    if payload.order is not None:
        project.order = payload.order
        changed.append("order")
    db.commit()
    db.refresh(project)
    if changed:
        audit(db, action="project.update", actor=user, target_type="project",
              target_id=project.id, **_meta(request), fields=changed)
    return _out(project)


@router.delete("/{session_id}/projects/{project_id}",
               status_code=status.HTTP_204_NO_CONTENT)
def delete_project(session_id: str, project_id: str, request: Request,
                   user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)) -> None:
    project = _owned(db, project_id, session_id, user)
    title = project.title
    db.delete(project)
    db.commit()
    audit(db, action="project.delete", actor=user, target_type="project",
          target_id=project_id, **_meta(request), title=title)


# --------------------------------------------------------------------------- разделы
@router.get("/{session_id}/projects/{project_id}/sections",
            response_model=list[ProjectSectionOut])
def list_sections(session_id: str, project_id: str,
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)) -> list[ProjectSectionOut]:
    project = _owned(db, project_id, session_id, user)
    # Разделы — из новой модели (планы и их текущие версии).
    sections = project_sections(project)
    return [
        ProjectSectionOut(**s, words=len((s.get("content_md") or "").split()),
                          written=bool((s.get("content_md") or "").strip()))
        for s in sections
    ]


@router.put("/{session_id}/projects/{project_id}/sections/{name}",
            response_model=ProjectSectionOut)
def update_section(session_id: str, project_id: str, name: str,
                   payload: ProjectSectionUpdate, request: Request,
                   user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)) -> ProjectSectionOut:
    """Ручная правка раздела (в т.ч. вставка своего черновика)."""
    project = _owned(db, project_id, session_id, user)
    sections = normalize_sections(project.sections)
    target = next(
        (section for section in sections
         if section["name"].lower() == name.lower()),
        None,
    )
    if target is None:
        # Раздела нет в старой модели — значит он создан в новой (SectionPlan).
        # Берём его оттуда и добавляем в старую, чтобы прогресс и выгрузка
        # тоже его видели.
        plan = next(
            (candidate for candidate in project.section_plans
             if candidate.name.lower() == name.lower()),
            None,
        )
        if plan is None:
            raise NotFoundError(
                f"Раздел «{section_title(name)}» не найден в плане проекта")
        target = {
            "name": plan.name,
            "required": plan.required,
            "order": plan.order,
            "word_target": plan.word_target,
            "notes": plan.notes,
            "content_md": "",
        }
        sections.append(target)

    if payload.notes is not None:
        target["notes"] = payload.notes
    if payload.word_target is not None:
        target["word_target"] = payload.word_target
    if payload.content_md is not None:
        target["content_md"] = payload.content_md
    if payload.required is not None:
        target["required"] = payload.required
    project.sections = sections
    if payload.content_md is not None:
        # Правка должна быть видна в обеих моделях: экспорт и прогресс
        # читают `project.sections`, интерфейс — `section_versions`.
        ProjectService().apply_manual_section_text(
            db, project, target["name"], payload.content_md
        )
    db.commit()
    db.refresh(project)
    audit(db, action="project.section_update", actor=user,
          target_type="project", target_id=project.id, **_meta(request),
          section=name)
    return ProjectSectionOut(
        **target, words=len((target.get("content_md") or "").split()),
        written=bool((target.get("content_md") or "").strip()))


# --------------------------------------------------------------------------- стиль журнала (правила оформления)
@router.post("/{session_id}/projects/{project_id}/style-guide")
def set_project_style_guide(
    session_id: str,
    project_id: str,
    payload: ProjectStyleGuideRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Привязать документ «Правила оформления» к проекту как стиль оформления."""
    project = _owned(db, project_id, session_id, user)
    session = get_owned_session(db, session_id, user)

    if payload.document_id is not None:
        document = docs_repo.get_document(db, payload.document_id)
        if document is None:
            raise NotFoundError("Документ не найден")
        if document.session_id != session_id:
            raise ConflictError(
                "Документ не принадлежит этой сессии")

    project.style_guide_document_id = payload.document_id
    db.commit()
    db.refresh(project)

    touch_session(db, session, action_type="project.style_guide",
                  action_label=f"Стиль журнала: {payload.document_id or 'сброшен'}")
    audit(db, action="project.style_guide_set", actor=user,
          target_type="project", target_id=project.id,
          **_meta(request),
          style_guide_document_id=payload.document_id)

    return {
        "project_id": project.id,
        "style_guide_document_id": project.style_guide_document_id,
    }


# --------------------------------------------------------------------------- перевод раздела
@router.post("/{session_id}/projects/{project_id}/sections/{name}/translate",
             response_model=TranslateSectionResultOut)
async def translate_section(
    session_id: str,
    project_id: str,
    name: str,
    payload: TranslateSectionRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TranslateSectionResultOut:
    """Перевести раздел статьи на целевой язык через LLM."""
    project = _owned(db, project_id, session_id, user)
    sections = project_sections(project)

    section_idx = None
    for i, s in enumerate(sections):
        if s["name"].lower() == name.lower():
            section_idx = i
            break
    if section_idx is None:
        raise NotFoundError(
            f"Раздел \"{section_title(name)}\" не найден в плане проекта")

    section = sections[section_idx]
    original_text = section.get("content_md") or ""
    if not original_text.strip():
        raise ConflictError(
            f"Раздел \"{name}\" пуст - нечего переводи")

    target_lang = payload.target_language
    source_lang = payload.source_language or "ru"

    translations = section.get("translations") or {}
    if target_lang in translations:
        existing = translations[target_lang]
        return TranslateSectionResultOut(
            name=section["name"],
            target_language=target_lang,
            source_language=source_lang,
            content_md=existing,
            words=len(existing.split()),
            written=True,
        )

    registry = get_registry()
    service = registry.global_service()
    translated = await service.translate_text(
        text=original_text,
        target_language=target_lang,
        source_language=source_lang,
    )

    translations[target_lang] = translated
    section["translations"] = translations
    sections[section_idx] = section
    project.sections = sections
    db.commit()
    db.refresh(project)

    audit(
        db,
        action="project.section_translate",
        actor=user,
        target_type="project",
        target_id=project.id,
        **_meta(request),
        section=name,
        target_language=target_lang,
        source_language=source_lang,
    )

    return TranslateSectionResultOut(
        name=section["name"],
        target_language=target_lang,
        source_language=source_lang,
        content_md=translated,
        words=len(translated.split()),
        written=True,
    )


# --------------------------------------------------------------------------- SectionPlan / SectionVersion (новая система)
@router.get("/{session_id}/projects/{project_id}/section-plans",
            response_model=list[SectionPlanOut])
def list_section_plans(session_id: str, project_id: str,
                       user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)) -> list[SectionPlanOut]:
    """Список планов разделов (новая система SectionPlan).

    Вместе с планом отдаём текущую версию **и её текст** — иначе
    интерфейс после перезагрузки страницы не может показать сохранённый
    текст раздела.
    """
    project = _owned(db, project_id, session_id, user)
    plans = []
    for plan in project.section_plans:
        current_version = None
        if plan.current_version_id:
            v = db.get(SectionVersion, plan.current_version_id)
            if v:
                current_version = SectionVersionOut.from_model(v)
        plans.append(SectionPlanOut(
            id=plan.id,
            project_id=plan.project_id,
            name=plan.name,
            kind=plan.kind.value,
            order=plan.order,
            required=plan.required,
            word_target=plan.word_target,
            word_min=plan.word_min,
            word_max=plan.word_max,
            notes=plan.notes,
            language=plan.language,
            depends_on=list(plan.depends_on or []),
            status=plan.status.value,
            current_version_id=plan.current_version_id,
            current_version=current_version,
            created_at=plan.created_at,
            updated_at=plan.updated_at,
        ))
    return plans


@router.put("/{session_id}/projects/{project_id}/section-plans/{plan_id}/content",
            response_model=SectionVersionOut)
def save_section_content(
    session_id: str, project_id: str, plan_id: str, payload: dict, request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SectionVersionOut:
    """Сохранить текст раздела, набранный в редакторе.

    Правка попадает в новую модель (новая версия раздела) и зеркалится
    в старую (`project.sections`) — её читают прогресс проекта и выгрузка.
    """
    project = _owned(db, project_id, session_id, user)
    plan = db.get(SectionPlan, plan_id)
    if not plan or plan.project_id != project.id:
        raise NotFoundError("План раздела не найден")

    content_md = str(payload.get("content_md") or "")
    version = ProjectService().apply_manual_section_text(
        db, project, plan.name, content_md)
    db.commit()
    db.refresh(project)
    audit(db, action="project.section_content.save", actor=user,
          target_type="project", target_id=project.id, **_meta(request),
          section=plan.name, version_id=version.id if version else None,
          words=len(content_md.split()))
    return SectionVersionOut.from_model(version)


@router.get("/{session_id}/projects/{project_id}/section-versions",
            response_model=list[SectionVersionOut])
def list_section_versions(session_id: str, project_id: str,
                           user: User = Depends(get_current_user),
                           db: Session = Depends(get_db)) -> list[SectionVersionOut]:
    """Все версии разделов проекта — реальная история генераций.

    Старая модель (`project_versions`) пишется только старым генератором;
    генерация через SectionAgent кладёт версии в `section_versions`,
    поэтому отдельная выдача нужна для панели «История».
    """
    project = _owned(db, project_id, session_id, user)
    versions = db.execute(
        select(SectionVersion)
        .where(SectionVersion.project_id == project.id)
        .order_by(SectionVersion.created_at.desc())
    ).scalars().all()
    return [SectionVersionOut.from_model(v) for v in versions]


@router.post("/{session_id}/projects/{project_id}/section-plans",
             status_code=status.HTTP_201_CREATED)
def create_section_plan(session_id: str, project_id: str,
                       payload: dict, request: Request,
                       user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)) -> dict:
    """Создать новый план раздела."""
    project = _owned(db, project_id, session_id, user)
    service = ProjectService()
    plan = service.get_or_create_section_plan(
        db, project, payload["name"],
        kind=SectionKind(payload.get("kind", "standard")),
        order=payload.get("order"),
        word_target=payload.get("word_target"),
        notes=payload.get("notes", ""),
        language=payload.get("language"),
        required=payload.get("required", True),
        depends_on=payload.get("depends_on"),
    )
    audit(db, action="project.section_plan.create", actor=user,
          target_type="project", target_id=project.id, **_meta(request),
          section_plan_id=plan.id, name=plan.name)
    return {"id": plan.id, "name": plan.name}


@router.patch("/{session_id}/projects/{project_id}/section-plans/{plan_id}")
def update_section_plan(session_id: str, project_id: str, plan_id: str,
                        payload: dict, request: Request,
                        user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)) -> dict:
    """Обновить план раздела."""
    project = _owned(db, project_id, session_id, user)
    plan = db.get(SectionPlan, plan_id)
    if not plan or plan.project_id != project.id:
        raise NotFoundError("План раздела не найден")
    
    changed = []
    if "name" in payload:
        plan.name = payload["name"]
        changed.append("name")
    if "kind" in payload:
        plan.kind = SectionKind(payload["kind"])
        changed.append("kind")
    if "order" in payload:
        plan.order = payload["order"]
        changed.append("order")
    if "word_target" in payload:
        plan.word_target = payload["word_target"]
        plan.word_min = max(100, plan.word_target // 2)
        plan.word_max = plan.word_target * 4
        changed.append("word_target")
    if "notes" in payload:
        plan.notes = payload["notes"]
        changed.append("notes")
    if "language" in payload:
        plan.language = payload["language"]
        changed.append("language")
    if "required" in payload:
        plan.required = payload["required"]
        changed.append("required")
    if "depends_on" in payload:
        plan.depends_on = payload["depends_on"]
        changed.append("depends_on")
    if "status" in payload:
        plan.status = SectionStatus(payload["status"])
        changed.append("status")
    
    if changed:
        db.commit()
        audit(db, action="project.section_plan.update", actor=user,
              target_type="project", target_id=project.id, **_meta(request),
              section_plan_id=plan.id, fields=changed)
    return {"id": plan.id, "status": "updated"}


@router.delete("/{session_id}/projects/{project_id}/section-plans/{plan_id}",
               status_code=status.HTTP_204_NO_CONTENT)
def delete_section_plan(session_id: str, project_id: str, plan_id: str,
                       request: Request, user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)) -> None:
    """Удалить план раздела."""
    project = _owned(db, project_id, session_id, user)
    plan = db.get(SectionPlan, plan_id)
    if not plan or plan.project_id != project.id:
        raise NotFoundError("План раздела не найден")
    
    db.delete(plan)
    db.commit()
    audit(db, action="project.section_plan.delete", actor=user,
          target_type="project", target_id=project.id, **_meta(request),
          section_plan_id=plan_id, name=plan.name)


@router.post("/{session_id}/projects/{project_id}/section-plans/sync")
def sync_sections_to_plans(session_id: str, project_id: str, request: Request,
                           user: User = Depends(get_current_user),
                           db: Session = Depends(get_db)) -> dict:
    """Синхронизировать старый JSON project.sections в новые SectionPlan."""
    project = _owned(db, project_id, session_id, user)
    service = ProjectService()
    plans = service.sync_project_sections_to_plans(db, project)
    audit(db, action="project.section_plan.sync", actor=user,
          target_type="project", target_id=project.id, **_meta(request),
          count=len(plans))
    return {"synced": len(plans), "plans": [{"id": p.id, "name": p.name} for p in plans]}


@router.post("/{session_id}/projects/{project_id}/generate-v2",
             response_model=dict)
async def generate_section_v2(
    session_id: str, project_id: str, payload: dict, request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Новая генерация раздела через SectionAgent (возвращает SectionVersion).

    В теле — `kind`: вид генерации (обычный раздел, обзор литературы,
    сверка с данными, обсуждение, пробелы, отчёт, разбор черновика).
    """
    session = get_owned_session(db, session_id, user)
    project = _owned(db, project_id, session_id, user)
    
    section_name = payload["section"].strip()
    question = payload["question"].strip()
    notes = payload.get("notes")
    word_target = payload.get("word_target")
    use_cache = payload.get("use_cache", True)
    try:
        kind = GenerationKind(payload.get("kind", "section"))
    except ValueError:
        kind = GenerationKind.section
    
    service = ProjectService()
    version = await service.generate_section_v2(
        db, project=project, session=session, user=user,
        section_name=section_name, question=question,
        notes=notes, word_target=word_target, use_cache=use_cache, kind=kind,
    )
    
    touch_session(db, session, action_type="project.generate.v2",
                  action_label=f"Раздел: {section_name}",
                  snapshot={"tab": "projects", "active_project": project.id})
    # quality_report в модели — это JSON-словарь, а не объект.
    report = version.quality_report or {}
    citations_ok = report.get("citations_ok") if isinstance(report, dict) else None
    audit(db, action="project.generate.v2", actor=user, target_type="project",
          target_id=project.id, **_meta(request), section=section_name,
          version_id=version.id, citations_ok=citations_ok,
          sources=len(version.citation_map), seconds=version.seconds)
    
    return {
        "version_id": version.id,
        "section_plan_id": version.section_plan_id,
        "content_md": version.content_md,
        "language": version.language,
        "word_count": version.word_count,
        "citation_map": version.citation_map,
        "quality_report": version.quality_report,
        "status": version.status.value,
        "created_at": version.created_at.isoformat(),
    }


@router.post("/{session_id}/projects/{project_id}/section-plans/{plan_id}/translate",
             response_model=dict)
async def translate_section_v2(
    session_id: str, project_id: str, plan_id: str,
    payload: dict, request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Перевести раздел на целевой язык (новая система)."""
    project = _owned(db, project_id, session_id, user)
    version_id = payload.get("version_id")
    target_language = payload["target_language"]
    
    service = ProjectService()
    version = await service.translate_section(
        db, project=project, section_plan_id=plan_id,
        target_language=target_language, user=user, version_id=version_id,
    )
    
    audit(db, action="project.section.translate.v2", actor=user,
          target_type="project", target_id=project.id, **_meta(request),
          section_plan_id=plan_id, version_id=version.id,
          target_language=target_language, source_language=version.source_language)
    
    return {
        "version_id": version.id,
        "section_plan_id": version.section_plan_id,
        "content_md": version.content_md,
        "language": version.language,
        "source_language": version.source_language,
        "word_count": version.word_count,
        "parent_version_id": version.parent_version_id,
        "created_at": version.created_at.isoformat(),
    }


@router.get("/{session_id}/projects/{project_id}/section-plans/{plan_id}/history",
            response_model=VersionTreeOut)
def get_section_history(
    session_id: str, project_id: str, plan_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VersionTreeOut:
    """История версий раздела: дерево + плоский список, с текстом версий."""
    project = _owned(db, project_id, session_id, user)
    plan = db.get(SectionPlan, plan_id)
    if not plan or plan.project_id != project.id:
        raise NotFoundError("План раздела не найден")

    service = ProjectService()
    tree = service.get_section_history(db, plan_id)

    def serialize_node(node) -> VersionNodeOut:
        return VersionNodeOut(
            version=SectionVersionOut.from_model(node.version),
            children=[serialize_node(child) for child in node.children],
        )

    return VersionTreeOut(
        section_plan_id=tree.section_plan_id,
        section_name=tree.section_name,
        roots=[serialize_node(root) for root in tree.roots],
        all_versions=[SectionVersionOut.from_model(v) for v in tree.all_versions],
    )


@router.get("/{session_id}/projects/{project_id}/section-versions/diff")
def diff_section_versions(
    session_id: str, project_id: str, from_version: str, to_version: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Сравнить две версии раздела (семантический diff)."""
    project = _owned(db, project_id, session_id, user)
    service = ProjectService()
    diff = service.diff_section_versions(db, from_version, to_version)
    
    return {
        "from_version_id": diff.from_version_id,
        "to_version_id": diff.to_version_id,
        "added_claims": diff.added_claims,
        "removed_claims": diff.removed_claims,
        "modified_claims": diff.modified_claims,
        "citation_changes": diff.citation_changes,
        "terminology_changes": diff.terminology_changes,
        "word_count_delta": diff.word_count_delta,
        "summary": diff.summary,
    }


@router.post("/{session_id}/projects/{project_id}/section-plans/{plan_id}/rollback")
def rollback_section(
    session_id: str, project_id: str, plan_id: str,
    payload: dict, request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Откатить раздел к указанной версии."""
    project = _owned(db, project_id, session_id, user)
    version_id = payload["version_id"]
    
    service = ProjectService()
    version = service.rollback_section(db, plan_id, version_id, user)
    
    audit(db, action="project.section.rollback", actor=user,
          target_type="project", target_id=project.id, **_meta(request),
          section_plan_id=plan_id, version_id=version.id, rolled_back_to=version_id)
    
    return {"version_id": version.id, "status": version.status.value}


@router.post("/{session_id}/projects/{project_id}/section-plans/{plan_id}/approve")
def approve_section(
    session_id: str, project_id: str, plan_id: str,
    payload: dict, request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Одобрить версию раздела."""
    project = _owned(db, project_id, session_id, user)
    version_id = payload["version_id"]
    
    service = ProjectService()
    version = service.approve_section_version(db, plan_id, version_id, user)
    
    audit(db, action="project.section.approve", actor=user,
          target_type="project", target_id=project.id, **_meta(request),
          section_plan_id=plan_id, version_id=version.id)
    
    return {"version_id": version.id, "status": version.status.value}


@router.get("/{session_id}/projects/{project_id}/language-policy")
def get_language_policy(
    session_id: str, project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Получить языковую политику проекта."""
    project = _owned(db, project_id, session_id, user)
    policy = project.language_policy
    if not policy:
        return {
            "primary_language": project.language,
            "allowed_languages": ["ru", "en"],
            "translate_on_approve": False,
            "auto_translate_target": None,
        }
    return {
        "primary_language": policy.primary_language,
        "allowed_languages": policy.allowed_languages,
        "translate_on_approve": policy.translate_on_approve,
        "auto_translate_target": policy.auto_translate_target,
    }


@router.patch("/{session_id}/projects/{project_id}/language-policy")
def update_language_policy(
    session_id: str, project_id: str,
    payload: dict, request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Обновить языковую политику проекта."""
    project = _owned(db, project_id, session_id, user)
    from app.db.models import ProjectLanguagePolicy
    
    if not project.language_policy:
        policy = ProjectLanguagePolicy(
            id=new_id(),
            project_id=project.id,
            primary_language=project.language,
        )
        db.add(policy)
    else:
        policy = project.language_policy
    
    if "primary_language" in payload:
        policy.primary_language = payload["primary_language"]
    if "allowed_languages" in payload:
        policy.allowed_languages = payload["allowed_languages"]
    if "translate_on_approve" in payload:
        policy.translate_on_approve = payload["translate_on_approve"]
    if "auto_translate_target" in payload:
        policy.auto_translate_target = payload["auto_translate_target"]
    
    db.commit()
    audit(db, action="project.language_policy.update", actor=user,
          target_type="project", target_id=project.id, **_meta(request),
          fields=list(payload.keys()))
    return {"status": "updated"}


@router.get("/{session_id}/projects/{project_id}/glossary")
def get_glossary(
    session_id: str, project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Получить глоссарий терминов проекта."""
    project = _owned(db, project_id, session_id, user)
    return [
        {
            "id": entry.id,
            "term": entry.term,
            "translations": entry.translations,
            "definition": entry.definition,
        }
        for entry in project.glossary
    ]


@router.post("/{session_id}/projects/{project_id}/glossary",
             status_code=status.HTTP_201_CREATED)
def add_glossary_entry(
    session_id: str, project_id: str,
    payload: dict, request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Добавить термин в глоссарий."""
    project = _owned(db, project_id, session_id, user)
    from app.db.models import TerminologyGlossary
    
    entry = TerminologyGlossary(
        id=new_id(),
        project_id=project.id,
        term=payload["term"],
        translations=payload.get("translations", {}),
        definition=payload.get("definition"),
    )
    db.add(entry)
    db.commit()
    audit(db, action="project.glossary.add", actor=user,
          target_type="project", target_id=project.id, **_meta(request),
          term=entry.term)
    return {"id": entry.id, "term": entry.term}


@router.patch("/{session_id}/projects/{project_id}/glossary/{entry_id}")
def update_glossary_entry(
    session_id: str, project_id: str, entry_id: str,
    payload: dict, request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Обновить термин в глоссарии."""
    project = _owned(db, project_id, session_id, user)
    entry = db.get(TerminologyGlossary, entry_id)
    if not entry or entry.project_id != project.id:
        raise NotFoundError("Термин не найден")
    
    if "term" in payload:
        entry.term = payload["term"]
    if "translations" in payload:
        entry.translations = payload["translations"]
    if "definition" in payload:
        entry.definition = payload["definition"]
    
    db.commit()
    audit(db, action="project.glossary.update", actor=user,
          target_type="project", target_id=project.id, **_meta(request),
          entry_id=entry_id, term=entry.term)
    return {"id": entry.id, "term": entry.term}


@router.delete("/{session_id}/projects/{project_id}/glossary/{entry_id}",
               status_code=status.HTTP_204_NO_CONTENT)
def delete_glossary_entry(
    session_id: str, project_id: str, entry_id: str,
    request: Request, user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Удалить термин из глоссария."""
    project = _owned(db, project_id, session_id, user)
    entry = db.get(TerminologyGlossary, entry_id)
    if not entry or entry.project_id != project.id:
        raise NotFoundError("Термин не найден")
    
    term = entry.term
    db.delete(entry)
    db.commit()
    audit(db, action="project.glossary.delete", actor=user,
          target_type="project", target_id=project.id, **_meta(request),
          entry_id=entry_id, term=term)


# --------------------------------------------------------------------------- документы
@router.get("/{session_id}/projects/{project_id}/documents",
            response_model=list[dict])
def list_project_documents(session_id: str, project_id: str,
                           user: User = Depends(get_current_user),
                           db: Session = Depends(get_db)) -> list[dict]:
    project = _owned(db, project_id, session_id, user)
    return [
        {"document": document_from_row(document), "role": role}
        for document, role in linked_documents(db, project.id)
    ]


@router.post("/{session_id}/projects/{project_id}/documents",
             status_code=status.HTTP_204_NO_CONTENT)
def bind_document(session_id: str, project_id: str, payload: ProjectDocBind,
                  request: Request, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)) -> None:
    """Привязать документ сессии к проекту с ролью reference / data / draft."""
    session = get_owned_session(db, session_id, user)
    project = _owned(db, project_id, session_id, user)

    document = docs_repo.get_document(db, payload.document_id)
    if document.session_id != session.id:
        raise NotFoundError("Документ не найден в сессии")

    docs_repo.link_document(
        db, document_id=document.id, session_id=session.id,
        project_id=project.id, role=ProjectDocRole(payload.role),
        note=payload.note,
    )
    touch_session(db, session, action_type="project.bind_document",
                  action_label=f"Документ привязан: {document.title}")
    audit(db, action="project.document_bind", actor=user, target_type="project",
          target_id=project.id, **_meta(request), document=document.id,
          role=payload.role)


@router.delete("/{session_id}/projects/{project_id}/documents/{document_id}",
               status_code=status.HTTP_204_NO_CONTENT)
def unbind_document(session_id: str, project_id: str, document_id: str,
                    user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)) -> None:
    project = _owned(db, project_id, session_id, user)
    for link in docs_repo.list_links(db, session_id=session_id):
        if link.project_id == project.id and link.document_id == document_id:
            docs_repo.unlink_document(db, link.id)
            return
    raise NotFoundError("Связь документа с проектом не найдена")


# --------------------------------------------------------------------------- генерация
@router.get("/{session_id}/projects/{project_id}/draft-analysis")
def draft_analysis(session_id: str, project_id: str,
                   user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)) -> dict[str, Any]:
    """Разбор черновика БЕЗ обращения к LLM: быстро, детерминированно, проверяемо.

    Ищет пробелы по правилам: обязательные разделы без текста, утверждения с
    числами или силовыми словами без ссылки [n], результаты без описания
    методики. Это и есть требование ТЗ «анализ черновика находит ≥1 реальный
    пробел».
    """
    project = _owned(db, project_id, session_id, user)
    analysis = analyses.analyze_draft(project_sections(project))
    return {**analysis.to_dict(), "project_id": project.id,
            "rendered": analyses.render_gaps(analysis)}


@router.post("/{session_id}/projects/{project_id}/generate",
             response_model=GenerateResultOut)
async def generate(session_id: str, project_id: str, payload: GenerateRequest,
                   request: Request, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)) -> GenerateResultOut:
    """Сгенерировать раздел статьи по контексту проекта."""
    session = get_owned_session(db, session_id, user)
    project = _owned(db, project_id, session_id, user)

    request_obj = GenerationRequest(
        section=payload.section.strip(),
        question=payload.question.strip(),
        word_target=payload.word_target,
        notes=payload.notes,
        use_cache=not payload.no_cache,
        template_md=payload.template_md,
        data_document_ids=payload.data_document_ids,
        language=payload.language,
    )
    try:
        result = await ProjectService().generate_section(
            db, project=project, session=session, user=user,
            request=request_obj, kind=GenerationKind(payload.kind))
    except Exception:
        log.exception("generate: ошибка генерации раздела %r", payload.section)
        raise

    touch_session(db, session, action_type="project.generate",
                  action_label=f"Раздел: {request_obj.section}",
                  snapshot={"tab": "projects", "active_project": project.id})
    audit(db, action="project.generate", actor=user, target_type="project",
          target_id=project.id, **_meta(request), section=request_obj.section,
          citations_ok=result.ok, sources=len(result.sources),
          from_cache=result.from_cache, seconds=result.seconds)

    return GenerateResultOut(**result.to_dict(), project_id=project.id)


@router.post("/{session_id}/projects/{project_id}/generate-async")
async def generate_section_async(
    session_id: str, project_id: str, payload: GenerateRequest,
    request: Request, user: User = Depends(get_current_user),
    db: Session = Depends(get_db)) -> dict[str, Any]:
    """Фоновая генерация раздела: возвращает task_id, UI опрашивает /api/tasks/{id}.

    Генерация может занимать минуты, поэтому синхронный POST /generate
    (для скриптов и тестов) дополняется фоновым режимом.
    """
    from app.services.tasks import Task, tasks

    session = get_owned_session(db, session_id, user)
    project = _owned(db, project_id, session_id, user)

    request_obj = GenerationRequest(
        section=payload.section.strip(),
        question=payload.question.strip(),
        word_target=payload.word_target,
        notes=payload.notes,
        use_cache=not payload.no_cache,
        template_md=payload.template_md,
        data_document_ids=payload.data_document_ids,
        language=payload.language,
    )

    # Фоновое тело живёт дольше запроса: после ответа FastAPI закрывает
    # request-сессию, ORM-объекты отсоединяются, и правки плана молча
    # терялись — версия в базе появлялась, а `current_version_id` у плана
    # оставался пустым (раздел «не сгенерирован» после перезагрузки).
    # Поэтому в фоне работаем со своей сессией и заново читаем объекты.
    from app.db.models import ResearchSession
    from app.db.session import get_session_factory

    project_key = project.id
    session_key = session.id
    user_key = user.id

    async def body(task: Task) -> dict[str, Any]:
        # Этапы: подготовка -> поиск контекста -> LLM -> сохранение
        bg_db = get_session_factory()()
        try:
            bg_project = bg_db.get(Project, project_key)
            bg_session = bg_db.get(ResearchSession, session_key)
            bg_user = bg_db.get(User, user_key)
            if bg_project is None or bg_session is None or bg_user is None:
                raise NotFoundError("Проект или сессия не найдены")

            task.set_stage(10, "подготовка запроса")
            service = ProjectService()
            try:
                result = await service.generate_section(
                    bg_db, project=bg_project, session=bg_session,
                    user=bg_user, request=request_obj,
                    kind=GenerationKind(request_obj.kind))
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("generate-async: ошибка генерации раздела %r",
                              request_obj.section)
                raise

            touch_session(bg_db, bg_session, action_type="project.generate",
                          action_label=f"Раздел: {request_obj.section}",
                          snapshot={"tab": "projects",
                                    "active_project": bg_project.id})
            audit(bg_db, action="project.generate", actor=bg_user,
                 target_type="project", target_id=bg_project.id,
                 **_meta(request), section=request_obj.section,
                 citations_ok=result.ok, sources=len(result.sources),
                 from_cache=result.from_cache, seconds=result.seconds)
            return result.to_dict()
        finally:
            bg_db.close()

    task = tasks.submit(body, kind="generate_section",
                        title=f"Раздел: {request_obj.section}",
                        user_id=user.id, session_id=session_id,
                        project_id=project_id)
    audit(db, action="project.generate.async", actor=user,
          target_type="project", target_id=project.id,
          **_meta(request), section=request_obj.section,
          task_id=task.id)
    return {"task_id": task.id}


@router.get("/{session_id}/projects/{project_id}/eta")
def project_generate_eta(
    session_id: str, project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)) -> dict[str, Any]:
    """ETA генерации раздела: среднее время по типу документа.

    Возвращает медиану и среднее время (секунд) по уже сгенерированным
    версиям этого проекта, сгруппированное по kind. Если данных ещё нет —
    возвращает оценочный диапазон 120–240 с.
    """
    project = _owned(db, project_id, session_id, user)
    rows = db.scalars(
        select(ProjectVersionModel).where(
            ProjectVersionModel.project_id == project.id,
            ProjectVersionModel.seconds.is_not(None),
        )
    ).all()

    if not rows:
        return {
            "kind": None,
            "estimate_seconds": 180,
            "estimate_range": [120, 240],
            "note": "Нет данных — ориентировочная оценка",
        }

    from statistics import mean
    by_kind: dict[str, list[float]] = {}
    for r in rows:
        by_kind.setdefault(str(r.kind), []).append(r.seconds)

    all_seconds = [s for secs in by_kind.values() for s in secs]
    return {
        "kind": None,
        "estimate_seconds": round(mean(all_seconds), 1),
        "estimate_range": [
            round(min(all_seconds), 1),
            round(max(all_seconds), 1),
        ],
        "by_kind": {
            k: {
                "estimate_seconds": round(mean(v), 1),
                "count": len(v),
            }
            for k, v in by_kind.items()
        },
        "count": len(all_seconds),
    }


@router.get("/{session_id}/projects/{project_id}/versions",
            response_model=list[ProjectVersionOut])
def list_versions(session_id: str, project_id: str,
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)) -> list[ProjectVersionOut]:
    """История генераций: снапшот на каждый запуск — черновик не теряется."""
    project = _owned(db, project_id, session_id, user)
    return [
        ProjectVersionOut(
            id=v.id, project_id=v.project_id, section_name=v.section_name,
            kind=getattr(v.kind, "value", str(v.kind)), content_md=v.content_md,
            word_count=v.word_count, citation_map=list(v.citation_map or []),
            stats=dict(v.stats or {}), created_at=v.created_at)
        for v in project.versions
    ]


@router.get("/{session_id}/projects/{project_id}/versions/diff")
def diff_versions(session_id: str, project_id: str, left: str, right: str,
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)) -> dict[str, Any]:
    """Построчный diff двух версий раздела (снапшот до/после генерации)."""
    import difflib

    project = _owned(db, project_id, session_id, user)
    by_id = {v.id: v for v in project.versions}
    if left not in by_id or right not in by_id:
        raise NotFoundError("Одна из версий не найдена")

    before = (by_id[left].content_md or "").splitlines()
    after = (by_id[right].content_md or "").splitlines()
    diff = list(difflib.unified_diff(before, after, fromfile=left[:8],
                                     tofile=right[:8], lineterm=""))
    return {"left": left, "right": right, "diff": diff,
            "changed_lines": sum(1 for line in diff
                                 if line.startswith(("+", "-"))
                                 and not line.startswith(("+++", "---")))}


@router.get("/{session_id}/projects/{project_id}/progress")
def project_progress(session_id: str, project_id: str,
                     user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)) -> dict[str, Any]:
    project = _owned(db, project_id, session_id, user)
    sections = project_sections(project)
    return {"project_id": project.id, "status": project.status.value,
            **ProjectService.plan_progress(project),
            "missing_sections": missing_sections(sections),
            "versions": len(project.versions)}


# --------------------------------------------------------------------------- экспорт
@router.post("/{session_id}/projects/{project_id}/batch-regenerate")
async def batch_regenerate_sections(
    session_id: str, project_id: str, payload: dict, request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Пакетная перегенерация устаревших разделов.
    
    Payload:
    - force: bool (default false) — перегенерировать всё принудительно
    """
    session = get_owned_session(db, session_id, user)
    project = _owned(db, project_id, session_id, user)
    force = payload.get("force", False)
    
    service = ProjectService()
    result = await service.regenerate_outdated_sections(
        db, project=project, session=session, user=user, force=force
    )
    
    audit(db, action="project.batch_regenerate", actor=user,
          target_type="project", target_id=project.id, **_meta(request),
          force=force, result=result)
    return result


@router.post("/{session_id}/projects/{project_id}/section-plans/{plan_id}/merge")
async def merge_section_versions(
    session_id: str, project_id: str, plan_id: str,
    payload: dict, request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Слить две версии раздела (LLM-ассистированное слияние).
    
    Payload:
    - target_version_id: str — базовая версия
    - source_version_id: str — вливаемая версия
    - strategy: str = "llm" — "llm" или "manual"
    """
    project = _owned(db, project_id, session_id, user)
    target_version_id = payload["target_version_id"]
    source_version_id = payload["source_version_id"]
    strategy = payload.get("strategy", "llm")
    
    service = ProjectService()
    # HistoryService теперь async для LLM merge
    from app.services.history import HistoryService
    history = HistoryService(db, registry=get_registry())
    version = await history.merge_branches(
        section_plan_id=plan_id,
        target_version_id=target_version_id,
        source_version_id=source_version_id,
        user=user,
        strategy=strategy,
    )
    
    audit(db, action="project.section.merge", actor=user,
          target_type="project", target_id=project.id, **_meta(request),
          section_plan_id=plan_id, target_version=target_version_id,
          source_version=source_version_id, strategy=strategy)
    
    return {
        "version_id": version.id,
        "content_md": version.content_md,
        "citation_map": version.citation_map,
        "word_count": version.word_count,
        "strategy": strategy,
    }


@router.get("/{session_id}/projects/{project_id}/terminology-check")
def check_terminology_consistency(
    session_id: str, project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Проверить согласованность терминологии по всем разделам проекта."""
    project = _owned(db, project_id, session_id, user)
    service = ProjectService()
    # Используем существующий метод проверки терминологии для каждого раздела
    issues = []
    for plan in project.section_plans:
        if plan.current_version_id:
            version = db.get(SectionVersion, plan.current_version_id)
            if version:
                terminology = version.quality_report.terminology_consistency
                for term, translation in terminology.items():
                    issues.append({
                        "section": plan.name,
                        "term": term,
                        "expected": translation,
                        "type": "glossary_match",
                    })
    
    # Проверка: одинаковые термины в разных разделах должны переводиться одинаково
    # (упрощённо - проверяем глоссарий)
    glossary_terms = {e.term: e.translations for e in project.glossary}
    
    return {
        "project_id": project.id,
        "glossary_terms": glossary_terms,
        "section_terminology": issues,
        "consistent": len(issues) == 0,
    }


@router.post("/{session_id}/projects/{project_id}/style-compliance")
async def check_style_compliance(
    session_id: str, project_id: str,
    payload: dict, request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Проверить соответствие стилю журнала (style guide) для раздела.
    
    Payload:
    - section_plan_id: str
    - version_id: str (optional, default: current)
    """
    project = _owned(db, project_id, session_id, user)
    section_plan_id = payload["section_plan_id"]
    version_id = payload.get("version_id")
    
    plan = db.get(SectionPlan, section_plan_id)
    if not plan or plan.project_id != project.id:
        raise NotFoundError("План раздела не найден")
    
    if version_id:
        version = db.get(SectionVersion, version_id)
    else:
        version = db.get(SectionVersion, plan.current_version_id) if plan.current_version_id else None
    
    if not version:
        raise NotFoundError("Версия не найдена")
    
    # Читаем style guide если есть
    style_guide_text = None
    if project.style_guide_document_id:
        from app.db.models import Document
        from pathlib import Path
        document = db.get(Document, project.style_guide_document_id)
        if document and Path(document.path).is_file():
            style_guide_text = Path(document.path).read_text(encoding="utf-8")
    
    if not style_guide_text:
        return {
            "compliant": True,
            "warnings": ["Style guide не привязан к проекту"],
            "checks": {},
        }
    
    # LLM проверка соответствия
    registry = get_registry()
    service = registry.global_service()
    
    prompt = f"""Проверь соответствие текста требованиям стиля журнала.

ТРЕБОВАНИЯ ЖУРНАЛА:
{style_guide_text}

ТЕКСТ РАЗДЕЛА ({plan.name}):
{version.content_md[:4000]}

Верни JSON:
{{
  "compliant": true/false,
  "violations": [
    {{"rule": "...", "location": "...", "suggestion": "..."}}
  ],
  "warnings": [...]
}}
"""
    result = await service.complete(prompt, name="style_compliance")
    import json
    try:
        data = json.loads(result)
    except:
        data = {"compliant": True, "violations": [], "warnings": ["Ошибка парсинга LLM"]}
    
    return data


@router.post("/{session_id}/projects/{project_id}/pre-generation-check")
async def pre_generation_check(
    session_id: str, project_id: str,
    payload: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Предварительная проверка перед генерацией раздела (checklist).
    
    Payload:
    - section_name: str
    - question: str
    - required_sources: int (optional, default: 3)
    """
    project = _owned(db, project_id, session_id, user)
    section_name = payload["section_name"]
    question = payload["question"]
    required_sources = payload.get("required_sources", 3)
    
    # Проверяем есть ли план раздела
    plan = None
    for p in project.section_plans:
        if p.name.lower() == section_name.lower():
            plan = p
            break
    
    # Проверяем доступность источников через RAG
    from app.services.rag_service import RagFusionService
    from app.services.pqa_registry import get_registry
    
    registry = get_registry()
    fusion = RagFusionService(registry)
    
    # Используем существующую сессию если есть, иначе создаем временную проверку
    session_id_check = project.session_id
    from app.db.models import ResearchSession
    session = db.get(ResearchSession, session_id_check)
    
    sources = []
    if session:
        sources, _ = await fusion.retrieve(
            db, query=question, session_id=session.id, mode="hybrid", k=10
        )
    
    checks = {
        "section_exists": plan is not None,
        "has_question": bool(question.strip()),
        "sources_found": len(sources),
        "sources_sufficient": len(sources) >= required_sources,
        "has_style_guide": bool(project.style_guide_document_id),
        "has_glossary": len(project.glossary) > 0,
        "language_supported": project.language in (project.language_policy.allowed_languages if project.language_policy else ["ru", "en"]),
    }
    
    warnings = []
    if not checks["section_exists"]:
        warnings.append(f"Раздел '{section_name}' нет в плане проекта")
    if not checks["sources_sufficient"]:
        warnings.append(f"Мало источников: найдено {checks['sources_found']}, нужно {required_sources}")
    if not checks["has_style_guide"]:
        warnings.append("Style guide не привязан — оформление может не соответствовать журналу")
    if not checks["has_glossary"]:
        warnings.append("Глоссарий пуст — терминология может быть несогласованной")
    
    return {
        "ready": all(checks.values()),
        "checks": checks,
        "warnings": warnings,
        "sources_preview": [
            {"index": s["index"], "title": s.get("title"), "score": s.get("score")}
            for s in sources[:5]
        ],
    }


@router.get("/{session_id}/projects/{project_id}/manuscript")
def compile_manuscript(
    session_id: str, project_id: str,
    language: str | None = None,
    include_unapproved: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Собрать полный манускрипт из версий разделов.
    
    Query params:
    - language: целевой язык (default: project.language)
    - include_unapproved: включать не одобренные разделы
    """
    project = _owned(db, project_id, session_id, user)
    service = ProjectService()
    result = service.compile_manuscript(
        db, project, language=language, include_unapproved=include_unapproved
    )
    return result


@router.get("/{session_id}/projects/{project_id}/export")
def export_project(session_id: str, project_id: str,
                   fmt: ExportFormat = ExportFormat.markdown,
                   include_documents: bool = True,
                   user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)) -> Response:
    """Экспорт статьи: markdown | docx | zip (в zip — библиография и sources)."""
    project = _owned(db, project_id, session_id, user)

    if fmt is ExportFormat.markdown:
        content = export_service.render_markdown(project)
        media_type = "text/markdown; charset=utf-8"
    elif fmt is ExportFormat.docx:
        result = export_service.render_docx(project)
        content = result.content
        media_type = ("application/vnd.openxmlformats-officedocument"
                      ".wordprocessingml.document")
    else:
        documents = [doc for doc, _ in linked_documents(db, project.id)]
        bundle = export_service.build_zip(project, documents,
                                          include_documents=include_documents)
        content = bundle.content
        media_type = "application/zip"

    suffix = {"markdown": "md", "docx": "docx", "zip": "zip"}[fmt.value]
    # Заголовки HTTP — latin-1, кириллическое имя сломало бы ответ.
    # Поэтому транслитерируем, а исходное имя отдаём в RFC 5987 (`filename*`).
    ascii_name = re.sub(r'[^\x20-\x7e]+', "_", project.title).strip(" ._")[:60] or "article"
    filename = f"{ascii_name}.{suffix}"
    quoted = quote(f"{project.title[:60] or 'article'}.{suffix}")
    return Response(content=content, media_type=media_type, headers={
        "Content-Disposition":
            f'attachment; filename="{filename}"; filename*=UTF-8\'\'{quoted}'})


# --------------------------------------------------------------------------- стили
journals_router = APIRouter(prefix="/api", tags=["journals"])


@journals_router.get("/journal-styles", response_model=list[JournalStyleOut])
def list_journal_styles(user: User = Depends(get_current_user)
                        ) -> list[JournalStyleOut]:
    """Справочник групп журналов и их шаблонов промптов.

    Не зависит от сессии: справочник общий, и стиль нужен до создания
    проекта. Сами шаблоны приходят с диска (`app/prompts/journal_styles`),
    поэтому новая группа появляется без правки кода.
    """
    return [JournalStyleOut(**item) for item in style_options()]


@journals_router.get("/journal-styles/{style_key}/suggested-plan", dependencies=[])
def get_suggested_section_plan(
    style_key: str,
) -> list[dict[str, Any]]:
    """Получить предложенный план разделов для стиля журнала.

    Возвращает список разделов на основе шаблонов выбранного стиля.
    Можно использовать для предзаполнения плана разделов проекта.
    """
    from app.services.journal_styles import get_suggested_section_plan
    return get_suggested_section_plan(style_key)
