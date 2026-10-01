"""Spike 07 — локализация ответов (русский язык) и «дешёвые» профили настроек.

Уроки спайка 06: prompts.pre / prompts.post — это ДОПОЛНИТЕЛЬНЫЕ вызовы LLM
(подсказка/пост-обработка), а не префикс системного промпта. Поэтому локализацию
делаем через prompts.system и prompts.qa.

Варианты:
  A) prompts.system = дефолт + требование отвечать по-русски
  B) prompts.qa      = дефолтный шаблон + инструкция внутри user-сообщения
  C) bundled-профиль "fast" из paperqa (проверяем, есть ли он и что он меняет)

Запуск: PYTHONIOENCODING=utf-8 .venv/Scripts/python spikes/07_localization.py [model]
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from paperqa import Docs, Settings
from paperqa.settings import MultimodalOptions, PromptSettings

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
PQA_HOME = ROOT / ".spike_pqa_home"
PQA_HOME.mkdir(exist_ok=True)

MODEL = sys.argv[1] if len(sys.argv) > 1 else "ollama/qwen2.5:3b"
OLLAMA_BASE = "http://localhost:11434"
ST_MODEL = "st-multi-qa-MiniLM-L6-cos-v1"
QUERY = "Какие методы измерения биомассы водорослей используются в Баренцевом море?"

RU_RULE = (
    "LANGUAGE REQUIREMENT (обязательно): отвечай ТОЛЬКО на русском языке. "
    "Не переводи и не перефразируй названия географических объектов, приборов, методов "
    "и аббревиатуры: «Баренцево море», «CTD-зонд», «хлорофилл-а», «GF/F», «потеря сухого вещества». "
    "Каждое утверждение снабжай ключом источника из контекста."
)

DEFAULT_SYSTEM = PromptSettings().system
DEFAULT_QA = PromptSettings().qa

report: dict[str, object] = {"default_system": DEFAULT_SYSTEM, "default_qa_len": len(DEFAULT_QA)}


def log(*a: object) -> None:
    print(*a, flush=True)


def base_settings(**over) -> Settings:
    # ВАЖНО: только legacy-форма model_list. Каноническая {"models": [...]}
    # перезаписывается валидатором paperqa (LiteLLMModel(name=..., config=...))
    # -> теряются timeout/api_base (падает обратно на 60s и дефолтный хост).
    llm_config = {
        "model_list": [
            {
                "model_name": MODEL,
                "litellm_params": {
                    "model": MODEL,
                    "api_base": OLLAMA_BASE,
                    "timeout": 3600,
                    "max_retries": 2,
                    "temperature": 0.0,
                },
            }
        ]
    }
    kw = dict(
        llm=MODEL,
        llm_config=llm_config,
        summary_llm=MODEL,
        summary_llm_config=llm_config,
        embedding=ST_MODEL,
        temperature=0.0,
        parsing={"use_doc_details": False, "multimodal": MultimodalOptions.OFF,
                 "reader_config": {"chunk_chars": 4000, "overlap": 200}},
        answer={"evidence_k": 4, "answer_max_sources": 3, "answer_length": "about 150 words"},
        agent={"agent_llm": MODEL, "agent_llm_config": llm_config, "timeout": 3600},
    )
    kw.update(over)
    return Settings(**kw)


def fresh(session):
    copied = session.model_copy(deep=True)
    copied.answer = ""
    copied.raw_answer = ""
    copied.formatted_answer = ""
    copied.references = ""
    return copied


async def main() -> None:  # noqa: PLR0915
    log(f"=== SPike 07 | локализация | model={MODEL} ===")

    settings = base_settings()
    docs = Docs()
    for path, docname in (
        (FIXTURES / "notes" / "biomass.md", "biomass_notes"),
        (FIXTURES / "data" / "biomass_barents_2024.csv", "biomass_data_2024"),
        (FIXTURES / "papers" / "PaperQA2.pdf", "paperqa2_arxiv"),
    ):
        await docs.aadd(str(path), docname=docname, citation=f"{path.name} (спайк)",
                        settings=settings)
    log(f"Docs: chunks={len(docs.texts)}")

    log("\n[evidence] один раз, переиспользуется всеми вариантами")
    t0 = time.perf_counter()
    session = await docs.aget_evidence(QUERY, settings=settings)
    log(f"  {time.perf_counter() - t0:.1f}s contexts={len(session.contexts)}")
    report["evidence_seconds"] = round(time.perf_counter() - t0, 1)

    # --- A: system ---
    log("\n[A] prompts.system = дефолт + правило языка")
    s_a = base_settings(prompts={"system": DEFAULT_SYSTEM + "\n\n" + RU_RULE})
    t0 = time.perf_counter()
    a = await docs.aquery(fresh(session), settings=s_a)
    log(f"  {time.perf_counter() - t0:.1f}s")
    log(f"  {a.formatted_answer[:700]}")
    report["variant_a_system"] = {"seconds": round(time.perf_counter() - t0, 1),
                                 "answer": a.formatted_answer}

    # --- B: qa ---
    log("\n[B] prompts.qa = дефолт + правило языка в конце user-сообщения")
    s_b = base_settings(prompts={"qa": DEFAULT_QA + "\n\n" + RU_RULE})
    t0 = time.perf_counter()
    b = await docs.aquery(fresh(session), settings=s_b)
    log(f"  {time.perf_counter() - t0:.1f}s")
    log(f"  {b.formatted_answer[:700]}")
    report["variant_b_qa"] = {"seconds": round(time.perf_counter() - t0, 1),
                              "answer": b.formatted_answer}

    # --- C: bundled fast profile ---
    log("\n[C] bundled-профиль 'fast' из paperqa (Settings.from_name)")
    try:
        from paperqa.settings import get_settings

        fast = get_settings("fast")
        log(f"  fast: evidence_k={fast.answer.evidence_k} "
            f"summary_len={fast.answer.evidence_summary_length!r} "
            f"answer_len={fast.answer.answer_length!r} agent={fast.agent.agent_type} "
            f"use_json={fast.prompts.use_json}")
        report["fast_profile"] = fast.model_dump(mode="json")

        # мержим с нашими LLM/embedding настройками
        fast.llm = settings.llm
        fast.llm_config = settings.llm_config
        fast.summary_llm = settings.summary_llm
        fast.summary_llm_config = settings.summary_llm_config
        fast.embedding = settings.embedding
        fast.parsing.multimodal = MultimodalOptions.OFF
        fast.parsing.reader_config = settings.parsing.reader_config
        fast.prompts.system = DEFAULT_SYSTEM + "\n\n" + RU_RULE

        t0 = time.perf_counter()
        fast_session = await docs.aget_evidence(QUERY, settings=fast)
        fast_ev = time.perf_counter() - t0
        t0 = time.perf_counter()
        fast_answer = await docs.aquery(fast_session, settings=fast)
        fast_ans = time.perf_counter() - t0
        log(f"  fast: evidence={fast_ev:.1f}s answer={fast_ans:.1f}s total={fast_ev + fast_ans:.1f}s "
            f"(vs high_quality ~{report['evidence_seconds']}s + ~120s)")
        log(f"  {fast_answer.formatted_answer[:700]}")
        report["fast_run"] = {
            "evidence_seconds": round(fast_ev, 1),
            "answer_seconds": round(fast_ans, 1),
            "answer": fast_answer.formatted_answer,
        }
    except Exception as exc:  # noqa: BLE001
        log(f"  fast profile не сработал: {type(exc).__name__}: {exc}")
        report["fast_error"] = f"{type(exc).__name__}: {exc}"

    out = ROOT / "spikes" / "07_localization.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    log(f"\n[saved] {out.relative_to(ROOT)}")
    log("SPike 07 done.")


if __name__ == "__main__":
    asyncio.run(main())