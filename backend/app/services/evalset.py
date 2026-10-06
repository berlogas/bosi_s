"""Эталонный набор вопросов и метрики обоснованности (Фаза 10).

Оценка RAG не сводится к «ответ звучит убедительно»: нужен набор вопросов
с заранее известными фактами, по которому считается,

* **context_hit** — найден ли ожидаемый факт в выдаче (качество поиска);
* **answer_support** — попал ли факт в сам ответ (качество генерации);
* **forbidden** — не появилось ли в ответе утверждения, которого нет ни в
  одном документе (громкая ловушка галлюцинаций);
* **grounded_ratio** — доля сущностей ответа, найденных в контексте
  (см. :mod:`app.services.grounding`).

Модуль чистый: ни LLM, ни сети, ни БД — поэтому метрики тестируются
юнит-тестами, а сам прогон живёт в ``backend/scripts/eval_grounding.py``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.services.grounding import normalize_text


@dataclass(frozen=True)
class EvalDocument:
    """Документ эталона; путь — относительно каталога датасета."""

    id: str
    path: str

    def resolve(self, root: Path) -> Path:
        return (root / self.path).resolve()


@dataclass(frozen=True)
class EvalCase:
    """Один вопрос: что обязан быть в выдаче, в ответе и чего не должно быть."""

    id: str
    question: str
    expect_in_context: tuple[str, ...] = ()
    expect_in_answer: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()


@dataclass
class EvalDataset:
    path: Path
    version: int
    documents: tuple[EvalDocument, ...] = ()
    cases: tuple[EvalCase, ...] = ()

    @property
    def root(self) -> Path:
        return self.path.parent

    def document_paths(self) -> list[Path]:
        return [doc.resolve(self.root) for doc in self.documents]

    def missing_documents(self) -> list[str]:
        return [str(doc.resolve(self.root)) for doc in self.documents
                if not doc.resolve(self.root).exists()]


def load_dataset(path: str | Path) -> EvalDataset:
    """Прочитать и провалидировать датасет (ошибка -> исключение)."""
    dataset_path = Path(path).resolve()
    raw = json.loads(dataset_path.read_text(encoding="utf-8"))
    documents = tuple(EvalDocument(id=str(doc["id"]), path=str(doc["path"]))
                      for doc in raw.get("documents") or [])
    cases: list[EvalCase] = []
    seen: set[str] = set()
    for item in raw.get("cases") or []:
        case = EvalCase(
            id=str(item["id"]),
            question=str(item["question"]).strip(),
            expect_in_context=tuple(item.get("expect_in_context") or ()),
            expect_in_answer=tuple(item.get("expect_in_answer") or ()),
            forbidden=tuple(item.get("forbidden") or ()),
        )
        if not case.question:
            raise ValueError(f"кейс {case.id}: пустой вопрос")
        if case.id in seen:
            raise ValueError(f"дублирующийся id кейса: {case.id}")
        seen.add(case.id)
        cases.append(case)
    if not cases:
        raise ValueError("датасет пуст: нужен хотя бы один вопрос")
    if not documents:
        raise ValueError("в датасете нет документов")
    return EvalDataset(path=dataset_path, version=int(raw.get("version") or 1),
                       documents=documents, cases=tuple(cases))


def contains(text: str, snippet: str) -> bool:
    """Нормализованное вхождение `snippet` в `text` (регистр, ё, пунктуация)."""
    needle = normalize_text(snippet).strip()
    return bool(needle) and needle in normalize_text(text)


@dataclass
class CaseResult:
    """Результат одного вопроса — строки для отчёта и агрегации."""

    case_id: str
    question: str
    context_hit: list[str] = field(default_factory=list)
    context_miss: list[str] = field(default_factory=list)
    answer_found: list[str] = field(default_factory=list)
    answer_miss: list[str] = field(default_factory=list)
    forbidden_found: list[str] = field(default_factory=list)
    grounding: dict[str, Any] | None = None
    answer: str = ""
    seconds: float = 0.0

    @property
    def context_ok(self) -> bool:
        """Все ожидаемые фрагменты найдены в выдаче."""
        return not self.context_miss

    @property
    def answer_ok(self) -> bool:
        """Все эталонные факты ответа присутствуют (или их не задано)."""
        return not self.answer_miss

    @property
    def clean(self) -> bool:
        """В ответе нет запрещённых утверждений и не хватает фактов."""
        return not self.forbidden_found and self.answer_ok

    @property
    def grounded_ok(self) -> bool:
        return bool(self.grounding) and bool(self.grounding.get("ok", True))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.case_id,
            "question": self.question,
            "context_ok": self.context_ok,
            "context_miss": list(self.context_miss),
            "answer_ok": self.answer_ok,
            "answer_miss": list(self.answer_miss),
            "forbidden_found": list(self.forbidden_found),
            "grounding": self.grounding,
            "seconds": round(self.seconds, 2),
            "answer": self.answer,
        }


def check_case(case: EvalCase, contexts: list[str], answer: str = "",
               grounding: dict[str, Any] | None = None) -> CaseResult:
    """Сверить один кейс с выдачей, ответом и отчётом grounding."""
    result = CaseResult(case_id=case.id, question=case.question,
                        grounding=grounding, answer=answer)
    haystack = "\n".join(contexts)
    for snippet in case.expect_in_context:
        (result.context_hit if contains(haystack, snippet)
         else result.context_miss).append(snippet)
    if answer:
        # ответа ещё нет (режим --retrieval-only) — нечего сверять
        for snippet in case.expect_in_answer:
            (result.answer_found if contains(answer, snippet)
             else result.answer_miss).append(snippet)
        for snippet in case.forbidden:
            if contains(answer, snippet):
                result.forbidden_found.append(snippet)
    return result


def summarize(results: list[CaseResult]) -> dict[str, Any]:
    """Свести результаты к метрикам для отчёта и порогов CI."""
    total = len(results)
    if not total:
        return {"cases": 0}

    with_expected_answer = [r for r in results if r.answer_miss or r.answer_found]
    with_grounding = [r for r in results if r.grounding is not None]
    ratios = [float(r.grounding.get("ratio", 1.0)) for r in with_grounding]

    return {
        "cases": total,
        "context_hit_rate": round(
            sum(1 for r in results if r.context_ok) / total, 3),
        "answer_support_rate": (
            round(sum(1 for r in with_expected_answer if r.answer_ok)
                  / len(with_expected_answer), 3)
            if with_expected_answer else None),
        "forbidden_rate": round(
            sum(1 for r in results if r.forbidden_found) / total, 3),
        "grounded_ratio": (
            round(sum(ratios) / len(ratios), 3) if ratios else None),
        "grounding_failures": (
            sum(1 for r in with_grounding if not r.grounded_ok)
            if with_grounding else 0),
        "seconds": round(sum(r.seconds for r in results), 1),
    }
