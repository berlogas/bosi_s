"""Админ-панель (Фаза 8): пользователи, глобальная база, задачи, аудит, сессии."""

from __future__ import annotations

import streamlit as st

from boasi_ui import state
from boasi_ui.api import ApiError
from boasi_ui.components import ui

TABS = ("Пользователи", "Глобальная база", "Задачи", "Сессии", "Аудит")


def _users(client) -> None:
    try:
        users = client.admin_users()
    except ApiError as exc:
        st.error(exc.message)
        return

    with st.expander("Создать пользователя", expanded=False):
        columns = st.columns([2, 2, 2, 1, 1])
        with columns[0]:
            username = st.text_input("Логин", key="new_user")
        with columns[1]:
            password = st.text_input("Пароль", type="password", key="new_pass")
        with columns[2]:
            full_name = st.text_input("ФИО", key="new_fullname")
        with columns[3]:
            role = st.selectbox("Роль", ["researcher", "admin"], key="new_role")
        with columns[4]:
            st.write("")
            if st.button("Создать", key="create_user",
                         disabled=not username or len(password) < 8):
                try:
                    client.admin_create_user(username=username, password=password,
                                             role=role, full_name=full_name)
                    st.success("Пользователь создан.")
                    st.rerun()
                except ApiError as exc:
                    st.error(exc.message)

    for user in users:
        columns = st.columns([3, 2, 2, 2])
        with columns[0]:
            st.markdown(f"**{user['username']}** · {user.get('full_name') or ''}")
        with columns[1]:
            new_role = st.selectbox("Роль", ["researcher", "admin"],
                                    index=["researcher", "admin"].index(
                                        user["role"]),
                                    key=f"role_{user['id']}")
        with columns[2]:
            new_password = st.text_input("Новый пароль", type="password",
                                         key=f"pw_{user['id']}")
        with columns[3]:
            if st.button("Сохранить", key=f"save_{user['id']}"):
                fields: dict = {"role": new_role}
                if new_password:
                    fields["password"] = new_password
                try:
                    client.admin_update_user(user["id"], **fields)
                    st.success("Сохранено.")
                    st.rerun()
                except ApiError as exc:
                    st.error(exc.message)


def _global_base(client) -> None:
    columns = st.columns([2, 1])
    with columns[0]:
        path = st.text_input("Путь к файлу", key="admin_path")
    with columns[1]:
        st.write("")
        if st.button("Добавить", key="admin_add_path",
                     disabled=not path.strip()):
            try:
                client.admin_add_path(path.strip())
                st.success("Добавлено.")
                st.rerun()
            except ApiError as exc:
                st.error(exc.message)

    uploaded = st.file_uploader("Или файлы", accept_multiple_files=True,
                                key="admin_upload")
    if uploaded and st.button("Загрузить", key="admin_upload_btn"):
        try:
            result = client.admin_upload(uploaded)
            st.success(f"Добавлено {len(result.get('added', []))}")
            st.rerun()
        except ApiError as exc:
            st.error(exc.message)

    st.markdown("##### Массовая индексация")
    st.caption("Фоновый режим: можно свернуть и отменить")
    paths_text = st.text_area("Пути через запятую или по одному в строке",
                              key="bulk_paths")
    if st.button("Запустить индексацию", key="bulk_run"):
        paths = [p.strip() for p in paths_text.replace(",", "\\n").splitlines()
                 if p.strip()]
        if not paths:
            st.warning("Укажите хотя бы один путь.")
        else:
            task = client.submit_bulk_index(paths)
            st.session_state["task_id"] = task["task_id"]
            st.success(f"Задача поставлена: {task['total']} файлов")

    if st.button("Переиндексировать всё", key="reindex_btn"):
        try:
            with st.spinner("Переиндексация…"):
                client.admin_reindex()
            st.success("Готово.")
        except ApiError as exc:
            st.error(exc.message)

    try:
        documents = client.admin_documents()
    except ApiError as exc:
        st.error(exc.message)
        return

    for document in documents:
        columns = st.columns([5, 1])
        with columns[0]:
            size_kb = document.get("size_bytes", 0) / 1024
            st.markdown(f"{document.get('title')} — {size_kb:.0f} КБ, "
                        f"{document.get('chunk_count', 0)} чанков")
        with columns[1]:
            if st.button("Удалить", key=f"adm_del_{document['id']}"):
                client.admin_delete_document(document["id"])
                st.rerun()


def _tasks(client) -> None:
    tasks = client.tasks()
    if not tasks:
        st.info("Задач нет.")
        return
    for task in tasks:
        ui.task_panel(client, task["id"])
        if task.get("error"):
            st.caption(task["error"])


def _sessions(client) -> None:
    try:
        sessions = client.sessions()
    except ApiError as exc:
        st.error(exc.message)
        return
    st.dataframe([{
        "id": s["id"][:8], "пользователь": s["user_id"][:8], "название": s["title"],
        "статус": s["status"], "действие": s.get("last_action_label") or "",
        "активность": (s.get("last_activity_at") or "")[:16],
    } for s in sessions], use_container_width=True, hide_index=True)


def _audit(client) -> None:
    try:
        entries = client.admin_audit(limit=200)
    except ApiError as exc:
        st.error(exc.message)
        return
    st.dataframe([{
        "время": (e.get("ts") or "")[:19],
        "кто": e.get("actor_username") or "—",
        "действие": e.get("action"),
        "цель": e.get("target_type") or "",
        "ok": e.get("ok"),
        "ip": e.get("ip") or "",
    } for e in entries], use_container_width=True, hide_index=True)


def render() -> None:
    client = state.require_auth()
    if not client.is_admin:
        st.error("Раздел доступен только администратору.")
        return

    st.markdown("### Администрирование")
    tabs = st.tabs(list(TABS))
    handlers = (_users, _global_base, _tasks, _sessions, _audit)
    for tab, handler in zip(tabs, handlers, strict=True):
        with tab:
            handler(client)