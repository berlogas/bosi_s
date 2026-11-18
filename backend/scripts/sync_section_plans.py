#!/usr/bin/env python3
"""Создать планы разделов (SectionPlan) для проектов, где их ещё нет.

Зачем. Старая модель хранила текст разделов в `projects.sections` (JSON),
новая — в `section_plans` + `section_versions`. Интерфейс читает новую
модель, поэтому проект, написанный до перехода, выглядит пустым: раздел
есть, текст есть, а показать его не из чего.

Скрипт переносит текст старой модели в новую: для каждого раздела создаётся
план, а его содержимое — версия (черновик), которая становится текущей.
Обратная связь уже есть: новая генерация сама пишет текст в
`projects.sections` (`SectionAgent._sync_to_project_json`).

Скрипт идемпотентен: у плана, у которого уже есть текущая версия, текст не
трогается; повторный запуск ничего не меняет.

    python backend/scripts/sync_section_plans.py             # перенести
    python backend/scripts/sync_section_plans.py --dry-run   # только показать
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import get_session_factory  # noqa: E402
from app.db.models import (  # noqa: E402
    Project,
    SectionKind,
    SectionPlan,
    SectionStatus,
    SectionVersion,
    VersionStatus,
    new_id,
)
from app.services.generation import normalize_sections  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Создать SectionPlan для проектов без плана разделов"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="ничего не менять, только показать")
    args = parser.parse_args()

    db = get_session_factory()()
    try:
        projects = db.query(Project).all()
        created_plans = 0
        created_versions = 0
        skipped = 0

        for project in projects:
            sections = normalize_sections(project.sections)
            if not sections:
                continue

            by_name = {plan.name.lower(): plan for plan in project.section_plans}
            changed = False

            for index, section in enumerate(sections):
                name = section["name"]
                content = section.get("content_md") or ""
                plan = by_name.get(name.lower())

                if plan is None:
                    created_plans += 1
                    print(f"  + план «{name}» (проект {project.id[:8]})")
                    if args.dry_run:
                        if content.strip():
                            created_versions += 1
                            print(f"  + версия «{name}» ({len(content)} симв.)")
                        continue
                    plan = SectionPlan(
                        id=new_id(),
                        project_id=project.id,
                        name=name,
                        kind=SectionKind.standard,
                        order=int(section.get("order") or index + 1),
                        required=bool(section.get("required", True)),
                        word_target=int(section.get("word_target") or 500),
                        word_min=max(100, int(section.get("word_target") or 500) // 2),
                        word_max=int(section.get("word_target") or 500) * 4,
                        notes=section.get("notes") or "",
                        language=project.language or "ru",
                        depends_on=[],
                        status=SectionStatus.pending,
                    )
                    db.add(plan)
                    db.flush()
                    by_name[name.lower()] = plan
                    changed = True

                if not content.strip():
                    continue
                if plan.current_version_id:
                    skipped += 1
                    continue

                created_versions += 1
                print(f"  + версия «{name}» ({len(content)} симв.)")
                if args.dry_run:
                    continue

                version = SectionVersion(
                    id=new_id(),
                    section_plan_id=plan.id,
                    project_id=project.id,
                    session_id=project.session_id,
                    content_md=content,
                    language=plan.language,
                    word_count=len(content.split()),
                    citation_map=[],
                    generation_params={"source": "migration"},
                    quality_report={},
                    # Текст из старой модели написан и закончен — версия одобрена.
                    status=VersionStatus.approved,
                )
                db.add(version)
                db.flush()
                plan.current_version_id = version.id
                plan.status = SectionStatus.review
                changed = True

            if changed and not args.dry_run:
                db.commit()
            elif changed:
                db.rollback()

        print(
            f"планов создано: {created_plans}, версий создано: {created_versions}, "
            f"пропущено (уже есть текущая версия): {skipped}"
        )
        if args.dry_run:
            print("режим --dry-run: изменения не записаны")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
