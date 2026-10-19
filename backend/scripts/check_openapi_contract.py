#!/usr/bin/env python3
"""Сверка `webapp/openapi/spec.json` с приложением backend.

Файл спецификации — звено в цепочке «код → `openapi/spec.json` → `schema.ts`»,
поэтому его устаревание всплывает только на сборке фронта
(`npm run codegen:check`). Скрипт ловит это на backend.

Сравниваются РАЗОБРАННЫЕ JSON, а не файлы: одинаковый контракт может
сериализоваться по-разному (порядок ключей, переводы строк, чуть свежая
версия FastAPI). Байтовое сравнение давало ложные падения.

Одна реализация на два места вызова: CI-шаг и тест
`tests/test_openapi_contract.py`. Пока код жил только в пайплайне, его
падение объяснить было нечем — причина уходила в лог шага, а логи читаются
не у всех. Теперь отчёт печатается в stdout, в `$GITHUB_STEP_SUMMARY` и в
`::error`-аннотацию, а файл отчёта уезжает артефактом.

Запуск::

    python scripts/check_openapi_contract.py          # 0 — совпало, 1 — расхождение
    python scripts/check_openapi_contract.py --quiet  # молчать, если совпало
    python scripts/check_openapi_contract.py --report build/openapi.md

Код 2 означает, что сверку не удалось выполнить вовсе (файл спецификации не
прочитан, приложение не импортировалось) — в отчёте тогда трейсбек.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

SPEC_PATH = REPO_ROOT / "webapp" / "openapi" / "spec.json"


def apply_runtime_env() -> None:
    """Выставить настройки, без которых `from app.main import app` не проходит.

    Приложение при импорте создаёт `Settings`, а `validate_runtime()` требует
    непустой SECRET_KEY. На машине разработчика это спасает `.env`; в CI его
    нет, и сверка падала не с расхождением, а с трейсбеком импорта (код
    выхода 2) — три прогона подряд, и причина уходила в лог шага.

    Функция общая на скрипт и фикстуру `tests/conftest.py`: значения тестового
    окружения заданы в одном месте, иначе сверка в pytest и вне pytest
    проверяли бы разное. Значения ставятся принудительно — сверка должна быть
    воспроизводимой и не зависеть от того, что лежит в локальном `.env`.
    """
    data_dir = Path(os.environ.get("BOASI_TEST_DATA", REPO_ROOT / ".test_data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ.update(
        ENVIRONMENT="test",
        DATA_DIR=str(data_dir),
        DATABASE_URL=f"sqlite:///{(data_dir / 'test.sqlite3').as_posix()}",
        SECRET_KEY="test-secret-key-0123456789",
        LLM_MODEL="ollama/qwen2.5:3b",
        EMBEDDING_MODEL="st-multi-qa-MiniLM-L6-cos-v1",
        LOG_LEVEL="WARNING",
    )
REGENERATE_HINT = (
    "починить: cd webapp && npm run codegen "
    "&& git add openapi/spec.json src/api/schema.ts"
)

# Отчёт печатается по-русски, а локаль консоли на машине разработчика и на
# раннере CI не обязана быть UTF-8: с cp1251 печать упала бы UnicodeEncodeError
# и унесла с собой отчёт, ради которого этот скрипт написан.
for _stream in (sys.stdout, sys.stderr):
    if getattr(_stream, "encoding", "").lower().replace("-", "") not in ("utf8", ""):
        with contextlib.suppress(AttributeError, ValueError):
            _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

MAX_SHOWN = 3  # сколько расхождений печатать целиком
MAX_CHARS = 400  # насколько подробно печатать фрагмент
MAX_ANNOTATION_CHARS = 300  # длиннее — только в отчёте, GitHub обрежет и при 10 аннотациях
MAX_ANNOTATIONS = 8  # GitHub показывает не больше десяти аннотаций на шаг, берём с запасом


def default_report_path() -> Path:
    """Каталог артефактов тот же, что у тестов (BOASI_TEST_DATA)."""
    data_dir = Path(os.environ.get("BOASI_TEST_DATA", REPO_ROOT / ".test_data"))
    return data_dir.resolve() / "openapi_diff.md"


def _paths(spec: dict[str, Any]) -> dict[str, Any]:
    return spec.get("paths") or {}


def _schemas(spec: dict[str, Any]) -> dict[str, Any]:
    return (spec.get("components") or {}).get("schemas") or {}


def _fragment(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + "…"


def _named(keys: list[str]) -> str:
    return ", ".join(keys) if keys else "нет"


def diff_report(committed: dict[str, Any], actual: dict[str, Any]) -> str:
    """Человекочитаемое описание расхождения.

    Пустая строка означает, что контракт совпал. Строки начинаются с маркера
    `::` только в публикуемом виде — здесь обычный текст, его читает и тест,
    и человек в логе CI.
    """
    if committed == actual:
        return ""

    lines = [f"эндпоинтов: было {len(_paths(committed))}, стало {len(_paths(actual))}"]

    committed_paths, actual_paths = _paths(committed), _paths(actual)
    gone = sorted(set(committed_paths) - set(actual_paths))
    new = sorted(set(actual_paths) - set(committed_paths))
    lines.append(f"пропали: {_named(gone)}")
    lines.append(f"новые: {_named(new)}")

    # Один и тот же путь может измениться по существу: параметр, код ответа,
    # описание операции. Их показываем отдельно от добавленных и удалённых.
    touched = sorted(
        key
        for key in set(committed_paths) & set(actual_paths)
        if committed_paths[key] != actual_paths[key]
    )
    lines.append(f"изменились: {_named(touched)}")
    for key in touched[:MAX_SHOWN]:
        lines.append(f"в файле {key}: {_fragment(committed_paths[key])}")
        lines.append(f"из кода {key}: {_fragment(actual_paths[key])}")

    committed_schemas, actual_schemas = _schemas(committed), _schemas(actual)
    differing = [
        key
        for key in sorted(set(committed_schemas) | set(actual_schemas))
        if committed_schemas.get(key) != actual_schemas.get(key)
    ]
    lines.append(f"различаются схемы ({len(differing)}): {_named(differing)}")
    for key in differing[:MAX_SHOWN]:
        lines.append(f"в файле схема {key}: {_fragment(committed_schemas.get(key))}")
        lines.append(f"из кода схема {key}: {_fragment(actual_schemas.get(key))}")

    other = sorted(
        key
        for key in set(committed) | set(actual)
        if key not in ("paths", "components") and committed.get(key) != actual.get(key)
    )
    if other:
        lines.append(f"различаются прочие разделы: {_named(other)}")

    if len(touched) > MAX_SHOWN or len(differing) > MAX_SHOWN:
        lines.append(
            f"показаны первые {MAX_SHOWN} из каждого списка; полный список расхождений — "
            "в файле отчёта и в webapp/openapi/spec.json"
        )
    lines.append(REGENERATE_HINT)
    return "\n".join(lines)


def load_committed() -> dict[str, Any]:
    """Спецификация из репозитория — эталон, с которым сверяем код."""
    with open(SPEC_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def load_actual() -> dict[str, Any]:
    """Спецификация из приложения.

    Настройки выставляются здесь, а не фикстурой conftest: скрипт зовут и из
    CI-шага, где pytest нет вообще. Импорт остаётся внутри функции — до
    `apply_runtime_env()` настройки не заданы.
    """
    apply_runtime_env()
    from app.config import reset_settings_cache

    reset_settings_cache()
    from app.main import app

    return app.openapi()


def check() -> str:
    """Сверить и вернуть отчёт (пустая строка — совпало)."""
    return diff_report(load_committed(), load_actual())


def write_report(text: str, path: Path | None = None) -> Path | None:
    """Положить отчёт в файл, чтобы он уехал артефактом CI."""
    if not text:
        return None
    target = path or default_report_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"# OpenAPI разошёлся с кодом\n\n```\n{text}\n```\n", encoding="utf-8")
    return target


def publish(text: str, *, title: str, headline: str | None = None) -> None:
    """Отчёт в stdout и в аннотации GitHub.

    Аннотации (`::error`) читаются через Checks API без прав администратора, в
    отличие от логов и артефактов, поэтому дублируем расхождение туда. Символ
    `%` в workflow-команде экранируется, иначе хвост сообщения отбрасывается.

    `headline` — короткое объяснение причины (например, «сверку не удалось
    выполнить: TypeError: ...»), которое печатается ПЕРВОЙ аннотацией.
    Трекбек идёт после, и обрезается: GitHub показывает не больше десяти
    аннотаций на шаг, а в обрезанном виде остаются середина стека, где нет ни
    типа, ни текста исключения. Именно так выглядел прогон 2026-10-19: девять
    аннотаций из трейсбека, и ни одна не говорила, что именно сломалось.

    Длинные строки (фрагменты схем) в аннотации не идут: длиннее
    ``MAX_ANNOTATION_CHARS`` GitHub обрезает, а читать их удобнее в сводке
    прогона и в файле отчёта.
    """
    print(text)
    lines = text.splitlines()
    if headline:
        print(f"::error title={title}::{headline.replace('%', '%25')}")
    short = [line for line in lines if len(line) <= MAX_ANNOTATION_CHARS]
    for line in short[:MAX_ANNOTATIONS]:
        print(f"::error title={title}::{line.replace('%', '%25')}")
    rest = len(short) - MAX_ANNOTATIONS
    if rest > 0:
        print(
            f"::error title={title}::ещё {rest} строк отчёта — в сводке прогора "
            "и в артефакте pytest-report (.test_data/openapi_diff.md)"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Сверка openapi/spec.json с кодом backend")
    parser.add_argument("--quiet", action="store_true", help="ничего не печатать при совпадении")
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help=f"куда писать отчёт (по умолчанию {default_report_path()})",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help=f"перезаписать эталон {SPEC_PATH} схемой из кода и выйти",
    )
    args = parser.parse_args(argv)

    if args.write:
        apply_runtime_env()
        from app.config import reset_settings_cache

        reset_settings_cache()
        from app.main import app

        SPEC_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Порядок ключей и переводы строк — как в эталоне: FastAPI отдаёт
        # openapi/info/paths в своём порядке, и sort_keys переставил бы весь
        # файл, превращая точечное обновление в diff на семь тысяч строк.
        # На Windows переводы строк LF явно, иначе git с core.autocrlf
        # перепишет весь файл при добавлении в индекс.
        SPEC_PATH.write_bytes(
            (json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n")
            .replace("\r\n", "\n")
            .encode("utf-8")
        )
        print(f"Спецификация обновлена: {SPEC_PATH}")
        print("дальше: cd webapp && npm run codegen")
        return 0

    try:
        report = check()
    except Exception as exc:  # причина нужна в отчёте: в логе шага её никто не читает
        report = "\n".join(
            [
                "сверку выполнить не удалось:",
                "",
                traceback.format_exc().rstrip(),
            ]
        )
        headline = (
            f"сверку выполнить не удалось: {type(exc).__name__}: {exc}"
        )[:MAX_ANNOTATION_CHARS]
        exit_code = 2
    else:
        headline = None
        exit_code = 1 if report else 0

    if exit_code == 0:
        if not args.quiet:
            print("Спецификация совпадает с кодом")
        return 0

    publish(report, title="Контракт OpenAPI разошёлся с кодом", headline=headline)
    saved = write_report(report, args.report)
    if saved is not None:
        print(f"Отчёт: {saved}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(f"## Контракт OpenAPI разошёлся с кодом\n\n```\n{report}\n```\n")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())