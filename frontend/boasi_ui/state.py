"""Состояние UI в `st.session_state` (Фаза 8).

Одно место, где живёт «текущая сессия», «текущий проект» и токены — чтобы
страницы не таскали токены из виджетов и не теряли авторизацию при навигации.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from boasi_ui.api import ApiClient

DEFAULTS = {
    "session_id": None,
    "project_id": None,
    "active_tab": "Документы",
    "chat_scroll": 0,
    "drafts": {},
    "task_id": None,
    "poll_interval": 2,
}


def init_state() -> None:
    for key, value in DEFAULTS.items():
        st.session_state.setdefault(key, value)
    st.session_state.setdefault("api", ApiClient())


def api() -> ApiClient:
    client = st.session_state.get("api")
    if client is None:
        client = ApiClient()
        st.session_state["api"] = client
    return client


def is_authenticated() -> bool:
    return bool(api().token)


def require_auth() -> ApiClient:
    """Страница без авторизации — глухой экран."""
    client = api()
    if not client.token:
        st.error("Требуется вход в систему.")
        st.stop()
        return client
    return client


def set_login(user: dict[str, Any]) -> None:
    st.session_state["user"] = user


def current_user() -> dict[str, Any]:
    return st.session_state.get("user") or {}


def select_session(session_id: str | None) -> None:
    st.session_state["session_id"] = session_id
    st.session_state["project_id"] = None
    st.session_state["drafts"] = {}
    st.session_state["task_id"] = None


def current_session_id() -> str | None:
    return st.session_state.get("session_id")


def select_project(project_id: str | None) -> None:
    st.session_state["project_id"] = project_id


def current_project_id() -> str | None:
    return st.session_state.get("project_id")


def draft(section: str, default: str = "") -> str:
    """Черновик раздела переживает перерисовку — это «точка возврата»."""
    return st.session_state["drafts"].get(section, default)


def set_draft(section: str, value: str) -> None:
    st.session_state["drafts"][section] = value


def snapshot(active_tab: str | None = None, *, chat_scroll: int | None = None,
             project_id: str | None = None) -> dict[str, Any]:
    """Снимок для точки возврата (Фаза 5: автосохранение состояния)."""
    state: dict[str, Any] = {
        "tab": active_tab or st.session_state.get("active_tab", ""),
        "chat_scroll": chat_scroll if chat_scroll is not None
        else st.session_state.get("chat_scroll", 0),
    }
    drafts = st.session_state.get("drafts") or {}
    if drafts:
        state["drafts"] = {k: v for k, v in drafts.items() if v}
    project = project_id if project_id is not None else st.session_state.get(
        "project_id")
    if project:
        state["active_project"] = project
    return state


def logout() -> None:
    api().logout()
    for key in ("user", "session_id", "project_id", "drafts", "task_id"):
        st.session_state.pop(key, None)