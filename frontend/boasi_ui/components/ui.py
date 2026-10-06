"""Компоненты UI (Фаза 8).

Здесь живёт главное требование по UX: долгая операция не должна оставлять
«висящий спиннер» — показываем прогресс по фоновой задаче и даём кнопку
«Отменить».
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import streamlit as st

from boasi_ui import state

STATUS_ICONS = {
    "queued": "⏳", "running": "🔄", "done": "✅",
    "error": "❌", "cancelled": "🚫",
}

# Имя и аватар ассистента. Пользователь просил, чтобы в разговорах его
# звали «Бо» — раньше ассистент был вовсе безымянным (в пузырях чата стоял
# дефолтный «Assistant»). Держим в одном месте, чтобы переименовать было
# не надо полазить по страницам.
ASSISTANT_NAME = "Бо"
ASSISTANT_AVATAR = "👨‍💻"
USER_NAME = "Вы"
USER_AVATAR = "👨‍🔬"


def chat_message(role: str):
    """Открывает пузырь чата.

    У `st.chat_message` первый параметр — это и роль, и подпись: туда
    принимается либо 'user'/'assistant', либо произвольная строка. Поэтому
    «Бо» передаём именно первым аргументом, а `avatar` идёт именованным.
    """
    if role == "assistant":
        return st.chat_message(ASSISTANT_NAME, avatar=ASSISTANT_AVATAR)
    return st.chat_message("user")


@contextmanager
def chat_bubble(role: str,
                action: Callable[[], None] | None = None) -> Iterator[None]:
    """Пузырь чата, у которого действие стоит в одной строке с аватаром.

    `st.chat_message` рисует заголовок (аватар и подпись) сам и не даёт
    положить туда виджет, поэтому пузыри с кнопкой удаления собираем
    сами: аватар, подпись и кнопка — три колонки в одной строке. Раньше
    кнопка стояла под текстом и занимала отдельную строку.

    `action` вызывается в третьей колонке; вернуть из него ничего не
    нужно. Если он не передан, колонка всё равно создаётся — чтобы
    аватары и подписи всех пузырей стояли на одной высоте.
    """
    label, icon = ((USER_NAME, USER_AVATAR) if role == "user"
                   else (ASSISTANT_NAME, ASSISTANT_AVATAR))
    with st.container(border=True):
        avatar_col, name_col, action_col = st.columns(
            [1, 30, 1], vertical_alignment="center")
        with avatar_col:
            st.markdown(f"<span style='font-size:1.15rem'>{icon}</span>",
                        unsafe_allow_html=True)
        with name_col:
            st.markdown(f"**{label}**")
        with action_col:
            if action is not None:
                action()
        yield
STATUS_COLORS = {
    "queued": "grey", "running": "blue", "done": "green",
    "error": "red", "cancelled": "orange",
}
CATEGORY_LABELS = {
    "project_draft": "Черновики проекта",
    "project_data": "Данные",
    "temp_literature": "Временная литература",
    "notes": "Заметки",
    "supplementary": "Дополнительные материалы",
    "global_knowledge": "Глобальная база",
}


def category_label(value: str | None) -> str:
    return CATEGORY_LABELS.get(value or "", value or "Без категории")


def ttl_label(days_left: int) -> str:
    if days_left <= 0:
        return "срок истёк"
    if days_left == 1:
        return "остался 1 день"
    if days_left < 5:
        return f"осталось {days_left} дня"
    return f"осталось {days_left} дней"


def session_card(session: dict[str, Any]) -> None:
    """Карточка сессии на дашборде: превью последнего действия и срок жизни."""
    title = session.get("title") or "Без названия"
    status = session.get("status", "active")
    columns = st.columns([3, 1, 1])

    with columns[0]:
        st.markdown(f"**{title}**")
        label = session.get("last_action_label") or "без действий"
        when = (session.get("last_action_at") or "")[:16].replace("T", " ")
        st.caption(f"{STATUS_ICONS.get(status, '')} {status} · {label} · {when}")
        if session.get("resume_note"):
            st.caption(f"Заметка: {session['resume_note']}")

    with columns[1]:
        if st.button("Продолжить", key=f"open_{session['id']}",
                     use_container_width=True,
                     disabled=status == "archived"):
            state.select_session(session["id"])
            st.session_state["page"] = "workspace"
            st.rerun()

    archive_ask = f"arch_ask_{session['id']}"
    with columns[2]:
        if st.session_state.get(archive_ask):
            # Второй шаг подтверждения — вместо кнопки «Архив».
            if st.button("Да, в архив", key=f"arch_yes_{session['id']}",
                         use_container_width=True,
                         disabled=status != "active"):
                try:
                    state.api().archive_session(session["id"])
                    st.session_state.pop(archive_ask, None)
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))
            if st.button("Отмена", key=f"arch_no_{session['id']}",
                         use_container_width=True):
                st.session_state.pop(archive_ask, None)
                st.rerun()
        elif st.button("Архив", key=f"arch_{session['id']}",
                       use_container_width=True, disabled=status != "active"):
            # Архивация необратима — спрашиваем, а не выполняем сразу.
            # Раньше один клик сразу уносил сессию в архив (и из
            # workspace, и отсюда), и вернуть её было нельзя.
            st.session_state[archive_ask] = True
            st.rerun()

    if st.session_state.get(archive_ask):
        st.caption("Подтвердите: сессия уйдёт в архив (только чтение).")


def limits_panel(summary: dict[str, Any]) -> None:
    """Лимиты сессии: документы и хранилище."""
    documents = summary.get("documents", 0)
    documents_limit = summary.get("documents_limit", 50)
    used_mb = summary.get("storage_bytes", 0) / (1024 * 1024)
    limit_mb = summary.get("storage_limit_bytes", 500 * 1024 * 1024) / (1024 * 1024)
    st.caption(f"Документы: {documents}/{documents_limit} · "
               f"Хранилище: {used_mb:.1f}/{limit_mb:.0f} МБ")
    if documents >= documents_limit:
        st.warning("Достигнут лимит документов — удалите лишние.")


def _fmt_seconds(value: Any) -> str:
    """42с / 3:07 / 1:02:05 — компактная запись времени для строк прогресса."""
    try:
        seconds = int(float(value or 0))
    except (TypeError, ValueError):
        return ""
    if seconds < 1:
        return ""
    if seconds < 60:
        return f"{seconds}с"
    if seconds < 3600:
        return f"{seconds // 60}:{seconds % 60:02d}"
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def task_panel(client, task_id: str) -> None:
    """Прогресс фоновой задачи с кнопкой отмены.

    Заменяет спиннер на минуты: видно, что происходит, и можно остановить.
    """
    try:
        task = client.task(task_id)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Не удалось получить статус задачи: {exc}")
        return

    status = task.get("status", "queued")
    icon = STATUS_ICONS.get(status, "")
    columns = st.columns([4, 1, 1])

    with columns[0]:
        if status in {"running", "queued"}:
            # Строка должна быть «живой»: подпись этапа тикает секундомером
            # этапа и общим временем. Без этого при долгой LLM панель
            # замирала на одних и тех же процентах и выглядела зависшей.
            text = f"{icon} {task.get('step', '')}".strip()
            stage = _fmt_seconds(task.get("stage_seconds"))
            total = _fmt_seconds(task.get("seconds"))
            if stage:
                text += f" · {stage}"
            text += f" ({task.get('progress', 0)}%)"
            if total:
                text += f" · всего {total}"
            st.progress(min(1.0, task.get("progress", 0) / 100), text=text)
        else:
            st.markdown(f"{icon} **{task.get('title', '')}** — {status}")
            if task.get("step"):
                st.caption(task["step"])

    with columns[1]:
        if status in {"running", "queued"}:
            if st.button("Отменить", key=f"cancel_{task_id}"):
                client.cancel_task(task_id)
                st.rerun()

    with columns[2]:
        if st.button("Обновить", key=f"refresh_{task_id}"):
            st.rerun()

    if status == "error":
        st.error(task.get("error") or "Задача завершилась с ошибкой")
    elif status == "cancelled":
        st.info("Задача отменена")
    elif status == "done":
        st.success(f"Готово за {task.get('seconds')} с")


def run_async_task(client, submit, *, key: str) -> dict[str, Any] | None:
    """Отправить фоновую задачу и опросить её до завершения.

    Streamlit не умеет «отвалиться» и вернуться, поэтому опрос идёт
    пошагово с паузой; пользователь может свернуть или отменить.
    """
    if not st.session_state.get(key):
        st.session_state[key] = submit()
    task_id = st.session_state[key]

    for _ in range(3):
        task_panel(client, task_id)
        task = client.task(task_id)
        if task["status"] in {"done", "error", "cancelled"}:
            break
        import time

        time.sleep(st.session_state.get("poll_interval", 2))

    task = client.task(task_id)
    if task["status"] == "done":
        st.session_state.pop(key, None)
        return task
    return None


def source_list(sources: list[dict[str, Any]]) -> None:
    """Источники ответа с разметкой 📚 (глобальная) / 📁 (сессия)."""
    if not sources:
        return
    st.caption("Источники:")
    for source in sources:
        scope = "глобальная база" if source.get("source_scope") == "global" \
            else "сессия"
        label = source.get("title") or source.get("docname") or source.get("dockey")
        st.markdown(
            f"{source.get('marker', '')} `[{source.get('index')}]` "
            f"**{label}** — {scope}, {category_label(source.get('category'))}, "
            f"score {source.get('score', 0):.2f}")


def collect_warnings(payload: dict[str, Any]) -> list[str]:
    """Предупреждения проверок ответа.

    Живой ответ несёт их в `stats`, история — в `checks` (одни и те же
    отчёты citation_guard/grounding, сохранённые в `messages.checks`).
    """
    container = payload.get("stats") or payload.get("checks") or {}
    warnings: list[str] = []
    for key in ("grounding", "citations"):
        section = container.get(key) or {}
        warnings.extend(section.get("warnings") or [])
    return warnings


def checks_view(payload: dict[str, Any]) -> None:
    """Предупреждения о качестве ответа: выдуманные факты, сломанные ссылки."""
    warnings = collect_warnings(payload)
    if not warnings:
        return
    st.warning("⚠️ " + warnings[0])
    if len(warnings) > 1:
        with st.expander(f"Все предупреждения проверки ({len(warnings)})"):
            for line in warnings[1:]:
                st.markdown(f"- {line}")


# Запись блока References «1. [2]: doc (…)»: markdown-it разбирает
# `[2]: doc (title)` как определение ссылки-сноски, съедает строку и
# в ответе остаются голые «1. 2.». Двоеточие убираем только при рендере —
# новые ответы такой формат уже чинит citation_guard, история нет.
_REF_ENTRY_RE = re.compile(r"^([ \t]*\d+\.)[ \t]+\[([0-9]+)\]:",
                           re.MULTILINE)


def md_safe_references(text: str) -> str:
    """«1. [2]: doc» → «1. [2] doc» перед рендером markdown."""
    return _REF_ENTRY_RE.sub(r"\1 [\2]", text or "")


def answer_view(answer: dict[str, Any]) -> None:
    text = (answer.get("answer") or "").strip()
    if text:
        st.markdown(md_safe_references(text))
    elif not answer.get("base_empty"):
        st.markdown("_Ответ пуст_")
    if answer.get("base_empty"):
        # Ответ без опоры на базу: раньше это выглядело как «Ответ пуст»
        # и выглядело поломкой, хотя на самом деле документов просто нет.
        st.info("Ответ без ссылок на источники: в базе знаний нет документов "
                "или по запросу ничего не нашлось. Загрузите документы в "
                "разделе «Администрирование».")
    source_list(answer.get("sources", []))
    checks_view(answer)
    if answer.get("from_cache"):
        st.caption("Ответ взят из кэша")
    if answer.get("references"):
        with st.expander("Список источников"):
            for line in answer["references"]:
                st.markdown(f"- {line}")


def messages_view(messages: list[dict[str, Any]]) -> None:
    for message in messages:
        role = message.get("role")
        if role == "user":
            st.markdown(f"**Вы:** {message.get('content')}")
        else:
            st.markdown(md_safe_references(message.get("content") or ""))
            source_list(message.get("sources", []))
            checks_view(message)


def error_box(exc: Exception) -> None:
    st.error(str(exc))