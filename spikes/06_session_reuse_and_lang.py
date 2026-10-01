"""Spike 06 — оптимизация и локализация ответа.

Проверяет:
  1) Docs.aquery(PQASession) с уже собранным evidence -> повторный ретривал НЕ выполняется
     (критично для RAG fusion: иначе каждый запрос платит двойную цену)
  2) русскоязычный ответ через prompts.pre / prompts.post (PaperQA-промпты английские)
  3) влияние prompts.evidence_skip_summary на скорость/качество

Запуск: PYTHONIOENCODING=utf-8 .venv/Scripts/python spikes/06_session_reuse_and_lang.py [model]
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from paperqa import Docs, Settings
from paperqa.settings import MultimodalOptions

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
PQA_HOME = ROOT / ".spike_pqa_home"
PQA_HOME.mkdir(exist_ok=True)

MODEL = sys.argv[1] if len(sys.argv) > 1 else "ollama/qwen2.5:3b"
OLLAMA_BASE = "http://localhost:11434"
ST_MODEL = "st-multi-qa-MiniLM-L6-cos-v1"
QUERY = "Какие методы измерения биомассы водорослей используются в Баренцевом море?"

llm_config = {
    "model_list": [
        {"model_name": MODEL,
         "litellm_params": {"model": MODEL, "api_base": OLLAMA_BASE, "timeout": 3600, "max_retries": 2}}
    ]
}

BASE = dict(
    llm=MODEL, llm_config=llm_config, summary_llm=MODEL, summary_llm_config=llm_config,
    embedding=ST_MODEL, temperature=0.0,
    parsing={"use_doc_details": False, "multimodal": MultimodalOptions.OFF,
             "reader_config": {"chunk_chars": 4000, "overlap": 200}},
    agent={"agent_llm": MODEL, "agent_llm_config": llm_config, "timeout": 3600},
)

RUSSIAN_PRE = (
    "Отвечай ТОЛЬКО на русском языке. Сохраняй без перевода названия географических объектов, "
    "приборов, методов и аббревиатуры (например: «Баренцево море», «CTD-зонд», «хлорофилл-а», "
    "«GF/F»). Не перефразируй названия методов. Всегда ссылайся на источники ключами из контекста."
)
RUSSIAN_POST = "Ответ должен быть полностью на русском языке, с исходными терминами и ссылками [ключ]."

report: dict[str, object] = {}


def log(*a: object) -> None:
    print(*a, flush=True)


async def build_docs(settings: Settings) -> Docs:
    docs = Docs()
    for path, docname in (
        (FIXTURES / "notes" / "biomass.md", "biomass_notes"),
        (FIXTURES / "data" / "biomass_barents_2024.csv", "biomass_data_2024"),
        (FIXTURES / "papers" / "PaperQA2.pdf", "paperqa2_arxiv"),
    ):
        await docs.aadd(str(path), docname=docname, citation=f"{path.name} (спайк boasi_s)",
                        settings=settings)
    log(f"Docs готов: docs={len(docs.docs)} chunks={len(docs.texts)}")
    return docs


def fresh_session(session):
    copied = session.model_copy(deep=True)
    copied.answer = ""
    copied.raw_answer = ""
    copied.formatted_answer = ""
    copied.references = ""
    return copied


async def main() -> None:  # noqa: PLR0915
    log(f"=== SPike 06 | session reuse + локализация | model={MODEL} ===")

    settings_en = Settings(answer={"evidence_k": 4, "answer_max_sources": 3,
                                   "answer_length": "about 150 words"}, **BASE)
    docs = await build_docs(settings_en)

    log("\n[1] aget_evidence (единоразовая стоимость ретривала)")
    t0 = time.perf_counter()
    session = await docs.aget_evidence(QUERY, settings=settings_en)
    ev_dt = time.perf_counter() - t0
    log(f"    {ev_dt:.1f}s contexts={len(session.contexts)} "
        f"scores={[c.score for c in session.contexts]}")
    report["evidence_seconds"] = round(ev_dt, 1)

    log("\n[2] aquery(session) — переиспользование готового evidence (английский дефолт)")
    t0 = time.perf_counter()
    answer_en = await docs.aquery(fresh_session(session), settings=settings_en)
    ans_dt = time.perf_counter() - t0
    log(f"    {ans_dt:.1f}s  (если ~ равно генерации, ретривал не повторяется)")
    log(f"    {answer_en.formatted_answer[:400]}")
    report["answer_only_seconds"] = round(ans_dt, 1)
    report["answer_en"] = answer_en.formatted_answer

    log("\n[3] aquery(session) с русскоязычными pre/post промптами")
    settings_ru = Settings(
        answer={"evidence_k": 4, "answer_max_sources": 3, "answer_length": "about 150 words"},
        prompts={"pre": RUSSIAN_PRE, "post": RUSSIAN_POST},
        **BASE,
    )
    t0 = time.perf_counter()
    answer_ru = await docs.aquery(fresh_session(session), settings=settings_ru)
    ans_ru_dt = time.perf_counter() - t0
    log(f"    {ans_ru_dt:.1f}s")
    log(f"    {answer_ru.formatted_answer}")
    report["answer_ru_seconds"] = round(ans_ru_dt, 1)
    report["answer_ru"] = answer_ru.formatted_answer

    log("\n[4] контроль: evidence_skip_summary=True (скорость vs качество)")
    settings_fast = Settings(
        answer={"evidence_k": 4, "answer_max_sources": 3, "evidence_skip_summary": True,
                "answer_length": "about 150 words"},
        prompts={"pre": RUSSIAN_PRE, "post": RUSSIAN_POST},
        **BASE,
    )
    t0 = time.perf_counter()
    fast_session = await docs.aget_evidence(QUERY, settings=settings_fast)
    fast_ev = time.perf_counter() - t0
    t0 = time.perf_counter()
    fast_answer = await docs.aquery(fast_session, settings=settings_fast)
    fast_ans = time.perf_counter() - t0
    log(f"    evidence={fast_ev:.1f}s answer={fast_ans:.1f}s total={fast_ev + fast_ans:.1f}s "
        f"(vs {ev_dt + ans_dt:.1f}s с RCS)")
    log(f"    {fast_answer.formatted_answer[:400]}")
    report["skip_summary"] = {
        "evidence_seconds": round(fast_ev, 1), "answer_seconds": round(fast_ans, 1),
        "answer": fast_answer.formatted_answer,
    }

    out = ROOT / "spikes" / "06_session_reuse_and_lang.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"\n[saved] {out.relative_to(ROOT)}")
    log("SPike 06 done.")


if __name__ == "__main__":
    asyncio.run(main())