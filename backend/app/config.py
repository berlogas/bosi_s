"""Конфигурация boasi_s (все параметры — из окружения / .env).

Правило проекта: в коде нет констант производительности.
Модель задаётся одним параметром LLM_MODEL и меняется в бою только через .env.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
PROJECT_ROOT = ENV_FILE.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE if ENV_FILE.exists() else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------- общее ----------
    app_name: str = "boasi_s"
    environment: Literal["dev", "prod", "test"] = "dev"
    debug: bool = False
    log_level: str = "INFO"
    # Только локальный доступ: данные не покидают инфраструктуру
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    # React dev-сервер (webapp/, Vite) — единственный интерфейс
    cors_origins: list[str] = Field(default_factory=lambda: ["http://127.0.0.1:5173"])

    # ---------- безопасность ----------
    secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(48))
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 30
    bcrypt_time_cost: int = 12  # argon2 time_cost, оставлено под названием из ТЗ
    argon2_time_cost: int = 3
    argon2_memory_cost: int = 65536  # KiB
    argon2_parallelism: int = 2

    # ---------- хранилище ----------
    data_dir: Path = Field(default=Path("/data"))
    database_url: str | None = None  # переопределяет data_dir/db_path
    db_path: Path | None = None
    pqa_home: Path | None = None
    upload_max_mb: int = 200
    allowed_extensions: list[str] = Field(
        default_factory=lambda: [
            ".pdf", ".txt", ".md", ".html", ".htm", ".docx", ".xlsx", ".pptx",
            ".csv", ".tsv", ".json", ".yaml", ".yml", ".py",
        ]
    )

    # ---------- LLM / эмбеддинги (единственный источник правды для paper-qa) ----------
    ollama_base_url: str = "http://localhost:11434"
    llm_model: str = "ollama/qwen2.5:3b"  # в бою — более мощная модель, меняется здесь
    llm_timeout_seconds: int = 3600  # большой таймаут обязателен на медленном inference
    llm_max_retries: int = 2
    summary_llm_model: str | None = None  # None -> llm_model
    embedding_model: str = "st-multi-qa-MiniLM-L6-cos-v1"
    evidence_k: int = 10
    # Больше источников в самом ответе = больше проверяемого материала
    # для модели и для проверки обоснованности (стоимость — только prefill).
    answer_max_sources: int = 8
    # Короткий ответ без «научно-статьной» простыни: простыня = больше
    # выдуманных фактов (см. grounding.py) и дольше генерация на CPU.
    answer_length: str = "no more than 120 words"
    # Сырой текст вместо LLM-сводок в контексте: честнее, но огромный
    # prefill (SPICE_REPORT: ответ 817 с) — включается только явно.
    evidence_skip_summary: bool = False
    max_concurrent_requests: int = 1  # Ollama на CPU обрабатывает запросы последовательно
    chunk_chars: int = 4000
    chunk_overlap: int = 200
    offline_mode: bool = True  # не ходим в Crossref / Semantic Scholar
    multimodal: bool = False
    # Язык ответов: ru (по умолчанию) | en. Реализуется через prompts.system.
    answer_language: str = "ru"
    # Русскоязычные промпты; если пусто — берётся дефолт paperqa + правило языка
    prompts_system: str | None = None
    # Шаблон qa-промпта; если пусто — дефолт paperqa с GROUNDING RULES
    prompts_qa: str | None = None

    # ---------- лимиты и жизненный цикл сессий (из ТЗ) ----------
    session_ttl_days: int = 90
    heartbeat_interval_minutes: int = 5
    archive_retention_days: int = 30
    max_sessions_per_user: int = 10
    max_documents_per_session: int = 50
    max_session_storage_mb: int = 500
    max_projects_per_session: int = 5
    max_quick_history: int = 200

    # ---------- безопасность (Фаза 9) ----------
    # Разрешить импорт документов откуда угодно. По умолчанию выключено:
    # исследователь может загружать только из каталога своей сессии.
    allow_external_import_paths: bool = False
    # Защита от перебора пароля на /api/auth/login
    login_max_attempts: int = 10
    login_window_seconds: int = 300
    login_lockout_seconds: int = 300
    # Минимальная длина SECRET_KEY (короткий ключ ломает подпись JWT)
    min_secret_key_length: int = 32

    # ---------- фоновая обработка ----------
    indexer_concurrency: int = 1
    background_poll_seconds: float = 2.0

    # ---------- вычисляемое ----------
    @property
    def resolved_db_url(self) -> str:
        if self.database_url:
            return self.database_url
        db = self.db_path or (self.data_dir / "boasi.sqlite3")
        return f"sqlite:///{db.as_posix()}"

    @property
    def resolved_pqa_home(self) -> Path:
        return self.pqa_home or (self.data_dir / "pqa")

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    @property
    def documents_dir(self) -> Path:
        return self.data_dir / "documents"

    @property
    def resolved_summary_llm(self) -> str:
        return self.summary_llm_model or self.llm_model

    @property
    def is_sqlite(self) -> bool:
        return self.resolved_db_url.startswith("sqlite")

    @field_validator("data_dir", "db_path", "pqa_home")
    @classmethod
    def _abs_path(cls, value: Path | None) -> Path | None:
        """Относительные пути в .env разрешаем от корня репозитория, а не от CWD."""
        if value is None:
            return None
        expanded = value.expanduser()
        if not expanded.is_absolute():
            expanded = (PROJECT_ROOT / expanded).resolve()
        return expanded

    @field_validator(
        "database_url", "db_path", "pqa_home", "summary_llm_model", "prompts_system",
        "prompts_qa",
        mode="before",
    )
    @classmethod
    def _empty_to_none(cls, value):  # noqa: ANN001, ANN206
        """Пустая переменная в .env означает «не задано», а не пустую строку."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    def validate_runtime(self) -> list[str]:
        """Проверки настроек при старте. Возвращает предупреждения.

        Ошибки (когда продолжать нельзя) поднимаются исключением.
        """
        warnings: list[str] = []
        if len(self.secret_key) < self.min_secret_key_length:
            raise RuntimeError(
                f"SECRET_KEY короче {self.min_secret_key_length} символов: "
                "подпись JWT будет ненадёжной. Сгенерируйте новый: "
                "python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        if "change-me" in self.secret_key.lower():
            raise RuntimeError(
                "SECRET_KEY остался шаблонным из .env.example — замените его.")
        if self.environment == "prod":
            if self.debug:
                warnings.append("DEBUG=true в prod — отключите отладочный режим.")
            if self.multimodal:
                warnings.append("MULTIMODAL=true в prod — требовался OFF.")
            if not self.offline_mode:
                warnings.append("OFFLINE_MODE=false: возможны внешние запросы "
                                "к Crossref/Semantic Scholar.")
        if self.evidence_skip_summary:
            warnings.append(
                "EVIDENCE_SKIP_SUMMARY=true: сырой текст в контексте даёт "
                "огромный prefill (замер SPICE_REPORT: ответ 817 с).")
        if self.allow_external_import_paths:
            warnings.append("ALLOW_EXTERNAL_IMPORT_PATHS=true: импорт файлов "
                            "разрешён вне каталога данных.")
        return warnings

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.resolved_pqa_home, self.sessions_dir, self.documents_dir):
            path.mkdir(parents=True, exist_ok=True)

    def public_summary(self) -> dict[str, object]:
        """Безопасная сводка для /api/health и логов (без секретов)."""
        return {
            "app": self.app_name,
            "environment": self.environment,
            "llm_model": self.llm_model,
            "summary_llm_model": self.resolved_summary_llm,
            "embedding_model": self.embedding_model,
            "ollama_base_url": self.ollama_base_url,
            "offline_mode": self.offline_mode,
            "data_dir": str(self.data_dir),
            "database": self.resolved_db_url.replace(str(self.data_dir), "<data>"),
            "session_ttl_days": self.session_ttl_days,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings


def reset_settings_cache() -> None:
    """Для тестов: сбросить кэш настроек."""
    get_settings.cache_clear()