"""Контракт OpenAPI не должен отставать от кода backend.

`webapp/openapi/spec.json` — звено между кодом и типами фронта: из него
генерируется `src/api/schema.ts`, и устаревший файл всплыл бы только на
сборке фронта. Проверка живёт здесь, а не только в CI-шаге, потому что
`make test` теперь ловит расхождение до пуша, на своей машине.

Разбор расхождения и публикация отчёта — в
`scripts/check_openapi_contract.py`: реализация одна, чтобы проверка в тесте
и в пайплайне не разъехалась.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR / "scripts") not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR / "scripts"))

from check_openapi_contract import (  # noqa: E402
    SPEC_PATH,
    diff_report,
    load_actual,
    load_committed,
    publish,
    write_report,
)


def test_openapi_spec_matches_code(_test_settings) -> None:
    """Схема в репозитории равна схеме, которую отдаёт приложение."""
    report = diff_report(load_committed(), load_actual())
    if report:
        write_report(report)  # отчёт уедет артефактом CI, локально останется в .test_data
    assert not report, (
        f"{SPEC_PATH} разошёлся с кодом:\n\n{report}"
    )


def test_diff_report_names_changed_schema() -> None:
    """Отчёт называет расхождение и подсказывает, что делать.

    Проверка самого отчёта: он молчал всё время, пока расхождение искали
    глазами в CI, — пустой или бессодержательный отчёт хуже падения.
    """
    report = diff_report(
        {"paths": {"/a": {"get": {"summary": "A"}}}, "components": {"schemas": {"S": {"type": "object"}}}},
        {"paths": {"/a": {"get": {"summary": "A (правка)"}}}, "components": {"schemas": {"S": {"type": "string"}}}},
    )

    assert "изменились: /a" in report
    assert "правка" in report
    assert "различаются схемы (1): S" in report
    assert "npm run codegen" in report


def test_diff_report_empty_when_specs_equal() -> None:
    """Совпадение контрактов не порождает отчёт — иначе CI краснеет впустую."""
    spec = {"paths": {"/a": {"get": {"summary": "A"}}}, "components": {"schemas": {"S": {"type": "object"}}}}

    assert diff_report(spec, spec) == ""


def test_annotations_lead_with_cause(capsys: pytest.CaptureFixture[str]) -> None:
    """Первая аннотация объясняет причину, а не содержит середину стека.

    GitHub отдаёт не больше десяти аннотаций на шаг и обрезает длинные, поэтому
    трейсбек в аннотациях обрывался на файлах и строках, и ни одна строка не
    говорила, что именно сломалось — прогон 2026-10-19. Причина отдельной
    строкой идёт первой.
    """
    publish(
        "сверку выполнить не удалось:\n\nTraceback (most recent call last):\n  ...\nValueError: ключ не найден",
        title="Контракт OpenAPI разошёлся с кодом",
        headline="сверку выполнить не удалось: ValueError: ключ не найден",
    )

    errors = [line for line in capsys.readouterr().out.splitlines() if line.startswith("::error")]
    assert errors
    assert "ValueError: ключ не найден" in errors[0]