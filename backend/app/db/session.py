"""Подключение к БД (SQLite + WAL) и фабрика сессий."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.models import Base

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _apply_sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
    cursor = dbapi_connection.cursor()
    # WAL — устойчивость и параллельное чтение во время долгих RAG-запросов;
    # на dev-машине (slow inference) это заметно снижает блокировки.
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=15000")
    cursor.close()


def get_engine(url: str | None = None, *, echo: bool = False) -> Engine:
    global _engine
    if _engine is not None and url is None:
        return _engine
    settings = get_settings()
    db_url = url or settings.resolved_db_url
    engine = create_engine(
        db_url,
        echo=echo,
        future=True,
        pool_pre_ping=True,
        connect_args=({"check_same_thread": False, "timeout": 30}
                       if db_url.startswith("sqlite") else {}),
    )
    if db_url.startswith("sqlite"):
        event.listen(engine, "connect", _apply_sqlite_pragmas)
    if url is None:
        _engine = engine
    return engine


def get_session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is not None and engine is None:
        return _session_factory
    factory = sessionmaker(bind=engine or get_engine(), expire_on_commit=False, future=True)
    if engine is None:
        _session_factory = factory
    return factory


def init_db(engine: Engine | None = None) -> None:
    """Создать таблицы (в проде схема накатывается Alembic-миграциями)."""
    Base.metadata.create_all(bind=engine or get_engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    """Транзакционный scope для фоновых задач и скриптов."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI-зависимость: синхронная сессия (выполняется в threadpool)."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None