"""Тесты `PaperQA2Service` (требования `interface.md` §10 + инварианты Фазы 0).

Идут без сети и без Ollama: LLM заглушен, эмбеддинги локальные.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.errors import DocumentProcessingError
from app.services.paperqa_service import (
    GLOBAL_COLLECTION,
    PaperQA2Service,
    collection_kind,
    normalize_collection,
    session_collection,
)
from app.services.pqa_profile import build_pqa_settings
from app.services.types import DocStatus, SourceKind


# ------------------------------------------------- 10.1 добавление текстового документа
async def test_add_file(service: PaperQA2Service, sample_text) -> None:
    document = await service.add_file(sample_text)

    assert document.status is DocStatus.READY
    assert document.path == str(sample_text)
    assert document.dockey
    assert document.chunk_count >= 1
    assert document.citation.endswith("(загружено пользователем)")
    assert service.list_documents()[0].dockey == document.dockey


async def test_add_file_marks_pages_and_hash(service: PaperQA2Service, sample_text) -> None:
    document = await service.add_file(sample_text)
    assert document.content_hash == document.dockey or len(document.dockey) == 32
    assert document.size_bytes == sample_text.stat().st_size


async def test_add_file_deduplicates_by_content(
    service: PaperQA2Service, tmp_path: Path, sample_text: Path,
) -> None:
    first = await service.add_file(sample_text)
    assert first is not None

    copy_path = tmp_path / "copy_of_notes.md"
    copy_path.write_text(sample_text.read_text(encoding="utf-8"), encoding="utf-8")

    second = await service.add_file(copy_path)  # тот же dockey -> дедуп
    assert second is None
    assert len(service.list_documents()) == 1


async def test_add_files_reports_added_and_failed(
    service: PaperQA2Service, sample_text: Path, tmp_path: Path,
) -> None:
    bad = tmp_path / "picture.png"
    bad.write_bytes(b"\x89PNG\r\n\x1a\n")

    batch = await service.add_files([sample_text, bad, tmp_path / "missing.md"])

    assert len(batch.added) == 1
    assert [f[0] for f in batch.failed] == [str(bad), str(tmp_path / "missing.md")]
    assert batch.total == 3


async def test_add_upload(service: PaperQA2Service) -> None:
    import io

    upload = io.BytesIO(
        "Биомасса водорослей Баренцева моря: метод GF/F и хлорофилл-а.".encode()
    )
    upload.name = "upload_note.txt"

    batch = await service.add_uploads([upload])

    assert len(batch.added) == 1
    assert batch.added[0].status is DocStatus.READY
    assert batch.added[0].chunk_count >= 1


async def test_add_upload_rejects_oversized(
    service: PaperQA2Service, service_app,
) -> None:
    import io

    service_app.upload_max_mb = 0  # любой файл больше лимита
    upload = io.BytesIO(b"x" * 1024)
    upload.name = "big.txt"

    batch = await service.add_uploads([upload])
    assert batch.added == []
    assert "больше" in batch.failed[0][1]


async def test_missing_file_raises_file_not_found(service: PaperQA2Service, tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        await service.add_file(tmp_path / "no_such_file.md")


async def test_unsupported_extension_raises(service: PaperQA2Service, tmp_path) -> None:
    path = tmp_path / "photo.png"
    path.write_bytes(b"\x89PNG")

    with pytest.raises(DocumentProcessingError) as exc:
        await service.add_file(path)
    assert "Неподдерживаемый тип файла" in str(exc.value)


# ------------------------------------------------------- удаление и очистка (§10.3, §10.5)
async def test_delete_returns_bool(service: PaperQA2Service, sample_text) -> None:
    document = await service.add_file(sample_text)

    assert await service.delete_document(dockey=document.dockey) is True
    assert await service.delete_document(dockey=document.dockey) is False


async def test_delete_by_path(service: PaperQA2Service, sample_text) -> None:
    await service.add_file(sample_text)
    assert await service.delete_document(path=str(sample_text)) is True
    assert len(service.list_documents()) == 0


async def test_delete_unknown_returns_false(service: PaperQA2Service) -> None:
    assert await service.delete_document(dockey="deadbeef") is False


async def test_delete_removes_chunks_from_store(service: PaperQA2Service, chunk_store, sample_text) -> None:
    document = await service.add_file(sample_text)
    assert await chunk_store.count_chunks("global") > 0

    await service.delete_document(dockey=document.dockey)
    assert await chunk_store.count_chunks("global") == 0


async def test_clear_documents(service: PaperQA2Service, chunk_store, sample_text, sample_csv) -> None:
    await service.add_files([sample_text, sample_csv])
    assert len(service.list_documents()) == 2

    assert await service.clear_documents() == 2
    assert len(service.list_documents()) == 0
    assert await chunk_store.count_chunks("global") == 0


# ------------------------------------------------------------------------- поиск/ответ
async def test_aget_evidence_scores(service: PaperQA2Service, sample_text, sample_csv) -> None:
    await service.add_files([sample_text, sample_csv])

    chunks, session = await service.get_evidence("метод измерения биомассы GF/F")

    assert chunks, "не найдено ни одного фрагмента"
    assert all(isinstance(c.score, int) for c in chunks)
    assert chunks == sorted(chunks, key=lambda c: -c.score), "чанки не отсортированы"
    assert all(c.kind is SourceKind.GLOBAL for c in chunks)
    assert all(c.marker == "📚" for c in chunks)
    assert len(session.contexts) == len(chunks)


async def test_search_respects_limit(service: PaperQA2Service, sample_text, sample_csv) -> None:
    await service.add_files([sample_text, sample_csv])
    assert len(await service.search("хлорофилл-а", limit=1)) <= 1


async def test_ask_returns_answer_and_citations(service: PaperQA2Service, sample_text) -> None:
    await service.add_file(sample_text)

    result = await service.ask("Как измеряют биомассу водорослей?")

    assert result.answer != ""
    assert result.formatted_answer != ""
    assert result.context and result.context[0]["docname"]
    assert result.context[0]["marker"] == "📚"
    assert result.citations == [] or all(isinstance(c, str) for c in result.citations)
    # has_successful_answer — три состояния paperqa (уверен/не уверен/не оценивал)
    assert result.has_successful_answer in (True, False, None)


async def test_ask_with_evidence_reuses_context(
    service: PaperQA2Service, stub_llm, sample_text: Path,
) -> None:
    """RAG-fusion: контекст ищется один раз (Фаза 0: 374 с -> 118 с)."""
    await service.add_file(sample_text)
    calls_before = len(stub_llm.calls)

    chunks, session = await service.get_evidence("метод GF/F")
    result = await service.ask(session, evidence=chunks)

    assert result.used_context is True
    assert result.question
    assert len(stub_llm.calls) > calls_before
    assert result.evidence and result.evidence[0].score >= result.evidence[-1].score


async def test_ask_with_evidence_helper(service: PaperQA2Service, sample_text) -> None:
    await service.add_file(sample_text)
    result = await service.ask_with_evidence("хлорофилл-а", k=2)
    assert result.answer
    assert result.used_context is True


async def test_answer_result_to_dict_is_json_serializable(
    service: PaperQA2Service, sample_text: Path,
) -> None:
    import json

    await service.add_file(sample_text)
    result = await service.ask("Что такое GF/F?")
    payload = json.dumps(result.to_dict(), ensure_ascii=False)
    assert "answer" in payload


# ------------------------------------------------------------------------- коллекции
def test_collection_names_and_kinds() -> None:
    assert normalize_collection("") == GLOBAL_COLLECTION
    assert normalize_collection("session:abc") == "session:abc"
    assert normalize_collection("abc") == "session:abc"
    assert collection_kind(GLOBAL_COLLECTION) is SourceKind.GLOBAL
    assert collection_kind(session_collection("abc")) is SourceKind.SESSION


async def test_session_collections_are_isolated(
    service_app, chunk_store, stub_llm, sample_text, tmp_path
) -> None:
    global_service = PaperQA2Service(service_app, "global", chunk_store, llm_model=stub_llm)
    session_service = PaperQA2Service(
        service_app, session_collection("s-1"), chunk_store, llm_model=stub_llm)

    await global_service.add_file(sample_text)

    assert len(global_service.list_documents()) == 1
    assert session_service.list_documents() == []

    chunks, _ = await session_service.get_evidence("GF/F")
    assert chunks == [], "сессионная база не должна видеть глобальные документы"


async def test_session_chunks_marked_with_folder_icon(
    service_app, chunk_store, stub_llm, sample_text
) -> None:
    session_service = PaperQA2Service(
        service_app, session_collection("s-1"), chunk_store, llm_model=stub_llm)
    await session_service.add_file(sample_text)

    chunks, _ = await session_service.get_evidence("биомасса")
    assert chunks[0].kind is SourceKind.SESSION
    assert chunks[0].marker == "📁"


# --------------------------------------------------------------------- профиль Settings
def test_settings_keep_phase0_invariants(service_app) -> None:
    settings = build_pqa_settings(service_app)

    # legacy-форма llm_config: канонический {"models": ...} теряет timeout/api_base
    assert list(settings.llm_config) == ["model_list"]
    params = settings.llm_config["model_list"][0]["litellm_params"]
    assert params["timeout"] == service_app.llm_timeout_seconds
    assert params["api_base"] == service_app.ollama_base_url
    assert settings.embedding == "st-multi-qa-MiniLM-L6-cos-v1"
    assert settings.parsing.use_doc_details is False
    assert settings.parsing.reader_config == {
        "chunk_chars": service_app.chunk_chars, "overlap": service_app.chunk_overlap}
    assert settings.answer.max_concurrent_requests == service_app.max_concurrent_requests
    assert "русском языке" in settings.prompts.system


def test_settings_override_keeps_other_answer_params(service_app) -> None:
    """Переопределение одного ключа не должно терять остальные параметры раздела."""
    settings = build_pqa_settings(service_app, answer={"evidence_k": 2})
    assert settings.answer.evidence_k == 2
    assert settings.answer.max_concurrent_requests == service_app.max_concurrent_requests
    assert settings.answer.answer_max_sources == service_app.answer_max_sources


def test_service_uses_evidence_k_override(service: PaperQA2Service, sample_text) -> None:
    settings = service._settings_with_k(3)
    assert settings.answer.evidence_k == 3
    assert settings.answer.max_concurrent_requests == service.app.max_concurrent_requests


def test_citation_for_user_upload(service: PaperQA2Service) -> None:
    from pathlib import Path

    citation = service.make_citation(Path("/data/documents/analiz_vyhodov.md"))
    assert citation == "analiz vyhodov (загружено пользователем)"

    assert service.make_citation(Path("/x/dataset.csv"), title="Данные Баренцева 2024") == (
        "Данные Баренцева 2024 (загружено пользователем)")


async def test_stats_report_collection(service: PaperQA2Service, sample_text) -> None:
    await service.add_file(sample_text)
    stats = await service.stats()

    assert stats["collection"] == "global"
    assert stats["kind"] == "global"
    assert stats["documents_in_memory"] == 1
    assert stats["chunks_in_memory"] == stats["chunks_in_store"] > 0
    assert stats["embedding"] == "st-multi-qa-MiniLM-L6-cos-v1"


async def test_documents_on_disk_survive_service_recreation(
    service_app, chunk_store, stub_llm, sample_text
) -> None:
    """Реестр документов читается из БД ещё до восстановления состояния."""
    first = PaperQA2Service(service_app, "global", chunk_store, llm_model=stub_llm)
    await first.add_file(sample_text)

    second = PaperQA2Service(service_app, "global", chunk_store, llm_model=stub_llm)
    on_disk = await second.documents_on_disk()
    assert len(on_disk) == 1
    assert on_disk[0].docname