#!/usr/bin/env python3
"""Сброс состояния платформы из командной строки.

    python scripts/reset_state.py                      # план сброса данных
    python scripts/reset_state.py --scope users        # план сброса входов
    python scripts/reset_state.py --scope data --yes   # выполнить

По умолчанию ничего не удаляется — печатается план (таблицы, строки, каталоги,
байты). Реальное удаление требует явного `--yes` и фразы подтверждения.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core.errors import AppError  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402
from app.services.reset import CONFIRM_PHRASES, SCOPES, plan_reset, run_reset  # noqa: E402


def _human_bytes(size: int) -> str:
    value = float(size)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if value < 1024 or unit == "ГБ":
            return f"{value:.1f} {unit}" if unit != "Б" else f"{int(value)} {unit}"
        value /= 1024
    return f"{value:.1f} ГБ"


def _print_plan(plan) -> None:  # noqa: ANN001
    print(f"Сброс: scope={plan.scope}")
    if plan.blocked_reason:
        print(f"  ЗАПРЕЩЕНО: {plan.blocked_reason}")
    if plan.tables:
        print("  Таблицы (строк):")
        for name, rows in plan.tables.items():
            print(f"    {name:<22} {rows}")
    if plan.paths:
        print("  Каталоги:")
        for item in plan.paths:
            print(f"    {item.path:<40} {item.files} файлов, "
                  f"{_human_bytes(item.bytes)}")
    if plan.kept_paths:
        print("  Не трогаем (кэш моделей, нужен для эмбеддингов):")
        for path in plan.kept_paths:
            print(f"    {path}")
    print(f"  Итого: {plan.rows} строк, {plan.files} файлов, "
          f"{_human_bytes(plan.total_bytes)}")
    print(f"  Для подтверждения введите: {CONFIRM_PHRASES.get(plan.scope, '')}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Сброс состояния boasi_s (по умолчанию — только план)")
    parser.add_argument("--scope", choices=list(SCOPES), default="data",
                        help="data — контент; users — контент и входы; "
                             "all — полностью пустая платформа")
    parser.add_argument("--yes", action="store_true",
                        help="выполнить удаление (без флага печатается план)")
    parser.add_argument("--confirm", default="",
                        help=f"фраза подтверждения: {CONFIRM_PHRASES.get('data')!r}")
    parser.add_argument("--include-models", action="store_true",
                        help="дополнительно удалить кэш моделей (HF_HOME/TORCH_HOME); "
                             "после этого нужен повторный download модели эмбеддингов")
    parser.add_argument("--json", action="store_true", help="вывод в JSON")
    args = parser.parse_args()

    phrase = CONFIRM_PHRASES[args.scope]
    if args.yes and args.confirm.strip() != phrase:
        print(f"Ошибка: для --scope {args.scope} нужна фраза подтверждения "
              f"{phrase!r} (--confirm)", file=sys.stderr)
        return 2

    factory = get_session_factory()
    try:
        with factory() as db:
            plan = plan_reset(args.scope, include_models=args.include_models, db=db)
            if not args.json:
                _print_plan(plan)
            if not plan.allowed:
                if args.json:
                    print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2))
                return 1
            if not args.yes:
                if args.json:
                    print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2))
                print("\nЭто был план. Повторите с --yes --confirm " + repr(phrase))
                return 0

            result = run_reset(args.scope, dry_run=False,
                               include_models=args.include_models, db=db,
                               meta={"source": "cli"})
    except AppError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"\nOK: удалено {sum(result.deleted_tables.values())} строк, "
              f"{len(result.deleted_paths)} каталогов, "
              f"{_human_bytes(result.freed_bytes)}")
        print("База остаётся пустой: загрузите документы заново "
              "или выполните `make reindex`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())