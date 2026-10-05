"""Дашборд (Фаза 8).

Быстрый вопрос по глобальной базе + карточки сессий с превью последнего
действия, кнопкой «Продолжить» и индикатором срока жизни.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from boasi_ui import state
from boasi_ui.api import ApiError
from boasi_ui.components import ui


def _chat_message(role: str):
    """Открывает пузырь чата (имя ассистента — Бо).

    Раньше тут был `st.chat_message`, но у него аватар и подпись рисует
    сам Streamlit: у спрашивающего оставался служебный значок, а у Бо —
    дефолтный. Теперь пузырь один на весь чат приложения, с нужными
    аватарами: учёный у спрашивающего, технарь у Бо.
    """
    return ui.chat_bubble(role)


def _quick_chat(client) -> None:
    """Чат по глобальной базе — в привычном виде: Enter отправляет.

    Раньше здесь был expander с текстовым полем и кнопкой «Спросить».
    Пользователь попросил обычный чат, поэтому история живёт в
    session_state, сообщения рисуются как диалог, а ввод — внизу.
    """
    history: list[dict[str, Any]] = st.session_state.setdefault("quick_chat", [])

    for item in history:
        with _chat_message(item["role"]):
            # У ассистента текст рисует answer_view — иначе ответ
            # продублируется (он и в content, и в answer["answer"]).
            if item.get("answer") is None:
                st.markdown(item.get("content") or "")
            else:
                ui.answer_view(item["answer"])

    suggestions = st.session_state.get("suggestions") or []
    if suggestions:
        st.caption("Можно уточнить:")
        for text in suggestions[:4]:
            st.caption(f"- {text}")

    prompt = st.chat_input("Спросите что-нибудь по базе знаний")
    if not prompt:
        return

    history.append({"role": "user", "content": prompt})
    with _chat_message("user"):
        st.markdown(prompt)

    with _chat_message("assistant"):
        try:
            with st.spinner("Ищу в глобальной базе…"):
                answer = client.quick_query(prompt)
        except ApiError as exc:
            st.error(exc.message)
            st.session_state["quick_chat"] = [
                *history[:-1],
                {"role": "assistant", "content": "",
                 "answer": {"answer": "", "base_empty": False,
                            "error": exc.message}},
            ]
            st.rerun()

        ui.answer_view(answer)

    entry = {"role": "assistant", "content": answer.get("answer") or "",
             "answer": answer}
    history.append(entry)

    # Уточняющие вопросы рисуем под ответом, как подсказки в чате.
    if not answer.get("base_empty") and answer.get("sources"):
        try:
            st.session_state["suggestions"] = client.suggest_queries(prompt)
        except ApiError:
            st.session_state["suggestions"] = []
    else:
        st.session_state["suggestions"] = []

    st.rerun()



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

    _quick_chat(client)

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