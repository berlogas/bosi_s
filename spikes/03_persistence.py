"""Spike 03 — персистентность состояния Docs (ключевое требование ТЗ) + краевые случаи API.

Проверяет:
  * Docs -> pickle / model_dump -> новый Docs (через add_texts) -> те же Context.score
  * aadd_file(BinaryIO) — загрузка без временных файлов (нужно для upload-эндпоинта)
  * delete(docname=) и delete(dockey=), повторный delete (bool строим сами)
  * повторный aadd того же файла (дедуп по dockey?)
  * clear_docs()
  * cyrillic-чанки не теряются при dump/restore

Запуск: PYTHONIOENCODING=utf-8 .venv/Scripts/python spikes/03_persistence.py
"""

from __future__ import annotations

import asyncio
import io
import json
import pickle
import time
from pathlib import Path

from paperqa import Docs, Settings
from paperqa.settings import MultimodalOptions

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
PQA_HOME = ROOT / ".spike_pqa_home"
PQA_HOME.mkdir(exist_ok=True)

MODEL = "ollama/qwen2.5:3b"
ST_MODEL = "st-multi-qa-MiniLM-L6-cos-v1"
OLLAMA_BASE = "http://localhost:11434"
QUERY = "Какие методы измерения биомассы используются?"

# Каноническая форма LLMConfig (lmi>=1.0): timeout по умолчанию 60s -> не хватает для CPU.
llm_config = {
    "model_list": [
        {
            "model_name": MODEL,
            "litellm_params": {
                "model": MODEL, "api_base": OLLAMA_BASE,
                "timeout": 3600, "max_retries": 2, "temperature": 0.0,
            },
        }
    ]
}

settings = Settings(
    llm=MODEL,
    llm_config=llm_config,
    summary_llm=MODEL,
    summary_llm_config=llm_config,
    embedding=ST_MODEL,
    parsing={"use_doc_details": False, "multimodal": MultimodalOptions.OFF},
    answer={"evidence_k": 4, "answer_max_sources": 3},
)

REPORT: dict[str, object] = {}


def log(*args: object) -> None:
    print(*args, flush=True)


async def main() -> None:  # noqa: PLR0915
    log("=== SPike 03 | persistence & edge cases ===")

    # ---------- 1. aadd_file через BinaryIO (upload) ----------
    log("\n[1] aadd_file(BinaryIO) — upload без temp-файлов")
    raw = (FIXTURES / "notes" / "biomass.md").read_bytes()
    docs = Docs()
    t0 = time.perf_counter()
    try:
        uploaded_name = await docs.aadd_file(
            io.BytesIO(raw), docname="uploaded_notes", citation="upload test"
        )
        log(f"    aadd_file OK: docname={uploaded_name!r} in {time.perf_counter() - t0:.2f}s")
    except Exception as exc:  # noqa: BLE001
        # Известная проблема на Windows: paperqa держит NamedTemporaryFile открытым
        # и пытается открыть тот же путь на чтение -> PermissionError.
        # Обходной путь: сохранить файл самим и использовать aadd(path).
        log(f"    aadd_file FAILED: {type(exc).__name__}: {exc}")
        tmp = ROOT / "spikes" / "_tmp_upload.md"
        tmp.write_bytes(raw)
        uploaded_name = await docs.aadd(
            str(tmp), docname="uploaded_notes", citation="upload test", settings=settings
        )
        tmp.unlink(missing_ok=True)
        log(f"    fallback aadd(path): docname={uploaded_name!r} "
            f"in {time.perf_counter() - t0:.2f}s")
    REPORT["aadd_file_docname"] = uploaded_name

    # ---------- 2. обычный aadd + состояние ----------
    t0 = time.perf_counter()
    name2 = await docs.aadd(
        str(FIXTURES / "data" / "biomass_barents_2024.csv"),
        docname="biomass_data",
        citation="Barents 2024 data",
        settings=settings,
    )
    log(f"[2] aadd(csv) -> {name2!r} in {time.perf_counter() - t0:.2f}s; "
        f"docs={len(docs.docs)} texts={len(docs.texts)}")

    # ---------- 3. evidence baseline ----------
    log("\n[3] baseline aget_evidence на исходном Docs")
    t0 = time.perf_counter()
    base = await docs.aget_evidence(QUERY, settings=settings)
    log(f"    {time.perf_counter() - t0:.2f}s contexts={len(base.contexts)}")
    baseline = sorted(
        [(c.score, c.text.doc.docname, c.text.name) for c in base.contexts], key=lambda x: -x[0]
    )
    for row in baseline:
        log(f"    score={row[0]:2d} {row[1]:18s} {row[2][:36]}")
    REPORT["baseline_evidence"] = baseline

    # ---------- 4. pickle ----------
    log("\n[4] pickle Docs")
    try:
        blob = pickle.dumps(docs)
        log(f"    pickle OK, {len(blob) / 1024:.1f} KiB")
        restored_pickle = pickle.loads(blob)
        log(f"    unpickled: docs={len(restored_pickle.docs)} texts={len(restored_pickle.texts)}")
        pickle_ok = len(restored_pickle.texts) == len(docs.texts)
    except Exception as exc:  # noqa: BLE001
        log(f"    pickle FAILED: {type(exc).__name__}: {exc}")
        pickle_ok = False
    REPORT["pickle_ok"] = pickle_ok

    # ---------- 5. aadd_texts: пересборка с нуля ----------
    log("\n[5] пересборка нового Docs через aadd_texts (эмуляция рестарта процесса)")
    texts = list(docs.texts)
    doc_objs = list(docs.docs.values())
    dump_path = ROOT / "spikes" / "fixture_state.json"
    payload = {
        "texts": [t.model_dump(mode="json") for t in texts],
        "docs": [d.model_dump(mode="json") for d in doc_objs],
    }
    dump_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"    дамп -> {dump_path.name} ({dump_path.stat().st_size / 1024:.1f} KiB), "
        f"texts={len(texts)}")

    from paperqa.types import Doc, Text  # noqa: PLC0415

    docs2 = Docs()
    t0 = time.perf_counter()
    for doc_payload in payload["docs"]:
        doc = Doc.model_validate(doc_payload)
        doc_texts = [Text.model_validate(tp) for tp in payload["texts"] if tp["doc"]["dockey"] == doc_payload["dockey"]]
        added = await docs2.aadd_texts(doc_texts, doc, settings=settings)
        log(f"    aadd_texts({doc.docname}) -> {added} chunks={len(doc_texts)}")
    restore_dt = time.perf_counter() - t0
    log(f"    восстановление за {restore_dt:.3f}s: docs={len(docs2.docs)} texts={len(docs2.texts)}")
    REPORT["restore_seconds"] = round(restore_dt, 3)

    log("\n[6] aget_evidence на восстановленном Docs")
    t0 = time.perf_counter()
    after = await docs2.aget_evidence(QUERY, settings=settings)
    log(f"    {time.perf_counter() - t0:.2f}s contexts={len(after.contexts)}")
    restored = sorted(
        [(c.score, c.text.doc.docname, c.text.name) for c in after.contexts], key=lambda x: -x[0]
    )
    for row in restored:
        log(f"    score={row[0]:2d} {row[1]:18s} {row[2][:36]}")
    same = baseline == restored
    log(f"\n  IDENTICAL evidence after restore: {same}")
    REPORT["identical_after_restore"] = same
    if not same:
        REPORT["restored_evidence"] = restored

    # ---------- 7. delete краевые случаи ----------
    log("\n[7] delete: по docname, по dockey, повторный")
    dockey = next(iter(docs2.docs))
    r1 = docs2.delete(docname="biomass_data")
    log(f"    delete(docname='biomass_data') -> {r1!r}; docs left={sorted(d.docname for d in docs2.docs.values())}")
    r2 = docs2.delete(dockey=dockey)
    log(f"    delete(dockey={str(dockey)[:8]}) -> {r2!r}; docs left={len(docs2.docs)}")
    r3 = docs2.delete(docname="does_not_exist")
    log(f"    delete(missing) -> {r3!r} (без исключения)")
    REPORT["delete_returns"] = [str(r1), str(r2), str(r3)]

    # ---------- 8. повторный add того же файла ----------
    log("\n[8] повторный aadd того же файла (дедуп)")
    docs3 = Docs()
    n1 = await docs3.aadd(str(FIXTURES / "notes" / "biomass.md"), docname="dup", settings=settings)
    n2 = await docs3.aadd(str(FIXTURES / "notes" / "biomass.md"), docname="dup", settings=settings)
    n3 = await docs3.aadd(
        str(FIXTURES / "notes" / "biomass.md"), docname="dup_other", settings=settings
    )
    log(f"    first={n1!r} second={n2!r} third(docname='dup_other')={n3!r} "
        f"docs={len(docs3.docs)} texts={len(docs3.texts)} docnames={sorted(docs3.docnames)}")
    REPORT["duplicate_add"] = {"first": n1, "second": n2, "third": n3, "docs": len(docs3.docs),
                               "texts": len(docs3.texts)}

    # ---------- 9. clear_docs ----------
    log("\n[9] clear_docs")
    docs3.clear_docs()
    log(f"    docs={len(docs3.docs)} texts={len(docs3.texts)} docnames={sorted(docs3.docnames)}")
    REPORT["after_clear"] = {"docs": len(docs3.docs), "texts": len(docs3.texts)}

    out = ROOT / "spikes" / "03_persistence.json"
    out.write_text(json.dumps(REPORT, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    log(f"\n[saved] {out.relative_to(ROOT)}")
    log("SPike 03 done.")


if __name__ == "__main__":
    asyncio.run(main())