"""Рабочее пространство сессии (Фаза 8).

Вкладки: Документы · Проекты · Чат · Заметки. Между вкладками состояние
сохраняется на backend (точка возврата Фазы 5), поэтому закрытие вкладки браузера
не теряет черновики и позицию.
"""

from __future__ import annotations

from typing import Any

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


def _asked(history: list[dict[str, Any]], question: str | None) -> bool:
    """Есть ли такой вопрос уже в истории — чтобы не рисовать его дважды."""
    target = (question or "").strip()
    if not target:
        return False
    return any((m.get("content") or "").strip() == target for m in history)


def _render_history(client, session_id: str, read_only: bool) -> list[dict[str, Any]]:
    """Переписка пузырями. Раньше была свёрнута в expander «История диалога»."""
    try:
        history = client.messages(session_id).get("messages") or []
    except ApiError:
        history = []
    for index, message in enumerate(history):
        role = message.get("role") or "user"
        # Кнопка удаления — одна на пару «вопрос + ответ», и стоит она
        # на вопросе: нажатие убирает сразу оба пузыря. Раньше кнопка
        # рисовалась в каждом пузыре, и пара выглядела как два
        # независимых сообщения с двумя отдельными удалениями.
        # Исключение — ответ без вопроса (старая запись): такой обмен
        # иначе нечем было бы удалить, поэтому кнопка при нём остаётся.
        without_question = (role != "user"
                            and not any(m.get("role") == "user"
                                        for m in history[:index]))
        # Кнопка рисуется в шапке пузыря, в одной строке с аватаром:
        # на вопросе — потому что нажатие убирает сразу оба пузыря пары.
        # Исключение — ответ без вопроса (старая запись): такой обмен
        # иначе нечем было бы удалить, поэтому кнопка при нём остаётся.
        action = None
        if role == "user" or without_question:
            def action(_m=message, _i=index, _r=read_only) -> None:
                _delete_message_button(client, _m, history, _i, _r)

        with ui.chat_bubble(role, action=action):
            st.markdown(message.get("content") or "")
            if role != "user":
                ui.source_list(message.get("sources", []))
    return history


def _pair_question(history: list[dict[str, Any]], index: int) -> str | None:
    """Вопрос из той же пары, что и сообщение под индексом.

    Нужен, чтобы вместе с удалённой парой убрать и её локальный кэш:
    иначе несохранённый ответ снова дорисуется поверх пустой истории.
    """
    message = history[index]
    if message.get("role") != "assistant":
        return message.get("content")
    for previous in reversed(history[:index]):
        if previous.get("role") == "user":
            return previous.get("content")
    return None


def _forget_cached_exchange(history: list[dict[str, Any]], index: int) -> None:
    """Сбросить кэш несохранённых обменов, если он про удалённую пару."""
    question = (_pair_question(history, index) or "").strip()
    if not question:
        return
    pending = (st.session_state.get("chat_pending") or "").strip()
    if pending and pending == question:
        st.session_state.pop("chat_pending", None)
    last = ((st.session_state.get("chat_last") or {}).get("q") or "").strip()
    if last and last == question:
        st.session_state.pop("chat_last", None)


def _delete_message_button(client, message: dict[str, Any],
                           history: list[dict[str, Any]], index: int,
                           read_only: bool) -> None:
    """Кнопка удаления вопроса вместе с ответом.

    Удаляется вся пара целиком — поэтому кнопка одна на оба пузыря, и
    нажимать её дважды не нужно.

    У сообщений, которых ещё нет в базе (вопрос в фоновой задаче или
    несохранённый синхронный ответ), кнопки нет — их удаляют
    `_delete_pending_exchange` и `_delete_cached_exchange`.
    """
    message_id = message.get("id")
    if read_only or not message_id:
        return
    if st.button("🗑", key=f"del_msg_{message_id}",
                 help="Удалить вопрос вместе с ответом"):
        try:
            client.delete_message(message_id)
        except ApiError as exc:
            st.error(exc.message)
            return
        # Удалённую пару нельзя воскресить локальным кэшем — иначе пузыри
        # появятся снова, хотя в базе их уже нет.
        _forget_cached_exchange(history, index)
        st.rerun()


def _delete_pending_exchange(client, read_only: bool) -> None:
    """Кнопка удаления вопроса, который ещё в фоновой задаче."""
    if read_only:
        return
    if not st.button("🗑", key="del_pending_exchange",
                     help="Отменить вопрос и убрать его из переписке"):
        return
    task_id = st.session_state.get("task_id")
    if task_id:
        try:
            client.cancel_task(task_id)
        except ApiError:
            pass          # задача могла уже завершиться — не страшно
        st.session_state.pop("task_id", None)
    st.session_state.pop("chat_pending", None)
    st.rerun()


def _delete_cached_exchange(read_only: bool) -> None:
    """Кнопка удаления обмена, которого нет в базе.

    Ответ, взятый из кэша сервера, в историю не пишется (`if not
    from_cache`), поэтому такой обмен живёт только в session_state и
    раньше было видно, но удалить его было нечем.
    """
    if read_only:
        return
    if not st.button("🗑", key="del_cached_exchange",
                     help="Убрать вопрос и ответ из переписки"):
        return
    st.session_state.pop("chat_last", None)
    st.rerun()


def _clear_chat_controls(client, session_id: str, read_only: bool) -> None:
    """Очистка всей переписки — в два шага, потому что отмены нет."""
    if read_only:
        return
    # Флаг читаем, а не pop(): pop здесь съел бы его на том самом проходе,
    # который рисует подтверждение, и кнопка «Да, очистить» ничего не сделала
    # бы. Сбрасываем его только после действия.
    if st.session_state.get("chat_clear_ask"):
        st.warning("Удалить всю переписку этой сессии? Отменить будет нельзя.")
        yes, no, _ = st.columns([1, 1, 3])
        with yes:
            if st.button("Да, очистить", key="chat_clear_yes"):
                try:
                    client.clear_messages(session_id)
                except ApiError as exc:
                    st.error(exc.message)
                    return
                # Локальный кэш несохранённого ответа тоже сбрасываем,
                # иначе он остался бы висеть поверх пустой истории.
                st.session_state.pop("chat_last", None)
                st.session_state.pop("chat_clear_ask", None)
                st.success("История очищена.")
                st.rerun()
        with no:
            if st.button("Отмена", key="chat_clear_no"):
                st.session_state.pop("chat_clear_ask", None)
                st.rerun()
        return
    if st.button("🗑 Очистить чат", key="chat_clear_open",
                 help="Удалить всю переписку этой сессии"):
        st.session_state["chat_clear_ask"] = True
        st.rerun()


def chat_tab(client, session_id: str, read_only: bool) -> None:
    st.markdown("#### Чат")

    history = _render_history(client, session_id, read_only)

    # Вопрос, ушедший в фоновую задачу: рисуем пузырём сразу, чтобы он не
    # «потерялся» в строке ввода. Ответа здесь не ждём — его допишет задача,
    # и он появится из истории. Раньше здесь дёргался синхронный client.chat
    # поверх фоновой задачи, из-за чего один и тот же обмен сохранялся
    # дважды и ответ удваивался.
    pending = st.session_state.get("chat_pending")
    if pending and not _asked(history, pending):
        with ui.chat_bubble("user",
                            action=lambda: _delete_pending_exchange(
                                client, read_only)):
            st.markdown(pending)
        with ui.chat_bubble("assistant"):
            st.info("Вопрос обрабатывается…")

    # Синхронный ответ, которого ещё нет в истории. Ответ из кэша сервер
    # не сохраняет (в chat_query стоит `if not from_cache`), поэтому без
    # этого он пропал бы после перерисовки.
    last = st.session_state.get("chat_last")
    if last:
        if _asked(history, last["q"]):
            st.session_state.pop("chat_last", None)
        else:
            with ui.chat_bubble("user",
                            action=lambda: _delete_cached_exchange(read_only)):
                st.markdown(last["q"])
            with ui.chat_bubble("assistant"):
                ui.answer_view(last["a"])

    # Чистим поле ввода ДО создания виджета: иначе Streamlit ругается на
    # изменение session_state виджета после его создания.
    if st.session_state.pop("chat_clear_input", False):
        st.session_state["chat_query"] = ""

    controls, _, _ = st.columns([1, 1, 3])
    with controls:
        use_async = st.toggle("Фоновый режим", value=True,
                              help="Позволяет видеть прогресс и отменять запрос")
    clear_col, _ = st.columns([1, 3])
    with clear_col:
        _clear_chat_controls(client, session_id, read_only)

    # Ввод, селектор режима и кнопка отправки — в одну строку.
    # st.chat_input для этого не годится: Streamlit всегда прижимает его
    # к низу окна на всю ширину и не даёт положить рядом селектор, поэтому
    # здесь форма: Enter отправляет, а кнопка — узкая, без слова «Спросить».
    with st.form("chat_form"):
        row = st.columns([5, 2, 1])
        with row[0]:
            query = st.text_input("Ваш вопрос", key="chat_query",
                                  placeholder="Спросите что-нибудь…")
        with row[1]:
            mode = st.selectbox("Режим поиска",
                                ["hybrid", "project_focus", "session_only",
                                 "global_only"], key="chat_mode")
        with row[2]:
            st.write("")
            submitted = st.form_submit_button("➤", use_container_width=True,
                                              disabled=read_only)

    if not (submitted and query.strip() and not read_only):
        return

    question = query.strip()
    if use_async:
        try:
            task = client.chat_async(session_id, question, mode=mode)
            st.session_state["task_id"] = task["task_id"]
            st.session_state["chat_pending"] = question
        except ApiError as exc:
            st.error(exc.message)
            return
    else:
        try:
            with st.spinner("Отвечаю…"):
                answer = client.chat(session_id, question, mode=mode)
            st.session_state["chat_last"] = {"q": question, "a": answer}
        except ApiError as exc:
            st.error(exc.message)
            return
    st.session_state["chat_clear_input"] = True
    st.rerun()


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

    # Фоновый вопрос: показываем прогресс, пока задача жива.
    #
    # Наблюдение завёрнуто в фрагмент с run_every — раньше панель обновлялась
    # только по кнопке «Обновить», поэтому после завершения задачи страница
    # не перерисовывалась и чат навсегда застревал на «Вопрос обрабатывается…».
    task_id = st.session_state.get("task_id")
    if task_id:

        @st.fragment(run_every=2.0)
        def _watch_task() -> None:
            try:
                ui.task_panel(client, task_id)
                status = client.task(task_id)["status"]
            except ApiError:
                st.session_state.pop("task_id", None)
                st.rerun()
                return
            if status in {"done", "error", "cancelled"}:
                st.session_state.pop("task_id", None)
                # Задача дописала обмен в историю — вопрос больше не pending,
                # а полная перерисовка покажет ответ из истории.
                st.session_state.pop("chat_pending", None)
                st.rerun()

        _watch_task()

    active = st.session_state.get("active_tab") or TABS[0]
    if active not in TABS:
        active = TABS[0]

    # Переключатель держим в session_state сами. st.tabs помнит выбор
    # только внутри себя и не отдаёт его приложению, поэтому любая
    # перерисовка (например, Enter в форме чата) возвращала раздел
    # «Документы». Управляемый radio выбранную вкладку сохраняет.
    active = st.radio(
        "Раздел", list(TABS), index=list(TABS).index(active), horizontal=True,
        key="workspace_tab", label_visibility="collapsed")
    st.session_state["active_tab"] = active

    if active == "Документы":
        documents_tab(client, session_id, read_only)
    elif active == "Проекты":
        projects_tab(client, session_id, read_only)
    elif active == "Чат":
        chat_tab(client, session_id, read_only)
    else:
        notes_tab(client, session_id, read_only)

    # автосохранение точки возврата при смене вкладки
    client.save_state(session_id, state.snapshot(active_tab=active),
                      force=True)