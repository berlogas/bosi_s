"""Фаза 6 — RAG fusion: детерминированность merge/rerank (юнит-тесты).

Сами `Context`/`Text`/`Doc` из paperqa не создаём: для проверки приоритетов
достаточно объекта с нужными атрибутами — так тесты не зависят от внутренностей
пакета и не считают эмбеддинги.
"""

from __future__ import annotations

import logging
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
from app.services.rag_service import RagFusionService


# --------------------------------------------------------------------------- helpers
def _doc(dockey: str, docname: str, citation: str = "") -> SimpleNamespace:
    return SimpleNamespace(dockey=dockey, docname=docname, citation=citation)


def _text(text: str, dockey: str, docname: str, name: str = "1",
          citation: str = "") -> SimpleNamespace:
    return SimpleNamespace(text=text, name=name, doc=_doc(dockey, docname, citation))


def _ctx(text: str, dockey: str, docname: str, score: float, name: str = "1",
         citation: str = "") -> SimpleNamespace:
    return SimpleNamespace(text=_text(text, dockey, docname, name, citation),
                           context=f"ctx:{text[:20]}", score=score)


def _cand(scope: SourceScope, category: str | None, *, text: str = "хлорофилл",
          dockey: str = "d", docname: str = "n", score: float = 10,
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

    # формат с номером `[n]` — он же ключ к цитатам в тексте ответа
    assert format_reference(global_cand, 1) == "📚 [1] Smith 2023 (загружено)"
    assert format_reference(session_cand, 2) == "📁 [2] Данные GF/F (project_data)"


def test_chunks_from_candidates_keeps_order() -> None:
    candidates = [_cand(SourceScope.SESSION, "notes", dockey="a", score=10),
                  _cand(SourceScope.GLOBAL, "global_knowledge", dockey="b", score=9)]

    chunks = chunks_from_candidates(candidates)

    assert [c.dockey for c in chunks] == ["a", "b"]
    assert [c.chunk_index for c in chunks] == [0, 1]
    assert chunks[1].kind.value == "global"


def test_tokenize_ignores_short_words() -> None:
    assert tokenize("в и GF/F хлорофилл") == {"хлорофилл", "gf"}

# ------------------------------------------------------------------ формат ссылок
def test_reference_from_source_matches_fresh_format() -> None:
    """Ссылка из кэша обязана выглядеть как из свежего ответа: `📁 [n] …`."""
    from app.services.rag_fusion import reference_from_source

    session_source = {"index": 2, "marker": "📁", "source_scope": "session",
                      "title": "Данные GF/F", "category": "project_data",
                      "docname": "biomass", "citation": "biomass (загружено)"}
    global_source = {"index": 1, "marker": "📚", "source_scope": "global",
                     "title": None, "category": None, "docname": "handbook",
                     "citation": "Руководство по CTD"}

    assert reference_from_source(session_source) == "📁 [2] Данные GF/F (project_data)"
    assert reference_from_source(global_source) == "📚 [1] Руководство по CTD"


def test_reference_without_category_says_so() -> None:
    from app.services.rag_fusion import reference_from_source

    source = {"index": 1, "marker": "📁", "source_scope": "session",
              "title": "Заметка", "category": None, "docname": "note"}

    assert reference_from_source(source) == "📁 [1] Заметка (без категории)"


def test_build_reference_keeps_marker_first() -> None:
    """UI-тесты и пользователи читают маркер первым символом."""
    from app.services.rag_fusion import build_reference

    assert build_reference("📁", 3, "Док (data)") == "📁 [3] Док (data)"


def test_min_relevance_drops_candidates_after_merge() -> None:
    """Порог релевантности применяется после слияния коллекций.

    `raw_score` — это косинус, умноженный на 10 (так его проставляет
    rag_service._restore_relevance при отключённых сводках), то есть шкала
    0..10, а `min_relevance` задаётся в шкале 0..1.
    """
    cands = [
        _cand(SourceScope.SESSION, DocumentCategory.temp_literature.value,
              dockey="nap", docname="napoleon", score=8.7),
        _cand(SourceScope.GLOBAL, DocumentCategory.global_knowledge.value,
              dockey="pet", docname="peter", score=8.1),
        _cand(SourceScope.GLOBAL, DocumentCategory.global_knowledge.value,
              dockey="pet2", docname="peter2", score=8.5),
    ]

    # порог отключён — решает только приоритет категории
    assert len(merge_and_rerank(cands, k=10)) == 3

    # порог выше посторонних: остаётся только napoleon, несмотря на вес 0.4
    # у global_knowledge против 0.6 у temp_literature
    kept = merge_and_rerank(cands, k=10, min_relevance=0.86)
    assert _dockeys(kept) == ["nap"]

    # порог ниже всех — ничего не отсекает
    assert len(merge_and_rerank(cands, k=10, min_relevance=0.5)) == 3


def test_max_per_document_limits_chunks_of_one_document() -> None:
    """Длинный документ не должен занимать всю выдачу."""
    cands = [
        _cand(SourceScope.SESSION, DocumentCategory.temp_literature.value,
              dockey="nap", docname="napoleon", name=str(i), score=90 - i)
        for i in range(6)
    ]
    cands.append(_cand(SourceScope.SESSION,
                       DocumentCategory.notes.value,
                       dockey="other", docname="notes", score=50))

    kept = merge_and_rerank(cands, k=10)
    assert _dockeys(kept).count("nap") == rf.MAX_CHUNKS_PER_DOCUMENT
    assert "other" in _dockeys(kept)


# ------------------------------------------------------- перенумерация цитат
def test_renumber_citations_shifts_markers_after_filtering() -> None:
    """После отсева нецитированных источники нумеруются 1..N, а маркеры в тексте
    следуют за ними. Без этого единственный показанный источник вышел бы «[4]».
    """
    from app.services.rag_service import _renumber_citations

    text = "Факт А [4]. Факт Б [7]. Факт В [1]. Вне списка [9]."
    assert _renumber_citations(text, [4, 7]) == (
        "Факт А [1]. Факт Б [2]. Факт В [1]. Вне списка [9].")

    # номера не должны «затирать» друг друга (4→1 при уже существующем 1)
    assert _renumber_citations("[1] и [4]", [1, 2, 4]) == "[1] и [3]"


def test_renumber_citations_handles_multi_source_markers() -> None:
    """citation_guard собирает «[1, 2]», когда модель сослалась на два документа."""
    from app.services.rag_service import _renumber_citations

    assert _renumber_citations("Факт [4, 7].", [4, 7]) == "Факт [1, 2]."
    # неполное совпадение не трогаем: перенумеровывать половину маркера нельзя
    assert _renumber_citations("Факт [4, 9].", [4, 7]) == "Факт [4, 9]."


# ------------------------------------------- удаление дубля списка источников
def test_strip_references_block_removes_paperqa_bibliography() -> None:
    """Блок литературы paperqa дублирует список источников в интерфейсе."""
    from app.services.rag_service import _strip_references_block

    text = "Факт [1].\n\nСсылки\n\n1. [1] doc_a\n\n2. [2] doc_b"
    assert _strip_references_block(text) == "Факт [1].\n"


def test_strip_references_block_keeps_answer_without_bibliography() -> None:
    """Без блока литературы и заголовка в тексте — ничего не трогаем."""
    from app.services.rag_service import _strip_references_block

    for text in ("Факт [1].", "Список источников обсуждается ниже.", ""):
        assert _strip_references_block(text) == text


def test_strip_references_block_does_not_eat_word_in_prose() -> None:
    """Заголовок ищется только как отдельная строка: слово «Ссылки» внутри
    предложения не должно обрезать ответ."""
    from app.services.rag_service import _strip_references_block

    text = "См. ссылки ниже.\n\nИ ещё абзац."
    assert _strip_references_block(text) == text


def test_document_decay_lets_relevant_chunk_outrank_foreign_documents() -> None:
    """Регрессия: вопрос о маршалах Наполеона.

    Нужный третий фрагмент документа (косинус 0.808) проигрывал постороннему
    тексту (0.789), потому что жёсткий предел в 2 фрагмента на документ его
    отбрасывал. Затухание вместо отсечения возвращает его в выдачу.
    """
    session, glob = SourceScope.SESSION, SourceScope.GLOBAL
    nap = DocumentCategory.temp_literature.value
    globcat = DocumentCategory.global_knowledge.value
    cands = [
        _cand(session, nap, dockey="nap", docname="napoleon",
              name="a", score=8.32),
        _cand(session, nap, dockey="nap", docname="napoleon",
              name="b", score=8.22),
        # третий фрагмент того же документа — тот самый вопрос про маршалов
        _cand(session, nap, dockey="nap", docname="napoleon",
              name="c", score=8.08),
        _cand(glob, globcat, dockey="elizabeth", docname="elizabeth",
              score=7.89),
    ]

    kept = _dockeys(merge_and_rerank(cands, k=10, query="маршалы Наполеона"))
    assert kept.count("nap") == 3, "нужный фрагмент не должен теряться"
    # посторонний документ при этом всё равно проигрывает нужному чанку
    assert kept[-1] == "elizabeth"


# --------------------------------------------------------------------------- сбой ветки
class _BrokenService:
    """Коллекция, у которой `get_evidence` падает — как это бывает с моделью."""

    async def get_evidence(self, *args, **kwargs):
        # Ровно то исключение, что приходит изнутри paperqa, когда модель
        # возвращает content не строкой: парсер зовёт re.sub по списку.
        raise TypeError("expected string or bytes-like object, got 'list'")

    async def restore_state(self, *args, **kwargs) -> int:
        return 0

    @staticmethod
    async def embedding_relevance(*args, **kwargs) -> dict:
        return {}


class _GoodService:
    def __init__(self, contexts: list[SimpleNamespace]) -> None:
        self._contexts = contexts

    async def get_evidence(self, *args, **kwargs):
        return [], SimpleNamespace(contexts=self._contexts)

    async def restore_state(self, *args, **kwargs) -> int:
        return 0

    @staticmethod
    async def embedding_relevance(*args, **kwargs) -> dict:
        return {}


def _fusion(global_service, session_service) -> RagFusionService:
    registry = SimpleNamespace(global_service=lambda: global_service,
                                session_service=lambda _sid: session_service)
    return RagFusionService(registry=registry)


@pytest.mark.asyncio
async def test_упавшая_коллекция_не_роняет_остальные() -> None:
    """Одна сломанная ветка не должна обнулять весь поиск.

    Так ведёт себя ошибка внутри paperqa, когда модель отвечает не строкой:
    ветка выпадает целиком, и если бы падение было фатальным, вопрос остался
    бы без источников из-за одного API-вызова.
    """
    # Контекст в форме, которую ждёт build_candidates: `text` — это объект
    # paperqa с вложенным `doc`, а не строка.
    context = SimpleNamespace(
        text=SimpleNamespace(doc=_doc("d1", "doc1"), name="1", text="фрагмент"),
        score=5)
    fusion = _fusion(_BrokenService(), _GoodService([context]))

    candidates = await fusion._evidence_once(
        "запрос", session_id="s-1", mode=SearchMode.hybrid, k=5,
        catalog=DocumentCatalog(), skip_summary=False)

    assert [c.context.text.text for c in candidates] == ["фрагмент"]
    assert [c.scope.value for c in candidates] == ["session"]


@pytest.mark.asyncio
async def test_сбой_логируется_со_стеком(caplog) -> None:
    """Без трассировки видно только текст ошибки — этого мало для разбора."""
    fusion = _fusion(_BrokenService(), _GoodService([]))

    with caplog.at_level(logging.WARNING):
        await fusion._evidence_once(
            "запрос", session_id="s-1", mode=SearchMode.hybrid, k=5,
            catalog=DocumentCatalog(), skip_summary=False)

    assert "aget_evidence" in caplog.text
    assert "expected string or bytes-like object" in caplog.text
