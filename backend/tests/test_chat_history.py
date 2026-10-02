"""История чата: сохранение вопроса/ответа, выдача и подрезка.

Закрывает пробел DoD Фазы 5: «после рестарта сессия восстанавливается
с документами, **историей** и заметками».
"""

from __future__ import annotations

import pytest

from app.db.models import Message, SearchMode
from app.db.repositories import messages as messages_repo
from tests.conftest import login_headers


@pytest.fixture
async def researcher(client, researcher_user):
    return await login_headers(client, "ivanov", "researcher-pass-123")


@pytest.fixture
async def session_id(client, researcher):
    response = await client.post("/api/sessions", json={"title": "Биомасса"},
                                 headers=researcher)
    return response.json()["id"]


@pytest.fixture
def talk(db, researcher_user):
    from app.db.repositories.users import create_research_session

    session = create_research_session(db, researcher_user, "Диалог")
    return session


# --------------------------------------------------------------------------- репозиторий
def test_save_exchange_writes_two_messages(db, researcher_user, talk) -> None:
    ask, reply = messages_repo.save_exchange(
        db, user=researcher_user, question="Как измеряют биомассу?",
        answer="Методом GF/F [1].", session_id=talk.id, mode=SearchMode.hybrid,
        sources=[{"dockey": "d1"}], duration_seconds=12.5)

    assert (ask.role, ask.content) == ("user", "Как измеряют биомассу?")
    assert (reply.role, reply.content) == ("assistant", "Методом GF/F [1].")
    assert reply.sources == [{"dockey": "d1"}]
    assert reply.duration_seconds == 12.5
    assert reply.mode is SearchMode.hybrid
    assert messages_repo.count_messages(db, talk.id) == 2


def test_list_messages_keeps_order(db, researcher_user, talk) -> None:
    for i in range(3):
        messages_repo.add_message(db, user_id=researcher_user.id,
                                  content=f"вопрос {i}", role="user",
                                  session_id=talk.id)

    items = messages_repo.list_messages(db, talk.id)

    assert [m.content for m in items] == ["вопрос 0", "вопрос 1", "вопрос 2"]


def test_last_exchange_returns_question_and_answer(db, researcher_user, talk) -> None:
    assert messages_repo.last_exchange(db, talk.id) is None

    messages_repo.save_exchange(db, user=researcher_user, question="Q1", answer="A1",
                               session_id=talk.id)
    messages_repo.save_exchange(db, user=researcher_user, question="Q2", answer="A2",
                               session_id=talk.id)

    assert messages_repo.last_exchange(db, talk.id) == ("Q2", "A2")


def test_quick_history_is_per_user_and_reversed(db, researcher_user, talk) -> None:
    from app.db.repositories.users import create_user

    other = create_user(db, username="petrov", password="password-1234",
                        hashed_password="x" * 40)
    messages_repo.add_message(db, user_id=researcher_user.id, content="мой быстрый",
                              session_id=None)

    mine = messages_repo.list_quick_messages(db, researcher_user.id)
    theirs = messages_repo.list_quick_messages(db, other.id)

    assert [m.content for m in mine] == ["мой быстрый"]
    assert theirs == []


def test_trim_quick_history_keeps_last_n(db, researcher_user, monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_quick_history", 3, raising=False)
    for i in range(6):
        messages_repo.add_message(db, user_id=researcher_user.id,
                                  content=f"q{i}", session_id=None)

    removed = messages_repo.trim_quick_history(db, researcher_user.id)

    assert removed == 3
    left = [m.content for m in
            reversed(messages_repo.list_quick_messages(db, researcher_user.id))]
    assert left == ["q3", "q4", "q5"]


def test_trim_keeps_history_when_under_limit(db, researcher_user) -> None:
    messages_repo.add_message(db, user_id=researcher_user.id, content="q", session_id=None)
    assert messages_repo.trim_quick_history(db, researcher_user.id) == 0


def test_delete_messages_clears_only_session(db, researcher_user, talk) -> None:
    messages_repo.add_message(db, user_id=researcher_user.id, content="в сессии",
                              session_id=talk.id)
    messages_repo.add_message(db, user_id=researcher_user.id, content="вне сессии",
                              session_id=None)

    assert messages_repo.delete_messages(db, talk.id) == 1
    assert messages_repo.count_messages(db, talk.id) == 0
    assert db.query(Message).filter(Message.session_id.is_(None)).count() == 1


# --------------------------------------------------------------------------- API
async def test_chat_query_persists_history(client, researcher, session_id,
                                           stub_registry, tmp_path) -> None:
    """Ответ на вопрос сохраняется в `messages` — иначе диалог теряется."""
    from app.services import paperqa_service as svc
    from tests.conftest import StubLLMModel

    registry = stub_registry
    doc = tmp_path / "a.md"
    doc.write_text("# A\n\nHlorofill-a 1.85 mg/m3.\n", encoding="utf-8")
    await registry.session_service(session_id).add_file(doc, session_id=session_id)
    # подменяем LLM заглушкой: запрос к реальной модели недопустим в тестах
    svc.get_registry().session_service(session_id)._llm_model = StubLLMModel()

    response = await client.post("/api/chat/query", headers=researcher,
                                 json={"session_id": session_id,
                                       "query": "Какая биомасса?"})

    assert response.status_code == 200, response.text

    history = await client.get(f"/api/chat/messages?session_id={session_id}",
                               headers=researcher)
    assert history.json()["total"] == 2
    assert [m["role"] for m in history.json()["messages"]] == ["user", "assistant"]
    assert history.json()["messages"][0]["content"] == "Какая биомасса?"


async def test_history_endpoint_is_readable_without_session(client, researcher,
                                                            session_id) -> None:
    import app.db.session as session_module
    from app.db.models import Message, ResearchSession, User

    with session_module.get_session_factory()() as db:
        owner_id = db.get(ResearchSession, session_id).user_id
        db.add(Message(user_id=owner_id, session_id=session_id, role="user",
                       content="старый вопрос"))
        db.commit()
        assert db.get(User, owner_id) is not None

    response = await client.get(f"/api/chat/messages?session_id={session_id}",
                                headers=researcher)

    assert response.status_code == 200
    assert response.json()["total"] == 1


async def test_resume_returns_last_exchange(client, researcher, session_id) -> None:
    import app.db.session as session_module
    from app.db.models import ResearchSession, User
    from app.db.repositories import messages as messages_repo

    with session_module.get_session_factory()() as db:
        owner_id = db.get(ResearchSession, session_id).user_id
        messages_repo.save_exchange(db, user=db.get(User, owner_id),
                                    question="Вопрос?", answer="Ответ.",
                                    session_id=session_id)

    response = await client.post(f"/api/sessions/{session_id}/resume", headers=researcher)

    assert response.json()["last_exchange"] == ["Вопрос?", "Ответ."]


async def test_clear_history_is_read_only_for_archive(client, researcher,
                                                      session_id) -> None:
    await client.post(f"/api/sessions/{session_id}/archive", headers=researcher)

    response = await client.delete(f"/api/chat/messages?session_id={session_id}",
                                   headers=researcher)
    assert response.status_code == 409


async def test_quick_message_and_history_api(client, researcher) -> None:
    saved = await client.post("/api/chat/quick-message", headers=researcher,
                              json={"query": "Что такое CTD?"})
    assert saved.status_code == 201
    assert saved.json()["session_id"] is None

    history = await client.get("/api/chat/quick-history", headers=researcher)
    assert history.json()["total"] == 1
    assert history.json()["messages"][0]["content"] == "Что такое CTD?"


async def test_history_of_foreign_session_is_404(client, researcher, session_id,
                                                 db_engine) -> None:
    from sqlalchemy.orm import sessionmaker

    from app.core.security import hash_password
    from app.db.models import Role
    from app.db.repositories.users import create_user

    with sessionmaker(bind=db_engine, expire_on_commit=False)() as db:
        create_user(db, username="petrov", password="password-1234",
                    role=Role.researcher, hashed_password=hash_password("password-1234"))
        db.commit()
    petrov = await login_headers(client, "petrov", "password-1234")

    response = await client.get(f"/api/chat/messages?session_id={session_id}",
                                headers=petrov)
    assert response.status_code == 404