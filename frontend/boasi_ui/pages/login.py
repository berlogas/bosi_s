"""Экран входа (Фаза 8).

Форма логина и пароля — единственная точка входа в интерфейс. Регистрации
нет: учётные записи создаёт администратор, а забытый пароль восстанавливается
из командной строки.

Список логинов здесь не показываем: чтобы его вывести, пришлось бы открыть
эндпоинт, доступный всем, кто дотянется до API, — то есть перечисление имён
ради удобства. Логины видны администратору в панели и в выводе скрипта
запуска, а пароли не показываются никогда.
"""

from __future__ import annotations

import streamlit as st

from boasi_ui import state
from boasi_ui.api import ApiError


def render() -> None:
    st.markdown("### Вход в boasi_s")
    st.caption("Локальная платформа для научной работы")

    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("Логин", key="login_username",
                                 placeholder="имя пользователя",
                                 autocomplete="username")
        password = st.text_input("Пароль", type="password", key="login_password",
                                 placeholder="пароль",
                                 autocomplete="current-password")
        submitted = st.form_submit_button("Войти", type="primary",
                                         key="login_submit")

    if not submitted:
        st.caption(
            "Логин и пароль выдаёт администратор. Регистрации нет.")
        with st.expander("Нет доступа?", expanded=False):
            st.markdown(
                "1. Создать администратора (если система пустая):\n"
                "   `./scripts/start.sh admin <логин>`\n"
                "2. Восстановить пароль:\n"
                "   `./scripts/start.sh password <логин>`\n"
                "3. Посмотреть список пользователей:\n"
                "   `./scripts/start.sh users`")
        return

    if not username or not password:
        st.warning("Заполните оба поля: логин и пароль.")
        return

    try:
        user = state.api().login(username.strip(), password)
    except ApiError as exc:
        st.error(exc.message)
        if exc.status == 401:
            st.caption("Сессия истекла — войдите заново.")
        st.caption("Забыли пароль? "
                   "`./scripts/start.sh password <логин>`")
        return

    state.set_login(user)
    st.session_state["page"] = "dashboard"
    st.success(f"Здравствуйте, {user['username']}!")
    st.rerun()


def logout_button() -> None:
    user = state.current_user()
    st.sidebar.caption(f"👤 {user.get('username', '?')} "
                       f"({user.get('role', '')})")
    if st.sidebar.button("Выйти", use_container_width=True, key="logout_btn"):
        state.logout()
        st.session_state["page"] = "login"
        st.rerun()