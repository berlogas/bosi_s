"""Сброс состояния платформы: один механизм для CLI, Makefile и админ-API.

Уровни (scope) — от мягкого к полному:

| scope   | что удаляется                                     | что остаётся              |
| ------- | ------------------------------------------------- | -------------------------- |
| `data`  | сессии, документы, проекты, версии, чанки, ответы | пользователи, аудит        |
| `users` | всё из `data` + все refresh-токены (сброс входов)  | пользователи, аудит        |
| `all`   | всё из `users` + таблицы `users` и `audit_log`    | только конфигурация        |

Два важных свойства реализации:

1. **Индекс RAG не хранится на диске.** PaperQA восстанавливает его из таблицы
   `document_chunks` (`SqliteChunkStore`), поэтому чистки БД достаточно.
   `reset_registry()` нужен, чтобы выбросить индекс из памяти — иначе
   `restore_state()` не перезагрузит его (см. `paperqa_service.py`).

2. **Кэш моделей лежит в том же томе.** `HF_HOME=/data/hf` и
   `TORCH_HOME=/data/torch` (Dockerfile) — внутри `boasi_data`. Сброс данных
   их не трогает: иначе оффлайн-контур останется без модели эмбеддингов,
   пока её не скачают заново. Удалить явно можно только `--include-models`.

Файлы сессий/документов на диске нужны для офлайн-поиска: после сброса их
можно не восстанавливать — придётся загрузить заново (см. `make warm-embedding`).
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.errors import ForbiddenError
from app.db.models import Base
from app.db.session import get_session_factory

log = logging.getLogger("boasi.reset")

ResetScope = Literal["data", "users", "all"]
SCOPES: tuple[ResetScope, ...] = ("data", "users", "all")

# Фразы подтверждения: их вводит человек в UI/CLI, чтобы сброс не был
# случайным нажатием кнопки.
CONFIRM_PHRASES: dict[str, str] = {
    "data": "СБРОС ДАННЫХ",
    "users": "СБРОС СЕССИЙ",
    "all": "ПОЛНЫЙ СБРОС",
}

# Порядок удаления важен: сначала дети, потом родители (FK с ondelete,
# но полагаться на каскады при массовом DELETE нельзя — они не срабатывают
# так предсказуемо и не дают посчитать строки).
_TABLE_ORDER: tuple[str, ...] = (
    "messages",             # FK -> research_sessions, users
    "document_links",       # FK -> documents, projects, research_sessions
    "project_versions",     # FK -> projects, research_sessions, users
    "documents",            # FK -> research_sessions, users
    "projects",             # FK -> research_sessions
    "research_sessions",    # FK -> users
    "document_chunks",      # состояние PaperQA, внешних FK нет
    "refresh_tokens",       # FK -> users
    "audit_log",            # внешних FK нет (actor_user_id — простой столбец)
    "users",                # корень
)

_SCOPE_TABLES: dict[str, tuple[str, ...]] = {
    "data": _TABLE_ORDER[:7],
    "users": _TABLE_ORDER[:8],
    "all": _TABLE_ORDER,
}


# --------------------------------------------------------------------------- модели
@dataclass(frozen=True)
class PathTarget:
    """Каталог, который будет удалён."""

    path: str
    files: int
    bytes: int


@dataclass(frozen=True)
class ResetPlan:
    """Что именно будет удалено. Строится без побочных эффектов."""

    scope: str
    tables: dict[str, int] = field(default_factory=dict)
    paths: list[PathTarget] = field(default_factory=list)
    kept_paths: list[str] = field(default_factory=list)
    includes_models: bool = False
    allowed: bool = True
    blocked_reason: str | None = None

    @property
    def rows(self) -> int:
        return sum(self.tables.values())

    @property
    def files(self) -> int:
        return sum(item.files for item in self.paths)

    @property
    def total_bytes(self) -> int:
        return sum(item.bytes for item in self.paths)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "tables": self.tables,
            "rows": self.rows,
            "paths": [{"path": p.path, "files": p.files, "bytes": p.bytes}
                      for p in self.paths],
            "files": self.files,
            "total_bytes": self.total_bytes,
            "kept_paths": self.kept_paths,
            "includes_models": self.includes_models,
            "allowed": self.allowed,
            "blocked_reason": self.blocked_reason,
            "confirmation": CONFIRM_PHRASES.get(self.scope, ""),
        }


@dataclass(frozen=True)
class ResetResult:
    """Итог выполнения (или dry-run)."""

    plan: ResetPlan
    dry_run: bool
    deleted_tables: dict[str, int] = field(default_factory=dict)
    deleted_paths: list[str] = field(default_factory=list)
    freed_bytes: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "scope": self.plan.scope,
            "dry_run": self.dry_run,
            "deleted_tables": self.deleted_tables,
            "deleted_rows": sum(self.deleted_tables.values()),
            "deleted_paths": self.deleted_paths,
            "freed_bytes": self.freed_bytes,
            "kept_paths": self.plan.kept_paths,
            "includes_models": self.plan.includes_models,
        }


# --------------------------------------------------------------------------- утилиты
def _is_within(path: Path, parent: Path) -> bool:
    """`path` лежит внутри `parent` (или совпадает с ним)."""
    try:
        path.resolve().relative_to(parent.resolve())
    except (ValueError, OSError):
        return False
    return True


def _dir_size(path: Path) -> tuple[int, int]:
    """(файлов, байт) в каталоге. Ошибки чтения не роняют план."""
    files = 0
    total = 0
    for root, _dirs, names in os.walk(path, onerror=lambda _e: None):
        for name in names:
            files += 1
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return files, total


def _tables_for(scope: str) -> tuple[str, ...]:
    if scope not in _SCOPE_TABLES:
        raise ValueError(f"Неизвестный scope: {scope!r}. Допустимо: {', '.join(SCOPES)}")
    return _SCOPE_TABLES[scope]


def tables_for(scope: str) -> tuple[str, ...]:
    """Публичная обёртка: какие таблицы чистит scope (в порядке удаления)."""
    return _tables_for(scope)


def wipe_paths(settings: Settings, *, include_models: bool = False
               ) -> tuple[list[Path], list[Path]]:
    """Каталоги к удалению и каталоги, которые бережём.

    Кэш моделей (HF_HOME/TORCH_HOME) лежит внутри data_dir и по умолчанию
    защищён. Страховка `_is_within` не даёт снести защищённый каталог, даже
    если кто-то подставил его в список целей.
    """
    protected: list[Path] = []
    candidates: list[Path] = [settings.sessions_dir, settings.documents_dir,
                              settings.resolved_pqa_home]
    if include_models:
        # Явное согласие на удаление кэша моделей: после этого оффлайн-контур
        # не сможет считать эмбеддинги, пока модель не скачана заново.
        candidates += [settings.resolved_hf_home, settings.resolved_torch_home]
    else:
        protected = [settings.resolved_hf_home, settings.resolved_torch_home]

    targets: list[Path] = []
    for path in candidates:
        if not path.exists():
            continue
        if any(_is_within(path, keep) or _is_within(keep, path) for keep in protected):
            log.warning("Каталог %s пропущен: пересекается с кэшем моделей", path)
            continue
        targets.append(path)
    kept = [str(p) for p in protected if p.exists()]
    return targets, kept


def ensure_allowed(settings: Settings) -> str | None:
    """Причина запрета сброса или None. В prod — только явным разрешением."""
    if settings.environment == "prod" and not settings.allow_destructive_reset:
        return ("сброс состояния в prod запрещён: установите "
                "ALLOW_DESTRUCTIVE_RESET=true в .env")
    return None


# --------------------------------------------------------------------------- план
def plan_reset(
    scope: str = "data",
    *,
    include_models: bool = False,
    db: Session | None = None,
    settings: Settings | None = None,
) -> ResetPlan:
    """Посчитать, что будет удалено. Ничего не меняет на диске и в БД."""
    settings = settings or get_settings()
    names = _tables_for(scope)

    counts: dict[str, int] = {}
    if db is not None:
        present = inspect(db.get_bind())
        for name in names:
            table = Base.metadata.tables.get(name)
            # Таблицы могли ещё не появиться (свежая БД до `alembic upgrade`).
            if table is None or not present.has_table(name):
                continue
            counts[name] = int(db.execute(select(func.count()).select_from(table)).scalar_one())

    blocked = ensure_allowed(settings)
    targets, kept = wipe_paths(settings, include_models=include_models)
    paths: list[PathTarget] = []
    for target in targets:
        files, size = _dir_size(target)
        paths.append(PathTarget(path=str(target), files=files, bytes=size))
    return ResetPlan(
        scope=scope,
        tables=counts,
        paths=paths,
        kept_paths=kept,
        includes_models=include_models,
        allowed=blocked is None,
        blocked_reason=blocked,
    )


# --------------------------------------------------------------------------- сброс
def _clear_in_memory() -> None:
    """Выбросить из памяти индекс PaperQA, задачи, локи и кэш ответов.

    Каждый шаг в своём try/except: сброс состояния не должен падать из-за
    второстепенного модуля (в CLI здесь же тянутся torch и transformers).
    """
    from app.core.leases import leases
    from app.core.locks import locks

    try:
        from app.services.paperqa_service import reset_registry

        reset_registry()
    except Exception:  # pragma: no cover - защитный код
        log.exception("Реестр PaperQA не сброшен")
    try:
        from app.services.answer_cache import get_answer_cache, reset_answer_cache

        reset_answer_cache()
        get_answer_cache().clear()
    except Exception:  # pragma: no cover
        log.exception("Кэш ответов не очищен")
    try:
        from app.services import tasks as task_service

        task_service.reset_registry()
    except Exception:  # pragma: no cover
        log.exception("Реестр задач не очищен")
    try:
        for session_id in leases.live():
            locks.reset_session_lock(session_id)
        leases.clear()
    except Exception:  # pragma: no cover
        log.exception("Аренды и локи сессий не очищены")


def _delete_rows(db: Session, names: tuple[str, ...]) -> dict[str, int]:
    """Удалить строки таблиц в порядке зависимостей. Одна транзакция."""
    metadata = Base.metadata
    present = inspect(db.get_bind())
    deleted: dict[str, int] = {}
    for name in names:
        table = metadata.tables.get(name)
        if table is None or not present.has_table(name):
            continue
        result = db.execute(delete(table))
        deleted[name] = int(result.rowcount or 0)
    db.commit()
    return deleted


def _compact_sqlite(settings: Settings, db: Session) -> None:
    """Сжать БД и сбросить счётчики AUTOINCREMENT (иначе id продолжатся).

    VACUUM нельзя выполнять внутри транзакции, поэтому для него открывается
    отдельное соединение в AUTOCOMMIT.
    """
    if not settings.is_sqlite:
        return
    try:
        with db.get_bind().connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text("VACUUM"))
    except Exception:  # pragma: no cover - файл может быть заблокирован
        log.warning("VACUUM не выполнен", exc_info=True)
    try:
        names = ", ".join(repr(name) for name in _SCOPE_TABLES["all"])
        db.execute(text(f"DELETE FROM sqlite_sequence WHERE name IN ({names})"))
        db.commit()
    except Exception:  # pragma: no cover - sqlite_sequence может не существовать
        db.rollback()
        log.debug("sqlite_sequence: нечего сбрасывать", exc_info=True)


def _record_audit(
    db: Session | None,
    *,
    scope: str,
    actor: Any,
    meta: dict[str, Any],
) -> None:
    """Запись в аудит ДО удаления: иначе при scope=all она исчезнет сама."""
    if db is None:
        return
    try:
        from app.db.repositories.users import audit

        audit(db, action="admin.reset", actor=actor, target_type="state",
              target_id=scope, **meta)
    except Exception:
        # Откат обязателен: после ошибки flush сессия нерабочая (PendingRollbackError),
        # и сброс упал бы на ровном месте. Причину — в лог, сброс продолжаем.
        db.rollback()
        log.exception("Не удалось записать сброс в аудит")


def run_reset(
    scope: str = "data",
    *,
    dry_run: bool = True,
    include_models: bool = False,
    db: Session | None = None,
    settings: Settings | None = None,
    actor: Any = None,
    meta: dict[str, Any] | None = None,
) -> ResetResult:
    """Сбросить состояние.

    `dry_run=True` (по умолчанию) только считает план — ничего не удаляет.
    Из API вызывается с готовым `db` (сессия запроса), из CLI — сессия
    открывается здесь и закрывается тут же.
    """
    settings = settings or get_settings()
    blocked = ensure_allowed(settings)
    plan = plan_reset(scope, include_models=include_models, db=db, settings=settings)
    if blocked:
        raise ForbiddenError(blocked)
    if dry_run:
        return ResetResult(plan=plan, dry_run=True)

    names = _tables_for(scope)
    audit_meta = {
        "scope": scope,
        "dry_run": False,
        "include_models": include_models,
        "planned": plan.as_dict(),
        **(meta or {}),
    }

    owns_session = db is None
    session = db
    if session is None:
        session = get_session_factory()()

    try:
        # 1. Аудит до удаления: если сброс оборвётся посередине, след останется.
        _record_audit(session, scope=scope, actor=actor, meta=audit_meta)
        # 2. БД.
        deleted = _delete_rows(session, names)
        if deleted.get("audit_log"):
            # scope=all: таблица очищена вместе с прежними записями — вернём
            # свежую запись о самом сбросе, иначе он не останется в истории.
            _record_audit(session, scope=scope, actor=actor,
                          meta={**audit_meta, "after_wipe": True})
        # 3. Файлы.
        freed = 0
        removed: list[str] = []
        for target in plan.paths:
            path = Path(target.path)
            if not path.exists():
                continue
            if not include_models and (
                    _is_within(path, settings.resolved_hf_home)
                    or _is_within(path, settings.resolved_torch_home)):
                log.warning("Каталог %s пропущен при сбросе: кэш моделей", path)
                continue
            try:
                shutil.rmtree(path)
            except OSError:
                log.exception("Не удалось удалить %s", path)
                continue
            removed.append(str(path))
            freed += target.bytes
        # 4. Скелет каталогов и память.
        settings.ensure_dirs()
        _compact_sqlite(settings, session)
        _clear_in_memory()
    finally:
        if owns_session:
            session.close()

    log.warning("Сброс выполнен: scope=%s строк=%d каталогов=%d",
                scope, sum(deleted.values()), len(removed))
    return ResetResult(plan=plan, dry_run=False, deleted_tables=deleted,
                       deleted_paths=removed, freed_bytes=freed)


__all__ = [
    "CONFIRM_PHRASES",
    "SCOPES",
    "ResetPlan",
    "ResetResult",
    "ResetScope",
    "ensure_allowed",
    "plan_reset",
    "run_reset",
    "tables_for",
    "wipe_paths",
]