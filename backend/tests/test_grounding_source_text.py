"""Сквозная проверка: grounding сверяет ответ с ИСХОДНЫМ текстом источников.

Случай из жизни (Ollama 3B на CPU, 2026-11-11): модель пересказала фрагмент
словами «сушка при 105 °C», хотя в документе — «сушка при 60 °C». Проверка
обоснованности сравнивала ответ со сводками модели, а «105 °C» уже было в
сводке, — выдумка проходила как подтверждённый факт (grounding.ok = true).

Тест гоняет настоящий цикл fusion с подставленной моделью: она пишет и в
сводку, и в ответ — одно и то же выдуманное число.
"""

from __future__ import annotations

import pytest

from tests.conftest import StubLLMModel, login_headers


@pytest.fixture
async def researcher(client, researcher_user):
    return await login_headers(client, "ivanov", "researcher-pass-123")


@pytest.fixture
async def session_id(client, researcher):
    response = await client.post("/api/sessions", json={"title": "Методы GF/F"},
                                 headers=researcher)
    return response.json()["id"]


@pytest.fixture
async def seeded_with_gf(client, researcher, session_id, stub_registry, tmp_path):
    """Документ, где сушка при 60 °C, и модель, которая выдумывает 105 °C."""
    import app.db.session as session_module
    from app.db.models import DocumentCategory, DocumentVisibility, ResearchSession, User
    from app.db.repositories import documents as docs_repo
    from app.db.repositories.users import get_owned_session

    source = tmp_path / "methods.md"
    source.write_text(
        "# Методы измерения биомассы\n\n"
        "Фильтры GF/F: фильтрация 1-2 л воды, сушка при 60 °C, "
        "взвешивание на весах с точностью 0.1 мг.\n"
        "Отношение биомассы к хлорофиллу-а 0,52 (0,42-0,63).\n",
        encoding="utf-8")

    registry = stub_registry
    global_service = registry.global_service()
    session_service = registry.session_service(session_id)

    # Модель выдумывает «105 °C» и в сводке фрагмента, и в ответе.
    hallucinating = StubLLMModel(
        answer=("Биомассу оценивают методом GF/F — взвешиванием сухого остатка "
                "после сушки при 105 °C, плюс пересчёт по хлорофиллу-а "
                "с коэффициентом 0,52 [1]."),
        summary=("Метод GF/F: сушка при 105 °C, взвешивание; коэффициент 0,52 "
                 "[1]."))
    global_service._llm_model = hallucinating
    session_service._llm_model = hallucinating

    ref = await global_service.add_file(source)
    with session_module.get_session_factory()() as db:
        owner = db.get(User, db.get(ResearchSession, session_id).user_id)
        session = get_owned_session(db, session_id, owner)
        docs_repo.upsert_document(
            db, dockey=ref.dockey, docname=ref.docname,
            title="Методы измерения биомассы", filename=source.name,
            path=ref.path, size_bytes=source.stat().st_size,
            chunk_count=ref.chunk_count, citation=ref.citation,
            category=DocumentCategory.global_knowledge,
            visibility=DocumentVisibility.global_, session_id=None,
            owner_user_id=session.user_id, added_by=session.user_id)

    return {"dockey": ref.dockey}


async def test_hallucinated_number_is_flagged_against_source_text(
    client, researcher, session_id, seeded_with_gf
) -> None:
    """Выдуманное «105 °C» должно попасть в отчёт обоснованности.

    Числа нет в документе (там 60 °C), но модель написала его и в сводку, и в
    ответ. Раньше сверка шла со сводкой, и выдумка проходила как подтверждённая.
    """
    response = await client.post(
        "/api/chat/query",
        headers=researcher,
        json={"session_id": session_id, "query": "метод GF/F и сушка фильтра",
              "k": 10, "no_cache": True})
    assert response.status_code == 200, response.text
    body = response.json()

    grounding = body["stats"]["grounding"]
    assert grounding["ok"] is False, "выдуманное число не должно считаться подтверждённым"
    assert "105" in grounding["ungrounded"]
    # Реальное число из документа остаётся подтверждённым:
    assert "0,52" not in grounding["ungrounded"]
    # И предупреждение пользователю тоже есть:
    assert grounding["warnings"]


async def test_grounding_report_reaches_history(
    client, researcher, session_id, seeded_with_gf
) -> None:
    """Отчёт обоснованности сохраняется в истории — его видно в интерфейсе."""
    await client.post(
        "/api/chat/query",
        headers=researcher,
        json={"session_id": session_id, "query": "метод GF/F и сушка фильтра",
              "k": 10, "no_cache": True})

    response = await client.get("/api/chat/messages",
                                params={"session_id": session_id},
                                headers=researcher)
    assert response.status_code == 200, response.text
    messages = response.json()["messages"]
    assistant = [m for m in messages if m["role"] == "assistant"]
    assert assistant, "ответ должен сохраниться в истории"
    checks = assistant[-1].get("checks") or {}
    assert "grounding" in checks
    assert checks["grounding"]["ok"] is False
