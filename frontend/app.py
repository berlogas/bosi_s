"""Точка входа Streamlit (Фаза 8).

Роутинг без `st.navigation`, чтобы приложение одинаково работало и в Docker,
и под `streamlit.testing.v1.AppTest` в тестах. Ширина — `wide`, но с
ограничениями, чтобы на 1366×768 не появлялся горизонтальный скролл.
"""

from __future__ import annotations

import logging
import os
import sys
import traceback
from pathlib import Path

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from boasi_ui import state  # noqa: E402
from boasi_ui.api import ApiClient, ApiError  # noqa: E402
from boasi_ui.pages import admin, dashboard, login, workspace  # noqa: E402

log = logging.getLogger("boasi.frontend")

# Метка версии интерфейса. Показывается в боковой панели: по ней видно, что
# браузер подхватил новый код, а не закэшировал старый модуль (ошибка в
# трассировке с указанием на `main` почти всегда означает старый файл).
UI_BUILD = "2026-10-02b"


def _setup_logging() -> None:
    """Писать логи интерфейса и в консоль, и в logs/frontend.log.

    Без файла трассировка упавшей страницы терялась: Streamlit отправляет её
    в браузер, а в stdout остаётся пусто.
    """
    log.setLevel(logging.INFO)
    if log.handlers:
        return
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    log.addHandler(stream)
    root = Path(__file__).resolve().parents[1] / "logs"
    try:
        root.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(root / "frontend.log", encoding="utf-8")
        file_handler.setFormatter(fmt)
        log.addHandler(file_handler)
    except OSError:
        # без прав на запись работаем только с консолью
        pass

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
    st.sidebar.caption(f"сборка {UI_BUILD}")
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


def render_page(name: str, renderer) -> None:
    """Отрисовать страницу, не давая одной упавшей вкладке обрушить всё.

    Раньше исключение из любой страницы всплывало прямо в `main()`, и
    пользователь видел только `File "app.py", line 90, in <module>` —
    без указания, что именно сломалось. Теперь ошибка показывается на
    месте: понятный текст, код ошибки и технические подробности под раскрытием.
    """
    try:
        renderer()
    except ApiError as exc:
        # Ошибки сервера тоже пишем в лог: по одной трассировке в браузере
        # причина не читается, а по логу — да.
        log.warning("Страница %s: ошибка API %s — %s", name, exc.status, exc.message)
        st.error(exc.message or "Ошибка обращения к серверу")
        if exc.detail:
            st.caption(f"Подробности: {exc.detail}")
    except Exception as exc:  # noqa: BLE001 — граница доверия к странице
        log.exception("Страница %s: непредвиденная ошибка", name)
        st.error(f"Страница «{name}» не отрисовалась: "
                 f"{type(exc).__name__}: {exc}")
        st.caption("Подробности — в logs/frontend.log и logs/backend.log. "
                   "Чтобы вернуться, откройте другую вкладку или перезапустите "
                   "интерфейс.")
        with st.expander("Технические подробности"):
            st.code(traceback.format_exc())


def main() -> None:
    _setup_logging()
    # Боковая панель вне границы страниц: падение здесь обрушило бы всё
    # приложение, поэтому она тоже защищена.
    try:
        sidebar()
    except Exception:  # noqa: BLE001
        log.exception("Боковая панель: непредвиденная ошибка")
        st.sidebar.caption("Панель недоступна — проверьте соединение с сервером.")
    page = st.session_state.get("page") or ("dashboard"
                                            if state.is_authenticated() else "login")
    if page == "login" or not state.is_authenticated():
        render_page("Вход", login.render)
    elif page == "admin":
        render_page("Администрирование", admin.render)
    elif page == "workspace":
        render_page("Сессия", workspace.render)
    else:
        render_page("Дашборд", dashboard.render)


main()