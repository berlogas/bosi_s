#!/usr/bin/env python3
"""Перевести пути файлов в БД из абсолютных в относительные (от DATA_DIR).

Зачем. Каталог данных стал общим для хоста и контейнера (вместо тома), а
путь к нему в средах разный: `N:\\...\\data` на хосте, `/data` в контейнере.
Абсолютный путь в БД привязывает запись к одной машине — в другой среде
документ «исчезает», экспорт не может прочитать файл, reaper не удалит его.

Скрипт идемпотентен: уже относительные пути не трогает, повторный запуск
ничего не меняет.

    python backend/scripts/relocate_paths.py            # перевести
    python backend/scripts/relocate_paths.py --dry-run  # только показать

Скрипт можно запускать и на хосте, и в контейнере: корни, под которые
подставляется путь, берутся из текущего DATA_DIR и из `--extra-root`
(для записей, сделанных в другой среде).
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings  # noqa: E402
from app.core.paths import norm_path, relativize_any  # noqa: E402

# Таблицы и колонки, где лежит путь к файлу.
TARGETS = (
    ("documents", "path"),
    ("inbox_files", "abs_path"),
    ("inbox_files", "final_path"),
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Перевод путей в относительные")
    parser.add_argument("--dry-run", action="store_true",
                        help="ничего не менять, только показать")
    parser.add_argument("--extra-root", action="append", default=[],
                        help="дополнительный корень DATA_DIR (записи из другой среды)")
    args = parser.parse_args()

    settings = get_settings()
    db_path = settings.resolved_db_path
    if db_path is None:
        print("БД не SQLite — нечего делать.", file=sys.stderr)
        return 1

    roots = [str(settings.data_dir), *args.extra_root]
    print(f"корни: {', '.join(roots)}")

    con = sqlite3.connect(db_path)
    changed = 0
    for table, column in TARGETS:
        try:
            rows = con.execute(
                f'SELECT id, "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL'
            ).fetchall()
        except sqlite3.OperationalError:
            continue  # таблицы ещё нет — не страшно
        for row_id, raw in rows:
            if not raw:
                continue
            relative = relativize_any(str(raw), roots)
            if relative is None:
                continue  # путь вне DATA_DIR — переносим он или нет
            new = norm_path(relative)
            if new == raw:
                continue
            print(f"  {table}.{column} {row_id[:8]}: {raw} -> {new}")
            changed += 1
            if not args.dry_run:
                con.execute(
                    f'UPDATE "{table}" SET "{column}" = ? WHERE id = ?', (new, row_id))
    if not args.dry_run:
        con.commit()
    con.close()

    verb = "будет изменено" if args.dry_run else "изменено"
    print(f"записей {verb}: {changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
