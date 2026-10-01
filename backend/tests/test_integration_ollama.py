"""Интеграционный тест с РЕАЛЬНЫМ Ollama (не мок).

Запуск:
    cd backend && python -m pytest tests/test_integration_ollama.py -m integration -q

Требует поднятый Ollama с моделью из `.env` (LLM_MODEL) и скачанные эмбеддинги.
На dev-машине (qwen2.5:3b, CPU) ответ занимает минуты — это ожидаемо.
"""

from __future__ import annotations

import pytest

from app.services.chunk_store import MemoryChunkStore
from app.services.paperqa_service import PaperQA2Service

pytestmark = pytest.mark.integration


@pytest.fixture
def live_service(tmp_path, _test_settings):
    """Сервис с реальной моделью из конфигурации (никаких заглушек)."""
    from app.config import get_settings
    from app.services.pqa_profile import build_pqa_settings

    app = get_settings().model_copy(update={"data_dir": tmp_path / "data"})
    app.data_dir.mkdir(parents=True, exist_ok=True)
    return PaperQA2Service(
        settings=app,
        collection="global",
        chunk_store=MemoryChunkStore(),
        pqa_settings=build_pqa_settings(app),
    )


async def test_live_ask_on_russian_fixture(live_service, sample_text, sample_csv) -> None:
    service = live_service
    batch = await service.add_files([sample_text, sample_csv])
    assert len(batch.added) == 2, batch.failed
    assert all(d.citation for d in batch.added), "у каждого документа должна быть citation"

    result = await service.ask_with_evidence(
        "Какими методами измеряют биомассу и хлорофилл-а водорослей в Баренцевом море?",
        k=4,
    )

    assert result.answer.strip()
    assert result.formatted_answer.strip()
    assert result.context, "контекст не собран"
    # локализация: ответ на русском с сохранением терминов
    assert any(term in result.formatted_answer.lower() for term in (
        "хлорофилл", "биомасс", "баренцев", "gf/f")), result.formatted_answer[:400]
    assert result.used_context is True  # контекст не переискался


async def test_live_evidence_scores_descending(live_service, sample_text) -> None:
    service = live_service
    await service.add_file(sample_text)

    chunks, _ = await service.get_evidence("метод GF/F", k=3)

    assert chunks
    scores = [c.score for c in chunks]
    assert scores == sorted(scores, reverse=True)
    assert all(c.citation for c in chunks)