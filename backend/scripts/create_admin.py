#!/usr/bin/env python3
"""Создание первого администратора (или любого пользователя с ролью admin)."""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core.security import hash_password
from app.db.models import Role
from app.db.repositories.users import create_user, get_user_by_username
from app.db.session import get_session_factory


def main() -> int:
    parser = argparse.ArgumentParser(description="Создание пользователя с ролью admin")
    parser.add_argument("username", nargs="?", help="Имя пользователя")
    parser.add_argument("--password", help="Пароль")
    parser.add_argument("--email", help="Email")
    parser.add_argument("--full-name", help="ФИО")
    args = parser.parse_args()

    username = args.username or input("Имя пользователя: ").strip()
    if not username:
        print("Ошибка: username обязателен", file=sys.stderr)
        return 1
    password = args.password
    if not password:
        password = getpass.getpass("Пароль (мин. 8 символов): ")
        confirm = getpass.getpass("Подтвердите пароль: ")
        if password != confirm:
            print("Пароли не совпадают", file=sys.stderr)
            return 1
    if len(password) < 8:
        print("Ошибка: пароль должен быть не короче 8 символов", file=sys.stderr)
        return 1

    session_factory = get_session_factory()
    with session_factory() as db:
        if get_user_by_username(db, username):
            print(f"Пользователь «{username}» уже существует", file=sys.stderr)
            return 1
        user = create_user(
            db,
            username=username,
            password=password,
            role=Role.admin,
            email=args.email,
            full_name=args.full_name,
            hashed_password=hash_password(password),
        )
        print(f"Администратор {user.username} (id={user.id}) успешно создан")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
