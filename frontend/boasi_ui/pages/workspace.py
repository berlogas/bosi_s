"""Рабочее пространство сессии (Фаза 8).

Вкладки: Документы · Проекты · Чат · Заметки. Между вкладками состояние
сохраняется на backend (точка возврата Фазы 5), поэтому закрытие вкладки браузера
не теряет черновики и позицию.
"""

from __future__ import annotations

import streamlit as st

from boasi_ui import state
from boasi_ui.api import ApiError
from boasi_ui.components import ui

TABS = ("Документы", "Проекты", "Чат", "Заметки")
CATEGORIES = ("temp_literature", "project_data", "project_draft", "notes",
              "supplementary")


def _header(client, session_id: str, detail: dict) -> None:
    st.markdown(f"### {detail['title']}")
    columns = st.columns([4, 1, 1, 1])
    with columns[0]:
        st.caption(f"Статус: {detail['status']} · "
                   f"Срок хранения: {ui.ttl_label(detail.get('days_left', 0))}")
        ui.limits_panel(detail.get("summary", {}))
    read_only = detail["status"] == "archived"

    with columns[1]:
        if st.button("Пауза", key="pause_btn", disabled=read_only):
            note = st.session_state.get("pause_note", "")
            client.pause_session(session_id, note)
            st.rerun()
    with columns[2]:
        if st.button("Архив", key="archive_btn", disabled=read_only):
            client.archive_session(session_id)
            st.session_state["page"] = "dashboard"
            st.rerun()
    with columns[3]:
        if st.button("← Дашборд", key="back_btn"):
            st.session_state["page"] = "dashboard"
            st.rerun()

    if read_only:
        st.warning("Сессия в архиве — доступно только чтение.")
    return read_only


# --------------------------------------------------------------------------- вкладки
def documents_tab(client, session_id: str, read_only: bool) -> None:
    st.markdown("#### Документы")
    columns = st.columns([2, 2, 2, 1])

    with columns[0]:
        category = st.selectbox("Категория", CATEGORIES, key="doc_category",
                                format_func=ui.category_label,
                                disabled=read_only)
    with columns[1]:
        path = st.text_input("Путь к файлу на диске", key="doc_path",
                             disabled=read_only)
    with columns[2]:
        tags = st.text_input("Теги через запятую", key="doc_tags",
                             disabled=read_only)
    with columns[3]:
        st.write("")
        if st.button("Добавить", key="doc_add",
                     disabled=read_only or not path.strip()):
            tag_list = [t.strip() for t in tags.split(",") if t.strip()]
            try:
                client.add_session_document(session_id, path.strip(),
                                            category=category, tags=tag_list)
                st.success("Документ добавлен.")
                st.rerun()
            except ApiError as exc:
                st.error(exc.message)

    uploaded = st.file_uploader("Или перетащите файлы сюда",
                                accept_multiple_files=True, key="doc_upload",
                                disabled=read_only)
    if uploaded and st.button("Загрузить файлы", key="doc_upload_btn",
                              disabled=read_only):
        try:
            with st.spinner("Индексирую — это может занять минуты…"):
                result = client.upload_session_documents(
                    session_id, uploaded,
                    category=st.session_state.get("doc_category",
                                                  "temp_literature"),
                    tags=st.session_state.get("doc_tags", ""))
            st.success(f"Добавлено: {len(result.get('added', []))}, "
                       f"ошибок: {len(result.get('failed', []))}")
            st.rerun()
        except ApiError as exc:
            st.error(exc.message)

    try:
        documents = client.session_documents(session_id)
    except ApiError as exc:
        st.error(exc.message)
        return

    if not documents:
        st.info("Документов пока нет.")
        return

    grouped: dict[str, list[dict]] = {}
    for document in documents:
        grouped.setdefault(document.get("category") or "notes", []).append(document)

    for group, items in grouped.items():
        with st.expander(f"{ui.category_label(group)} ({len(items)})",
                         expanded=True):
            for document in items:
                columns = st.columns([5, 1, 1])
                with columns[0]:
                    size_kb = document.get("size_bytes", 0) / 1024
                    st.markdown(f"{document.get('title') or document.get('docname')}"
                                f" — {size_kb:.0f} КБ, "
                                f"{document.get('chunk_count', 0)} чанков")
                    if document.get("tags"):
                        st.caption("теги: " + ", ".join(document["tags"]))
                with columns[1]:
                    if document.get("dockey"):
                        st.caption(f"`{document['dockey'][:8]}`")
                with columns[2]:
                    if st.button("Удалить", key=f"del_{document['id']}",
                                 disabled=read_only):
                        client.delete_document(session_id, document["id"])
                        st.rerun()


def projects_tab(client, session_id: str, read_only: bool) -> None:
    from boasi_ui.pages import project_editor

    project_editor.render(client, session_id, read_only)


def chat_tab(client, session_id: str, read_only: bool) -> None:
    st.markdown("#### Чат")
    columns = st.columns([2, 2, 1])
    with columns[0]:
        mode = st.selectbox("Режим поиска",
                            ["hybrid", "project_focus", "session_only",
                             "global_only"], key="chat_mode")
    with columns[1]:
        query = st.text_input("Ваш вопрос", key="chat_query")
    with columns[2]:
        st.write("")
        use_async = st.toggle("Фоновый режим", value=True,
                              help="Позволяет видеть прогресс и отменять запрос")

    if st.button("Спросить", key="chat_send",
                 disabled=not query.strip() or read_only):
        if use_async:
            try:
                task = client.chat_async(session_id, query.strip(), mode=mode)
                st.session_state["task_id"] = task["task_id"]
                st.session_state["chat_pending"] = query.strip()
                st.rerun()
            except ApiError as exc:
                st.error(exc.message)
        else:
            try:
                with st.spinner("Отвечаю…"):
                    answer = client.chat(session_id, query.strip(), mode=mode)
                ui.answer_view(answer)
            except ApiError as exc:
                st.error(exc.message)

    pending = st.session_state.pop("chat_pending", None)
    if pending:
        try:
            answer = client.chat(session_id, pending, mode=mode)
            ui.answer_view(answer)
        except ApiError as exc:
            st.error(exc.message)

    try:
        history = client.messages(session_id)
        if history.get("messages"):
            with st.expander("История диалога", expanded=False):
                ui.messages_view(history["messages"])
    except ApiError:
        pass


def notes_tab(client, session_id: str, read_only: bool) -> None:
    st.markdown("#### Заметки и точка возврата")
    try:
        detail = client.session_detail(session_id)
    except ApiError as exc:
        st.error(exc.message)
        return

    note = st.text_area("Заметка о работе", key="notes_text",
                        value=detail.get("resume_note") or "",
                        height=120, disabled=read_only)
    if st.button("Сохранить заметку", key="save_notes", disabled=read_only):
        client.save_state(session_id, state.snapshot(),
                          note=note or None, force=True)
        st.success("Заметка сохранена.")
        st.rerun()

    st.markdown("#### Состояние (точка возврата)")
    snapshot = detail.get("state_snapshot") or {}
    if snapshot:
        st.json({k: v for k, v in snapshot.items() if k != "saved_at"})
    else:
        st.caption("Состояние пока не сохранялось.")

    last = detail.get("last_action_label")
    if last:
        st.caption(f"Последнее действие: {last}")


# --------------------------------------------------------------------------- страница
def render() -> None:
    client = state.require_auth()
    session_id = state.current_session_id()
    if not session_id:
        st.warning("Сессия не выбрана.")
        st.session_state["page"] = "dashboard"
        st.rerun()

    try:
        detail = client.session_detail(session_id)
    except ApiError as exc:
        st.error(exc.message)
        state.select_session(None)
        st.session_state["page"] = "dashboard"
        st.rerun()
        return

    read_only = _header(client, session_id, detail)

    # фоновый вопрос: показываем прогресс, пока задача жива
    task_id = st.session_state.get("task_id")
    if task_id:
        try:
            ui.task_panel(client, task_id)
            if client.task(task_id)["status"] in {"done", "error", "cancelled"}:
                st.session_state.pop("task_id", None)
                st.session_state["chat_pending"] = st.session_state.get(
                    "chat_pending") or ""
        except ApiError:
            st.session_state.pop("task_id", None)

    active = st.session_state.get("active_tab") or "Документы"
    if active not in TABS:
        active = "Документы"
    tabs = st.tabs(list(TABS))
    for tab, name in zip(tabs, TABS, strict=True):
        with tab:
            if name == "Документы":
                documents_tab(client, session_id, read_only)
            elif name == "Проекты":
                projects_tab(client, session_id, read_only)
            elif name == "Чат":
                chat_tab(client, session_id, read_only)
            else:
                notes_tab(client, session_id, read_only)

    # автосохранение точки возврата при смене вкладки
    client.save_state(session_id, state.snapshot(active_tab=active),
                      force=True)