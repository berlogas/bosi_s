"""Дашборд (Фаза 8).

Быстрый вопрос по глобальной базе + карточки сессий с превью последнего
действия, кнопкой «Продолжить» и индикатором срока жизни.
"""

from __future__ import annotations

import streamlit as st

from boasi_ui import state
from boasi_ui.api import ApiError
from boasi_ui.components import ui


def _quick_question(client) -> None:
    with st.expander("Быстрый вопрос по базе знаний", expanded=True):
        query = st.text_input("Ваш вопрос", key="quick_query",
                              placeholder="Например: как измеряют биомассу?")
        if not st.button("Спросить", key="quick_ask", disabled=not query):
            return
        try:
            with st.spinner("Ищу в глобальной базе…"):
                answer = client.quick_query(query)
            ui.answer_view(answer)
            if query in (st.session_state.get("suggestions") or []):
                st.caption("повторный вопрос")
            st.session_state["quick_ask"] = query
            st.session_state["suggestions"] = client.suggest_queries(query)
        except ApiError as exc:
            st.error(exc.message)


def _new_session(client) -> None:
    st.markdown("#### Новая сессия")
    title = st.text_input("Название", key="new_session_title",
                          placeholder="Например: Баренцево море, 2026")
    if st.button("Создать", key="create_session", disabled=not title.strip()):
        try:
            created = client.create_session(title.strip())
        except ApiError as exc:
            st.error(exc.message)
            return
        state.select_session(created["id"])
        st.session_state["page"] = "workspace"
        st.rerun()


def _tasks(client) -> None:
    active = [t for t in client.tasks() if not t["status"]
              in {"done", "error", "cancelled"}]
    if not active:
        return
    st.markdown("#### Активные задачи")
    for task in active:
        ui.task_panel(client, task["id"])


def render() -> None:
    client = state.require_auth()
    st.markdown("### Дашборд")

    _quick_question(client)

    try:
        sessions = client.sessions()
    except ApiError as exc:
        st.error(exc.message)
        return

    _tasks(client)

    active = [s for s in sessions if s["status"] == "active"]
    paused = [s for s in sessions if s["status"] == "paused"]
    archived = [s for s in sessions if s["status"] == "archived"]

    _new_session(client)

    st.markdown(f"#### Мои сессии ({len(active)})")
    if not active:
        st.info("Активных сессий нет — создайте первую.")
    for session in active:
        detail = _safe_detail(client, session["id"], session)
        with st.container(border=True):
            ui.session_card(session)
            st.caption(f"Срок хранения: {ui.ttl_label(detail.get('days_left', 0))}")

    if paused:
        with st.expander(f"На паузе ({len(paused)})"):
            for session in paused:
                ui.session_card(session)

    if archived:
        with st.expander(f"Архив ({len(archived)}) — только чтение"):
            for session in archived:
                ui.session_card(session)


def _safe_detail(client, session_id: str, session: dict) -> dict:
    try:
        return client.session_detail(session_id)
    except ApiError:
        return {"days_left": 0, "summary": {}}