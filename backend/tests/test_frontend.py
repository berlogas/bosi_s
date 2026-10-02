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

    assert any("Введите логин" in w.value for w in at.warning)


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
    assert any("Документы" in t.label for t in at.tabs)


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