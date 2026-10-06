"""Фаза 10 — эталонный набор вопросов и метрики обоснованности.

Датасет живёт в `backend/scripts/eval/dataset.json`, документы — рядом в
`backend/scripts/eval/docs/`. Главный тест здесь — **честность датасета**:
каждый ожидаемый факт обязан реально присутствовать в документах, иначе
метрика context_hit врёт. Остальные тесты — чистая логика сводки.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.evalset import (
    CaseResult,
    EvalCase,
    check_case,
    contains,
    load_dataset,
    summarize,
)

BACKEND = Path(__file__).resolve().parents[1]
DATASET_PATH = BACKEND / "scripts" / "eval" / "dataset.json"


@pytest.fixture(scope="module")
def dataset():
    return load_dataset(DATASET_PATH)


# ------------------------------------------------------------------- датасет
def test_dataset_has_enough_cases(dataset) -> None:
    assert len(dataset.cases) >= 20, "минимум 20 вопросов по условию"
    assert len(dataset.documents) >= 3
    assert dataset.version >= 1


def test_dataset_documents_exist(dataset) -> None:
    assert dataset.missing_documents() == []
    for path in dataset.document_paths():
        assert path.stat().st_size > 100


def test_expected_context_facts_really_in_documents(dataset) -> None:
    corpus = "\n".join(path.read_text(encoding="utf-8")
                       for path in dataset.document_paths())
    missing: list[str] = []
    for case in dataset.cases:
        for snippet in case.expect_in_context:
            if not contains(corpus, snippet):
                missing.append(f"{case.id}: {snippet!r}")
    assert not missing, "факты не найдены в документах: " + ", ".join(missing)


def test_expected_answer_facts_really_in_documents(dataset) -> None:
    corpus = "\n".join(path.read_text(encoding="utf-8")
                       for path in dataset.document_paths())
    missing: list[str] = []
    for case in dataset.cases:
        for snippet in case.expect_in_answer:
            if not contains(corpus, snippet):
                missing.append(f"{case.id}: {snippet!r}")
    assert not missing, "эталонных фактов ответа нет в документах: " + ", ".join(missing)


def test_questions_are_unique_and_non_empty(dataset) -> None:
    ids = [case.id for case in dataset.cases]
    assert len(ids) == len(set(ids))
    questions = [case.question for case in dataset.cases]
    assert all(q.strip() and len(q) > 10 for q in questions)


# ------------------------------------------------------------------ загрузка
def test_load_dataset_rejects_duplicates(tmp_path: Path) -> None:
    import json

    payload = {"version": 1,
               "documents": [{"id": "d", "path": "docs/x.md"}],
               "cases": [{"id": "a", "question": "вопрос?"}]}
    payload["cases"].append(dict(payload["cases"][0]))
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="дублирующийся"):
        load_dataset(path)


def test_load_dataset_rejects_empty_cases(tmp_path: Path) -> None:
    import json

    path = tmp_path / "dataset.json"
    path.write_text(json.dumps({"version": 1,
                                "documents": [{"id": "d", "path": "x.md"}],
                                "cases": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="пуст"):
        load_dataset(path)


# -------------------------------------------------------------------- логика
def test_contains_is_normalized() -> None:
    assert contains("Биомасса 1,85 мг/м3.", "1,85")
    assert contains("методом GF/F", "gf/f")
    assert contains("Фёдорович", "Фёдорович")
    assert not contains("1,85", "2,85")


def test_check_case_counts_hits_misses_and_forbidden() -> None:
    case = EvalCase(id="x", question="Что было в 1762?",
                    expect_in_context=("1762", "1775"),
                    expect_in_answer=("1762", "1796"),
                    forbidden=("Наполеон",))
    contexts = ["В 1762 году произошёл переворот."]
    answer = "В 1762 году переворот устроил Наполеон."

    result = check_case(case, contexts, answer)

    assert result.context_hit == ["1762"]
    assert result.context_miss == ["1775"]
    assert result.answer_found == ["1762"]
    assert result.answer_miss == ["1796"]
    assert result.forbidden_found == ["Наполеон"]
    assert result.context_ok is False
    assert result.answer_ok is False
    assert result.clean is False


def test_check_case_without_answer_skips_answer_checks() -> None:
    case = EvalCase(id="y", question="?", expect_in_answer=("1762",),
                    forbidden=("Наполеон",))

    result = check_case(case, ["контекст"], answer="")

    assert result.answer_ok is True  # ответа ещё нет — нечего ругать
    assert result.forbidden_found == []


def test_summarize_rates() -> None:
    good = CaseResult(case_id="a", question="?")
    good.context_hit = ["1729"]
    good.answer_found = ["1729"]
    good.grounding = {"ok": True, "ratio": 1.0}

    bad = CaseResult(case_id="b", question="?")
    bad.context_miss = ["1775"]
    bad.answer_miss = ["1775"]
    bad.forbidden_found = ["Наполеон"]
    bad.grounding = {"ok": False, "ratio": 0.5}

    summary = summarize([good, bad])

    assert summary["cases"] == 2
    assert summary["context_hit_rate"] == 0.5
    assert summary["answer_support_rate"] == 0.5
    assert summary["forbidden_rate"] == 0.5
    assert summary["grounded_ratio"] == 0.75
    assert summary["grounding_failures"] == 1


def test_summarize_of_empty_results() -> None:
    assert summarize([]) == {"cases": 0}


def test_case_result_serializes() -> None:
    result = CaseResult(case_id="a", question="?", answer="ответ",
                        grounding={"ok": True})

    payload = result.to_dict()

    assert payload["id"] == "a"
    assert payload["answer"] == "ответ"
    assert payload["grounding"] == {"ok": True}
    assert "context_ok" in payload
