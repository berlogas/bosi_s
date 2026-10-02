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


def _version(citation_map: list[dict]) -> object:
    class _V:
        def __init__(self, mapping):
            self.citation_map = mapping
    return _V(citation_map)


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
    return _Project(SECTIONS, [_version(CITATIONS)])


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
    assert references[0].startswith("Smith et al. 2019")
    assert "project_data" in references[1]


def test_markdown_flags_unresolved_reference() -> None:
    sections = [{"name": "Results", "content_md": "Факт [5].", "required": True,
                 "order": 1, "word_target": 500, "notes": ""}]
    project = _Project(sections, [])
    references = export_service.collect_references(project)

    assert "не определён" in references[0], "неразрешённая ссылка видна как дефект"


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