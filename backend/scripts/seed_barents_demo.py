"""Засев демо-проекта про Баренцево море: ручное тестирование без загрузки.

Демонстрационные материалы лежат в `demo/barents-article/`: три статьи, CSV со
станциями и черновик. Загружать их через интерфейс каждый раз не нужно, а без
привязанных документов проект нечего генерировать.

Скрипт идемпотентен: при повторном запуске он не плодит проекты, а только
добирает недостающее — стиль, привязки документов, план разделов.

    ../.venv/Scripts/python.exe scripts/seed_barents_demo.py            # проект по умолчанию
    ../.venv/Scripts/python.exe scripts/seed_barents_demo.py --fresh    # отдельный чистый проект

`--fresh` нужен для проверки с нуля: у проекта с уже сгенерированными
разделами повторная генерация того же раздела с тем же вопросом отдаёт
прошлую версию из кэша, и легко решить, что стиль не сработал.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.models import Document, DocumentLink, Project, ProjectDocRole, ResearchSession
from app.db.session import session_scope
from app.services.generation import DEFAULT_SECTIONS
from app.services.journal_styles import find_style

DEMO_ROOT = Path(__file__).resolve().parents[2] / "demo" / "barents-article"

SESSION_TITLE = "Фитопланктон Баренцева, 2026"
PROJECT_TITLE = "Весенний фитопланктон Баренцева моря: хлорофилл-а и биомасса"

# Стиль группы, а не название журнала: «Ocean Science» в справочнике нет, и
# промпт стиля не подставился бы. У группы есть шаблоны Results и
# Discussion — их и проверяют в первую очередь.
DEFAULT_STYLE = "specialized_top"

# (файл в demo, роль в проекте)
DEMO_FILES = [
    ("literature/ref1_annesen_2009_chlorophyll.md", "reference"),
    ("literature/ref2_havskjold_2014_biomass.md", "reference"),
    ("literature/ref3_wassmann_1998_algorithms.md", "reference"),
    ("data/barents_stations_2026.csv", "data"),
    ("draft/черновик_статьи.md", "draft"),
]


def _find_demo_document(db, relative: str) -> Document | None:  # noqa: ANN001
    """Документ demo по имени файла: у загруженных файлов в `filename`
    остаётся dockey-префикс, поэтому сверяем и по нему, и по имени."""
    wanted = Path(relative).name.lower()
    tail = wanted.split("_", 1)[-1]
    for document in db.query(Document).all():
        if document.status.value != "ready":
            continue
        filename = (document.filename or "").lower()
        if tail in filename or Path(filename).name.lower() == wanted:
            return document
    return None


def _plan_sections() -> list[dict[str, object]]:
    """План разделов проекта: список, а не JSON-строка.

    Колонка JSON-типа сама сериализует значение; сохранённая строка потом
    читалась бы как список символов, и план молча рассыпался бы.
    """
    return [dict(section) for section in DEFAULT_SECTIONS]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fresh", action="store_true",
                        help="создать отдельный проект без готовых разделов")
    args = parser.parse_args()

    title = f"{PROJECT_TITLE} (ручной тест)" if args.fresh else PROJECT_TITLE
    style_key = DEFAULT_STYLE
    style = find_style(style_key)
    if style is None:
        raise SystemExit(f"группа стилей {style_key!r} не найдена в справочнике")

    with session_scope() as db:
        session = db.query(ResearchSession).filter(
            ResearchSession.title == SESSION_TITLE).first()
        if session is None:
            raise SystemExit(
                f"сессия {SESSION_TITLE!r} не найдена — загрузите документы "
                "через интерфейс или создайте сессию с таким названием")

        project = db.query(Project).filter(
            Project.session_id == session.id,
            Project.title == title).first()
        created = project is None
        if project is None:
            project = Project(
                session_id=session.id,
                title=title,
                target_journal=style_key,
                sections=_plan_sections(),
                status="planning")
            db.add(project)
            db.flush()
            print(f"создан проект {project.id} — {title}")
        else:
            if project.target_journal != style_key:
                project.target_journal = style_key
                print(f"стиль проекта: {style.title}")
            if not project.sections:
                project.sections = _plan_sections()
                print("добавлен план разделов по умолчанию")

        # Документы опознаются по dockey-префиксу в имени файла: он уже
        # есть в `documents.filename` после загрузки, а сам файл лежит в
        # хранилище. Повторная загрузка того же файла создала бы дубль.
        bound, missing = 0, []
        for relative, role in DEMO_FILES:
            if not (DEMO_ROOT / relative).is_file():
                missing.append(f"нет файла {relative}")
                continue
            document = _find_demo_document(db, relative)
            if document is None:
                missing.append(f"нет документа {relative} в базе")
                continue
            already = db.query(DocumentLink).filter(
                DocumentLink.project_id == project.id,
                DocumentLink.document_id == document.id).first()
            if already is not None:
                continue
            db.add(DocumentLink(
                document_id=document.id, session_id=session.id,
                project_id=project.id, role=ProjectDocRole(role),
                relation="cites"))
            bound += 1
        for note in missing:
            print(f"ПРОПУЩЕНО: {note}")
        print(f"привязано документов: {bound}" if bound
              else "документы уже привязаны")

        print(f"\nсессия:  {session.id}")
        print(f"проект: {project.id}")
        print(f"стиль:  {style.title} ({style_key})")
        print(f"статус: {'создан' if created else 'обновлён'}")
        print(f"\nОткрыть: /s/{session.id}/projects")


if __name__ == "__main__":
    main()