"""HTTP-клиент API: разбор ошибок и успешных ответов.

До появления этого файла UI-тесты работали с заглушкой FakeApi и не касались
настоящего `ApiClient`. Из-за этого в код прокралась ошибка: кортеж из
`_explain` распаковывался в `ApiError` позиционно, хотя `status` и `detail`
объявлены keyword-only. Любой ответ 4xx/5xx ронял интерфейс с TypeError
вместо нормального сообщения — то есть неверный пароль показывался аварийно.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
sys.path.insert(0, str(FRONTEND))

from boasi_ui.api import ApiClient, ApiError  # noqa: E402


class FakeResponse:
    """Минимальный ответ requests.Response."""

    def __init__(self, status_code: int, body=None, text: str = "") -> None:
        self.status_code = status_code
        self._body = body
        self.text = text
        self.content = json.dumps(body).encode("utf-8") if body is not None else text.encode()

    def json(self) -> dict:
        if self._body is None:
            raise ValueError("нет json")
        return self._body


@pytest.fixture
def client(monkeypatch) -> ApiClient:
    api = ApiClient(base_url="http://test")
    return api


def _patch(monkeypatch, api: ApiClient, response: FakeResponse) -> None:
    import requests

    def fake_request(*args, **kwargs):
        return response

    monkeypatch.setattr(requests, "request", fake_request)


# --------------------------------------------------------------------------- ошибки
def test_error_response_is_parsed(client, monkeypatch) -> None:
    """403 от логина должен превратиться в ApiError с текстом, а не TypeError."""
    _patch(monkeypatch, client,
           FakeResponse(403, {"error": "forbidden",
                              "detail": "Неверный логин или пароль"}))

    with pytest.raises(ApiError) as exc:
        client.login("ivanov", "wrong")

    assert exc.value.message == "Неверный логин или пароль"
    assert exc.value.status == 403
    # detail хранит сырой текст ответа (здесь он совпадает с message)
    assert exc.value.detail


def test_limit_error_includes_limit(client, monkeypatch) -> None:
    """409 с лимитом должен называть сам лимит — этим пользуется UI."""
    _patch(monkeypatch, client,
           FakeResponse(409, {"error": "limit_exceeded",
                              "detail": "Достигнут лимит",
                              "meta": {"limit": 50, "current": 50}}))

    with pytest.raises(ApiError) as exc:
        client.sessions()

    assert exc.value.status == 409
    assert "50" in exc.value.message
    assert "Достигнут лимит" in exc.value.message


def test_unauthorized_is_reported_as_session_expired(client, monkeypatch) -> None:
    _patch(monkeypatch, client, FakeResponse(401, {"detail": "Токен истёк"}))

    with pytest.raises(ApiError) as exc:
        client.me()

    assert exc.value.status == 401
    assert "Сессия истекла" in exc.value.message


def test_non_json_error_body_is_handled(client, monkeypatch) -> None:
    """Ответ без JSON (например, HTML от прокси) не должен ронять UI."""
    _patch(monkeypatch, client, FakeResponse(502, None, text="<html>Bad Gateway</html>"))

    with pytest.raises(ApiError) as exc:
        client.sessions()

    assert exc.value.status == 502
    assert "Bad Gateway" in exc.value.message


def test_backend_unreachable_gives_actionable_message(client, monkeypatch) -> None:
    import requests

    def boom(*args, **kwargs):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(requests, "request", boom)

    with pytest.raises(ApiError) as exc:
        client.sessions()

    assert "недоступен" in exc.value.message.lower()
    assert "http://test" in exc.value.message


# --------------------------------------------------------------------------- успех
def test_login_stores_tokens(client, monkeypatch) -> None:
    _patch(monkeypatch, client,
           FakeResponse(200, {"user": {"username": "ivanov", "role": "researcher"},
                              "tokens": {"access_token": "a", "refresh_token": "r"}}))

    user = client.login("ivanov", "correct-pass")

    assert user["username"] == "ivanov"
    assert client.token == "a"
    assert client.refresh_token == "r"
    assert client.is_admin is False


def test_admin_role_detected(client, monkeypatch) -> None:
    _patch(monkeypatch, client,
           FakeResponse(200, {"user": {"username": "admin", "role": "admin"},
                              "tokens": {"access_token": "a", "refresh_token": "r"}}))

    client.login("admin", "pass")
    assert client.is_admin is True


def test_authorization_header_is_sent(client, monkeypatch) -> None:
    """Токен должен уходить в заголовке — иначе запросы 401."""
    import requests

    seen: dict = {}

    def fake_request(method, url, **kwargs):
        seen.update(kwargs.get("headers") or {})
        return FakeResponse(200, {"id": "s-1"})

    monkeypatch.setattr(requests, "request", fake_request)

    client.token = "secret-token"
    client.session_detail("s-1")

    assert seen.get("Authorization") == "Bearer secret-token"


def test_logout_clears_tokens_even_if_server_errors(client, monkeypatch) -> None:
    """Выход не должен падать из-за сети — состояние чистится локально."""
    _patch(monkeypatch, client, FakeResponse(500, {"detail": "oops"}))
    client.token = "a"
    client.refresh_token = "r"

    client.logout()

    assert client.token is None and client.refresh_token is None


def test_raw_request_returns_bytes(client, monkeypatch) -> None:
    """Экспорт отдаёт бинарный файл — response.content должен доходить."""
    _patch(monkeypatch, client, FakeResponse(200, {"a": 1}))

    content = client.export_project("s-1", "p-1", "docx")

    assert isinstance(content, bytes) and content

# ------------------------------------------------------- нестандартные тела ошибок
def test_meta_null_does_not_crash(client, monkeypatch) -> None:
    """`"meta": null` раньше ронял интерфейс AttributeError прямо на вызове.

    dict.get возвращает None, если ключ есть со значением null, — а следом
    .get("limit") на None падал. Ловушка страницы такое исключение не ловила,
    поэтому пользователь видел трассировку вместо сообщения об ошибке.
    """
    _patch(monkeypatch, client,
           FakeResponse(409, {"error": "limit_exceeded", "detail": "Лимит",
                              "meta": None}))

    with pytest.raises(ApiError) as exc:
        client.admin_audit()

    assert exc.value.status == 409
    assert "Лимит" in exc.value.message


def test_meta_is_not_dict(client, monkeypatch) -> None:
    _patch(monkeypatch, client,
           FakeResponse(409, {"detail": "Лимит", "meta": ["a", "b"]}))

    with pytest.raises(ApiError) as exc:
        client.admin_audit()

    assert "Лимит" in exc.value.message


def test_body_is_json_array(client, monkeypatch) -> None:
    """Прокси мог вернуть массив вместо объекта."""
    _patch(monkeypatch, client, FakeResponse(502, ["upstream", "error"]))

    with pytest.raises(ApiError) as exc:
        client.admin_audit()

    assert exc.value.status == 502
    assert "upstream" in exc.value.message


def test_body_is_json_string(client, monkeypatch) -> None:
    _patch(monkeypatch, client, FakeResponse(500, "internal error"))

    with pytest.raises(ApiError) as exc:
        client.admin_audit()

    assert exc.value.status == 500


def test_empty_error_body_is_reported_cleanly(client, monkeypatch) -> None:
    """Пустое тело не должно давать ни исключений, ни пустых сообщений."""
    _patch(monkeypatch, client, FakeResponse(503, None, text=""))

    with pytest.raises(ApiError) as exc:
        client.admin_audit()

    assert exc.value.status == 503
    assert exc.value.message.strip()
