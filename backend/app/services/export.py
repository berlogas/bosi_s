"""Экспорт проекта статьи (Фаза 7): Markdown, BibTeX, DOCX, ZIP.

DOCX собираем `python-docx`: он пишет корректный OOXML, который открывается
в Word и LibreOffice. Зависимость зафиксирована в `requirements.lock`.

Формат DOCX зависит от журнала, поэтому структура абзацев строится из плана
разделов: заголовок 1 -> название статьи, заголовок 2 -> раздел, обычный
абзац -> текст, а список источников оформляется нумерованным списком.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.db.models import Document, Project
from app.services.generation import normalize_sections, parse_citations

CITE_RE = re.compile(r"\[(\d+(?:\s*[,\-–]\s*\d+)*)\]")
MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


# --------------------------------------------------------------------------- утилиты
def strip_citations(text: str) -> str:
    """Убрать `[1]` из текста — DOCX получает нумерованный список отдельно."""
    return CITE_RE.sub("", text or "").strip()


def inline_markdown(text: str) -> tuple[str, bool, bool]:
    """Минимальный разбор инлайновой разметки -> (текст, есть_жирный, есть_курсив)."""
    bold = bool(re.search(r"\*\*.+?\*\*", text))
    italic = bool(re.search(r"(?<!\*)\*[^*]+?\*(?!\*)", text))
    return text, bold, italic


def _iter_blocks(markdown: str) -> Iterable[tuple[str, str]]:
    """Разобрать markdown на блоки: ('heading', текст) / ('paragraph', текст)."""
    buffer: list[str] = []
    for raw_line in (markdown or "").splitlines():
        heading = MD_HEADING_RE.match(raw_line)
        if heading:
            if buffer:
                yield "paragraph", "\n".join(buffer).strip()
                buffer = []
            yield "heading", heading.group(2).strip()
        elif raw_line.strip():
            buffer.append(raw_line.rstrip())
        elif buffer:
            yield "paragraph", "\n".join(buffer).strip()
            buffer = []
    if buffer:
        yield "paragraph", "\n".join(buffer).strip()


# --------------------------------------------------------------------------- markdown
def render_markdown(project: Project, *, author: str | None = None) -> str:
    """Полный текст статьи в markdown."""
    lines: list[str] = [f"# {project.title}", ""]
    if project.target_journal:
        lines += [f"*{project.target_journal}*", ""]

    sections = normalize_sections(project.sections)
    for section in sections:
        content = (section.get("content_md") or "").strip()
        if not content:
            continue
        lines += [f"## {section['name']}", "", content, ""]

    references = collect_references(project, sections)
    if references:
        lines += ["## References", ""]
        lines += [f"[{i}] {ref}" for i, ref in enumerate(references, start=1)]
    return "\n".join(lines).strip() + "\n"


def collect_references(project: Project,
                       sections: Sequence[dict[str, Any]] | None = None) -> list[str]:
    """Ссылки из текста разделов — в порядке первого появления."""
    sections = sections if sections is not None else normalize_sections(project.sections)
    seen: list[int] = []
    for section in sections:
        for number in parse_citations(section.get("content_md") or ""):
            if number not in seen:
                seen.append(number)
    if not seen:
        return []
    max_index = max(seen)
    known = project_citation_index(project)
    # Номер без записи в карте цитат — это дефект генерации, а не источник.
    # Показываем это явно, иначе в списке литературы появится «источник 3».
    return [known.get(i) or f"(источник [{i}] не определён — проверьте генерацию)"
            for i in range(1, max_index + 1)]


def project_citation_index(project: Project) -> dict[int, str]:
    """Карта `номер -> подпись источника` из последней версии проекта."""
    index: dict[int, str] = {}
    for version in reversed(project.versions or []):
        for entry in version.citation_map or []:
            number = entry.get("index")
            if number is None:
                continue
            if entry.get("source_scope") == "global":
                label = entry.get("citation") or entry.get("title") or ""
            else:
                label = (f"{entry.get('title') or entry.get('docname')} "
                         f"({entry.get('category') or 'без категории'})")
            index[int(number)] = str(label).strip()
    return index


# --------------------------------------------------------------------------- bibtex
def to_bibtex(entries: Sequence[dict[str, Any]]) -> str:
    """Минимальный BibTeX из словарей с ключами article/inbook/misc."""
    types = {"article": "article", "book": "book", "inbook": "inbook",
             "inproceedings": "inproceedings", "misc": "misc", "report": "techreport"}
    out: list[str] = []
    for entry in entries:
        kind = types.get(str(entry.get("type") or "misc").lower(), "misc")
        key = entry.get("key") or entry.get("id") or "source"
        fields = ["  author = {" + str(entry.get("author") or "Anonymous") + "}",
                  "  title = {" + str(entry.get("title") or "Untitled") + "}"]
        if entry.get("journal"):
            fields.append(f"  journal = {{{entry['journal']}}}")
        if entry.get("year"):
            fields.append(f"  year = {{{entry['year']}}}")
        if entry.get("doi"):
            fields.append(f"  doi = {{{entry['doi']}}}")
        if entry.get("url"):
            fields.append(f"  url = {{{entry['url']}}}")
        out.append(f"@{kind}{{{key},\n" + ",\n".join(fields) + "\n}")
    return "\n\n".join(out) + ("\n" if out else "")


# --------------------------------------------------------------------------- docx
@dataclass
class DocxResult:
    content: bytes
    filename: str
    warnings: list[str] = field(default_factory=list)


def render_docx(project: Project, *, author: str | None = None) -> DocxResult:
    """Собрать .docx из плана разделов. Открывается в Word."""
    from docx import Document as DocxDocument
    from docx.shared import Pt

    document = DocxDocument()
    style = document.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(12)

    document.add_heading(project.title, level=1)
    if project.target_journal:
        document.add_paragraph(project.target_journal).italic = True
    if author:
        document.add_paragraph(author)

    sections = normalize_sections(project.sections)
    written = 0
    for section in sections:
        content = (section.get("content_md") or "").strip()
        if not content:
            continue
        written += 1
        document.add_heading(section["name"], level=2)
        for kind, text in _iter_blocks(content):
            if kind == "heading":
                document.add_heading(text, level=3)
            else:
                plain, bold, italic = inline_markdown(strip_citations(text))
                paragraph = document.add_paragraph(plain)
                paragraph.paragraph_format.space_after = Pt(6)
                if bold or italic:
                    for run in paragraph.runs:
                        run.bold = run.bold or bold
                        run.italic = run.italic or italic

    references = collect_references(project, sections)
    if references:
        document.add_heading("References", level=2)
        for number, reference in enumerate(references, start=1):
            document.add_paragraph(f"[{number}] {reference}")

    warnings: list[str] = []
    if not written:
        warnings.append("Ни один раздел не написан — документ почти пуст")
    total = len(sections)
    if written < total:
        warnings.append(f"Написано {written} из {total} разделов")

    buffer = io.BytesIO()
    document.save(buffer)
    safe = re.sub(r'[<>:"/\\|?*]+', "_", project.title)[:60] or "article"
    return DocxResult(content=buffer.getvalue(), filename=f"{safe}.docx",
                      warnings=warnings)


# --------------------------------------------------------------------------- zip
@dataclass
class ExportBundle:
    content: bytes
    filename: str
    files: list[str] = field(default_factory=list)


def build_zip(project: Project, documents: Sequence[Document], *,
              include_documents: bool = True) -> ExportBundle:
    """ZIP со статьёй, библиографией и папкой references/ с исходниками."""
    buffer = io.BytesIO()
    safe = re.sub(r'[<>:"/\\|?*]+', "_", project.title)[:60] or "article"
    files: list[str] = []

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        markdown = render_markdown(project)
        archive.writestr(f"{safe}.md", markdown)
        files.append(f"{safe}.md")

        docx = render_docx(project)
        archive.writestr(f"{safe}.docx", docx.content)
        files.append(f"{safe}.docx")

        bibtex = to_bibtex(_bibtex_entries(project))
        if bibtex:
            archive.writestr("references.bib", bibtex)
            files.append("references.bib")

        if include_documents:
            for document in documents:
                if not document.path:
                    continue
                try:
                    with open(document.path, "rb") as handle:
                        payload = handle.read()
                except OSError:
                    continue
                archive.writestr(f"references/{document.filename or document.id}",
                                 payload)
                files.append(f"references/{document.filename or document.id}")

    return ExportBundle(content=buffer.getvalue(), filename=f"{safe}.zip",
                        files=files)


def _bibtex_entries(project: Project) -> list[dict[str, Any]]:
    """Записи BibTeX из привязанных документов (по метаданным реестра)."""
    entries: list[dict[str, Any]] = []
    for version in project.versions or []:
        for citation in version.citation_map or []:
            if citation.get("source_scope") != "global":
                continue
            key = (citation.get("docname") or citation.get("dockey") or "")[:40]
            entries.append({
                "key": key,
                "type": "article",
                "title": citation.get("title") or citation.get("docname") or "",
                "author": "Anonymous",
                "year": "",
            })
    return entries