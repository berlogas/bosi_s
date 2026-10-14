"""Фаза 7 — экспорт: Markdown, DOCX, BibTeX, ZIP.

DoD требует, чтобы экспорт открывался в Word, поэтому здесь проверяем не
только байты, но и структуру OOXML-контейнера.
"""

from __future__ import annotations

import io
import re
import zipfile

import pytest

from app.services import export as export_service


def _version(citation_map: list[dict], section_name: str = "",
             content_md: str = "") -> object:
    """Версия проекта: экспорт сопоставляет раздел с версией по тексту."""
    class _V:
        def __init__(self, mapping, name, text):
            self.citation_map = mapping
            self.section_name = name
            self.content_md = text
    return _V(citation_map, section_name, content_md)


def _versions_for(sections, mapping: list[dict]) -> list[object]:
    """По версии на раздел — карта цитат у каждого своя."""
    return [_version(mapping, section["name"], section.get("content_md") or "")
            for section in sections if (section.get("content_md") or "").strip()]




class _Project:
    """Минимальный проект для рендера: экспорт не ходит в БД."""

    def __init__(self, sections, versions=None):
        self.title = "Биомасса водорослей Баренцева моря"
        self.target_journal = "Marine Biology"
        self.status = "drafting"
        self.sections = sections
        self.versions = versions or []


SECTIONS = [
    {"name": "Introduction", "required": True, "order": 1, "word_target": 600,
     "notes": "", "content_md": "Биомасса — ключевой показатель [1]."},
    {"name": "Methods", "required": True, "order": 2, "word_target": 800,
     "notes": "", "content_md": "Отбор проб батернет-граблями [2]."},
    {"name": "Discussion", "required": True, "order": 3, "word_target": 900,
     "notes": "", "content_md": "Наши значения согласуются [1,2]."},
    {"name": "Conclusions", "required": True, "order": 4, "word_target": 300,
     "notes": "", "content_md": ""},
]

CITATIONS = [
    {"index": 1, "source_scope": "global", "marker": "📚", "dockey": "g1",
     "docname": "smith2019", "title": "Smith 2019",
     "citation": "Smith et al. 2019 (загружено пользователем)",
     "category": "global_knowledge"},
    {"index": 2, "source_scope": "session", "marker": "📁", "dockey": "s1",
     "docname": "biomass", "title": "Данные GF/F",
     "citation": "Данные GF/F (загружено пользователем)",
     "category": "project_data"},
]


@pytest.fixture
def project() -> _Project:
    return _Project(SECTIONS, _versions_for(SECTIONS, CITATIONS))


# --------------------------------------------------------------------------- утилиты
def test_strip_citations_removes_markers() -> None:
    stripped = export_service.strip_citations("Факт [1] и [2,3].")
    assert "[1]" not in stripped and "[2" not in stripped
    assert stripped.startswith("Факт")


def test_inline_markdown_detects_emphasis() -> None:
    _, bold, italic = export_service.inline_markdown("**жирный**")
    assert bold and not italic
    _, bold, italic = export_service.inline_markdown("обычный")
    assert not bold and not italic


def test_iter_blocks_splits_headings() -> None:
    blocks = list(export_service._iter_blocks("## Заголовок\n\nабзац\n\n### Под"))
    assert blocks[0] == ("heading", "Заголовок")
    assert blocks[1] == ("paragraph", "абзац")
    assert blocks[2] == ("heading", "Под")


def test_iter_blocks_of_empty_text() -> None:
    assert list(export_service._iter_blocks("")) == []


# --------------------------------------------------------------------------- markdown
def test_markdown_contains_sections_and_references(project: _Project) -> None:
    text = export_service.render_markdown(project)

    assert text.startswith("# Биомасса водорослей Баренцева моря")
    assert "## Introduction" in text
    assert "## Discussion" in text
    assert "## Conclusions" not in text, "пустой раздел не выводится"
    assert "## References" in text
    assert "[1] Smith et al. 2019" in text
    assert "[2] Данные GF/F (project_data)" in text


def test_markdown_marks_global_vs_session(project: _Project) -> None:
    references = export_service.collect_references(project)
    assert references[0].label.startswith("Smith et al. 2019")
    assert "project_data" in references[1].label


def test_markdown_flags_unresolved_reference() -> None:
    sections = [{"name": "Results", "content_md": "Факт [5].", "required": True,
                 "order": 1, "word_target": 500, "notes": ""}]
    project = _Project(sections, [])
    references = export_service.collect_references(project)

    assert "не определён" in references[0].label, "неразрешённая ссылка видна как дефект"


def test_markdown_without_citations_has_no_references(project: _Project) -> None:
    sections = [{"name": "Results", "content_md": "Без ссылок.", "required": True,
                 "order": 1, "word_target": 500, "notes": ""}]
    text = export_service.render_markdown(_Project(sections, []))
    assert "## References" not in text


# --------------------------------------------------------------------------- bibtex
def test_bibtex_article_entry() -> None:
    bib = export_service.to_bibtex([
        {"key": "smith2019", "type": "article", "title": "Biomass",
         "author": "Smith J.", "journal": "Marine Biology", "year": 2019,
         "doi": "10.1/x"},
    ])

    assert bib.startswith("@article{smith2019,")
    assert "author = {Smith J.}" in bib
    assert "journal = {Marine Biology}" in bib
    assert "doi = {10.1/x}" in bib


def test_bibtex_defaults_to_misc() -> None:
    assert export_service.to_bibtex([{"key": "k", "title": "T"}]).startswith("@misc{")


def test_bibtex_of_empty_list() -> None:
    assert export_service.to_bibtex([]) == ""


# --------------------------------------------------------------------------- нумерация
def test_same_document_is_listed_once_across_sections() -> None:
    """Один документ, процитированный в двух разделах, — одна запись.

    Номера `[n]` выдаёт каждая генерация отдельно, поэтому «Данные GF/F»
    в Methods — это [1], а в Results — уже [2]. В списке литературы такой
    источник обязан остаться один, а в тексте оба маркера — превратиться
    в номер этой единственной записи.
    """
    sections = [
        {"name": "Introduction", "required": True, "order": 1, "word_target": 600,
         "notes": "", "content_md": "Общая постановка [1]."},
        {"name": "Methods", "required": True, "order": 2, "word_target": 800,
         "notes": "", "content_md": "Отбор проб батернет-граблями [2]."},
        {"name": "Results", "required": True, "order": 3, "word_target": 700,
         "notes": "", "content_md": "Наши данные [1] и литература [3]."},
    ]
    intro_map = [*CITATIONS[:1], dict(CITATIONS[1], index=3)]
    methods_map = [dict(CITATIONS[1], index=1), dict(CITATIONS[0], index=2)]
    results_map = [dict(CITATIONS[1], index=1),
                   {"index": 3, "source_scope": "global", "marker": "📚",
                    "dockey": "g2", "docname": "brown2020", "title": "Brown 2020",
                    "citation": "Brown et al. 2020 (загружено пользователем)",
                    "category": "global_knowledge"}]
    project = _Project(sections, [
        _version(intro_map, "Introduction", sections[0]["content_md"]),
        _version(methods_map, "Methods", sections[1]["content_md"]),
        _version(results_map, "Results", sections[2]["content_md"]),
    ])

    plan = export_service.plan_citations(project)

    assert [ref.number for ref in plan.references] == [1, 2, 3], "сквозная нумерация без пропусков"
    keys = [ref.key for ref in plan.references]
    assert len(keys) == len(set(keys)), f"дубликаты в списке литературы: {keys}"
    assert keys == ["g1", "s1", "g2"], "порядок — по первому появлению в тексте"
    # маркеры в тексте приведены к тому же списку
    by_name = {section["name"]: section["content_md"] for section in plan.sections}
    assert by_name["Introduction"] == "Общая постановка [1]."
    assert by_name["Methods"] == "Отбор проб батернет-граблями [1]."
    assert by_name["Results"] == "Наши данные [2] и литература [3]."


def test_reference_numbers_are_contiguous() -> None:
    sections = [
        {"name": "Results", "required": True, "order": 1, "word_target": 700,
         "notes": "", "content_md": "Данные [2] подтверждены [3]."},
    ]
    project = _Project(sections, [_version(
        [dict(CITATIONS[1], index=2), dict(CITATIONS[0], index=3)],
        "Results", sections[0]["content_md"])])

    numbers = [ref.number for ref in export_service.collect_references(project)]

    assert numbers == [1, 2], "пропусков в нумерации быть не должно"


def test_markdown_numbers_references_without_gaps(project: _Project) -> None:
    text = export_service.render_markdown(project)

    assert "[1] Smith et al. 2019" in text
    assert "[2] Данные GF/F (project_data)" in text


def test_markers_in_text_resolve_to_the_reference_list() -> None:
    """Главное свойство выгрузки: `[n]` в тексте есть в списке литературы.

    Именно это ломалось на демо-прогоне: карта цитат Discussion знала
    источники 1, 3, 4 и 6, текст ссылался на `[6]`, а сквозной список
    содержал пять записей — шестого номера в нём не было.
    """
    sections = [
        {"name": "Introduction", "required": True, "order": 1, "word_target": 600,
         "notes": "", "content_md": "Постановка [1]."},
        {"name": "Discussion", "required": True, "order": 2, "word_target": 900,
         "notes": "", "content_md": "Расходится [3] и совпадает [6]."},
    ]
    discussion_map = [
        dict(CITATIONS[1], index=1),
        dict(CITATIONS[0], index=3),
        {"index": 6, "source_scope": "session", "marker": "📁", "dockey": "s2",
         "docname": "wassmann", "title": "Wassmann 1998",
         "citation": "Wassmann 1998 (загружено пользователем)",
         "category": "temp_literature"},
    ]
    project = _Project(sections, [
        _version([dict(CITATIONS[0], index=1)], "Introduction",
                 sections[0]["content_md"]),
        _version(discussion_map, "Discussion", sections[1]["content_md"]),
    ])

    text = export_service.render_markdown(project)

    listed = {int(n) for n in re.findall(r"^\[(\d+)\] ", text, re.M)}
    cited = {int(n) for n in re.findall(r"\[(\d+)\]",
                                        text.split("## References")[0])}
    assert cited <= listed, f"ссылки без записи в списке: {sorted(cited - listed)}"
    body = text.split("## Discussion", 1)[1]
    assert "[6]" not in body, "старый номер из карты цитат не должен утекать в текст"


def test_range_marker_is_written_ascending() -> None:
    """Диапазон `[3-5]` после перенумерации не должен стать «[5]–[4]»."""
    rewritten = export_service.rewrite_citations("См. [3-5].", {3: 5, 4: 1, 5: 4})

    assert rewritten == "См. [1, 4, 5]."


def test_bracketed_range_is_treated_as_one_marker() -> None:
    """`[3]–[5]` — это диапазон, а не две ссылки: порядок не должен рваться."""
    sections = [
        {"name": "Results", "required": True, "order": 1, "word_target": 700,
         "notes": "", "content_md": "Источники [3]–[5] вымышленные."},
    ]
    project = _Project(sections, [_version(
        [dict(CITATIONS[1], index=3), dict(CITATIONS[0], index=4),
         {"index": 5, "source_scope": "session", "marker": "📁",
          "dockey": "s2", "docname": "wassmann", "title": "Wassmann 1998",
          "citation": "Wassmann 1998 (загружено пользователем)",
          "category": "temp_literature"}],
        "Results", sections[0]["content_md"])])

    text = export_service.render_markdown(project)

    body = text.split("## Results", 1)[1]
    assert "Источники [1, 2, 3] вымышленные." in body


def test_marker_list_keeps_order_of_appearance() -> None:
    rewritten = export_service.rewrite_citations("См. [2, 3].", {2: 3, 3: 2})

    assert rewritten == "См. [3, 2]."


def test_manual_edit_keeps_numbers_of_the_section() -> None:
    """Правка текста вручную не должна рассогласовать раздел с картой цитат.

    Совпадения по тексту уже нет — версия остаётся последней для раздела,
    и её номера те же, с которыми исследователь работал в интерфейсе.
    """
    sections = [
        {"name": "Results", "required": True, "order": 1, "word_target": 700,
         "notes": "", "content_md": "Наши данные [2] и литература [3]."},
    ]
    project = _Project(sections, [_version(
        [dict(CITATIONS[1], index=2), dict(CITATIONS[0], index=3)],
        "Results", "черновик до правки [2].")])

    text = export_service.render_markdown(project)

    assert "Наши данные [1] и литература [2]." in text
    assert "[1] Данные GF/F (project_data)" in text


# --------------------------------------------------------------------------- PaperQA2
SOURCE_HEADER = """# Хлорофилл-а в Баренцевом море

## Источник

Annesen S. O. A. Хлорофилл-а в Баренцевом море: сезонная динамика и связь с
температурой // Reports on Polar Research. 2009. Vol. 28, no. 4. P. 401-414.
DOI: 10.0000/example.2009.28.401

## Методы

Пробы отбирали батернет-граблями.
"""


def test_citation_header_is_parsed_into_bibtex_fields() -> None:
    fields = export_service._parse_citation_header(SOURCE_HEADER)

    assert fields["author"] == "Annesen, S. O. A."
    assert fields["title"] == ("Хлорофилл-а в Баренцевом море: сезонная динамика "
                               "и связь с температурой")
    assert fields["journal"] == "Reports on Polar Research"
    assert fields["year"] == "2009"
    assert fields["volume"] == "28"
    assert fields["number"] == "4"
    assert fields["pages"] == "401-414"
    assert fields["doi"] == "10.0000/example.2009.28.401"


def test_bibtex_is_readable_by_paperqa_parser() -> None:
    """BibTeX должен разбираться штатным парсером PaperQA2 без правок."""
    from pybtex.database.input.bibtex import Parser

    entry = export_service._parse_citation_header(SOURCE_HEADER)
    parsed = Parser().parse_string(export_service.to_bibtex([entry]))

    assert list(parsed.entries) == ["Annesen2009"]
    assert parsed.entries["Annesen2009"].type == "article"


def test_bibtex_keys_are_ascii() -> None:
    """Кириллица в ключе ломает часть сценариев сборки BibTeX."""
    keys = [
        export_service._bibtex_key({"title": "Один", "year": "2020",
                                    "author": "Ivanov, I."}),
        export_service._bibtex_key({"title": "Без автора"}),
    ]

    assert all(k.isascii() for k in keys), f"не-ASCII в ключах: {keys}"


# --------------------------------------------------------------------------- docx
def test_docx_is_valid_ooxml_container(project: _Project) -> None:
    result = export_service.render_docx(project)

    assert result.filename.endswith(".docx")
    assert result.content[:2] == b"PK", "DOCX — это zip-контейнер"
    with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
        names = archive.namelist()
        assert "word/document.xml" in names
        assert "[Content_Types].xml" in names
        assert archive.testzip() is None


def test_docx_contains_text_without_citation_markers(project: _Project) -> None:
    result = export_service.render_docx(project)
    with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")

    assert "Биомасса" in xml
    assert "Discussion" in xml
    # ссылки вынесены в список литературы, из текста убраны
    body = xml.split("Discussion", 1)[-1].split("References", 1)[0]
    assert not re.search(r"\[\d+", body), "в тексте разделов не должно быть [n]"


def test_docx_has_references_list(project: _Project) -> None:
    result = export_service.render_docx(project)
    with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    assert "References" in xml
    assert "Smith et al. 2019" in xml


def test_docx_warns_when_nothing_written() -> None:
    sections = [{"name": "Results", "content_md": "", "required": True,
                 "order": 1, "word_target": 500, "notes": ""}]
    result = export_service.render_docx(_Project(sections, []))

    assert any("не написан" in w for w in result.warnings)


def test_docx_filename_is_filesystem_safe(project: _Project) -> None:
    project.title = 'Статья / "кавычки" < >'
    assert re.match(r"^[\w\-. ]+\.docx$", export_service.render_docx(project).filename)


# --------------------------------------------------------------------------- zip
def test_zip_contains_markdown_docx_and_references(project: _Project) -> None:
    class _Doc:
        dockey = "d1"
        title = "Данные"
        citation = "Данные (загружено пользователем)"
        url = None
        filename = "data.csv"
        path = None  # файла нет -> пропускаем, но не падаем

    bundle = export_service.build_zip(project, [_Doc()])

    with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
        names = archive.namelist()
    assert any(n.endswith(".md") for n in names)
    assert any(n.endswith(".docx") for n in names)
    assert any(n.endswith(".bib") for n in names)


def test_zip_embeds_documents(project: _Project, tmp_path) -> None:
    source = tmp_path / "biomass.csv"
    source.write_text("station,gf_f\nBS1,0.42\n", encoding="utf-8")

    class _Doc:
        dockey = "d1"
        title = "Данные"
        citation = "Данные (загружено пользователем)"
        url = None
        filename = "biomass.csv"
        path = str(source)

    bundle = export_service.build_zip(project, [_Doc()], include_documents=True)

    with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
        assert "references/biomass.csv" in archive.namelist()
        # читаем в бинарном виде: переводы строк при записи не меняются
        assert archive.read("references/biomass.csv") == source.read_bytes()


def test_zip_without_documents(project: _Project, tmp_path) -> None:
    source = tmp_path / "x.csv"
    source.write_text("a\n", encoding="utf-8")

    class _Doc:
        dockey = "d1"
        title = "Данные"
        citation = "Данные (загружено пользователем)"
        url = None
        filename = "x.csv"
        path = str(source)

    bundle = export_service.build_zip(project, [_Doc()], include_documents=False)
    with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
        assert not any(n.startswith("references/") and n.endswith(".csv")
                       for n in archive.namelist())


def test_zip_is_readable_archive(project: _Project) -> None:
    bundle = export_service.build_zip(project, [])
    with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
        assert archive.testzip() is None
    assert bundle.files