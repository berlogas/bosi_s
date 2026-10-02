"""Точка входа Streamlit (Фаза 8).

Роутинг без `st.navigation`, чтобы приложение одинаково работало и в Docker,
и под `streamlit.testing.v1.AppTest` в тестах. Ширина — `wide`, но с
ограничениями, чтобы на 1366×768 не появлялся горизонтальный скролл.
"""

from __future__ import annotations

import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from boasi_ui import state  # noqa: E402
from boasi_ui.api import ApiClient, ApiError  # noqa: E402
from boasi_ui.pages import admin, dashboard, login, workspace  # noqa: E402

st.set_page_config(page_title="boasi_s", page_icon="📚", layout="wide",
                   initial_sidebar_state="expanded")

# Ограничиваем ширину контента: на 1366×768 длинные таблицы и выдача RAG
# иначе дают горизонтальный скролл (требование ТЗ).
st.markdown(
    """
    <style>
      .block-container { max-width: 1180px; padding-left: 2rem; padding-right: 2rem; }
      [data-testid="stSidebar"] { min-width: 220px; }
    </style>
    """,
    unsafe_allow_html=True,
)

state.init_state()


def sidebar() -> None:
    st.sidebar.title("📚 boasi_s")
    if not state.is_authenticated():
        st.sidebar.caption("Войдите, чтобы начать работу.")
        return

    st.sidebar.markdown("**Навигация**")
    if st.sidebar.button("Дашборд", use_container_width=True,
                         key="nav_dashboard"):
        st.session_state["page"] = "dashboard"
        st.rerun()
    if st.sidebar.button("Текущая сессия", use_container_width=True,
                         key="nav_workspace",
                         disabled=not state.current_session_id()):
        st.session_state["page"] = "workspace"
        st.rerun()
    if state.api().is_admin:
        if st.sidebar.button("Администрирование", use_container_width=True,
                             key="nav_admin"):
            st.session_state["page"] = "admin"
            st.rerun()
    st.sidebar.divider()
    login.logout_button()

    with st.sidebar.expander("Состояние системы"):
        client: ApiClient = state.api()
        try:
            health = client.health()
            st.caption(f"API: {health.get('status')}")
            st.caption(f"Модель: {health.get('llm_model')}")
            st.caption(f"Эмбеддинги: {health.get('embedding_model')}")
            ollama = health.get("ollama", {})
            st.caption(f"Ollama: {'доступен' if ollama.get('reachable') else 'недоступен'}")
        except ApiError as exc:
            st.warning(exc.message)


def main() -> None:
    sidebar()
    page = st.session_state.get("page") or ("dashboard"
                                            if state.is_authenticated() else "login")
    if page == "login" or not state.is_authenticated():
        login.render()
    elif page == "admin":
        admin.render()
    elif page == "workspace":
        workspace.render()
    else:
        dashboard.render()


main()