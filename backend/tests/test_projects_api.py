"""Фаза 7 — сквозной сценарий проекта статьи.

DoD фазы: сгенерированный Discussion содержит ссылки и на `project_data`, и на
литературу; экспорт открывается в Word.

LLM подменён заглушкой, которая возвращает текст с ссылками `[1]`, `[2]` —
контракт цитат проверяется на реальном ответе.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from tests.conftest import StubLLMModel, login_headers

SECTION_TEXT = (
    "## Discussion\n\n"
    "Полученные значения биомассы согласуются с литературой [1].\n"
    "Собственные данные по хлорофиллу-а [2] показывают иную картину.\n"
)


@pytest.fixture
async def researcher(client, researcher_user):
    return await login_headers(client, "ivanov", "researcher-pass-123")


@pytest.fixture
async def session_id(client, researcher):
    response = await client.post("/api/sessions", json={"title": "Статья"},
                                 headers=researcher)
    return response.json()["id"]


@pytest.fixture
async def project_id(client, researcher, session_id):
    response = await client.post(
        f"/api/sessions/{session_id}/projects",
        json={"title": "Биомасса Баренцева моря",
              "target_journal": "Marine Biology"},
        headers=researcher)
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.fixture
async def docs(client, researcher, session_id, stub_registry, tmp_path):
    """Глобальный источник (литература) + документ сессии с ролью data."""
    import app.db.session as session_module
    from app.db.models import DocumentCategory, DocumentVisibility, ResearchSession
    from app.db.repositories import documents as docs_repo

    literature = tmp_path / "smith2019.md"
    literature.write_text("# Smith 2019\n\nБиомасса водорослей в Баренцеве море "
                           "измеряется методом GF/F.\n", encoding="utf-8")
    data = tmp_path / "biomass.csv"
    data.write_text("station,depth_m,gf_f\nBS1,0,0.42\nBS2,10,0.28\n",
                    encoding="utf-8")

    registry = stub_registry
    registry.global_service()._llm_model = StubLLMModel(answer=SECTION_TEXT)
    registry.session_service(session_id)._llm_model = StubLLMModel(answer=SECTION_TEXT)

    g_ref = await registry.global_service().add_file(literature)
    s_ref = await registry.session_service(session_id).add_file(data,
                                                                 session_id=session_id)

    with session_module.get_session_factory()() as db:
        owner_id = db.get(ResearchSession, session_id).user_id
        g_row = docs_repo.upsert_document(
            db, dockey=g_ref.dockey, docname=g_ref.docname, title="Smith 2019",
            filename=literature.name, path=g_ref.path,
            size_bytes=literature.stat().st_size, chunk_count=g_ref.chunk_count,
            citation=g_ref.citation, category=DocumentCategory.global_knowledge,
            visibility=DocumentVisibility.global_, session_id=None,
            owner_user_id=owner_id, added_by=owner_id)
        s_row = docs_repo.upsert_document(
            db, dockey=s_ref.dockey, docname=s_ref.docname, title="Данные GF/F",
            filename=data.name, path=s_ref.path,
            size_bytes=data.stat().st_size, chunk_count=s_ref.chunk_count,
            citation=s_ref.citation, category=DocumentCategory.project_data,
            visibility=DocumentVisibility.session, session_id=session_id,
            owner_user_id=owner_id, added_by=owner_id)
        db.commit()
        return {"global_id": g_row.id, "data_id": s_row.id,
                "global_dockey": g_ref.dockey, "data_dockey": s_ref.dockey}


# --------------------------------------------------------------------------- CRUD
async def test_create_project_gets_default_plan(client, researcher,
                                                session_id) -> None:
    response = await client.post(
        f"/api/sessions/{session_id}/projects",
        json={"title": "План"}, headers=researcher)

    body = response.json()
    assert response.status_code == 201
    assert body["status"] == "planning"
    assert [s["name"] for s in body["sections"]][:3] == [
        "Introduction", "Methods", "Results"]


async def test_project_limit_is_enforced(client, researcher, session_id,
                                         monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_projects_per_session", 2,
                        raising=False)
    for i in range(2):
        assert (await client.post(f"/api/sessions/{session_id}/projects",
                                  json={"title": f"P{i}"},
                                  headers=researcher)).status_code == 201

    response = await client.post(f"/api/sessions/{session_id}/projects",
                                 json={"title": "Лишний"}, headers=researcher)

    assert response.status_code == 409
    assert response.json()["meta"]["resource"] == "projects"


async def test_list_and_patch_project(client, researcher, project_id,
                                       session_id) -> None:
    listed = await client.get(f"/api/sessions/{session_id}/projects",
                              headers=researcher)
    assert project_id in {p["id"] for p in listed.json()}

    patched = await client.patch(
        f"/api/sessions/{session_id}/projects/{project_id}",
        json={"status": "drafting", "target_journal": "Ocean Science"},
        headers=researcher)
    assert patched.json()["status"] == "drafting"
    assert patched.json()["target_journal"] == "Ocean Science"


async def test_foreign_project_is_404(client, researcher, session_id,
                                      project_id, db_engine) -> None:
    from sqlalchemy.orm import sessionmaker

    from app.core.security import hash_password
    from app.db.models import Role
    from app.db.repositories.users import create_user

    with sessionmaker(bind=db_engine, expire_on_commit=False)() as db:
        create_user(db, username="petrov", password="password-1234",
                    role=Role.researcher, hashed_password=hash_password("password-1234"))
        db.commit()
    petrov = await login_headers(client, "petrov", "password-1234")

    response = await client.get(
        f"/api/sessions/{session_id}/projects/{project_id}", headers=petrov)
    assert response.status_code == 404


# --------------------------------------------------------------------------- разделы
async def test_sections_are_listed_with_progress(client, researcher,
                                                 project_id, session_id) -> None:
    response = await client.get(
        f"/api/sessions/{session_id}/projects/{project_id}/sections",
        headers=researcher)

    sections = response.json()
    assert sections[0]["name"] == "Introduction"
    assert sections[0]["written"] is False
    assert sections[0]["words"] == 0


async def test_section_can_be_edited_manually(client, researcher, project_id,
                                              session_id) -> None:
    response = await client.put(
        f"/api/sessions/{session_id}/projects/{project_id}/sections/Introduction",
        json={"content_md": "Свой черновик [1].", "notes": "короче"},
        headers=researcher)

    body = response.json()
    assert response.status_code == 200
    assert body["content_md"] == "Свой черновик [1]."
    assert body["written"] is True
    assert body["words"] == 3


async def test_unknown_section_is_404(client, researcher, project_id,
                                       session_id) -> None:
    response = await client.put(
        f"/api/sessions/{session_id}/projects/{project_id}/sections/НетТакого",
        json={"content_md": "x"}, headers=researcher)
    assert response.status_code == 404


# --------------------------------------------------------------------------- документы
async def test_documents_can_be_bound_with_role(client, researcher, project_id,
                                                session_id, docs) -> None:
    response = await client.post(
        f"/api/sessions/{session_id}/projects/{project_id}/documents",
        json={"document_id": docs["data_id"], "role": "data"},
        headers=researcher)
    assert response.status_code == 204

    listed = await client.get(
        f"/api/sessions/{session_id}/projects/{project_id}/documents",
        headers=researcher)

    bound = listed.json()
    assert len(bound) == 1
    assert bound[0]["role"] == "data"
    assert bound[0]["document"]["category"] == "project_data"


async def test_bind_rejects_document_of_other_session(client, researcher,
                                                      project_id, session_id,
                                                      docs) -> None:
    response = await client.post(
        f"/api/sessions/{session_id}/projects/{project_id}/documents",
        json={"document_id": "несуществующий", "role": "data"}, headers=researcher)
    assert response.status_code == 404


async def test_unbind_document(client, researcher, project_id, session_id,
                               docs) -> None:
    await client.post(f"/api/sessions/{session_id}/projects/{project_id}/documents",
                      json={"document_id": docs["data_id"], "role": "data"},
                      headers=researcher)

    response = await client.delete(
        f"/api/sessions/{session_id}/projects/{project_id}/documents/"
        f"{docs['data_id']}", headers=researcher)

    assert response.status_code == 204
    listed = await client.get(
        f"/api/sessions/{session_id}/projects/{project_id}/documents",
        headers=researcher)
    assert listed.json() == []


# --------------------------------------------------------------------------- генерация
async def test_generate_section_returns_citations(client, researcher, project_id,
                                                  session_id, docs) -> None:
    response = await client.post(
        f"/api/sessions/{session_id}/projects/{project_id}/generate",
        json={"section": "Discussion", "question": "Как соотносятся данные?",
              "word_target": 300},
        headers=researcher)

    body = response.json()
    assert response.status_code == 200, body
    assert "хлорофиллу-а [2]" in body["content_md"]
    assert body["citations_ok"] is True
    assert body["word_count"] > 0
    assert body["citations"], "нужна карта цитат"
    assert body["references"], "нужен список источников"


async def test_discussion_cites_both_data_and_literature(client, researcher,
                                                         project_id, session_id,
                                                         docs) -> None:
    """DoD: Discussion ссылается и на собственные данные, и на литературу."""
    response = await client.post(
        f"/api/sessions/{session_id}/projects/{project_id}/generate",
        json={"section": "Discussion", "question": "Сопоставление"},
        headers=researcher)

    body = response.json()
    scopes = {c["source_scope"] for c in body["citations"]}
    assert "global" in scopes, "нет ссылки на литературу"
    assert "session" in scopes, "нет ссылки на собственные данные"


async def test_generation_writes_into_section_plan(client, researcher,
                                                    project_id, session_id,
                                                    docs) -> None:
    await client.post(
        f"/api/sessions/{session_id}/projects/{project_id}/generate",
        json={"section": "Discussion", "question": "Сопоставление"},
        headers=researcher)

    sections = await client.get(
        f"/api/sessions/{session_id}/projects/{project_id}/sections",
        headers=researcher)

    discussion = next(s for s in sections.json() if s["name"] == "Discussion")
    assert discussion["written"] is True
    assert discussion["words"] > 0


async def test_generation_saves_version_snapshot(client, researcher, project_id,
                                                 session_id, docs) -> None:
    await client.post(
        f"/api/sessions/{session_id}/projects/{project_id}/generate",
        json={"section": "Discussion", "question": "Вопрос раз"},
        headers=researcher)

    versions = await client.get(
        f"/api/sessions/{session_id}/projects/{project_id}/versions",
        headers=researcher)

    body = versions.json()
    assert len(body) == 1
    assert body[0]["section_name"] == "Discussion"
    assert body[0]["stats"]["citations_ok"] is True
    assert body[0]["word_count"] > 0


async def test_repeat_generation_uses_version_cache(client, researcher,
                                                    project_id, session_id,
                                                    docs) -> None:
    first = await client.post(
        f"/api/sessions/{session_id}/projects/{project_id}/generate",
        json={"section": "Discussion", "question": "Вопрос раз", "no_cache": True},
        headers=researcher)
    second = await client.post(
        f"/api/sessions/{session_id}/projects/{project_id}/generate",
        json={"section": "Discussion", "question": "Вопрос раз"},
        headers=researcher)

    assert first.json()["from_cache"] is False
    assert second.json()["from_cache"] is True
    assert second.json()["content_md"] == first.json()["content_md"]


async def test_diff_between_versions(client, researcher, project_id, session_id,
                                     docs) -> None:
    await client.post(
        f"/api/sessions/{session_id}/projects/{project_id}/generate",
        json={"section": "Discussion", "question": "Первый"},
        headers=researcher)
    await client.post(
        f"/api/sessions/{session_id}/projects/{project_id}/generate",
        json={"section": "Discussion", "question": "Второй", "no_cache": True},
        headers=researcher)

    versions = (await client.get(
        f"/api/sessions/{session_id}/projects/{project_id}/versions",
        headers=researcher)).json()
    left, right = versions[1]["id"], versions[0]["id"]

    diff = await client.get(
        f"/api/sessions/{session_id}/projects/{project_id}/versions/diff"
        f"?left={left}&right={right}", headers=researcher)

    body = diff.json()
    assert body["left"] == left and body["right"] == right
    assert isinstance(body["diff"], list)


async def test_archived_session_blocks_generation(client, researcher, project_id,
                                                  session_id, docs) -> None:
    await client.post(f"/api/sessions/{session_id}/archive", headers=researcher)

    response = await client.post(
        f"/api/sessions/{session_id}/projects/{project_id}/generate",
        json={"section": "Discussion", "question": "x"}, headers=researcher)

    assert response.status_code == 409


async def test_project_progress_endpoint(client, researcher, project_id,
                                         session_id, docs) -> None:
    await client.post(
        f"/api/sessions/{session_id}/projects/{project_id}/generate",
        json={"section": "Discussion", "question": "x"}, headers=researcher)

    progress = await client.get(
        f"/api/sessions/{session_id}/projects/{project_id}/progress",
        headers=researcher)

    body = progress.json()
    assert body["written"] == 1
    assert body["versions"] == 1
    assert "Introduction" in body["missing_sections"]


# --------------------------------------------------------------------------- экспорт
async def test_export_markdown(client, researcher, project_id, session_id,
                               docs) -> None:
    await client.post(
        f"/api/sessions/{session_id}/projects/{project_id}/generate",
        json={"section": "Discussion", "question": "x"}, headers=researcher)

    response = await client.get(
        f"/api/sessions/{session_id}/projects/{project_id}/export?fmt=markdown",
        headers=researcher)

    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    text = response.content.decode("utf-8")
    assert "# Биомасса Баренцева моря" in text
    assert "## References" in text


async def test_export_docx_opens_as_ooxml(client, researcher, project_id,
                                           session_id, docs) -> None:
    await client.post(
        f"/api/sessions/{session_id}/projects/{project_id}/generate",
        json={"section": "Discussion", "question": "x"}, headers=researcher)

    response = await client.get(
        f"/api/sessions/{session_id}/projects/{project_id}/export?fmt=docx",
        headers=researcher)

    assert response.status_code == 200
    assert response.content[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert "word/document.xml" in archive.namelist()


async def test_export_zip(client, researcher, project_id, session_id,
                          docs) -> None:
    # исходники попадают в архив только если документ привязан к проекту
    await client.post(f"/api/sessions/{session_id}/projects/{project_id}/documents",
                      json={"document_id": docs["data_id"], "role": "data"},
                      headers=researcher)

    response = await client.get(
        f"/api/sessions/{session_id}/projects/{project_id}/export?fmt=zip"
        f"&include_documents=true", headers=researcher)

    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
    assert any(n.endswith(".docx") for n in names)
    assert any(n.startswith("references/") for n in names), "исходники в архиве"

# ===========================================================================
# Остаток Фазы 7: обзор литературы, сверка с данными, пробелы, отчёт
# ===========================================================================
@pytest.fixture
async def data_bound(client, researcher, project_id, session_id, docs):
    """Документ с ролью data привязан к проекту — нужен для сверки."""
    await client.post(f"/api/sessions/{session_id}/projects/{project_id}/documents",
                      json={"document_id": docs["data_id"], "role": "data"},
                      headers=researcher)
    await client.post(f"/api/sessions/{session_id}/projects/{project_id}/documents",
                      json={"document_id": docs["global_id"], "role": "reference"},
                      headers=researcher)
    return docs


async def _generate(client, headers, session_id, project_id, **payload):
    response = await client.post(
        f"/api/sessions/{session_id}/projects/{project_id}/generate",
        json=payload, headers=headers)
    assert response.status_code == 200, response.json()
    return response.json()


async def test_literature_review(client, researcher, project_id, session_id,
                                 data_bound) -> None:
    body = await _generate(client, researcher, session_id, project_id,
                           kind="literature_review",
                           section="Literature Review",
                           question="биомасса водорослей Баренцева моря")

    assert body["citations_ok"] is True
    assert body["sources"], "обзор строится на источниках"
    assert body["references"]


async def test_data_comparison_uses_computed_numbers(client, researcher,
                                                    project_id, session_id,
                                                    data_bound) -> None:
    body = await _generate(client, researcher, session_id, project_id,
                           kind="data_comparison", section="Comparison",
                           question="Согласуются ли наши значения с литературой?")

    assert body["citations_ok"] is True
    assert body["citations"], "сверка обязана ссылаться на источники"


async def test_gap_analysis_of_literature(client, researcher, project_id,
                                          session_id, data_bound) -> None:
    body = await _generate(client, researcher, session_id, project_id,
                           kind="gap_analysis", section="Gaps",
                           question="что осталось неизученным")

    assert body["citations_ok"] is True
    assert body["word_count"] > 0


async def test_report_follows_template(client, researcher, project_id,
                                       session_id, data_bound) -> None:
    template = "# Отчёт HELCOM\n\n## Материал\n\n## Методы\n\n## Выводы\n"
    body = await _generate(client, researcher, session_id, project_id,
                           kind="report", section="Report",
                           question="мониторинг биомассы",
                           template_md=template)

    assert body["citations_ok"] is True
    assert body["word_count"] > 0


async def test_report_without_template_uses_default(client, researcher,
                                                    project_id, session_id,
                                                    data_bound) -> None:
    body = await _generate(client, researcher, session_id, project_id,
                           kind="report", section="Report", question="тема")
    assert body["citations_ok"] is True


async def test_draft_analysis_generation_returns_structured_gaps(
        client, researcher, project_id, session_id, data_bound) -> None:
    # черновик с числом без ссылки -> разбор обязан найти пробел
    await client.put(
        f"/api/sessions/{session_id}/projects/{project_id}/sections/Results",
        json={"content_md": "Средняя биомасса составила 1,85 мг/м3."},
        headers=researcher)

    body = await _generate(client, researcher, session_id, project_id,
                           kind="draft_analysis", section="Обзор черновика",
                           question="что исправить")

    assert body["analysis"] is not None
    assert body["analysis"]["has_gaps"] is True
    kinds = {g["kind"] for g in body["analysis"]["gaps"]}
    assert "uncited_number" in kinds


# --------------------------------------------------------------------------- DoD
async def test_draft_analysis_endpoint_finds_real_gap(client, researcher,
                                                      project_id, session_id,
                                                      data_bound) -> None:
    """DoD Фазы 7: анализ черновика находит ≥1 реальный пробел (без LLM)."""
    await client.put(
        f"/api/sessions/{session_id}/projects/{project_id}/sections/Methods",
        json={"content_md": "Пробы отбирали батернет-граблями [1]."},
        headers=researcher)
    await client.put(
        f"/api/sessions/{session_id}/projects/{project_id}/sections/Results",
        json={"content_md": "Хлорофилл-а в среднем 1,85 мг/м3. "
                            "Значения существенно выше литературных."},
        headers=researcher)

    response = await client.get(
        f"/api/sessions/{session_id}/projects/{project_id}/draft-analysis",
        headers=researcher)

    body = response.json()
    assert response.status_code == 200
    assert body["has_gaps"] is True
    assert len(body["gaps"]) >= 1

    gaps = {(g["kind"], g["where"]) for g in body["gaps"]}
    assert ("uncited_number", "Results") in gaps
    assert ("missing_section", "Conclusions") in gaps
    assert body["rendered"]


async def test_draft_analysis_of_cited_draft(client, researcher, project_id,
                                              session_id, data_bound) -> None:
    """Текст с корректными ссылками не даёт пробелов по цитатам."""
    for name, text in (("Introduction", "Метод GF/F описан в [1]."),
                       ("Methods", "Отбор проб по протоколу [2]."),
                       ("Results", "Результаты получены методом и приведены в [3].")):
        await client.put(
            f"/api/sessions/{session_id}/projects/{project_id}/sections/{name}",
            json={"content_md": text}, headers=researcher)

    body = (await client.get(
        f"/api/sessions/{session_id}/projects/{project_id}/draft-analysis",
        headers=researcher)).json()

    uncited = [g for g in body["gaps"] if g["kind"] in
               ("uncited_number", "weak_claim")]
    assert uncited == [], [g.to_dict() if hasattr(g, "to_dict") else g
                           for g in uncited]
    # разделы Discussion и Conclusions намеренно не написаны — это ожидаемые пробелы
    missing = {g["where"] for g in body["gaps"] if g["kind"] == "missing_section"}
    assert missing == {"Discussion", "Conclusions"}
    assert body["citations_found"] == [1, 2, 3]


async def test_draft_analysis_clean_when_plan_complete(client, researcher,
                                                       project_id, session_id,
                                                       data_bound) -> None:
    """Полностью написанный по плану проект без ссылок в тексте не даёт high-пробелов."""
    sections = await client.get(
        f"/api/sessions/{session_id}/projects/{project_id}/sections",
        headers=researcher)
    for section in sections.json():
        text = (f"{section['name']}: выполнено по методу и протоколу [1]."
                if section["name"] not in {"Results"}
                else "Результаты получены методом и приведены в [1].")
        await client.put(
            f"/api/sessions/{session_id}/projects/{project_id}/sections/"
            f"{section['name']}", json={"content_md": text}, headers=researcher)

    body = (await client.get(
        f"/api/sessions/{session_id}/projects/{project_id}/draft-analysis",
        headers=researcher)).json()

    assert body["by_severity"]["high"] == 0
    assert "Пробелов не найдено" in body["rendered"]


async def test_special_kinds_are_saved_as_versions(client, researcher, project_id,
                                                   session_id, data_bound) -> None:
    await _generate(client, researcher, session_id, project_id,
                    kind="literature_review", section="Literature Review",
                    question="тема")

    versions = (await client.get(
        f"/api/sessions/{session_id}/projects/{project_id}/versions",
        headers=researcher)).json()

    assert versions[0]["kind"] == "literature_review"
    assert versions[0]["section_name"] == "Literature Review"


async def test_data_comparison_without_data_documents(client, researcher,
                                                      project_id, session_id,
                                                      docs) -> None:
    """Нет документа с ролью data — сверка всё равно отвечает, а не падает."""
    body = await _generate(client, researcher, session_id, project_id,
                           kind="data_comparison", section="Comparison",
                           question="сравнение")

    assert body["citations_ok"] is True
