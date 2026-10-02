"""Фикстуры тестов: изолированная БД в tmp, настройки из окружения тестов."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

TEST_DATA_DIR = Path(os.environ.get("BOASI_TEST_DATA", "N:/Development/boasi_s/.test_data"))


@pytest.fixture(scope="session", autouse=True)
def _test_settings() -> Iterator[Settings]:
    """Настройки тестов: отдельная БД, детерминированные параметры."""
    TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)
    os.environ.update(
        ENVIRONMENT="test",
        DATA_DIR=str(TEST_DATA_DIR),
        DATABASE_URL=f"sqlite:///{(TEST_DATA_DIR / 'test.sqlite3').as_posix()}",
        SECRET_KEY="test-secret-key-0123456789",
        LLM_MODEL="ollama/qwen2.5:3b",
        EMBEDDING_MODEL="st-multi-qa-MiniLM-L6-cos-v1",
        LOG_LEVEL="WARNING",
    )
    from app.config import get_settings, reset_settings_cache

    reset_settings_cache()
    settings = get_settings()
    settings.ensure_dirs()
    yield settings
    reset_settings_cache()


@pytest.fixture
def db_engine(_test_settings: Settings):
    from sqlalchemy import create_engine, event

    from app.db.models import Base
    from app.db.session import _apply_sqlite_pragmas

    path = TEST_DATA_DIR / f"unit_{os.getpid()}.sqlite3"
    if path.exists():
        path.unlink()
    engine = create_engine(f"sqlite:///{path.as_posix()}", future=True,
                           connect_args={"check_same_thread": False})
    event.listen(engine, "connect", _apply_sqlite_pragmas)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            candidate.unlink()


@pytest.fixture
def db(db_engine):
    from sqlalchemy.orm import sessionmaker

    session = sessionmaker(bind=db_engine, expire_on_commit=False, future=True)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def admin_user(db):
    from app.core.security import hash_password
    from app.db.models import Role
    from app.db.repositories.users import create_user

    return create_user(db, username="admin", password="admin-pass-123",
                       role=Role.admin, hashed_password=hash_password("admin-pass-123"))


@pytest.fixture
def researcher_user(db):
    from app.core.security import hash_password
    from app.db.models import Role
    from app.db.repositories.users import create_user

    return create_user(db, username="ivanov", password="researcher-pass-123",
                       role=Role.researcher, hashed_password=hash_password("researcher-pass-123"))


# ---------------------------------------------------------------------------- API
@pytest.fixture
async def client(db_engine, _test_settings):
    """httpx-клиент поверх ASGI-приложения с изолированной БД."""
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.orm import sessionmaker

    import app.db.session as session_module
    from app.db.session import init_db
    from app.main import create_app

    session_module._session_factory = sessionmaker(
        bind=db_engine, expire_on_commit=False, future=True
    )
    init_db(db_engine)

    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
    session_module._session_factory = None


async def login_headers(client, username: str, password: str) -> dict[str, str]:
    """Логин и заголовок Authorization для исследователя/админа."""
    response = await client.post("/api/auth/login",
                                 json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['tokens']['access_token']}"}


@pytest.fixture
def stub_registry(monkeypatch, service_app, chunk_store, tmp_path):
    """Реестр сервисов на заглушке, подменённый в глобальном `_registry`.

    Нужен, чтобы API-тесты не поднимали ни Ollama, ни реальные эмбеддинги
    по сети: `service_app` уже содержит быстрый тестовый профиль.
    """
    from app.services import paperqa_service as svc

    service_app.data_dir = tmp_path / "registry-data"
    service_app.ensure_dirs()
    registry = svc.ServiceRegistry(service_app, chunk_store)
    monkeypatch.setattr(svc, "_registry", registry)
    return registry

# ------------------------------------------------------- сервисный слой PaperQA
# LLM подменяется заглушкой: тесты идут без сети и без Ollama;
# эмбеддинги — локальные sentence-transformers.
TEST_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("HF_HOME", str(TEST_ROOT / ".hf-cache"))
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

from app.config import Settings  # noqa: E402
from app.config import Settings as AppSettings  # noqa: E402
from app.services.chunk_store import MemoryChunkStore  # noqa: E402
from app.services.paperqa_service import PaperQA2Service  # noqa: E402


class StubLLMModel:
    """Минимальная заглушка LLMModel: отвечает заранее заданным текстом.

    Нужна, чтобы `aget_evidence`/`aquery` работали оффлайн и мгновенно.
    Реализует тот же duck-интерфейс, что использует paperqa:
    `call_single` (summary/citation) и `acompletion` (основной вызов).
    """

    def __init__(self, name: str = "stub", answer: str | None = None,
                 summary: str | None = None) -> None:
        from lmi import LLMResult

        self.name = name
        self.llm_type = "stub"
        self._LLMResult = LLMResult
        self.answer = answer or (
            "Это тестовый ответ заглушки на основе найденного контекста [1]."
        )
        self.summary = summary or "Краткое резюме найденного фрагмента [1]."
        self.calls: list[list[Any]] = []  # noqa: F821

    async def call_single(self, messages=None, **kwargs):
        self.calls.append(list(messages or []))
        text = "".join(getattr(m, "content", "") or "" for m in (messages or []))
        summary_prompt = "question:" in text.lower() or "summary" in text.lower()
        return self._LLMResult(text=self.summary if summary_prompt else self.answer,
                              model=self.name)

    async def acompletion(self, messages=None, *, spec=None, **kwargs):
        return [self._LLMResult(text=self.answer, model=self.name)]

    async def acompletion_iter(self, messages=None, *, spec=None, **kwargs):
        yield self._LLMResult(text=self.answer, model=self.name)

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    def __str__(self) -> str:  # pragma: no cover
        return f"StubLLMModel({self.name})"


@pytest.fixture
def service_app(_test_settings) -> AppSettings:
    """Настройки теста: быстрый профиль, маленькие чанки, без сети."""
    app = _test_settings.model_copy(update={
        "llm_model": "stub/model",
        "summary_llm_model": None,
        "embedding_model": "st-multi-qa-MiniLM-L6-cos-v1",
        "chunk_chars": 600,
        "chunk_overlap": 60,
        "evidence_k": 3,
        "answer_max_sources": 2,
        "offline_mode": True,
        "answer_language": "ru",
    })
    return app


@pytest.fixture
def stub_llm() -> StubLLMModel:
    return StubLLMModel()


@pytest.fixture
def chunk_store() -> MemoryChunkStore:
    return MemoryChunkStore()


@pytest.fixture
def service(service_app, chunk_store, stub_llm, tmp_path) -> PaperQA2Service:
    """Сервис поверх временных каталогов и заглушки LLM."""
    service_app.data_dir = tmp_path / "data"
    service_app.documents_dir.mkdir(parents=True, exist_ok=True)
    return PaperQA2Service(
        settings=service_app,
        collection="global",
        chunk_store=chunk_store,
        llm_model=stub_llm,
    )


@pytest.fixture
def sample_text(tmp_path: Path) -> Path:
    """Текстовый документ с проверяемым содержимым."""
    path = tmp_path / "biomass_notes.md"
    path.write_text(
        "# Замеры биомассы водорослей\n\n"
        "Биомасса водорослей в Баренцевом море измеряется методом GF/F, "
        "то есть отношением сухого вещества к сырому.\n\n"
        "Хлорофилл-а определяют экстракционным методом в ацетоне "
        "с последующим измерением на спектрофотометре.\n\n"
        "Пробы отбирают батернет-граблями на стандартных горизонтах Баренцева моря.\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    path = tmp_path / "barents_biomass.csv"
    path.write_text(
        "station,depth_m,chlorophyll_a_mg_m3,gf_f_ratio\n"
        "BS1,0,1.85,0.42\nBS1,10,1.12,0.31\nBS2,0,2.03,0.47\nBS2,10,0.98,0.28\n",
        encoding="utf-8",
    )
    return path