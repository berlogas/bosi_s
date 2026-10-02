"""Логин (Фаза 8).

Страница намеренно простая: логин, пароль и подсказка про первоначальную
настройку. Регистрации нет — пользователей создаёт администратор.
"""

from __future__ import annotations

import streamlit as st

from boasi_ui import state
from boasi_ui.api import ApiError


def render() -> None:
    st.markdown("### Вход")
    st.caption("Локальная платформа для научной работы")

    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("Логин", key="login_username",
                                 autocomplete="username")
        password = st.text_input("Пароль", type="password", key="login_password",
                                 autocomplete="current-password")
        submitted = st.form_submit_button("Войти", type="primary",
                                          key="login_submit")

    if not submitted:
        return

    if not username or not password:
        st.warning("Введите логин и пароль.")
        return

    try:
        user = state.api().login(username.strip(), password)
    except ApiError as exc:
        st.error(exc.message)
        return

    state.set_login(user)
    st.session_state["page"] = "dashboard"
    st.success(f"Здравствуйте, {user['username']}!")
    st.rerun()


def logout_button() -> None:
    user = state.current_user()
    st.sidebar.caption(f"👤 {user.get('username', '?')} "
                       f"({user.get('role', '')})")
    if st.sidebar.button("Выйти", use_container_width=True):
        state.logout()
        st.session_state["page"] = "login"
        st.rerun()