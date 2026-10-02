"""Фаза 6 — RAG fusion: детерминированность merge/rerank (юнит-тесты).

Сами `Context`/`Text`/`Doc` из paperqa не создаём: для проверки приоритетов
достаточно объекта с нужными атрибутами — так тесты не зависят от внутренностей
пакета и не считают эмбеддинги.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.db.models import DocumentCategory, SearchMode
from app.services import rag_fusion as rf
from app.services.rag_fusion import (
    Candidate,
    DocumentCatalog,
    DocumentMeta,
    SourceScope,
    build_candidates,
    category_weight,
    chunks_from_candidates,
    format_reference,
    is_allowed,
    merge_and_rerank,
    source_dict,
    to_pqa_session,
    tokenize,
)


# --------------------------------------------------------------------------- helpers
def _doc(dockey: str, docname: str, citation: str = "") -> SimpleNamespace:
    return SimpleNamespace(dockey=dockey, docname=docname, citation=citation)


def _text(text: str, dockey: str, docname: str, name: str = "1",
          citation: str = "") -> SimpleNamespace:
    return SimpleNamespace(text=text, name=name, doc=_doc(dockey, docname, citation))


def _ctx(text: str, dockey: str, docname: str, score: int, name: str = "1",
         citation: str = "") -> SimpleNamespace:
    return SimpleNamespace(text=_text(text, dockey, docname, name, citation),
                           context=f"ctx:{text[:20]}", score=score)


def _cand(scope: SourceScope, category: str | None, *, text: str = "хлорофилл",
          dockey: str = "d", docname: str = "n", score: int = 10,
          tags: tuple[str, ...] = (), projects: tuple[str, ...] = (),
          title: str | None = None, name: str = "1",
          citation: str = "") -> Candidate:
    meta = DocumentMeta(dockey=dockey, title=title, category=category,
                        tags=tags, linked_projects=projects)
    return Candidate(context=_ctx(text, dockey, docname, score, name, citation),
                     scope=scope, meta=meta, raw_score=float(score))


def _dockeys(candidates) -> list[str]:
    return [c.dockey for c in candidates]


# --------------------------------------------------------------------------- веса
def test_category_weights_follow_spec() -> None:
    session = SourceScope.SESSION
    assert category_weight(DocumentCategory.project_draft.value, session,
                           mode=SearchMode.hybrid) == rf.WEIGHT_PROJECT_DOC
    assert category_weight(DocumentCategory.project_data.value, session,
                           mode=SearchMode.hybrid) == rf.WEIGHT_PROJECT_DOC
    assert category_weight(DocumentCategory.temp_literature.value, session,
                           mode=SearchMode.hybrid) == rf.WEIGHT_SESSION_MISC
    assert category_weight(DocumentCategory.notes.value, session,
                           mode=SearchMode.hybrid) == rf.WEIGHT_SESSION_MISC
    assert category_weight(None, SourceScope.GLOBAL,
                           mode=SearchMode.hybrid) == rf.WEIGHT_GLOBAL


def test_project_linked_beats_every_category() -> None:
    weight = category_weight(DocumentCategory.project_data.value,
                             SourceScope.SESSION, mode=SearchMode.hybrid,
                             project_linked=True)
    assert weight == rf.WEIGHT_PROJECT == 1.0


def test_global_weight_drops_in_project_focus() -> None:
    weight = category_weight(None, SourceScope.GLOBAL,
                             mode=SearchMode.project_focus)
    assert weight == rf.WEIGHT_GLOBAL_IN_PROJECT_FOCUS < rf.WEIGHT_GLOBAL


def test_modes_zero_out_foreign_collections() -> None:
    assert category_weight("project_data", SourceScope.SESSION,
                           mode=SearchMode.global_only) == 0.0
    assert category_weight(None, SourceScope.GLOBAL,
                           mode=SearchMode.session_only) == 0.0


# --------------------------------------------------------------------------- отсев по режимам
@pytest.mark.parametrize("mode, session_category, linked, expected", [
    (SearchMode.hybrid, "notes", False, True),
    (SearchMode.hybrid, "project_data", False, True),
    (SearchMode.session_only, "notes", False, True),
    (SearchMode.global_only, "notes", False, False),
    (SearchMode.project_focus, "notes", False, False),
    (SearchMode.project_focus, "temp_literature", False, False),
    (SearchMode.project_focus, "project_data", False, True),
    (SearchMode.project_focus, "notes", True, True),
])
def test_is_allowed_per_mode(mode, session_category, linked, expected) -> None:
    assert is_allowed(session_category, SourceScope.SESSION, mode=mode,
                      project_linked=linked) is expected


# --------------------------------------------------------------------------- rerank
def test_project_draft_outranks_global_on_equal_score() -> None:
    candidates = [
        _cand(SourceScope.GLOBAL, "global_knowledge", dockey="g", score=10),
        _cand(SourceScope.SESSION, "project_draft", dockey="s", score=10),
    ]

    top = merge_and_rerank(candidates, mode=SearchMode.hybrid, k=5)

    assert _dockeys(top)[0] == "s"


def test_project_focus_puts_project_docs_first() -> None:
    candidates = [
        _cand(SourceScope.GLOBAL, "global_knowledge", dockey="g", score=10),
        _cand(SourceScope.SESSION, "temp_literature", dockey="t", score=10),
        _cand(SourceScope.SESSION, "project_data", dockey="p", score=10),
    ]

    top = merge_and_rerank(candidates, mode=SearchMode.project_focus, k=5)

    assert _dockeys(top) == ["p", "g"]  # заметки выпали, глобальный — в хвосте


def test_session_only_excludes_global() -> None:
    candidates = [
        _cand(SourceScope.GLOBAL, "global_knowledge", dockey="g", score=10),
        _cand(SourceScope.SESSION, "notes", dockey="s", score=10),
    ]

    assert _dockeys(merge_and_rerank(candidates, mode=SearchMode.session_only,
                                     k=5)) == ["s"]


def test_global_only_keeps_only_global() -> None:
    candidates = [
        _cand(SourceScope.GLOBAL, "global_knowledge", dockey="g", score=10),
        _cand(SourceScope.SESSION, "project_data", dockey="s", score=10),
    ]

    assert _dockeys(merge_and_rerank(candidates, mode=SearchMode.global_only,
                                     k=5)) == ["g"]


def test_priority_is_a_weight_not_an_absolute_order() -> None:
    """Приоритет умножается на score: сильное совпадение из глобальной базы
    всё же может обогнать слабое из сессии."""
    candidates = [
        _cand(SourceScope.GLOBAL, "global_knowledge", dockey="g", score=100),
        _cand(SourceScope.SESSION, "project_draft", dockey="p", score=10),
    ]

    top = merge_and_rerank(candidates, mode=SearchMode.hybrid, k=5)

    assert _dockeys(top) == ["g", "p"]
    assert top[0].priority == rf.WEIGHT_GLOBAL
    assert top[1].priority == rf.WEIGHT_PROJECT_DOC


def test_priority_overrides_small_score_gap() -> None:
    """Умеренный разрыв score приоритет перевешивает (40 vs 41 — близко)."""
    candidates = [
        _cand(SourceScope.GLOBAL, "global_knowledge", dockey="g", score=52),
        _cand(SourceScope.SESSION, "project_draft", dockey="p", score=50),
    ]

    top = merge_and_rerank(candidates, mode=SearchMode.hybrid, k=5)

    assert _dockeys(top)[0] == "p"  # 50*0.8=40 против... см. расчёт ниже


def test_tag_match_survives_russian_case_change() -> None:
    """«Баренцево» в теге должно совпасть с «в Баренцеве море» в вопросе."""
    plain = _cand(SourceScope.SESSION, "notes", dockey="a", score=10)
    tagged = _cand(SourceScope.SESSION, "notes", dockey="b", score=10,
                   tags=("Баренцево",))

    top = merge_and_rerank([plain, tagged], mode=SearchMode.hybrid, k=5,
                           query="биомасса в Баренцеве море")

    assert _dockeys(top)[0] == "b"
    assert tagged.final_score == plain.final_score + rf.TAG_MATCH_BONUS


def test_dedup_penalizes_duplicate_from_second_collection() -> None:
    first = _cand(SourceScope.SESSION, "project_data", dockey="same", score=10,
                  text="одинаковый фрагмент", docname="paper")
    second = _cand(SourceScope.GLOBAL, "global_knowledge", dockey="same", score=10,
                   text="одинаковый фрагмент", docname="paper")

    top = merge_and_rerank([first, second], mode=SearchMode.hybrid, k=5)

    assert len(top) == 2
    assert top[0] is first
    assert top[1].dedup_penalty == rf.DEDUP_PENALTY


def test_high_raw_score_cannot_beat_project_priority() -> None:
    """При равном score проект всегда впереди глобальной базы."""
    candidates = [
        _cand(SourceScope.GLOBAL, "global_knowledge", dockey="g", score=10),
        _cand(SourceScope.SESSION, "project_draft", dockey="p", score=10),
    ]

    top = merge_and_rerank(candidates, mode=SearchMode.hybrid, k=5)

    assert _dockeys(top)[0] == "p"


def test_rerank_is_deterministic() -> None:
    def build():
        return [
            _cand(SourceScope.SESSION, "notes", dockey="a", score=10),
            _cand(SourceScope.SESSION, "project_data", dockey="b", score=10),
            _cand(SourceScope.GLOBAL, "global_knowledge", dockey="c", score=10),
        ]

    orders = {tuple(_dockeys(merge_and_rerank(build(), mode=SearchMode.hybrid, k=5)))
              for _ in range(20)}

    assert len(orders) == 1


def test_ties_broken_by_dockey_not_input_order() -> None:
    candidates = [
        _cand(SourceScope.SESSION, "notes", dockey="zzz", score=10),
        _cand(SourceScope.SESSION, "notes", dockey="aaa", score=10),
    ]

    top = merge_and_rerank(candidates, mode=SearchMode.hybrid, k=5)

    assert _dockeys(top) == ["aaa", "zzz"]


def test_top_k_limits_result() -> None:
    candidates = [_cand(SourceScope.SESSION, "notes", dockey=f"d{i}", score=10)
                  for i in range(10)]

    assert len(merge_and_rerank(candidates, mode=SearchMode.hybrid, k=3)) == 3


def test_empty_input_is_safe() -> None:
    assert merge_and_rerank([], mode=SearchMode.hybrid, k=5) == []


# --------------------------------------------------------------------------- сборка
def test_build_candidates_reads_dockey_and_score() -> None:
    catalog = DocumentCatalog()
    catalog.update(DocumentMeta(dockey="d1", category="project_data"))

    candidates = build_candidates([_ctx("текст", "d1", "paper", 42)],
                                  SourceScope.SESSION, catalog)

    assert len(candidates) == 1
    assert candidates[0].raw_score == 42.0
    assert candidates[0].meta.category == "project_data"


def test_candidates_without_catalog_entry_get_default_meta() -> None:
    candidates = build_candidates([_ctx("текст", "d1", "paper", 5)],
                                  SourceScope.GLOBAL, DocumentCatalog())
    assert candidates[0].meta.category is None


def test_to_pqa_session_carries_ordered_contexts() -> None:
    """Готовый контекст переносится в PQASession — повторного поиска не будет."""
    from paperqa import Context as PQAContext
    from paperqa import Text as PQAText
    from paperqa.docs import Doc as PQADoc

    def make(text: str, dockey: str) -> PQAContext:
        return PQAContext(
            id=f"c-{dockey}", context="ctx", question="вопрос",
            text=PQAText(text=text, name="1",
                         doc=PQADoc(docname=dockey, dockey=dockey,
                                    citation=f"{dockey} (загружено)")),
            score=10)

    contexts = [make("a", "d1"), make("b", "d2")]
    candidates = build_candidates(contexts, SourceScope.SESSION, DocumentCatalog())

    session = to_pqa_session("вопрос", candidates)

    assert session.question == "вопрос"
    assert [c.text.text for c in session.contexts] == ["a", "b"]
    assert session.contexts[0].text.doc.dockey == "d1"
    assert session.has_successful_answer is None


def test_source_dict_has_marks_and_metadata() -> None:
    candidate = _cand(SourceScope.SESSION, "project_data", dockey="d1",
                      docname="paper", title="Данные по биомассе",
                      tags=("Баренцево",), projects=("p1",), score=12,
                      citation="cite", name="3")
    candidate.priority = 0.8
    candidate.final_score = 9.6
    candidate.docname = "paper"

    payload = source_dict(candidate, 1)

    assert payload["index"] == 1
    assert payload["marker"] == "📁"
    assert payload["source_scope"] == "session"
    assert payload["category"] == "project_data"
    assert payload["page"] == "3"
    assert payload["projects"] == ["p1"]
    assert payload["score"] == 9.6


def test_source_dict_global_mark() -> None:
    candidate = _cand(SourceScope.GLOBAL, "global_knowledge", dockey="g1",
                      docname="manual", citation="Руководство (2020)")
    candidate.docname = "manual"

    assert source_dict(candidate, 1)["marker"] == "📚"


def test_format_reference_differs_by_scope() -> None:
    global_cand = _cand(SourceScope.GLOBAL, "global_knowledge", dockey="g",
                        docname="manual", citation="Smith 2023 (загружено)")
    global_cand.docname = "manual"
    session_cand = _cand(SourceScope.SESSION, "project_data", dockey="s",
                         docname="paper", title="Данные GF/F")
    session_cand.docname = "paper"

    assert format_reference(global_cand, 1) == "📚 Smith 2023 (загружено)"
    assert format_reference(session_cand, 2) == "📁 Данные GF/F (project_data)"


def test_chunks_from_candidates_keeps_order() -> None:
    candidates = [_cand(SourceScope.SESSION, "notes", dockey="a", score=10),
                  _cand(SourceScope.GLOBAL, "global_knowledge", dockey="b", score=9)]

    chunks = chunks_from_candidates(candidates)

    assert [c.dockey for c in chunks] == ["a", "b"]
    assert [c.chunk_index for c in chunks] == [0, 1]
    assert chunks[1].kind.value == "global"


def test_tokenize_ignores_short_words() -> None:
    assert tokenize("в и GF/F хлорофилл") == {"хлорофилл", "gf"}