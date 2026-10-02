"""Вкладка проектов статей (Фаза 8).

Структура разделов, статус, привязка документов, генерация с прогрессом и
разбор черновика. Тяжёлые операции уходят в фоновые задачи, поэтому вкладка
не «залипает».
"""

from __future__ import annotations

import streamlit as st

from boasi_ui import state
from boasi_ui.api import ApiError
from boasi_ui.components import ui

STATUSES = ("planning", "drafting", "reviewing", "done")
KINDS = ("section", "literature_review", "data_comparison", "gap_analysis",
         "draft_analysis", "report")


def _create(client, session_id: str, read_only: bool) -> None:
    with st.expander("Новый проект"):
        columns = st.columns([3, 2, 1])
        with columns[0]:
            title = st.text_input("Название", key="project_title")
        with columns[1]:
            journal = st.text_input("Целевой журнал", key="project_journal")
        with columns[2]:
            st.write("")
            if st.button("Создать", key="project_create",
                         disabled=read_only or not title.strip()):
                client.create_project(session_id, title.strip(), journal.strip())
                st.rerun()


def _sections(client, session_id: str, project_id: str, read_only: bool) -> None:
    try:
        sections = client.sections(session_id, project_id)
    except ApiError as exc:
        st.error(exc.message)
        return

    for section in sections:
        label = f"{section['name']} — {section.get('word_target', 0)} слов"
        with st.expander(label, expanded=not section.get("written")):
            body = st.text_area(
                "Текст раздела", key=f"sec_{section['name']}",
                value=state.draft(section["name"], section.get("content_md", "")),
                height=160, disabled=read_only)
            if body != state.draft(section["name"], ""):
                state.set_draft(section["name"], body)
            columns = st.columns([2, 1, 1])
            with columns[0]:
                st.caption(f"написано слов: {section.get('words', 0)}")
            with columns[1]:
                if st.button("Сохранить", key=f"save_{section['name']}",
                             disabled=read_only):
                    client.save_section(session_id, project_id, section["name"],
                                        content_md=body)
                    st.success("Раздел сохранён.")
                    st.rerun()
            with columns[2]:
                if st.button("Сгенерировать", key=f"gen_{section['name']}",
                             disabled=read_only):
                    _generate(client, session_id, project_id,
                              section=section["name"])


def _generate(client, session_id: str, project_id: str, **payload) -> None:
    try:
        with st.spinner("Генерирую раздел — это может занять минуты…"):
            result = client.generate(session_id, project_id, **payload)
    except ApiError as exc:
        st.error(exc.message)
        return

    st.markdown(result.get("content_md", ""))
    if not result.get("citations_ok", True):
        st.warning("Проверьте ссылки: часть из них не разрешается в источники.")
    for warning in result.get("warnings", []):
        st.caption(f"⚠ {warning}")
    if result.get("references"):
        with st.expander("Источники"):
            for line in result["references"]:
                st.markdown(f"- {line}")


def _generate_panel(client, session_id: str, project_id: str,
                    read_only: bool) -> None:
    with st.expander("Генерация и анализ"):
        columns = st.columns([2, 3, 1])
        with columns[0]:
            kind = st.selectbox("Вид", KINDS, key="gen_kind")
        with columns[1]:
            question = st.text_input("Вопрос или тема", key="gen_question")
        with columns[2]:
            st.write("")
            if st.button("Запустить", key="gen_run",
                         disabled=read_only or not question.strip()):
                _generate(client, session_id, project_id, kind=kind,
                           section="", question=question.strip())

        if st.button("Разбор черновика", key="draft_analysis_btn",
                     disabled=read_only):
            try:
                analysis = client.draft_analysis(session_id, project_id)
            except ApiError as exc:
                st.error(exc.message)
                return
            if not analysis["has_gaps"]:
                st.success("Пробелов не найдено.")
                return
            st.warning(f"Найдено пробелов: {len(analysis['gaps'])} "
                       f"(критичных {analysis['by_severity']['high']})")
            for gap in analysis["gaps"]:
                st.markdown(f"- **{gap['severity']}** · {gap['where']}: "
                            f"{gap['hint']}"
                            + (f" — «{gap['excerpt']}»" if gap.get("excerpt")
                               else ""))


def _documents(client, session_id: str, project_id: str,
               read_only: bool) -> None:
    st.markdown("##### Документы проекта")
    try:
        available = client.session_documents(session_id)
        bound = client.project_documents(session_id, project_id)
    except ApiError as exc:
        st.error(exc.message)
        return

    bound_ids = {item["document"]["id"]: item["role"] for item in bound}
    for item in bound:
        document = item["document"]
        columns = st.columns([5, 1])
        with columns[0]:
            st.markdown(f"{document.get('title')} — "
                        f"роль: {item['role']}")
        with columns[1]:
            if st.button("Отвязать", key=f"unbind_{document['id']}",
                         disabled=read_only):
                client.unbind_document(session_id, project_id, document["id"])
                st.rerun()

    free = [d for d in available if d["id"] not in bound_ids]
    if free:
        columns = st.columns([3, 1])
        with columns[0]:
            chosen = st.selectbox("Привязать документ",
                                  options=[d["id"] for d in free],
                                  format_func=lambda i: next(
                                      d["title"] for d in free if d["id"] == i),
                                  key="bind_doc")
        with columns[1]:
            st.write("")
            role = st.selectbox("Роль", ["reference", "data", "draft"],
                                key="bind_role")
            if st.button("Привязать", key="bind_btn", disabled=read_only):
                client.bind_document(session_id, project_id, chosen, role)
                st.rerun()


def _export(client, session_id: str, project_id: str) -> None:
    st.markdown("##### Экспорт")
    columns = st.columns([2, 1])
    with columns[0]:
        fmt = st.selectbox("Формат", ["docx", "markdown", "zip"],
                           key="export_fmt")
    with columns[1]:
        st.write("")
        if st.button("Скачать", key="export_btn"):
            try:
                payload = client.export_project(session_id, project_id, fmt)
            except ApiError as exc:
                st.error(exc.message)
                return
            st.download_button(f"article.{fmt}", payload,
                               file_name=f"article.{fmt}")


def render(client, session_id: str, read_only: bool) -> None:
    st.markdown("#### Проекты статей")
    _create(client, session_id, read_only)

    try:
        projects = client.projects(session_id)
    except ApiError as exc:
        st.error(exc.message)
        return

    if not projects:
        st.info("Проектов нет — создайте первый.")
        return

    ids = [p["id"] for p in projects]
    current = state.current_project_id()
    index = ids.index(current) if current in ids else 0
    labels = {p["id"]: f"{p['title']} ({p['status']})" for p in projects}
    selected = st.selectbox("Проект", options=ids,
                            index=index, format_func=lambda i: labels[i],
                            key="project_select")
    state.select_project(selected)
    project = projects[ids.index(selected)]

    columns = st.columns([2, 2, 1, 1])
    with columns[0]:
        try:
            progress = client.project_progress(session_id, selected)
            st.progress(min(1.0, progress["percent"] / 100),
                        text=f"{progress['written']}/{progress['sections']} "
                             f"разделов · {progress['words']} слов")
        except ApiError:
            pass
    with columns[1]:
        status_value = st.selectbox("Статус", STATUSES,
                                    index=STATUSES.index(project["status"]),
                                    key="project_status", disabled=read_only)
    with columns[2]:
        st.write("")
        if st.button("Обновить", key="status_save", disabled=read_only):
            client.patch_project(session_id, selected, status=status_value)
            st.rerun()
    with columns[3]:
        st.write("")
        if st.button("Удалить", key="project_delete", disabled=read_only):
            client.delete_project(session_id, selected)
            state.select_project(None)
            st.rerun()

    _generate_panel(client, session_id, selected, read_only)
    _sections(client, session_id, selected, read_only)
    _documents(client, session_id, selected, read_only)
    _export(client, session_id, selected)