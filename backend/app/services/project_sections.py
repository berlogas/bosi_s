"""Разделы проекта из новой модели (`section_plans` + `section_versions`).

Новая модель — источник истины: текст разделов, ссылки и номера цитат
берутся из неё. Старая (`projects.sections`, `project_versions`) осталась
зеркалом для совместимости (её читают старые скрипты и отчёты), но читать
из неё перестали.

Пока планов нет (проект до перехода) — откат на старую модель, чтобы
переход можно было делать по частям.
"""

from __future__ import annotations

from typing import Any

from app.db.models import Project, SectionPlan, SectionVersion
from app.services.generation import normalize_sections


def current_version(plan: SectionPlan) -> SectionVersion | None:
    """Текущая версия плана — та, на которую ссылается `current_version_id`."""
    version_id = getattr(plan, "current_version_id", None)
    if not version_id:
        return None
    for version in getattr(plan, "versions", None) or []:
        if version.id == version_id:
            return version
    return None


def project_sections(project: Project) -> list[dict[str, Any]]:
    """Разделы проекта с текстом — из планов и их текущих версий."""
    plans = sorted(getattr(project, "section_plans", None) or [],
                   key=lambda p: p.order)
    if not plans:
        # Проект ещё не переведён на новую модель — откат на старую.
        return normalize_sections(project.sections)

    sections: list[dict[str, Any]] = []
    for plan in plans:
        version = current_version(plan)
        sections.append({
            "name": plan.name,
            "required": plan.required,
            "order": plan.order,
            "word_target": plan.word_target,
            "notes": plan.notes,
            "content_md": (version.content_md if version else "") or "",
        })
    return sections


def citation_entries(project: Project) -> list[dict[str, Any]]:
    """Записи цитат из текущих версий разделов — источник списка литературы."""
    entries: list[dict[str, Any]] = []
    for plan in getattr(project, "section_plans", None) or []:
        version = current_version(plan)
        if version is not None:
            entries.extend(version.citation_map or [])
    return entries
