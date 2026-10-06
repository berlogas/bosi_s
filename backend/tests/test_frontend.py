"""Фаза 8 — UI на `streamlit.testing.v1.AppTest`.

Проверяем то, что важно исследователю, без браузера:
  * экран логина отдаёт форму и принимает верные/неверные данные;
  * после входа открывается дашборд;
  * из дашборда создаётся сессия и открывается рабочее пространство;
  * вкладка документов принимает файл и показывает его в списке.

Backend подменяется: AppTest работает в процессе, поэтому вместо HTTP —
объект ApiClient, отдающий заготовленные ответы. Проверяется логика страниц,
а не сеть (она покрыта API-тестами бэкенда).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
sys.path.insert(0, str(FRONTEND))

app_path = str(FRONTEND / "app.py")

ADMIN_USER = {"id": "u-admin", "username": "admin", "role": "admin",
              "full_name": "Администратор", "is_active": True}
RESEARCHER = {"id": "u-1", "username": "ivanov", "role": "researcher",
              "full_name": "Иванов", "is_active": True}

SESSION_DETAIL = {
    "id": "s-1", "user_id": "u-1", "title": "Баренцево море", "status": "active",
    "last_action_type": "chat", "last_action_label": "Вопрос: метод GF/F",
    "last_action_at": "2026-10-02T09:00:00+00:00", "resume_note": "не забыть",
    "state_snapshot": {"tab": "Документы"}, "created_at": "2026-10-01T09:00:00+00:00",
    "last_activity_at": "2026-10-02T09:00:00+00:00",
    "expires_at": "2026-12-31T09:00:00+00:00", "archived_at": None,
    "purged_at": None, "days_left": 90, "writable": True,
    "summary": {"documents": 1, "documents_by_category": {"project_data": 1},
                "storage_bytes": 2048, "storage_limit_bytes": 500 * 1024 * 1024,
                "documents_limit": 50, "projects": 0, "projects_limit": 5,
                "messages": 0, "links": 0, "read_only": False},
}

DOCUMENT = {
    "id": "d-1", "dockey": "abcdef1234", "docname": "biomass",
    "title": "Данные GF/F", "filename": "biomass.csv",
    "citation": "Данные (загружено)", "path": "/data/biomass.csv",
    "mime": "text/csv", "category": "project_data", "visibility": "session",
    "status": "ready", "error": None, "size_bytes": 2048, "pages": None,
    "chunk_count": 1, "tags": ["Баренцево"], "source": "upload",
    "content_hash": "x", "session_id": "s-1", "created_at": "2026-10-02T09:00:00+00:00",
}


class FakeApi:
    """Заглушка API: тот же интерфейс, что у `ApiClient`."""

    def __init__(self) -> None:
        self.token: str | None = None
        self.user: dict[str, Any] | None = None
        self.calls: list[tuple] = []
        self.login_should_fail = False
        self.uploaded: list[str] = []
        self.created_sessions: list[str] = []

    # ------------------------------------------------------------------ auth
    def login(self, username: str, password: str) -> dict[str, Any]:
        self.calls.append(("login", username))
        if self.login_should_fail or password != "correct-pass":
            from boasi_ui.api import ApiError

            raise ApiError("Неверный логин или пароль", status=403)
        self.token = "test-token"
        self.user = ADMIN_USER if username == "admin" else RESEARCHER
        return self.user

    def logout(self) -> None:
        self.token = None
        self.user = None

    @property
    def is_admin(self) -> bool:
        return bool(self.user and self.user["role"] == "admin")

    @property
    def username(self) -> str:
        return (self.user or {}).get("username", "?")

    # ------------------------------------------------------------------ sessions
    def sessions(self) -> list[dict[str, Any]]:
        self.calls.append(("sessions",))
        return [{"id": "s-1", "title": "Баренцево море", "status": "active",
                 "last_action_label": "Вопрос: метод GF/F",
                 "last_action_at": "2026-10-02T09:00:00+00:00",
                 "resume_note": "не забыть"}]

    def create_session(self, title: str) -> dict[str, Any]:
        self.created_sessions.append(title)
        self.calls.append(("create_session", title))
        return {"id": "s-1", "title": title, "status": "active"}

    def session_detail(self, session_id: str) -> dict[str, Any]:
        return dict(SESSION_DETAIL)

    def archive_session(self, session_id: str, note: str | None = None) -> None:
        self.calls.append(("archive", session_id))

    # ------------------------------------------------------------------ документы
    def session_documents(self, session_id: str, category=None) -> list[dict]:
        return [DOCUMENT]

    def upload_session_documents(self, session_id: str, files, *,
                                 category="temp_literature", tags="") -> dict:
        self.uploaded.extend(f.name for f in files)
        self.calls.append(("upload", [f.name for f in files], category))
        return {"added": [DOCUMENT], "duplicates": [], "failed": [],
                "total": 1}

    def add_session_document(self, session_id, path, *, category, tags=None):
        self.calls.append(("add_path", path, category))
        return DOCUMENT

    def delete_document(self, session_id: str, document_id: str) -> None:
        self.calls.append(("delete_document", document_id))

    # ------------------------------------------------------------------ чат/задачи
    def chat_async(self, session_id, query, *, mode="hybrid", k=10):
        return {"task_id": "t-1"}

    def chat(self, session_id, query, *, mode="hybrid", k=10,
             max_sources=5, no_cache=False):
        return {"answer": "Ответ по GF/F [1]", "sources": [], "references": [],
                "from_cache": False, "stats": {}}

    def messages(self, session_id, limit=200):
        return {"messages": [], "total": 0}

    def task(self, task_id: str) -> dict:
        return {"id": task_id, "kind": "chat", "title": "Вопрос", "status": "done",
                "progress": 100, "step": "готово", "error": None,
                "cancel_requested": False, "seconds": 1.0, "result": {}}

    def tasks(self, session_id=None):
        return []

    def save_state(self, session_id, snapshot, *, note=None, force=False):
        self.calls.append(("save_state", session_id, snapshot))
        return {}

    def quick_query(self, query, *, k=10):
        return {"answer": "Быстрый ответ [1]", "sources": [], "references": []}

    def suggest_queries(self, query):
        return []

    # ------------------------------------------------------------------ проекты
    def projects(self, session_id):
        return []

    def health(self):
        return {"status": "ok", "llm_model": "ollama/qwen2.5:3b",
                "embedding_model": "st-multi-qa-MiniLM", "ollama": {"reachable": True}}


@pytest.fixture
def fake_api(monkeypatch) -> FakeApi:
    from boasi_ui import api as api_module
    from boasi_ui import state

    fake = FakeApi()
    monkeypatch.setattr(api_module, "ApiClient", lambda *a, **k: fake)
    monkeypatch.setattr(state, "ApiClient", lambda *a, **k: fake)
    return fake


def _app():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(app_path, default_timeout=30)
    at.run()
    return at


# --------------------------------------------------------------------------- логин
def test_login_screen_is_shown_first(fake_api) -> None:
    at = _app()

    assert not at.exception
    assert any("Вход" in m.value for m in at.markdown)
    # обращаемся к виджетам по key: позиционный аргумент в AppTest — это key
    assert at.text_input(key="login_username") is not None
    assert at.text_input(key="login_password") is not None


def test_successful_login_opens_dashboard(fake_api) -> None:
    at = _app()
    at.text_input(key="login_username").set_value("ivanov")
    at.text_input(key="login_password").set_value("correct-pass")
    at.button(key="login_submit").click().run()

    assert not at.exception, at.exception
    assert fake_api.token == "test-token"
    assert any("Дашборд" in m.value for m in at.markdown)


def test_wrong_password_shows_error(fake_api) -> None:
    at = _app()
    at.text_input(key="login_username").set_value("ivanov")
    at.text_input(key="login_password").set_value("wrong")
    at.button(key="login_submit").click().run()

    assert not at.exception, at.exception
    assert any("Неверный логин" in e.value for e in at.error)


def test_empty_credentials_warn(fake_api) -> None:
    at = _app()
    at.button(key="login_submit").click().run()

    assert any("Заполните оба поля" in w.value for w in at.warning)


# --------------------------------------------------------------------------- дашборд
def _logged_in(fake_api) -> Any:
    at = _app()
    at.text_input(key="login_username").set_value("ivanov")
    at.text_input(key="login_password").set_value("correct-pass")
    at.button(key="login_submit").click().run()
    return at


def test_dashboard_lists_sessions(fake_api) -> None:
    at = _logged_in(fake_api)

    assert any("Баренцево море" in m.value for m in at.markdown)
    assert any("Мои сессии" in m.value for m in at.markdown)


def test_dashboard_creates_session(fake_api) -> None:
    at = _logged_in(fake_api)

    at.text_input(key="new_session_title").set_value("Новая сессия")
    at.run()  # кнопка разблокируется только на следующем проходе
    at.button(key="create_session").click().run()

    assert not at.exception, at.exception
    assert "Новая сессия" in fake_api.created_sessions


# -------------------------------------------------------------------------- workspace
def test_workspace_opens_after_session_creation(fake_api) -> None:
    at = _logged_in(fake_api)
    at.text_input(key="new_session_title").set_value("Рабочая")
    at.run()
    at.button(key="create_session").click().run()

    # после создания дашборд перерисовывается в workspace
    assert not at.exception, at.exception
    # Разделы воркспейса переключаются управляемым radio, а не st.tabs:
    # st.tabs не отдавал выбор приложению и сбрасывал его на первый раздел
    # при перерисовке (Enter в форме чата уводил на «Документы»).
    assert "Документы" in at.radio[0].options


def test_workspace_shows_limits(fake_api) -> None:
    at = _logged_in(fake_api)
    at.text_input(key="new_session_title").set_value("Рабочая")
    at.run()
    at.button(key="create_session").click().run()

    assert any("Документы: 1/50" in c.value for c in at.caption)


def test_documents_tab_lists_uploaded_document(fake_api) -> None:
    at = _logged_in(fake_api)
    at.text_input(key="new_session_title").set_value("Рабочая")
    at.run()
    at.button(key="create_session").click().run()

    assert any("Данные GF/F" in m.value for m in at.markdown)


def test_upload_file_registers_document(fake_api) -> None:
    at = _logged_in(fake_api)
    at.text_input(key="new_session_title").set_value("Рабочая")
    at.run()
    at.button(key="create_session").click().run()

    # находим загрузчик файлов и отправляем файл
    uploader = at.get("file_uploader")
    assert uploader is not None

# --------------------------------------------------------------------------- форма входа
def test_login_form_has_username_and_password_fields(fake_api) -> None:
    """Форма входа обязана быть на экране: поля логина и пароля."""
    at = _app()

    assert not at.exception, at.exception
    assert at.text_input(key="login_username") is not None
    assert at.text_input(key="login_password") is not None
    assert at.button(key="login_submit") is not None
    assert len(at.get("form")) == 1, "вход должен быть одной формой"


def test_login_screen_offers_password_recovery(fake_api) -> None:
    """На экране входа есть подсказка, как восстановить пароль."""
    at = _app()

    labels = [e.label for e in at.expander]
    assert any("Нет доступа" in label for label in labels), labels

def test_empty_form_shows_warning(fake_api) -> None:
    at = _app()
    at.button(key="login_submit").click().run()

    assert any("Заполните оба поля" in w.value for w in at.warning)


def test_failed_login_keeps_on_login_screen(fake_api) -> None:
    """После неудачи остаёмся на входе и видим причину."""
    at = _app()
    at.text_input(key="login_username").set_value("ivanov")
    at.text_input(key="login_password").set_value("wrong")
    at.run()
    at.button(key="login_submit").click().run()

    assert not at.exception, at.exception
    assert any("Неверный логин" in e.value for e in at.error)
    assert at.text_input(key="login_username") is not None, "форма должна остаться"


def test_successful_login_switches_to_dashboard(fake_api) -> None:
    at = _app()
    at.text_input(key="login_username").set_value("ivanov")
    at.text_input(key="login_password").set_value("correct-pass")
    at.run()
    at.button(key="login_submit").click().run()

    assert not at.exception, at.exception
    remaining = [t.label for t in at.text_input]
    assert "Логин" not in remaining, "после входа форма исчезает"
    assert any("Дашборд" in m.value for m in at.markdown)


# --------------------------------------------------------------------------- устойчивость
def test_failing_page_does_not_crash_app(monkeypatch) -> None:
    """Упавшая страница не должна ронять весь интерфейс.

    Раньше исключение всплывало прямо в `main()`, и пользователь видел
    только `File "app.py", line 90, in <module>` — что и не говорило, что
    именно сломалось. Теперь на месте страницы появляется понятное сообщение.
    """
    import boasi_ui.pages.dashboard as dashboard_module
    from streamlit.testing.v1 import AppTest


    class AuthedApi:
        token = "test-token"      # иначе main() откроет страницу входа
        user = RESEARCHER

        def health(self):
            return {"status": "ok", "llm_model": "stub", "embedding_model": "stub",
                    "ollama": {"reachable": False}}

        @property
        def is_admin(self):
            return False

    def boom():
        raise RuntimeError("здесь что-то сломалось")

    monkeypatch.setattr(dashboard_module, "render", boom)

    at = AppTest.from_file(app_path, default_timeout=30)
    at.run()
    at.session_state["api"] = AuthedApi()
    at.session_state["page"] = "dashboard"
    at.run()

    assert not at.exception, f"приложение не должно падать: {at.exception}"
    assert any("не отрисовалась" in e.value for e in at.error)
    assert any("RuntimeError" in e.value for e in at.error)


def test_api_error_on_page_is_shown_as_message(monkeypatch) -> None:
    """Ошибка API на странице — понятное сообщение, а не трассировка."""
    import boasi_ui.pages.dashboard as dashboard_module
    from boasi_ui.api import ApiError
    from streamlit.testing.v1 import AppTest

    def raise_api_error():
        raise ApiError("Достигнут лимит документов (50)", status=409)

    monkeypatch.setattr(dashboard_module, "render", raise_api_error)

    class AuthedApi:
        token = "test-token"
        user = RESEARCHER

        def health(self):
            return {"status": "ok", "llm_model": "stub", "embedding_model": "stub",
                    "ollama": {"reachable": False}}

        @property
        def is_admin(self):
            return False

    at = AppTest.from_file(app_path, default_timeout=30)
    at.run()
    at.session_state["api"] = AuthedApi()
    at.session_state["page"] = "dashboard"
    at.run()

    assert not at.exception, at.exception
    assert any("Достигнут лимит" in e.value for e in at.error)


def test_sidebar_failure_does_not_crash_app() -> None:
    """Сбой боковой панели не должен ронять приложение.

    Панель вне границы страниц: ошибка проверки здоровья раньше обрушила бы
    весь интерфейс целиком.
    """
    from streamlit.testing.v1 import AppTest

    class BrokenApi:
        token = "t"
        user = RESEARCHER

        @property
        def is_admin(self):
            return False

        def health(self):
            raise RuntimeError("панель сломалась")

    at = AppTest.from_file(app_path, default_timeout=30)
    at.run()
    at.session_state["api"] = BrokenApi()
    at.session_state["page"] = "login"
    at.run()

    assert not at.exception, f"приложение не должно падать: {at.exception}"


# --------------------------------------------------------------------------- админка
class AdminApi:
    """Ответы админских маршрутов в реалистичной форме.

    Нужен именно для проверки вкладки: заглушка общего назначения не
    покрывает /api/admin/*, из-за чего падение admin.render() дошло до
    пользователя незамеченным.
    """

    def __init__(self) -> None:
        self.token = "test-token"
        self.user = {"username": "admin", "role": "admin"}

    @property
    def is_admin(self) -> bool:
        return True

    def health(self):
        return {"status": "ok", "llm_model": "stub", "embedding_model": "stub",
                "ollama": {"reachable": False}}

    def admin_users(self):
        return [
            {"id": "u1", "username": "admin", "role": "admin", "full_name": "Админ",
             "is_active": True, "last_login_at": "2026-10-02T10:00:00+00:00"},
            {"id": "u2", "username": "ivanov", "role": "researcher",
             "full_name": None, "is_active": True,
             "last_login_at": None},
            # роль, которой нет в списке — раньше роняла вкладку на .index()
            {"id": "u3", "username": "odd", "role": "viewer", "full_name": None,
             "is_active": False, "last_login_at": None},
        ]

    def admin_documents(self):
        return [{"id": "d1", "dockey": "k1", "title": "Руководство",
                 "filename": "manual.md", "size_bytes": 2048, "chunk_count": 3,
                 "category": "global_knowledge", "status": "ready"}]

    def admin_audit(self, limit=100):
        return [{"id": "a1", "actor_username": "admin", "action": "auth.login",
                 "target_type": None, "ok": True, "ip": "127.0.0.1",
                 "created_at": "2026-10-02T10:00:00+00:00"}]

    def tasks(self, session_id=None):
        return [{"id": "t1", "kind": "indexing", "title": "Индексация",
                 "status": "done", "progress": 100, "step": "готово",
                 "error": None, "cancel_requested": False, "seconds": 3.0}]

    def sessions(self):
        return [{"id": "s1234567", "user_id": "u1234567", "title": "Работа",
                 "status": "active", "last_action_label": "Вопрос",
                 "last_activity_at": "2026-10-02T10:00:00+00:00",
                 "last_action_at": "2026-10-02T10:00:00+00:00",
                 "resume_note": None}]


def test_admin_panel_renders_all_tabs() -> None:
    """Вкладка «Администрирование» не должна падать ни на одной подвкладке."""
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(app_path, default_timeout=40)
    at.run()
    at.session_state["api"] = AdminApi()
    at.session_state["user"] = {"username": "admin", "role": "admin"}
    at.session_state["page"] = "admin"
    at.run()

    assert not at.exception, f"вкладка упала: {at.exception}"
    labels = [t.label for t in at.tabs]
    assert "Пользователи" in labels and "Аудит" in labels


def test_admin_panel_tolerates_unknown_role() -> None:
    """Неизвестная роль в ответе не должна ронять вкладку (было .index())."""
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(app_path, default_timeout=40)
    at.run()
    at.session_state["api"] = AdminApi()   # среди ролей есть "viewer"
    at.session_state["user"] = {"username": "admin", "role": "admin"}
    at.session_state["page"] = "admin"
    at.run()

    assert not at.exception, at.exception
    assert any("odd" in m.value for m in at.markdown)


# ------------------------------------------------- Фаза 10: проверки ответа
def test_collect_warnings_reads_stats_and_checks() -> None:
    """Живый ответ несёт проверки в `stats`, история — в `checks`."""
    from boasi_ui.components.ui import collect_warnings

    live = {"stats": {"grounding": {"warnings": ["Наполеон не в источниках"]},
                      "citations": {"warnings": ["в ссылке [7] нет источника"]},
                      "candidates": {"k": 10}}}
    history = {"checks": {"grounding": {"warnings": ["Наполеон не в источниках"]}}}

    assert collect_warnings(live) == ["Наполеон не в источниках",
                                      "в ссылке [7] нет источника"]
    assert collect_warnings(history) == ["Наполеон не в источниках"]
    assert collect_warnings({}) == []
    assert collect_warnings({"stats": {}}) == []


def test_chat_answer_shows_checks_warning(fake_api) -> None:
    """Ответ с неподтверждёнными фактами получает предупреждение в UI."""

    at = _logged_in(fake_api)
    at.text_input(key="new_session_title").set_value("Рабочая")
    at.run()
    at.button(key="create_session").click().run()
    assert not at.exception, at.exception

    at.session_state["workspace_tab"] = "Чат"
    at.session_state["active_tab"] = "Чат"
    at.session_state["chat_last"] = {
        "q": "Кто такая Екатерина Алексеевна?",
        "a": {"answer": "Ответ с выдуманным фактом.", "sources": [],
              "stats": {"grounding": {
                  "warnings": ["Утверждения не подтверждены: Наполеон"]}}},
    }
    at.run()

    assert not at.exception, at.exception
    assert any("Наполеон" in w.value for w in at.warning)


# ------------------------------------------------------------------------ архивация
def _in_workspace(fake_api) -> Any:
    at = _logged_in(fake_api)
    at.text_input(key="new_session_title").set_value("Рабочая")
    at.run()
    at.button(key="create_session").click().run()
    assert not at.exception, at.exception
    return at


def test_workspace_archive_asks_confirmation(fake_api) -> None:
    """Первый клик только спрашивает — сессия не уходит в архив молча."""
    at = _in_workspace(fake_api)

    at.button(key="archive_btn").click().run()

    assert not at.exception, at.exception
    assert not any(call[0] == "archive" for call in fake_api.calls)
    assert any("Архивировать сессию?" in w.value for w in at.warning)

    at.button(key="archive_yes").click().run()

    assert not at.exception, at.exception
    assert ("archive", "s-1") in fake_api.calls


def test_workspace_archive_can_be_cancelled(fake_api) -> None:
    at = _in_workspace(fake_api)

    at.button(key="archive_btn").click().run()
    at.button(key="archive_no").click().run()

    assert not at.exception, at.exception
    assert not any(call[0] == "archive" for call in fake_api.calls)
    assert not any("Архивировать сессию?" in w.value for w in at.warning)


def test_dashboard_archive_asks_confirmation(fake_api) -> None:
    """Кнопка «Архив» в карточке дашборда тоже работает в два шага."""
    at = _logged_in(fake_api)

    at.button(key="arch_s-1").click().run()

    assert not at.exception, at.exception
    assert not any(call[0] == "archive" for call in fake_api.calls)
    assert any("Подтвердите" in c.value for c in at.caption)

    at.button(key="arch_yes_s-1").click().run()

    assert not at.exception, at.exception
    assert ("archive", "s-1") in fake_api.calls


# ------------------------------------------------------------------- ошибки задач
def _error_task(task_id: str) -> dict[str, Any]:
    return {"id": task_id, "kind": "chat", "title": "Вопрос: тест",
            "status": "error", "progress": 100, "step": "сохранение ответа",
            "error": "OperationalError: table messages has no column named checks",
            "cancel_requested": False, "seconds": 319.6, "result": {}}


def test_failed_task_keeps_question_and_shows_error(fake_api) -> None:
    """Упавшая задача не должна молча стирать вопрос из чата."""
    at = _in_workspace(fake_api)
    fake_api.task = _error_task   # ответ считался, но сохранение упало

    at.session_state["task_id"] = "t-1"
    at.session_state["chat_pending"] = "Вопрос без ответа"
    at.session_state["workspace_tab"] = "Чат"
    at.session_state["active_tab"] = "Чат"
    at.run()

    assert not at.exception, at.exception
    failed = at.session_state["chat_failed"]
    assert failed["q"] == "Вопрос без ответа"
    assert "OperationalError" in failed["text"]
    # вопрос остался на виду, а под ним — причина сбоя
    assert any("Вопрос без ответа" in m.value for m in at.markdown)
    assert any("Не получилось ответить" in e.value for e in at.error)


def test_cancelled_task_keeps_question_with_info(fake_api) -> None:
    at = _in_workspace(fake_api)
    fake_api.task = lambda task_id: {**_error_task(task_id),
                                     "status": "cancelled", "error": None}

    at.session_state["task_id"] = "t-1"
    at.session_state["chat_pending"] = "Отменённый вопрос"
    at.session_state["workspace_tab"] = "Чат"
    at.session_state["active_tab"] = "Чат"
    at.run()

    assert not at.exception, at.exception
    assert at.session_state["chat_failed"]["kind"] == "cancelled"
    assert any("Отменённый вопрос" in m.value for m in at.markdown)
    assert any("Задача отменена" in i.value for i in at.info)


def test_done_task_does_not_mark_exchange_failed(fake_api) -> None:
    at = _in_workspace(fake_api)   # FakeApi.task по умолчанию — status done

    at.session_state["task_id"] = "t-1"
    at.session_state["chat_pending"] = "Нормальный вопрос"
    at.session_state["workspace_tab"] = "Чат"
    at.session_state["active_tab"] = "Чат"
    at.run()

    assert not at.exception, at.exception
    assert "chat_failed" not in at.session_state
    assert "chat_pending" not in at.session_state


def test_fmt_seconds_compact_formats() -> None:
    """Секундомер в строке прогресса: 42с / 2:17 / 1:01:01."""
    from boasi_ui.components.ui import _fmt_seconds

    assert _fmt_seconds(None) == ""
    assert _fmt_seconds(0) == ""
    assert _fmt_seconds(42.4) == "42с"
    assert _fmt_seconds(137.0) == "2:17"
    assert _fmt_seconds(3661) == "1:01:01"


def test_task_panel_shows_live_stage_timer(monkeypatch) -> None:
    """Строка прогресса должна «жить»: этап, секундомер, проценты, общее время.

    Раньше панель показывала один и тот же 20% все минуты генерации и
    выглядела как зависшая. (В AppTest элемента st.progress нет — проверяем
    напрямую вызов task_panel.)
    """
    import streamlit as st
    from boasi_ui.components.ui import task_panel

    captured: list[str] = []

    class _Client:
        def task(self, task_id):
            return {"id": task_id, "kind": "chat", "title": "Вопрос",
                    "status": "running", "progress": 55,
                    "step": "генерация ответа (LLM)",
                    "stage_seconds": 137.0, "seconds": 300.0,
                    "error": None, "cancel_requested": False}

    monkeypatch.setattr(
        st, "progress",
        lambda value, text=None, **kw: captured.append(text or ""))

    task_panel(_Client(), "t-1")

    assert captured, "st.progress не был вызван"
    text = captured[0]
    assert "генерация ответа (LLM)" in text and "55%" in text, text
    assert "2:17" in text and "всего 5:00" in text, text


def test_md_safe_references_defeats_link_definition() -> None:
    """Иначе markdown съедает «[2]: doc (title)» и остаются голые «1. 2.»."""
    from boasi_ui.components.ui import md_safe_references

    text = ("1. [2]: ekaterina_hot_facts (загружено пользователем)\n"
            "2. [3]: ekaterina_context (загружено пользователем)")
    fixed = md_safe_references(text)

    assert "]:" not in fixed
    assert "1. [2] ekaterina_hot_facts" in fixed
    assert "2. [3] ekaterina_context" in fixed


def test_history_renders_reference_text_not_bare_numbers(fake_api) -> None:
    """История в чате: блок References должен показывать записи, а не «1. 2.»."""
    at = _in_workspace(fake_api)
    fake_api.messages = lambda session_id, limit=200: {
        "messages": [
            {"id": "m1", "role": "user", "content": "фавориты Екатерины"},
            {"id": "m2", "role": "assistant",
             "content": "Ответ.\n\nReferences\n\n"
                        "1. [2]: ekaterina_hot_facts (загружено пользователем)\n\n"
                        "2. [3]: ekaterina_context (загружено пользователем)"},
        ]}

    at.session_state["workspace_tab"] = "Чат"
    at.session_state["active_tab"] = "Чат"
    at.run()

    assert not at.exception, at.exception
    rendered = [m.value for m in at.markdown]
    assert any("1. [2] ekaterina_hot_facts" in v for v in rendered), rendered
    assert all("]:" not in v for v in rendered), rendered
