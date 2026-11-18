import asyncio
from unittest.mock import AsyncMock, patch

from paperqa import PQASession, Settings
from paperqa.agents import AnswerResponse
from paperqa.agents.models import AgentStatus

from app.config import get_settings, reset_settings_cache
from app.services.chunk_store import MemoryChunkStore
from app.services.paperqa_service import PaperQA2Service
from app.services.pqa_profile import settings_fingerprint


async def main() -> None:
    reset_settings_cache()
    app_settings = get_settings()
    app_settings = app_settings.model_copy(update={
        "environment": "test", "log_level": "WARNING", "offline_mode": True, "agent_type": "fake",
    })

    store = MemoryChunkStore()
    pqa_settings = Settings(
        llm="ollama/qwen2.5:3b",
        llm_config={"model_list": [{"model_name": "ollama/qwen2.5:3b",
                                   "litellm_params": {"model": "ollama/qwen2.5:3b"}}]},
        embedding="st-multi-qa-MiniLM-L6-cos-v1",
        parsing={"reader_config": {"chunk_chars": 4000, "overlap": 200}},
        answer={"evidence_k": 3, "answer_max_sources": 2, "max_concurrent_requests": 1},
        agent={"agent_type": "fake"},
        parsing__use_doc_details=False,
    )
    service = PaperQA2Service(app_settings, "global", store, pqa_settings=pqa_settings)
    service.fingerprint = settings_fingerprint(pqa_settings)

    fake_session = PQASession(
        question="What is the temperature of the Barents Sea?",
        answer="The barents sea is cold.",
        formatted_answer="The barents sea is cold.",
        contexts=[],
        has_successful_answer=True,
    )
    fake_response = AnswerResponse(
        session=fake_session,
        status=AgentStatus.SUCCESS,
    )

    with patch(
        "app.services.paperqa_service.agent_query", new=AsyncMock(return_value=fake_response)
    ) as mock_agent_query:
        result = await service.agent_ask("What is the temperature of the Barents Sea?")

    print("question:", result.question)
    print("answer:", result.answer[:200])
    print("citations:", result.citations)
    print("agent_status:", result.agent_status)
    print("has_successful_answer:", result.has_successful_answer)
    print("seconds:", result.seconds)
    print("agent_query called:", mock_agent_query.call_count)

    assert result.agent_status == "success"
    assert result.question == "What is the temperature of the Barents Sea?"
    assert result.answer == "The barents sea is cold."
    assert result.mode == "agent"
    assert mock_agent_query.call_count == 1
    print("SMOKE OK")


asyncio.run(main())
