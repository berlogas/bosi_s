"""Фаза 6 — сквозной цикл fusion: две коллекции, режимы, разметка 📚/📁.

LLM подменён заглушкой, эмбеддинги локальные. Проверяем ровно то, что важно:
  * hybrid возвращает источники обоих типов;
  * project_focus поднимает проектные документы и прячет заметки;
  * session_only / global_only не смешивают коллекции;
  * ответ сохраняется в истории и попадает в кэш;
  * при готовом контексте повторный поиск НЕ выполняется (инвариант Фазы 0).
"""

from __future__ import annotations

import pytest

from tests.conftest import StubLLMModel, login_headers


@pytest.fixture
async def researcher(client, researcher_user):
    return await login_headers(client, "ivanov", "researcher-pass-123")


@pytest.fixture
async def session_id(client, researcher):
    response = await client.post("/api/sessions", json={"title": "Баренцево море"},
                                 headers=researcher)
    return response.json()["id"]


@pytest.fixture
async def seeded(client, researcher, session_id, stub_registry, tmp_path):
    """Глобальная база + документы сессии разных категорий."""
    import app.db.session as session_module
    from app.db.models import DocumentCategory, DocumentVisibility, User
    from app.db.repositories import documents as docs_repo
    from app.db.repositories.users import get_owned_session

    global_doc = tmp_path / "global_manual.md"
    global_doc.write_text(
        "# Руководство по CTD\n\n"
        "CTD-зонд измеряет температуру и солёность в Баренцеве море.\n",
        encoding="utf-8")

    draft = tmp_path / "draft.md"
    draft.write_text(
        "# Черновик раздела\n\n"
        "Хлорофилл-а в Баренцеве море измеряется экстракционным методом в ацетоне.\n",
        encoding="utf-8")
    notes = tmp_path / "notes.md"
    notes.write_text(
        "# Заметки\n\n"
        "Спросить автора про метод GF/F и хлорофилл-а в Баренцеве море.\n",
        encoding="utf-8")

    registry = stub_registry
    global_service = registry.global_service()
    session_service = registry.session_service(session_id)
    # заглушка вместо реальной модели — тесты не ходят в Ollama
    global_service._llm_model = StubLLMModel()
    session_service._llm_model = StubLLMModel()

    global_ref = await global_service.add_file(global_doc)
    draft_ref = await session_service.add_file(draft, session_id=session_id)
    notes_ref = await session_service.add_file(notes, session_id=session_id)

    with session_module.get_session_factory()() as db:
        session = get_owned_session(db, session_id, db.get(User, "1") or _owner(db, session_id))
        docs_repo.upsert_document(
            db, dockey=global_ref.dockey, docname=global_ref.docname,
            title="Руководство по CTD", filename=global_doc.name,
            path=global_ref.path, size_bytes=global_doc.stat().st_size,
            chunk_count=global_ref.chunk_count, citation=global_ref.citation,
            category=DocumentCategory.global_knowledge,
            visibility=DocumentVisibility.global_, session_id=None,
            owner_user_id=session.user_id, added_by=session.user_id)
        docs_repo.upsert_document(
            db, dockey=draft_ref.dockey, docname=draft_ref.docname,
            title="Черновик раздела", filename=draft.name, path=draft_ref.path,
            size_bytes=draft.stat().st_size, chunk_count=draft_ref.chunk_count,
            citation=draft_ref.citation, category=DocumentCategory.project_draft,
            visibility=DocumentVisibility.session, session_id=session_id,
            owner_user_id=session.user_id, added_by=session.user_id)
        docs_repo.upsert_document(
            db, dockey=notes_ref.dockey, docname=notes_ref.docname,
            title="Заметки", filename=notes.name, path=notes_ref.path,
            size_bytes=notes.stat().st_size, chunk_count=notes_ref.chunk_count,
            citation=notes_ref.citation, category=DocumentCategory.notes,
            visibility=DocumentVisibility.session, session_id=session_id,
            owner_user_id=session.user_id, added_by=session.user_id)

    return {"global_dockey": global_ref.dockey, "draft_dockey": draft_ref.dockey,
            "notes_dockey": notes_ref.dockey}


def _owner(db, session_id):
    from app.db.models import ResearchSession, User

    return db.get(User, db.get(ResearchSession, session_id).user_id)


async def _query(client, researcher, session_id, **payload) -> dict:
    body = {"session_id": session_id, "query": "хлорофилл-а и метод GF/F",
            "k": 10, **payload}
    response = await client.post("/api/chat/query", headers=researcher, json=body)
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------------- hybrid
async def test_hybrid_returns_both_scopes(client, researcher, session_id,
                                          seeded) -> None:
    body = await _query(client, researcher, session_id, mode="hybrid")

    scopes = {s["source_scope"] for s in body["sources"]}
    assert scopes == {"global", "session"}
    assert body["stats"]["candidates"] > 0
    assert body["stats"]["selected"] == len(body["sources"])


async def test_sources_are_marked_and_numbered(client, researcher, session_id,
                                               seeded) -> None:
    body = await _query(client, researcher, session_id, mode="hybrid")

    markers = {s["marker"] for s in body["sources"]}
    assert markers <= {"📚", "📁"}
    assert [s["index"] for s in body["sources"]] == list(
        range(1, len(body["sources"]) + 1))
    assert body["references"], "ссылки на источники обязательны"
    for reference in body["references"]:
        assert reference[0] in "📚📁"
    # в списке источников — те же номера, что и в цитатах ответа `[n]`
    assert [r.split(" ")[1] for r in body["references"]] == [
        f"[{i}]" for i in range(1, len(body["sources"]) + 1)]


async def test_project_focus_ranks_project_documents_first(client, researcher,
                                                          session_id, seeded) -> None:
    body = await _query(client, researcher, session_id, mode="project_focus")

    categories = [s["category"] for s in body["sources"]]
    assert "notes" not in categories, "заметки не должны попадать в project_focus"
    if categories:
        assert categories[0] in {"project_draft", "project_data", "global_knowledge"}


async def test_session_only_and_global_only_are_separated(client, researcher,
                                                           session_id, seeded) -> None:
    session_body = await _query(client, researcher, session_id,
                                mode="session_only", no_cache=True)
    global_body = await _query(client, researcher, session_id,
                               mode="global_only", no_cache=True)

    assert {s["source_scope"] for s in session_body["sources"]} == {"session"}
    assert {s["source_scope"] for s in global_body["sources"]} == {"global"}


# --------------------------------------------------------------------------- кэш
async def test_repeated_question_uses_cache(client, researcher, session_id,
                                             seeded) -> None:
    first = await _query(client, researcher, session_id, no_cache=True)
    second = await _query(client, researcher, session_id)

    assert first["from_cache"] is False
    assert second["from_cache"] is True
    assert second["answer"] == first["answer"]


async def test_cache_is_used_for_repeated_quick_query(client, researcher,
                                                      seeded) -> None:
    first = await client.post("/api/chat/quick-query", headers=researcher,
                              json={"query": "Что такое CTD?", "no_cache": True})
    second = await client.post("/api/chat/quick-query", headers=researcher,
                               json={"query": "Что такое CTD?"})

    assert first.json()["from_cache"] is False
    assert second.json()["from_cache"] is True


# --------------------------------------------------------------------------- история
async def test_answer_is_saved_to_history(client, researcher, session_id,
                                          seeded) -> None:
    await _query(client, researcher, session_id, mode="hybrid", no_cache=True)

    history = await client.get(f"/api/chat/messages?session_id={session_id}",
                               headers=researcher)
    body = history.json()

    assert body["total"] == 2
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][1]["sources"], "в ответе должны быть источники"


async def test_cached_answer_does_not_duplicate_history(client, researcher,
                                                        session_id, seeded) -> None:
    await _query(client, researcher, session_id, no_cache=True)
    await _query(client, researcher, session_id)  # из кэша

    history = await client.get(f"/api/chat/messages?session_id={session_id}",
                               headers=researcher)
    assert history.json()["total"] == 2, "повтор из кэша не должен плодить записи"


# --------------------------------------------------------------------------- инвариант
async def test_ready_context_skips_second_search(client, researcher, session_id,
                                                 seeded, monkeypatch) -> None:
    """Главный инвариант Фазы 0: при готовом контексте `aget_evidence` повторно
    НЕ вызывается (иначе 374 с вместо 118 с на CPU)."""
    from app.services.paperqa_service import PaperQA2Service

    calls: list[int] = []
    original = PaperQA2Service.get_evidence

    async def counting(self, query, k=None, doc_filter=None):
        calls.append(1)
        return await original(self, query, k=k, doc_filter=doc_filter)

    monkeypatch.setattr(PaperQA2Service, "get_evidence", counting)

    body = await _query(client, researcher, session_id, mode="hybrid",
                        no_cache=True)

    # ровно по одному поиску на коллекцию: глобальная и сессионная
    assert len(calls) == 2
    assert body["stats"]["selected"] > 0


async def test_archived_session_blocks_query(client, researcher, session_id,
                                             seeded) -> None:
    await client.post(f"/api/sessions/{session_id}/archive", headers=researcher)

    response = await client.post("/api/chat/query", headers=researcher,
                                 json={"session_id": session_id, "query": "хлорофилл"})

    assert response.status_code == 409
    assert "только чтение" in response.json()["detail"]


async def test_quick_query_needs_no_session(client, researcher, seeded) -> None:
    response = await client.post("/api/chat/quick-query", headers=researcher,
                                 json={"query": "Что такое CTD-зонд?"})

    body = response.json()
    assert response.status_code == 200
    assert {s["source_scope"] for s in body["sources"]} <= {"global"}
    assert body["references"]


async def test_empty_answer_when_no_evidence(client, researcher, session_id,
                                             stub_registry) -> None:
    response = await client.post("/api/chat/query", headers=researcher,
                                 json={"session_id": session_id,
                                       "query": "чего нет в базе", "no_cache": True})

    body = response.json()
    assert response.status_code == 200
    assert body["sources"] == []
    assert body["stats"]["selected"] == 0


async def test_suggest_queries_returns_list(client, researcher) -> None:
    response = await client.get("/api/chat/suggest-queries?query=хлорофилл",
                                headers=researcher)

    body = response.json()
    assert response.status_code == 200
    assert isinstance(body["suggestions"], list)
    assert body["query"] == "хлорофилл"

# --------------------------------------------------------------------------- цитаты
class _MarkerStub(StubLLMModel):
    """Отдаёт маркерный текст только на вызов генерации ответа.

    Сводки контекста идут обычной заглушкой (`relevance_score` в промпте),
    иначе paperqa не разберёт оценку релевантности и уронит сборку контекста.
    """

    async def call_single(self, messages=None, **kwargs):
        text = "".join(getattr(m, "content", "") or "" for m in (messages or []))
        if "relevance_score" in text:
            return await super().call_single(messages, **kwargs)
        return self._LLMResult(text=self.answer, model=self.name)


async def test_llm_citation_markers_are_repaired(client, researcher, session_id,
                                                 seeded, stub_registry) -> None:
    """Выдуманные LLM маркеры «(степень N)» не доходят до пользователя.

    Слабая модель пишет их вместо ключей PaperQA; ответ должен прийти со
    ссылками `[n]` (нумерация источников в интерфейсе), а номера за пределами
    выдачи — удалены и видны в stats["citations"].
    """
    from app.services import paperqa_service as svc

    stub = _MarkerStub(answer=(
        "Хлорофилл-а измеряют экстракционным методом (степень 1, степень 2), "
        "а редкие случаи (степень 9) не опираются ни на что."))
    svc._registry.session_service(session_id)._llm_model = stub

    body = await _query(client, researcher, session_id, no_cache=True)

    assert "степень" not in body["answer"], body["answer"]
    assert "[1" in body["answer"], body["answer"]
    assert "(степень 9)" not in body["answer"]

    check = body["stats"]["citations"]
    assert check["repaired"][0].startswith("(степень 1, степень 2) → [")
    assert check["dropped"] == ["(степень 9)"]
    assert check["ok"] is False
    assert check["warnings"]


async def test_stale_cached_markers_repaired_on_read(db) -> None:
    """Ответ, закэшированный ДО починки («docname lines 0-0»), чинится при чтении.

    Иначе пользователь навсегда увидит мусор из старого кэша: переиндексация
    сбрасывает ключ, а повторный тот же вопрос — нет.
    """
    from app.services.answer_cache import CachedAnswer
    from app.services.rag_service import RagFusionService

    class _StaleCache:
        async def get_or_none(self, **kwargs):
            return CachedAnswer(
                answer="Факт (2b_context lines 47-77) и (ghost lines 0-0).",
                sources=[{"index": 1, "docname": "2b_context",
                          "page": "2b_context lines 47-77"}],
                citations=["📁 2b_context (temp_literature)"],
                seconds=1.0)

    fusion = RagFusionService(cache=_StaleCache())

    result = await fusion.answer(db, query="повторный вопрос")

    assert result.from_cache is True
    # имя фрагмента заменено на номер источника, мусорная ссылка удалена
    assert result.answer.formatted_answer == "Факт [1] и."
    # ссылки списка пересобраны с номером — иначе [n] в ответе не сопоставить
    assert result.references == ["📁 [1] 2b_context (без категории)"]
    check = result.stats["citations"]
    assert check["changed"] is True
    assert check["repaired"] == ["(2b_context lines 47-77) → [1]"]
    assert check["dropped"] == ["(ghost lines 0-0)"]


async def test_on_stage_reports_growing_progress(db, seeded, session_id) -> None:
    """Колбэк on_stage отдаёт растущие проценты и подписанный LLM-этап.

    Без этапов строка прогресса в чате замирает на 20%, пока LLM считает
    ответ минутами, и выглядит как зависшая («мёртвая строка»).
    """
    from app.services.rag_service import RagFusionService

    seen: list[tuple[int, str]] = []
    fusion = RagFusionService()

    result = await fusion.answer(
        db, query="Что такое CTD-зонд?", session_id=session_id,
        on_stage=lambda percent, label: seen.append((percent, label)))

    assert result.from_cache is False
    percents = [percent for percent, _ in seen]
    assert percents, "fusion не сообщил ни одного этапа"
    assert percents == sorted(percents), percents
    assert any("LLM" in label for _, label in seen), seen
