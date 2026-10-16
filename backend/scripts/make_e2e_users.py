#!/usr/bin/env python3
"""Заводит пользователей для e2e проверки многопользовательского режима.

    python backend/scripts/make_e2e_users.py          # создать, если нет
    python backend/scripts/make_e2e_users.py --list   # показать

Пароль у всех одинаковый (`mu-pass-123`) — стенд локальный, эти учётки
не для боевого контура. Скрипт идемпотентен: повторный запуск ничего не
ломает, поэтому его можно держать в дежурных командах перед e2e.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core.security import hash_password  # noqa: E402
from app.db.models import Role  # noqa: E402
from app.db.repositories.users import create_user, get_user_by_username  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402

PASSWORD = "mu-pass-123"

# Два исследователя и админ: ровно те роли, которые проверяет
# webapp/e2e/multiuser.spec.ts.
USERS = [
    ("mu_ivan", Role.researcher),
    ("mu_petr", Role.researcher),
    ("mu_admin", Role.admin),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="только показать")
    args = parser.parse_args()

    db = get_session_factory()()
    for username, role in USERS:
        existing = get_user_by_username(db, username)
        if args.list:
            state = "есть" if existing else "нет"
            print(f"{username:10} {role.value:12} {state}")
            continue
        if existing:
            print(f"{username}: уже есть, пропускаем")
            continue
        create_user(db, username=username, password=PASSWORD, role=role,
                    hashed_password=hash_password(PASSWORD))
        db.commit()
        print(f"{username}: создан ({role.value})")

    if not args.list:
        print(f"\nПароль всех: {PASSWORD}")
        print("Дальше: cd webapp && npx playwright test e2e/multiuser.spec.ts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())