"""HTTP-клиент к backend API (Фаза 8).

Отдельный слой, чтобы UI не знал деталей транспорта: страницы вызывают
`api.login(...)`, `api.sessions()` и т.д. Ошибки превращаются в `ApiError`
с понятным текстом — Streamlit сам по себе показывает голый traceback, а
исследователю это не помогает.
"""

from __future__ import annotations

import os
from typing import Any

import requests

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")
DEFAULT_TIMEOUT = 30


class ApiError(Exception):
    """Ошибка API с сообщением для пользователя."""

    def __init__(self, message: str, *, status: int | None = None,
                 detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.detail = detail


class ApiClient:
    def __init__(self, base_url: str = API_URL,
                 timeout: int = DEFAULT_TIMEOUT) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.token: str | None = None
        self.refresh_token: str | None = None
        self.user: dict[str, Any] | None = None

    # ------------------------------------------------------------------ транспорт
    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def request(self, method: str, path: str, *, json: Any = None,
                files: Any = None, data: Any = None, params: Any = None,
                timeout: int | None = None, raw: bool = False) -> Any:
        try:
            response = requests.request(
                method, self.url(path), json=json, files=files, data=data,
                params=params, headers=self.headers,
                timeout=timeout or self.timeout)
        except requests.RequestException as exc:
            raise ApiError(
                f"Backend недоступен ({self.base_url}). Проверьте, что он запущен."
            ) from exc

        if response.status_code == 401:
            raise ApiError("Сессия истекла. Войдите заново.", status=401)

        if response.status_code >= 400:
            # status/detail — keyword-only, поэтому кортеж из _explain нельзя
            # распаковывать позиционно: передаём по именам явно.
            message, error_status, detail = self._explain(response)
            raise ApiError(message, status=error_status, detail=detail)

        if raw:
            return response
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

    @staticmethod
    def _explain(response: requests.Response) -> tuple[str, int | None, str | None]:
        detail: str | None = None
        message = f"Ошибка {response.status_code}"
        try:
            body = response.json()
            detail = body.get("detail") or body.get("error")
            if body.get("meta", {}).get("limit"):
                message = f"{detail or message} (лимит: {body['meta']['limit']})"
            else:
                message = detail or message
        except ValueError:
            detail = response.text[:300]
            message = detail or message
        return message, response.status_code, detail

    # ------------------------------------------------------------------ auth
    def login(self, username: str, password: str) -> dict[str, Any]:
        body = self.request("POST", "/api/auth/login",
                            json={"username": username, "password": password})
        self.token = body["tokens"]["access_token"]
        self.refresh_token = body["tokens"]["refresh_token"]
        self.user = body["user"]
        return self.user

    def logout(self) -> None:
        if self.refresh_token:
            try:
                self.request("POST", "/api/auth/logout",
                             json={"refresh_token": self.refresh_token})
            except ApiError:
                pass  # выход не должен падать из-за сети
        self.token = self.refresh_token = None
        self.user = None

    def me(self) -> dict[str, Any]:
        self.user = self.request("GET", "/api/auth/me")
        return self.user

    @property
    def is_admin(self) -> bool:
        return bool(self.user and self.user.get("role") == "admin")

    @property
    def username(self) -> str:
        return (self.user or {}).get("username", "?")

    # ------------------------------------------------------------------ сессии
    def sessions(self) -> list[dict[str, Any]]:
        return self.request("GET", "/api/sessions")

    def create_session(self, title: str) -> dict[str, Any]:
        return self.request("POST", "/api/sessions", json={"title": title})

    def session_detail(self, session_id: str) -> dict[str, Any]:
        return self.request("GET", f"/api/sessions/{session_id}")

    def patch_session(self, session_id: str, **fields: Any) -> dict[str, Any]:
        return self.request("PATCH", f"/api/sessions/{session_id}", json=fields)

    def save_state(self, session_id: str, snapshot: dict[str, Any],
                   *, note: str | None = None, force: bool = False) -> Any:
        return self.request("PUT", f"/api/sessions/{session_id}/state",
                            json={"snapshot": snapshot, "resume_note": note,
                                  "force": force})

    def resume_session(self, session_id: str) -> dict[str, Any]:
        return self.request("POST", f"/api/sessions/{session_id}/resume")

    def pause_session(self, session_id: str, note: str | None = None) -> Any:
        return self.request("POST",
                            f"/api/sessions/{session_id}/pause",
                            params={"note": note} if note else None)

    def archive_session(self, session_id: str, note: str | None = None) -> Any:
        return self.request("POST",
                            f"/api/sessions/{session_id}/archive",
                            params={"note": note} if note else None)

    def heartbeat(self, session_id: str) -> Any:
        return self.request("POST", f"/api/sessions/{session_id}/heartbeat")

    # ------------------------------------------------------------------ документы
    def session_documents(self, session_id: str,
                          category: str | None = None) -> list[dict[str, Any]]:
        return self.request("GET", f"/api/sessions/{session_id}/documents",
                            params={"category": category} if category else None)

    def add_session_document(self, session_id: str, path: str, *,
                             category: str = "temp_literature",
                             tags: list[str] | None = None) -> dict[str, Any]:
        return self.request(
            "POST", f"/api/sessions/{session_id}/documents/path",
            json={"path": path, "category": category, "tags": tags or []})

    def upload_session_documents(self, session_id: str, files: list[Any], *,
                                 category: str = "temp_literature",
                                 tags: str = "") -> dict[str, Any]:
        payload = [("files", (f.name, f.getvalue())) for f in files]
        return self.request("POST",
                            f"/api/sessions/{session_id}/documents/upload",
                            files=payload,
                            data={"category": category, "tags": tags},
                            timeout=3600)

    def delete_document(self, session_id: str, document_id: str) -> Any:
        return self.request(
            "DELETE", f"/api/sessions/{session_id}/documents/{document_id}")

    # ------------------------------------------------------------------ чат
    def chat(self, session_id: str, query: str, *, mode: str = "hybrid",
             k: int = 10, max_sources: int = 5,
             no_cache: bool = False) -> dict[str, Any]:
        return self.request("POST", "/api/chat/query",
                            json={"session_id": session_id, "query": query,
                                  "mode": mode, "k": k,
                                  "max_sources": max_sources,
                                  "no_cache": no_cache},
                            timeout=3600)

    def chat_async(self, session_id: str, query: str, *, mode: str = "hybrid",
                   k: int = 10) -> dict[str, Any]:
        return self.request("POST", "/api/chat/query-async",
                            json={"session_id": session_id, "query": query,
                                  "mode": mode, "k": k})

    def quick_query(self, query: str, *, k: int = 10) -> dict[str, Any]:
        return self.request("POST", "/api/chat/quick-query",
                            json={"query": query, "k": k}, timeout=3600)

    def messages(self, session_id: str, limit: int = 200) -> dict[str, Any]:
        return self.request("GET", "/api/chat/messages",
                            params={"session_id": session_id, "limit": limit})

    def suggest_queries(self, query: str) -> list[str]:
        body = self.request("GET", "/api/chat/suggest-queries",
                            params={"query": query})
        return body.get("suggestions", [])

    # ------------------------------------------------------------------ проекты
    def projects(self, session_id: str) -> list[dict[str, Any]]:
        return self.request("GET", f"/api/sessions/{session_id}/projects")

    def create_project(self, session_id: str, title: str,
                       journal: str | None = None) -> dict[str, Any]:
        return self.request("POST", f"/api/sessions/{session_id}/projects",
                            json={"title": title,
                                  "target_journal": journal or None})

    def patch_project(self, session_id: str, project_id: str,
                      **fields: Any) -> dict[str, Any]:
        return self.request(
            "PATCH", f"/api/sessions/{session_id}/projects/{project_id}",
            json=fields)

    def delete_project(self, session_id: str, project_id: str) -> Any:
        return self.request(
            "DELETE", f"/api/sessions/{session_id}/projects/{project_id}")

    def sections(self, session_id: str, project_id: str) -> list[dict[str, Any]]:
        return self.request(
            "GET", f"/api/sessions/{session_id}/projects/{project_id}/sections")

    def save_section(self, session_id: str, project_id: str, name: str, **fields
                     ) -> dict[str, Any]:
        return self.request(
            "PUT",
            f"/api/sessions/{session_id}/projects/{project_id}/sections/{name}",
            json=fields)

    def project_documents(self, session_id: str, project_id: str) -> list[dict]:
        return self.request(
            "GET", f"/api/sessions/{session_id}/projects/{project_id}/documents")

    def bind_document(self, session_id: str, project_id: str, document_id: str,
                      role: str = "reference") -> Any:
        return self.request(
            "POST", f"/api/sessions/{session_id}/projects/{project_id}/documents",
            json={"document_id": document_id, "role": role})

    def unbind_document(self, session_id: str, project_id: str,
                        document_id: str) -> Any:
        return self.request(
            "DELETE",
            f"/api/sessions/{session_id}/projects/{project_id}/documents/{document_id}")

    def generate(self, session_id: str, project_id: str, **payload
                 ) -> dict[str, Any]:
        return self.request(
            "POST", f"/api/sessions/{session_id}/projects/{project_id}/generate",
            json=payload, timeout=3600)

    def draft_analysis(self, session_id: str, project_id: str) -> dict[str, Any]:
        return self.request(
            "GET",
            f"/api/sessions/{session_id}/projects/{project_id}/draft-analysis")

    def project_progress(self, session_id: str, project_id: str) -> dict[str, Any]:
        return self.request(
            "GET", f"/api/sessions/{session_id}/projects/{project_id}/progress")

    def export_project(self, session_id: str, project_id: str, fmt: str = "docx"
                       ) -> bytes:
        response = self.request(
            "GET", f"/api/sessions/{session_id}/projects/{project_id}/export",
            params={"fmt": fmt}, raw=True)
        return response.content

    # ------------------------------------------------------------------ задачи
    def submit_bulk_index(self, paths: list[str],
                          tags: list[str] | None = None) -> dict[str, Any]:
        return self.request("POST", "/api/admin/documents/bulk-async",
                            json={"paths": paths, "tags": tags or []})

    def tasks(self, session_id: str | None = None) -> list[dict[str, Any]]:
        body = self.request("GET", "/api/tasks",
                            params={"session_id": session_id} if session_id
                            else None)
        return body.get("tasks", [])

    def task(self, task_id: str) -> dict[str, Any]:
        return self.request("GET", f"/api/tasks/{task_id}")

    def cancel_task(self, task_id: str) -> dict[str, Any]:
        return self.request("POST", f"/api/tasks/{task_id}/cancel")

    # ------------------------------------------------------------------ админ
    def health(self) -> dict[str, Any]:
        return self.request("GET", "/api/health", timeout=10)

    def admin_users(self) -> list[dict[str, Any]]:
        return self.request("GET", "/api/admin/users")

    def admin_create_user(self, **fields: Any) -> dict[str, Any]:
        return self.request("POST", "/api/admin/users", json=fields)

    def admin_update_user(self, user_id: str, **fields: Any) -> dict[str, Any]:
        return self.request("PATCH", f"/api/admin/users/{user_id}", json=fields)

    def admin_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.request("GET", "/api/admin/audit",
                            params={"limit": limit})

    def admin_documents(self) -> list[dict[str, Any]]:
        return self.request("GET", "/api/admin/documents")

    def admin_upload(self, files: list[Any], tags: str = "") -> dict[str, Any]:
        payload = [("files", (f.name, f.getvalue())) for f in files]
        return self.request("POST", "/api/admin/documents/upload",
                            files=payload, data={"tags": tags}, timeout=3600)

    def admin_add_path(self, path: str) -> dict[str, Any]:
        return self.request("POST", "/api/admin/documents/path",
                            json={"path": path}, timeout=3600)

    def admin_delete_document(self, document_id: str) -> Any:
        return self.request("DELETE", f"/api/admin/documents/{document_id}")

    def admin_reindex(self) -> dict[str, Any]:
        return self.request("POST", "/api/admin/documents/reindex",
                            timeout=3600)