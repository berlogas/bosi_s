"""Spike 05 — альтернатива эмбеддингам: локальные sentence-transformers вместо Ollama.

Проверяет:
  * установку paper-qa[local] -> Settings(embedding="st-multi-qa-MiniLM-L6-cos-v1")
  * скорость эмбеддинга на CPU (документ 25 страниц -> ~20-40 чанков)
  * корректность aget_evidence с локальными эмбеддингами
  * поддержку кириллицы (русские чанки)

Запуск: PYTHONIOENCODING=utf-8 .venv/Scripts/python spikes/05_st_embed_bench.py
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from paperqa import Docs, Settings
from paperqa.settings import MultimodalOptions

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
PQA_HOME = ROOT / ".spike_pqa_home"
PQA_HOME.mkdir(exist_ok=True)

MODEL = "ollama/qwen2.5:3b"
OLLAMA_BASE = "http://localhost:11434"
ST_MODEL = "st-multi-qa-MiniLM-L6-cos-v1"
QUERY = "Какие методы измерения биомассы используются?"

llm_config = {
    "model_list": [
        {"model_name": MODEL, "litellm_params": {"model": MODEL, "api_base": OLLAMA_BASE}}
    ]
}


def make_settings(chunk_chars: int = 4000) -> Settings:
    return Settings(
        llm=MODEL,
        llm_config=llm_config,
        summary_llm=MODEL,
        summary_llm_config=llm_config,
        embedding=ST_MODEL,  # локальный sentence-transformers, без сети и без Ollama
        parsing={
            "use_doc_details": False,
            "multimodal": MultimodalOptions.OFF,
            "reader_config": {"chunk_chars": chunk_chars, "overlap": 200},
        },
        answer={"evidence_k": 4, "answer_max_sources": 3, "answer_length": "about 150 words"},
        agent={"agent_llm": MODEL, "agent_llm_config": llm_config},
    )


def log(*a: object) -> None:
    print(*a, flush=True)


async def main() -> None:
    log("=== SPike 05 | sentence-transformers embeddings (CPU) ===")
    log(f"ST model: {ST_MODEL}")

    settings = make_settings()
    log(f"settings.md5={settings.md5}")

    docs = Docs()
    timings: dict[str, float] = {}

    for path, docname in (
        (FIXTURES / "notes" / "biomass.md", "biomass_notes"),
        (FIXTURES / "data" / "biomass_barents_2024.csv", "biomass_data_2024"),
        (FIXTURES / "papers" / "PaperQA2.pdf", "paperqa2_arxiv"),
    ):
        t0 = time.perf_counter()
        name = await docs.aadd(str(path), docname=docname, citation=f"{path.name} (spike)",
                              settings=settings)
        dt = time.perf_counter() - t0
        chunks = sum(1 for t in docs.texts if t.doc.docname == docname)
        timings[path.name] = round(dt, 2)
        log(f"[add] {path.name:26s} {dt:7.2f}s docname={name!r} chunks={chunks} "
            f"dims={len(docs.texts[0].embedding) if docs.texts else 0}")

    log(f"\nвсего чанков: {len(docs.texts)}, документов: {len(docs.docs)}")
    log(f"размер эмбеддинга: {len(docs.texts[0].embedding)}")
    log(f"эмбеддинги на CPU: {sum(1 for t in docs.texts if t.embedding)}/{len(docs.texts)}")

    # проверка кириллицы
    cyr = [t for t in docs.texts if any("Ѐ" <= ch <= "ӿ" for ch in t.text)]
    log(f"чанков с кириллицей: {len(cyr)}")
    if cyr:
        log(f"  пример: {cyr[0].text[:120]!r}")

    log("\n[aget_evidence] (summary_llm через Ollama — это отдeльная стоимость)")
    t0 = time.perf_counter()
    session = await docs.aget_evidence(QUERY, settings=settings)
    ev_dt = time.perf_counter() - t0
    log(f"  {ev_dt:.2f}s contexts={len(session.contexts)}")
    for c in sorted(session.contexts, key=lambda c: -c.score):
        log(f"  score={c.score:2d} {c.text.doc.docname:18s} {c.text.name[:34]:34s} {c.context[:80]!r}")

    out = ROOT / "spikes" / "05_st_embed_bench.json"
    out.write_text(json.dumps({
        "st_model": ST_MODEL,
        "add_seconds": timings,
        "total_chunks": len(docs.texts),
        "embedding_dims": len(docs.texts[0].embedding) if docs.texts else 0,
        "chunks_with_cyrillic": len(cyr),
        "evidence_seconds": round(ev_dt, 2),
        "evidence": [
            {"score": c.score, "docname": c.text.doc.docname, "name": c.text.name,
             "summary": c.context}
            for c in session.contexts
        ],
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"\n[saved] {out.relative_to(ROOT)}")
    log("SPike 05 done.")


if __name__ == "__main__":
    asyncio.run(main())