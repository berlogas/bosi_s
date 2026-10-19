"""Фаза 6 — сквозной цикл fusion: две коллекции, режимы, разметка 📚/📁.

LLM подменён заглушкой, эмбеддинги локальные. Проверяем ровно то, что важно:
  * hybrid возвращает источники обоих типов;
  * project_focus поднимает проектные документы и прячет заметки;
  * session_only / global_only не смешивают коллекции;
  * ответ сохраняется в истории и попадает в кэш;
  * при готовом контексте повторный поиск НЕ выполняется (инвариант Фазы 0).
"""

from __future__ import annotations

import asyncio

import pytest

from app.db.models import SearchMode
from app.services.rag_fusion import DocumentCatalog
from tests.conftest import StubLLMModel, login_headers


def _empty_catalog() -> DocumentCatalog:
    return DocumentCatalog()


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


async def _quick(client, researcher, **payload) -> dict:
    """Быстрый вопрос: отдать его фоном и дождаться результата задачи.

    Маршрут отвечает мгновенно task_id'ом — сам ответ лежит в Task.result,
    поэтому тест опрашивает /api/tasks/{id}, как это делает UI.
    """
    response = await client.post("/api/chat/quick-query", headers=researcher,
                                 json={"query": "Что такое CTD?", "k": 10, **payload})
    assert response.status_code == 200, response.text
    task_id = response.json()["task_id"]

    loop = asyncio.get_running_loop()
    deadline = loop.time() + 10.0
    while True:
        status = await client.get(f"/api/tasks/{task_id}", headers=researcher)
        body = status.json()
        if body["status"] in ("done", "error", "cancelled"):
            assert body["status"] == "done", body.get("error")
            return body["result"]
        assert loop.time() < deadline, "фоновая задача зависла"
        await asyncio.sleep(0.01)


# --------------------------------------------------------------------------- hybrid
async def test_hybrid_returns_both_scopes(client, researcher, session_id,
                                          seeded) -> None:
    body = await _query(client, researcher, session_id, mode="hybrid")

    # Оба scope участвуют в поиске, но в списке источников остаются только те,
    # на которые модель сослалась в ответе (заглушка цитирует только [1]).
    cited = body["stats"]["citations"]["cited"]
    assert set(cited) == {s["index"] for s in body["sources"]}
    assert body["stats"]["candidates"] > 0
    assert body["stats"]["selected"] == len(body["sources"])


async def test_sources_only_cited_in_answer(client, researcher, session_id,
                                            seeded) -> None:
    """Документ, на который нет ссылки в ответе, в источниках не показывается."""
    body = await _query(client, researcher, session_id, mode="hybrid",
                        no_cache=True)

    sources = body["sources"]
    assert sources, "нужен хотя бы один источник"
    cited = body["stats"]["citations"]["cited"]
    assert cited
    assert [s["index"] for s in sources] == cited
    # нумерация источников остаётся исходной и совпадает с цитатами в тексте
    assert f"[{sources[0]['index']}]" in body["answer"]
    assert len({s["source_scope"] for s in sources}) == 1


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
    first = await _quick(client, researcher, no_cache=True)
    second = await _quick(client, researcher)

    assert first["from_cache"] is False
    assert second["from_cache"] is True
    assert second["answer"] == first["answer"]


async def test_quick_query_returns_task_with_progress(client, researcher) -> None:
    """Вопрос уходит фоном: маршрут отвечает task_id'ом, а не минутами тишины."""
    response = await client.post("/api/chat/quick-query", headers=researcher,
                                 json={"query": "Что такое CTD?"})

    assert response.status_code == 200
    assert set(response.json()) == {"task_id"}

    task = (await client.get(f"/api/tasks/{response.json()['task_id']}",
                             headers=researcher)).json()
    assert task["kind"] == "chat"
    assert task["title"].startswith("Быстрый вопрос:")
    # ответ считает фоновая задача: у задачи есть автор, иначе её не увидит
    # ни админ в списке задач, ни пользователь в своей переписке
    assert task["user_id"]


async def test_quick_query_task_is_visible_only_to_its_author(client, researcher,
                                                               db) -> None:
    """Чужой быстрый вопрос не отдаётся постороннему (паритет сессионного чата)."""
    from app.core.security import hash_password
    from app.db.models import Role
    from app.db.repositories.users import create_user

    create_user(db, username="petrov", password="researcher-pass-123",
                role=Role.researcher,
                hashed_password=hash_password("researcher-pass-123"))
    other = await login_headers(client, "petrov", "researcher-pass-123")

    response = await client.post("/api/chat/quick-query", headers=researcher,
                                 json={"query": "Что такое CTD?"})
    task_id = response.json()["task_id"]

    assert (await client.get(f"/api/tasks/{task_id}", headers=other)).status_code == 404
    assert (await client.get(f"/api/tasks/{task_id}",
                             headers=researcher)).status_code == 200


async def test_quick_query_saves_exchange_to_history(client, researcher,
                                                      seeded) -> None:
    """Ответ доезжает до истории: перезагрузка страницы его не теряет."""
    await _quick(client, researcher, no_cache=True)

    history = await client.get("/api/chat/quick-history", headers=researcher)
    body = history.json()

    assert body["total"] == 2
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][1]["sources"]


# --------------------------------------------------------------------------- болтовня
# Замер 2026-10-18: «привет» стоил ~43 с (12 параллельных LLM-сводок плюс
# автоматический повтор поиска без сводок) и давал ответ СО ССЫЛКОЙ на
# нерелевантный документ — прямое нарушение GROUNDING RULES промпта paperqa.
# Болтовня теперь идёт мимо поиска по базе.


async def test_trivial_query_skips_search_and_returns_no_citations(
        client, researcher, seeded, monkeypatch) -> None:
    """«привет» не ищет по базе и не притворяется, что нашёл источник."""
    import app.services.rag_service as rs

    calls: list[str] = []

    async def boom(*args, **kwargs):
        calls.append("evidence")
        raise AssertionError("поиск по базе для болтовни запускаться не должен")

    monkeypatch.setattr(rs.RagFusionService, "_evidence", boom)

    body = await _quick(client, researcher, query="привет")

    assert calls == [], "болтовня не должна доходить до поиска"
    assert body["sources"] == []
    assert body["references"] == []
    assert body["stats"].get("trivial") is True
    # ответ без источников честно помечен: интерфейс покажет пояснение
    assert body["base_empty"] is True
    assert body["answer"].strip(), "нужен хотя бы разговорный ответ"


async def test_real_question_still_searches(client, researcher, seeded) -> None:
    """Содержательный вопрос по-прежнему идёт в базу и приносит источники."""
    body = await _quick(client, researcher, query="Что такое CTD-зонд?", no_cache=True)

    assert body["sources"], "по содержательному вопросу должны быть источники"
    assert body["stats"].get("trivial") is None


async def test_trivial_fast_path_can_be_switched_off(client, researcher, seeded,
                                               monkeypatch) -> None:
    """Настройка TRIVIAL_QUERY_FAST_PATH=false возвращает строгий путь paperqa."""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "trivial_query_fast_path", False,
                        raising=False)

    body = await _quick(client, researcher, query="привет", no_cache=True)

    # строгий путь: модель получает контекст и отвечает по нему (заглушка),
    # поэтому в ответе либо источники, либо явный отказ
    assert body["stats"].get("trivial") is None
    assert body["answer"].strip()


@pytest.mark.parametrize("query", ["привет", "Привет!", "  привет  ", "СПАСИБО",
                                   "добрый день", "ok", "Hello!"])
def test_is_trivial_query_accepts_smalltalk(query: str) -> None:
    from app.services.rag_service import is_trivial_query

    assert is_trivial_query(query) is True


@pytest.mark.parametrize("query", [
    "привет, что такое CTD?",   # болтовня + вопрос по теме
    "GF/F?",                     # короткий, но содержательный термин
    "хлорофилл",
    "что такое CTD-зонд",
    "сравни методы GF/F и CTD",
    "метод GF/F",
    "нет данных",               # слова из словаря в другой форме — не болтовня
    "",                          # пустой запрос
    "   ",
])
def test_is_trivial_query_rejects_research_questions(query: str) -> None:
    from app.services.rag_service import is_trivial_query

    assert is_trivial_query(query) is False


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

    async def counting(self, query, k=None, doc_filter=None, skip_summary=None):
        calls.append(1)
        return await original(self, query, k=k, doc_filter=doc_filter,
                              skip_summary=skip_summary)

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
    body = await _quick(client, researcher, query="Что такое CTD-зонд?")

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


async def test_summary_fallback_when_llm_scores_everything_zero(
        service_app, monkeypatch) -> None:
    """Пустой результат сводок → один повтор без них.

    Режим сводок (рекомендация PaperQA) опирается на `relevance_score` от LLM.
    Облачная модель часто ставит 0, и paperqa отбрасывает все контексты, потратив
    время впустую. Тогда делаем один повтор без сводок — релевантность считается
    по эмбеддингам.
    """
    from app.services.rag_service import RagFusionService

    calls: list[bool | None] = []

    async def fake_once(self, query, session_id, mode, k, catalog, skip_summary):
        calls.append(skip_summary)
        return [] if skip_summary is None else ["fallback-ok"]

    monkeypatch.setattr(RagFusionService, "_evidence_once", fake_once)
    service = RagFusionService(app=service_app)

    result = await service._evidence("вопрос", "sid", SearchMode.hybrid, 10,
                                     _empty_catalog())

    assert calls == [None, True], "сначала сводки, затем повтор без них"
    assert result == ["fallback-ok"]


async def test_no_fallback_when_summaries_returned_something(
        service_app, monkeypatch) -> None:
    """Если сводки дали результат, повтор не делаем — лишних вызовов не нужно."""
    from app.services.rag_service import RagFusionService

    calls: list[bool | None] = []

    async def fake_once(self, query, session_id, mode, k, catalog, skip_summary):
        calls.append(skip_summary)
        return ["ok"]

    monkeypatch.setattr(RagFusionService, "_evidence_once", fake_once)
    service = RagFusionService(app=service_app)

    result = await service._evidence("вопрос", "sid", SearchMode.hybrid, 10,
                                     _empty_catalog())

    assert calls == [None]
    assert result == ["ok"]


async def test_no_fallback_when_skip_summary_is_configured(
        service_app, monkeypatch) -> None:
    """Если сводки выключены конфигом, повтор делать нечего."""
    from app.services.rag_service import RagFusionService

    calls: list[bool | None] = []

    async def fake_once(self, query, session_id, mode, k, catalog, skip_summary):
        calls.append(skip_summary)
        return []

    monkeypatch.setattr(RagFusionService, "_evidence_once", fake_once)
    service = RagFusionService(app=service_app.model_copy(
        update={"evidence_skip_summary": True}))

    await service._evidence("вопрос", "sid", SearchMode.hybrid, 10, _empty_catalog())

    assert calls == [None]


# --------------------------------------------------------------------------- кто я
# Жалоба 2026-10-19: на «ты кто?» чат отвечал «В предоставленных источниках нет
# информации, чтобы ответить на этот вопрос». Отказ формально честный — вопрос
# действительно не о базе, — но пользователю это не отвечает ни на что: он
# спрашивал, с кем говорит. Теперь вопрос о помощнике уходит мимо поиска и
# модель представляется.


async def test_identity_query_skips_search(client, researcher, seeded,
                                            monkeypatch) -> None:
    """«Ты кто?» не ищет по базе и не отвечает отказом."""
    import app.services.rag_service as rs

    calls: list[str] = []

    async def boom(*args, **kwargs):
        calls.append("evidence")
        raise AssertionError("поиск по базе для вопроса обо мне запускаться не должен")

    monkeypatch.setattr(rs.RagFusionService, "_evidence", boom)

    body = await _quick(client, researcher, query="ты кто?", no_cache=True)

    assert calls == [], "вопрос о помощнике не должен доходить до базы"
    assert body["sources"] == []
    assert body["references"] == []
    assert body["stats"].get("identity") is True
    assert body["stats"].get("trivial") is True  # тот же быстрый путь
    assert body["answer"].strip()


async def test_identity_answer_names_assistant_or_explains_itself(
        client, researcher, seeded) -> None:
    """Ответ на вопрос о помощнике не должен быть отказом «нет источников».

    Заглушка LLM в тестах отвечает заранее заданным текстом, поэтому здесь
    проверяется контракт: если модель всё же отказалась, подставляется
    запасное представление, а не отказ.
    """
    import app.services.rag_service as rs

    async def refusing_llm(*args, **kwargs):
        class R:
            text = "В предоставленных источниках нет информации, чтобы ответить."
        return R()

    service = rs.RagFusionService()
    chat_llm = service.registry.global_service().chat_llm
    chat_llm.call_single = refusing_llm

    result = await service._answer_trivial(
        "ты кто?", mode=rs.SearchMode.global_only, kind="identity")

    answer = result.answer.answer.lower()
    # отказ заменён представлением: имя есть, а отказа — нет.
    # Проверять «нет источников» во всём ответе нельзя: нормальное
    # представление о них упоминает (отвечаю со ссылками на источники).
    assert "бо" in answer
    assert not answer.startswith("в предоставленных источниках")
    assert "ответить на этот вопрос" not in answer


@pytest.mark.parametrize("query", [
    "ты кто", "Ты кто?", "кто ты", "кто ты такой", "как тебя зовут",
    "твоё имя", "представься", "расскажи о себе", "ты бот", "ты робот",
    "ты машина", "ты человек или машина", "что ты умеешь", "чем ты можешь помочь",
    "что ты делаешь", "как ты работаешь", "who are you", "what can you do",
    "introduce yourself",
])
def test_is_identity_query_accepts_questions_about_assistant(query: str) -> None:
    from app.services.rag_service import is_identity_query

    assert is_identity_query(query) is True


@pytest.mark.parametrize("query", [
    "что такое биобот",              # «ты бот» в теме — это вопрос по базе
    "ты знаешь что такое биомасса",  # «ты» в начале, но это вопрос по теме
    "что ты такое",                  # похоже, но не в списке: лучше уйти в базу
    "CTD-зонд", "хлорофилл",
    "ты и я вместе изучаем океан",  # длиннее 4 слов — не вопрос обо мне
    "",
])
def test_is_identity_query_rejects_research_questions(query: str) -> None:
    """Словарь закрытый: цена ложного срабатывания — потерянный ответ по теме."""
    from app.services.rag_service import is_identity_query

    assert is_identity_query(query) is False


def test_refusal_detection_does_not_swallow_normal_answers() -> None:
    """Отказ ловится по началу ответа, а не по вхождению где угодно."""
    from app.services.rag_service import _is_refusal

    assert _is_refusal("В предоставленных источниках нет информации.") is True
    assert _is_refusal("Источников по этому вопросу нет.") is True
    assert _is_refusal("В базе среди них сведений не нашлось.") is True
    assert _is_refusal("Не могу ответить на этот вопрос.") is True
    # нормальный ответ может упоминать ограничения — это не отказ
    assert _is_refusal(
        "Меня зовут Бо. В источниках нет данных по этому вопросу, но вот что я умею."
    ) is False


async def test_identity_fast_path_respects_trivial_query_switch(
        client, researcher, seeded, monkeypatch) -> None:
    """TRIVIAL_QUERY_FAST_PATH=false отключает и представление.

    Иначе получился бы разнобой: «привет» по настройке строгий, а «ты кто?»
    всё равно отвечает разговорчиво.
    """
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "trivial_query_fast_path", False,
                        raising=False)

    body = await _quick(client, researcher, query="ты кто?", no_cache=True)

    assert body["stats"].get("identity") is None
