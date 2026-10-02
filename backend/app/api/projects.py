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

import logging
import re
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.serializers import document_from_row, project_out
from app.core.errors import NotFoundError
from app.core.security import get_current_user, require_researcher
from app.db.models import (
    GenerationKind,
    Project,
    ProjectDocRole,
    User,
)
from app.db.repositories import documents as docs_repo
from app.db.repositories.users import audit, get_owned_session, touch_session
from app.db.session import get_db
from app.schemas.api import (
    ExportFormat,
    GenerateRequest,
    GenerateResultOut,
    ProjectCreate,
    ProjectDocBind,
    ProjectOut,
    ProjectPatch,
    ProjectSectionOut,
    ProjectSectionUpdate,
    ProjectVersionOut,
)
from app.services import analyses
from app.services import export as export_service
from app.services.generation import missing_sections, normalize_sections
from app.services.projects import (
    GenerationRequest,
    ProjectService,
    find_project,
    linked_documents,
)

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
    projects = db.scalars(
        select(Project).where(Project.session_id == session_id)
        .order_by(Project.updated_at.desc()))
    return [_out(p) for p in projects]


@router.post("/{session_id}/projects", response_model=ProjectOut,
             status_code=status.HTTP_201_CREATED)
def create_project(session_id: str, payload: ProjectCreate, request: Request,
                   user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)) -> ProjectOut:
    session = get_owned_session(db, session_id, user)
    docs_repo.check_project_limit(db, session.id)

    project = Project(
        session_id=session.id,
        title=payload.title.strip(),
        target_journal=payload.target_journal,
        status=payload.status,
        sections=normalize_sections(payload.sections),
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
    sections = normalize_sections(project.sections)
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
    for section in sections:
        if section["name"].lower() == name.lower():
            if payload.notes is not None:
                section["notes"] = payload.notes
            if payload.word_target is not None:
                section["word_target"] = payload.word_target
            if payload.content_md is not None:
                section["content_md"] = payload.content_md
            if payload.required is not None:
                section["required"] = payload.required
            project.sections = sections
            db.commit()
            db.refresh(project)
            audit(db, action="project.section_update", actor=user,
                  target_type="project", target_id=project.id, **_meta(request),
                  section=name)
            return ProjectSectionOut(
                **section, words=len((section.get("content_md") or "").split()),
                written=bool((section.get("content_md") or "").strip()))
    raise NotFoundError(f"Раздел «{name}» не найден в плане проекта")


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
    analysis = analyses.analyze_draft(normalize_sections(project.sections))
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
    sections = normalize_sections(project.sections)
    return {"project_id": project.id, "status": project.status.value,
            **ProjectService.plan_progress(project),
            "missing_sections": missing_sections(sections),
            "versions": len(project.versions)}


# --------------------------------------------------------------------------- экспорт
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