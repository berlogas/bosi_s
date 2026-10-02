#!/usr/bin/env python3
"""Восстановление пароля пользователя из командной строки.

Нужно, когда пароль забыт или утерян: через интерфейс это невозможно —
вход требует пароля, а создание пользователей доступно только админу.

    python backend/scripts/reset_password.py ivanov
    python backend/scripts/reset_password.py ivanov --password "новый-пароль"
    python backend/scripts/reset_password.py --list

Заодно сбрасывает активные refresh-токены: после смены пароля старые сессии
должны быть вынуты.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core.security import hash_password  # noqa: E402
from app.db.models import RefreshToken, User, utcnow  # noqa: E402
from app.db.repositories.users import get_user_by_username  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402


def list_users() -> int:
    with get_session_factory()() as db:
        users = db.query(User).order_by(User.created_at).all()
        if not users:
            print("Пользователей нет.")
            return 1
        print(f"Пользователей: {len(users)}\n")
        for user in users:
            state = "активен" if user.is_active else "ЗАБЛОКИРОВАН"
            last = user.last_login_at.strftime("%Y-%m-%d %H:%M") if user.last_login_at else "ни разу"
            print(f"  {user.username:<20} {user.role.value:<11} {state:<12} создан {user.created_at:%Y-%m-%d}  вход: {last}")
    return 0


def reset(username: str, password: str | None) -> int:
    with get_session_factory()() as db:
        user = get_user_by_username(db, username)
        if user is None:
            print(f"Пользователь «{username}» не найден.", file=sys.stderr)
            print("Список пользователей: reset_password.py --list", file=sys.stderr)
            return 1

        if not password:
            password = getpass.getpass(f"Новый пароль для {username}: ")
            if len(password) < 8:
                print("Пароль короче 8 символов.", file=sys.stderr)
                return 1
            confirm = getpass.getpass("Подтвердите пароль: ")
            if password != confirm:
                print("Пароли не совпадают.", file=sys.stderr)
                return 1

        user.hashed_password = hash_password(password)
        user.updated_at = utcnow()
        # пароль сменился — прежние refresh-токены больше не действуют
        revoked = (db.query(RefreshToken)
                     .filter(RefreshToken.user_id == user.id,
                             RefreshToken.revoked_at.is_(None))
                     .update({"revoked_at": utcnow()}, synchronize_session=False))
        db.commit()
        print(f"Пароль пользователя «{username}» изменён.")
        print(f"Отозвано активных refresh-токенов: {revoked}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Восстановление пароля")
    parser.add_argument("username", nargs="?", help="Логин пользователя")
    parser.add_argument("--password", help="Новый пароль (иначе спросит интерактивно)")
    parser.add_argument("--list", action="store_true", help="Показать всех пользователей")
    args = parser.parse_args()

    if args.list:
        return list_users()
    if not args.username:
        parser.print_help()
        return 1
    return reset(args.username, args.password)


if __name__ == "__main__":
    raise SystemExit(main())