"""Сравнение стилей журналов на одном и том же материале.

Задача шаблона — не «красиво», а предсказуемо: один и тот же раздел в разных
стилях должен отличаться тоном, структурой и строгостью, а не случайно.
Проверяется это одним замером: контекст собирается один раз, а генерация
делается по нему для каждой группы — иначе сравнивать пришлось бы два
разных материала.

    ../.venv/Scripts/python.exe scripts/style_probe.py --section Results
    ../.venv/Scripts/python.exe scripts/style_probe.py --style sound_science \
        --style specialized_top

Результат печатается и складывается в `.run/style_probe.md` — там же
собираются метрики (слова, цитаты, время), по которым видно, что шаблон
вообще применился, а не был молча проигнорирован.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.models import Project, ResearchSession, SearchMode
from app.db.session import session_scope
from app.services import generation as gen
from app.services.journal_styles import find_style, style_prompt, styles
from app.services.paperqa_service import ServiceRegistry
from app.services.rag_service import RagFusionService

REPORT = Path(__file__).resolve().parents[2] / ".run" / "style_probe.md"

# Проект по умолчанию — тот, где есть материал и рукопись.
DEFAULT_PROJECT = "95e827bc-c046-4ffc-a129-64869163b75f"


async def probe(project_id: str, section: str, question: str,
                style_keys: list[str], words: int) -> None:
    registry = ServiceRegistry()

    with session_scope() as db:
        project = db.get(Project, project_id)
        if project is None:
            raise SystemExit(f"проект {project_id} не найден")
        session = db.get(ResearchSession, project.session_id)
        started = time.perf_counter()
        sources, _stats = await RagFusionService(registry).retrieve(
            db, query=question, session_id=session.id,
            mode=SearchMode.project_focus, k=15)
        print(f"источников: {len(sources)} · сборка контекста: "
              f"{time.perf_counter() - started:.1f} с", flush=True)
        if not sources:
            raise SystemExit("в контексте нет источников — сравнивать нечего")

        rows: list[tuple[str, str, float, int, int, str]] = []
        for key in style_keys:
            style = find_style(key)
            title = style.title if style else key
            # Стиль подставляем напрямую: поле проекта здесь не участвует,
            # иначе пришлось бы править его между прогонами.
            text_style = style_prompt(key, section)
            prompt = gen.build_prompt(
                section, question, sources,
                language=registry.app.answer_language,
                word_target=words, style=text_style or None,
                require_citations=gen.citations_required(section))
            started = time.perf_counter()
            text = await registry.session_service(session.id).complete(
                prompt, name="section")
            elapsed = time.perf_counter() - started
            # Проверка цитат обязательна: стиль, забывший про ссылки,
            # даст красивый текст без источников — это провал, а не успех.
            check = gen.validate_citations(
                text, len(sources),
                require_any=gen.citations_required(section))
            words = len(text.split())
            cited = len(gen.CITE_RE.findall(text))
            bad = len(check.dangling)
            print(f"  {title}: {words} слов, цитат {cited}, битых {bad}, "
                  f"{elapsed:.0f} с", flush=True)
            rows.append((title, key, elapsed, words, cited, bad, text))

    _report(section, question, len(sources), rows)


def _report(section: str, question: str, sources: int,
            rows: list[tuple[str, str, float, int, int, int, str]]) -> None:
    """Отчёт в файл: тексты длинные, в консоль не помещаются."""
    lines = [f"# Сравнение стилей: раздел «{section}»",
             "",
             f"Вопрос: {question}",
             "",
             f"Источников в контексте: {sources}. Один и тот же контекст "
             "для всех стилей — различается только промпт.",
             "",
             "| Стиль | Слов | Цитат | Битых ссылок | Секунд |",
             "|---|---:|---:|---:|---:|"]
    for title, _key, elapsed, words, cited, bad, _text in rows:
        lines.append(f"| {title} | {words} | {cited} | {bad} | "
                     f"{elapsed:.0f} |")
    for title, key, elapsed, words, cited, bad, text in rows:
        lines += ["", "---", "", f"## {title} (`{key}`) — {words} слов, {cited} "
                  f"цитат, битых {bad}, {elapsed:.0f} с", "", text, ""]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nотчёт: {REPORT}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--section", default="Results")
    parser.add_argument("--question", default="")
    parser.add_argument("--style", action="append", dest="styles")
    # Объём задаётся отдельно: на локальной модели 1.5B шестьсот слов — это
    # минуты ожидания, а для сравнения стилей хватает короткого текста.
    parser.add_argument("--words", type=int, default=600)
    args = parser.parse_args()

    keys = args.styles or [style.key for style in styles()]
    question = args.question or args.section
    asyncio.run(probe(args.project, args.section, question, keys, args.words))


if __name__ == "__main__":
    main()