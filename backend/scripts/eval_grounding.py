#!/usr/bin/env python3
"""Оценка обоснованности ответов на эталонном наборе (Фаза 10).

Два режима:

* ``--retrieval-only`` — офлайн и быстро: только поиск, метрика «ожидаемый
  факт найден в выдаче». LLM-сводки отключаются (иначе каждый запрос =
  несколько вызовов модели), поэтому режим годится для CI и для проверки
  того, что документ вообще находится;
* по умолчанию — полный цикл: поиск + генерация ответа + сверка с эталоном
  + grounding-проверка сущностей. **Нужен Ollama**, один кейс на CPU считается
  минуты: начинайте с ``--limit 3``.

Метрики (см. app/services/evalset.py):

* ``context_hit_rate``  — доля вопросов, где эталонный факт найден в выдаче;
* ``answer_support_rate`` — доля ответов, содержащих обязательные факты;
* ``forbidden_rate``    — доля ответов с утверждениями, которых нет в документах;
* ``grounded_ratio``    — средняя доля сущностей ответа, найденных в контексте.

Примеры::

    python backend/scripts/eval_grounding.py --retrieval-only
    python backend/scripts/eval_grounding.py --limit 3
    python backend/scripts/eval_grounding.py --retrieval-only \
        --min-context-hit 0.9 --json report.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.services.chunk_store import MemoryChunkStore  # noqa: E402
from app.services.evalset import (  # noqa: E402
    CaseResult,
    check_case,
    load_dataset,
    summarize,
)
from app.services.grounding import check_grounding  # noqa: E402
from app.services.paperqa_service import PaperQA2Service  # noqa: E402
from app.services.pqa_profile import build_pqa_settings  # noqa: E402

DEFAULT_DATASET = Path(__file__).resolve().parent / "eval" / "dataset.json"


async def run(args: argparse.Namespace) -> tuple[int, dict[str, Any] | None]:
    dataset = load_dataset(args.dataset)
    missing = dataset.missing_documents()
    if missing:
        print("Нет документов эталона:", ", ".join(missing), file=sys.stderr)
        return 2, None

    # Поиск без LLM-сводок: быстрый и офлайновый (SPICE_REPORT §3.3).
    pqa_settings = (build_pqa_settings(answer={"evidence_skip_summary": True})
                    if args.retrieval_only else None)
    service = PaperQA2Service(collection="eval", chunk_store=MemoryChunkStore(),
                              pqa_settings=pqa_settings)

    indexed = await service.add_files(dataset.document_paths())
    if indexed.failed:
        print("Не проиндексированы: "
              + ", ".join(path for path, _ in indexed.failed), file=sys.stderr)
        return 2, None
    if not indexed.added:
        print("Ни один документ не проиндексирован", file=sys.stderr)
        return 2, None

    cases = dataset.cases[: args.limit] if args.limit else dataset.cases
    mode = "поиск" if args.retrieval_only else "поиск + ответ LLM"
    print(f"Режим: {mode} | документов: {len(indexed.added)} | "
          f"вопросов: {len(cases)}")

    results: list[CaseResult] = []
    for case in cases:
        started = time.perf_counter()
        chunks, session = await service.get_evidence(case.question,
                                                     k=args.k or None)
        contexts = [chunk.text for chunk in chunks]

        answer = ""
        grounding: dict[str, Any] | None = None
        if not args.retrieval_only:
            produced = await service.ask(session, evidence=chunks)
            answer = produced.formatted_answer
            grounding = check_grounding(answer, contexts).to_dict()

        result = check_case(case, contexts, answer, grounding)
        result.seconds = time.perf_counter() - started
        results.append(result)

        status = "ok " if result.context_ok and result.clean else "FAIL"
        checked = len(result.context_hit) + len(result.context_miss)
        detail = [f"контекст {len(result.context_hit)}/{checked}"]
        if grounding is not None:
            detail.append(f"обоснованность {grounding['ratio']}")
            detail.append(f"без источника {len(grounding['ungrounded'])}")
        if result.answer_miss:
            detail.append(f"нет фактов: {', '.join(result.answer_miss)}")
        if result.forbidden_found:
            detail.append(f"ВЫДУМКА: {', '.join(result.forbidden_found)}")
        print(f"  [{status}] {case.id}: {case.question} — {'; '.join(detail)}")
        if args.verbose and answer:
            print("      " + answer.replace("\n", " ")[:400])

    summary = summarize(results)
    print("\nИтог:")
    for key, value in summary.items():
        print(f"  {key}: {value}")

    payload: dict[str, Any] | None = None
    if args.json:
        # запись файла — в main(): блокирующий ввод-вывод в async не пишем
        payload = {"mode": mode, "summary": summary,
                   "results": [r.to_dict() for r in results]}

    return _check_thresholds(summary, args), payload


def _check_thresholds(summary: dict[str, Any], args: argparse.Namespace) -> int:
    """Пороги для CI: не выполнены — ненулевой код выхода."""
    problems: list[str] = []
    checks = (
        ("min_context_hit", "context_hit_rate"),
        ("min_answer_support", "answer_support_rate"),
        ("min_grounded", "grounded_ratio"),
    )
    for arg_name, metric in checks:
        threshold = getattr(args, arg_name)
        value = summary.get(metric)
        if threshold is not None and value is not None and value < threshold:
            problems.append(f"{metric}={value} < {threshold}")
    if problems:
        print("\nПороги не выполнены: " + "; ".join(problems), file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Эталон обоснованности ответов (Фаза 10)")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET,
                        help="путь к dataset.json")
    parser.add_argument("--retrieval-only", action="store_true",
                        help="только поиск, без LLM (офлайн и быстро)")
    parser.add_argument("--limit", type=int, default=0,
                        help="сколько вопросов считать (0 = все)")
    parser.add_argument("--k", type=int, default=0,
                        help="сколько контекстов брать на вопрос (0 = из конфига)")
    parser.add_argument("--json", type=Path, help="куда записать отчёт JSON")
    parser.add_argument("--verbose", action="store_true",
                        help="печатать тексты ответов")
    parser.add_argument("--min-context-hit", type=float, default=None,
                        help="порог context_hit_rate для CI")
    parser.add_argument("--min-answer-support", type=float, default=None,
                        help="порог answer_support_rate для CI")
    parser.add_argument("--min-grounded", type=float, default=None,
                        help="порог grounded_ratio для CI")
    args = parser.parse_args()
    code, payload = asyncio.run(run(args))
    if payload is not None and args.json:
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        print(f"Отчёт: {args.json}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
