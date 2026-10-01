"""Spike 02 — end-to-end PaperQA2 на локальном Ollama (CPU) + локальные эмбеддинги.

Конфигурация, отобранная по результатам спайков 04/05:
  * embedding = "st-multi-qa-MiniLM-L6-cos-v1"  (sentence-transformers локально;
    эмбеддинги через Ollama давали 10m42s на PDF и HTTP 400 на русском тексте >3.8k символов)
  * llm = ollama/qwen2.5:3b (8.6 ток/с на CPU), summary_llm = тот же
  * litellm timeout = 3600 (дефолтные 60с не проходят)
  * parsing.use_doc_details = False (офлайн), multimodal = OFF
  * reader_config: chunk_chars=4000, overlap=200

Запуск:
  PYTHONIOENCODING=utf-8 .venv/Scripts/python spikes/02_e2e_ollama.py [model] [evidence_k]
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
EVIDENCE_K = int(sys.argv[2]) if len(sys.argv) > 2 else 4
OLLAMA_BASE = "http://localhost:11434"
ST_MODEL = "st-multi-qa-MiniLM-L6-cos-v1"

llm_config = {
    "model_list": [
        {
            "model_name": MODEL,
            "litellm_params": {
                "model": MODEL,
                "api_base": OLLAMA_BASE,
                "timeout": 3600,
                "max_retries": 2,
            },
        }
    ]
}


def make_settings() -> Settings:
    return Settings(
        llm=MODEL,
        llm_config=llm_config,
        summary_llm=MODEL,
        summary_llm_config=llm_config,
        embedding=ST_MODEL,
        temperature=0.0,
        answer={
            "evidence_k": EVIDENCE_K,
            "answer_max_sources": 3,
            "answer_length": "about 150 words",
        },
        parsing={
            "use_doc_details": False,
            "multimodal": MultimodalOptions.OFF,
            "reader_config": {"chunk_chars": 4000, "overlap": 200},
        },
        agent={"agent_llm": MODEL, "agent_llm_config": llm_config, "timeout": 3600},
    )


def log(*a: object) -> None:
    print(*a, flush=True)


async def main() -> None:  # noqa: PLR0915
    settings = make_settings()
    log(f"=== SPike 02 | model={MODEL} evidence_k={EVIDENCE_K} embed={ST_MODEL} ===")
    log(f"PQA_HOME={PQA_HOME} settings.md5={settings.md5}\n")

    docs = Docs()
    index_times: dict[str, float] = {}

    for path, docname in (
        (FIXTURES / "notes" / "biomass.md", "biomass_notes"),
        (FIXTURES / "data" / "biomass_barents_2024.csv", "biomass_data_2024"),
        (FIXTURES / "papers" / "PaperQA2.pdf", "paperqa2_arxiv"),
    ):
        t0 = time.perf_counter()
        try:
            returned = await docs.aadd(
                str(path), docname=docname,
                citation=f"{path.name} (спайк boasi_s)", settings=settings,
            )
            dt = time.perf_counter() - t0
            index_times[path.name] = round(dt, 2)
            doc = next(d for d in docs.docs.values() if d.docname == docname)
            log(f"[add] {path.name:26s} {dt:6.2f}s docname={returned!r} "
                f"dockey={str(doc.dockey)[:10]} "
                f"chunks={sum(1 for t in docs.texts if t.doc.dockey == doc.dockey)}")
        except Exception as exc:  # noqa: BLE001
            log(f"[add] {path.name:26s} FAILED {time.perf_counter() - t0:.2f}s "
                f"{type(exc).__name__}: {exc}")

    log(f"\nDocs: docs={len(docs.docs)} texts={len(docs.texts)} "
        f"dims={len(docs.texts[0].embedding) if docs.texts else 0} "
        f"with_embeddings={sum(1 for t in docs.texts if t.embedding)}\n")

    query = "Какие методы измерения биомассы водорослей используются в Баренцевом море?"

    log(f"=== aget_evidence: {query} ===")
    t0 = time.perf_counter()
    session = await docs.aget_evidence(query, settings=settings)
    ev_dt = time.perf_counter() - t0
    log(f"evidence_time={ev_dt:.2f}s contexts={len(session.contexts)}")
    for c in sorted(session.contexts, key=lambda c: -c.score):
        log(f"  score={c.score:2d} {c.text.doc.docname:18s} {c.text.name[:30]:30s} {c.context[:100]!r}")
    log("")

    log("=== aquery ===")
    t0 = time.perf_counter()
    result = await docs.aquery(query, settings=settings)
    q_dt = time.perf_counter() - t0
    log(f"query_time={q_dt:.2f}s has_successful_answer={result.has_successful_answer} "
        f"cost={result.cost:.4f} token_counts={result.token_counts}")
    log(f"--- formatted_answer ---\n{result.formatted_answer}")
    log(f"--- references ---\n{result.references}")
    log(f"unique_docs={[d.docname for d in result.get_unique_docs_from_contexts()]}")
    for i, c in enumerate(result.contexts, 1):
        log(f"  [{i}] score={c.score} {c.text.doc.docname} page/name={c.text.name}")

    (ROOT / "spikes" / "02_result.json").write_text(json.dumps({
        "model": MODEL, "embedding": ST_MODEL, "evidence_k": EVIDENCE_K,
        "settings_md5": settings.md5, "index_seconds": index_times,
        "evidence_seconds": round(ev_dt, 2), "query_seconds": round(q_dt, 2),
        "question": query, "answer": result.answer,
        "formatted_answer": result.formatted_answer, "references": result.references,
        "has_successful_answer": result.has_successful_answer, "cost": result.cost,
        "token_counts": result.token_counts,
        "contexts": [{"score": c.score, "docname": c.text.doc.docname,
                      "citation": c.text.doc.citation, "name": c.text.name,
                      "chunk_head": c.text.text[:200], "summary": c.context}
                     for c in result.contexts],
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    log("\n[saved] spikes/02_result.json")

    log("=== delete / clear_docs ===")
    r = docs.delete(docname="biomass_notes")
    log(f"delete(docname='biomass_notes') -> {r!r}; docs={len(docs.docs)} texts={len(docs.texts)}")
    dockey = next(iter(docs.docs))
    r2 = docs.delete(dockey=dockey)
    log(f"delete(dockey) -> {r2!r}; docs={len(docs.docs)}")
    docs.clear_docs()
    log(f"clear_docs() -> docs={len(docs.docs)} texts={len(docs.texts)}")
    log("SPike 02 done.")


if __name__ == "__main__":
    asyncio.run(main())