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

# Диапазон, записанный с обеих сторон в скобках — «[3]–[5]». Для парсера
# это два независимых маркера, поэтому порядок их после перенумерации может
# развернуться; сливаем такой диапазон в один до разбора.
BRACKETED_RANGE_RE = re.compile(r"\[(\d+)\]\s*[-–]\s*\[(\d+)\]")

# Префикс для номера, процитированного в тексте, но не найденного в картах
# цитат: в списке литературы он обязан быть виден явно, а не молча пропасть.
UNRESOLVED_PREFIX = "__unresolved_"

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

    plan = plan_citations(project)
    for section in plan.sections:
        content = (section.get("content_md") or "").strip()
        if not content:
            continue
        lines += [f"## {section['name']}", "", content, ""]

    if plan.references:
        lines += ["## References", ""]
        lines += [f"[{ref.number}] {ref.label}" for ref in plan.references]
    return "\n".join(lines).strip() + "\n"


@dataclass
class BibliographyEntry:
    """Запись списка литературы в сквозной нумерации статьи."""

    number: int
    key: str          # стабильный ключ источника (dockey) — для дедупликации
    label: str        # подпись в списке литературы
    old_numbers: list[int]  # номера из карт цитат отдельных генераций


@dataclass
class CitationPlan:
    """Разделы с перенумерованными ссылками и список литературы к ним.

    Номера `[n]` в тексте выдаёт та генерация, которая писала раздел, и
    раздел за разделом они не совпадают: один и тот же документ в Methods —
    это `[1]`, в Results — уже `[2]`. Поэтому перенумеровываются не только
    записи списка, но и маркеры в тексте: иначе `[6]` в Discussion остаётся
    шестым, а в списке литературы такой записи нет вовсе.
    """

    sections: list[dict[str, Any]]
    references: list[BibliographyEntry]


def _section_number_maps(project: Project,
                         sections: Sequence[dict[str, Any]]
                         ) -> dict[str, dict[int, str]]:
    """Карта `номер -> dockey` для текста каждого раздела.

    Раздел опирается на ту версию, чей текст стал его содержимым: ручная
    правка сохраняет текст, но не версию, поэтому при отсутствии точного
    совпадения берётся последняя версия этого раздела — номера в ней те же,
    с которыми исследователь работал.
    """
    versions = list(project.versions or [])
    maps: dict[str, dict[int, str]] = {}
    for section in sections:
        name = str(section.get("name") or "")
        content = section.get("content_md") or ""
        same_section = [v for v in versions
                        if str(getattr(v, "section_name", "") or "").lower()
                        == name.lower()]
        exact = [v for v in same_section
                 if (getattr(v, "content_md", "") or "") == content]
        chosen = exact[-1] if exact else (same_section[-1] if same_section else None)
        numbers: dict[int, str] = {}
        for entry in getattr(chosen, "citation_map", None) or []:
            index = entry.get("index")
            key = str(entry.get("dockey") or "").strip()
            if index is None or not key:
                continue
            numbers[int(index)] = key
        maps[name] = numbers
    return maps


def _normalize_bracketed_ranges(text: str) -> str:
    """`[3]–[5]` -> `[3-5]`: диапазон в одном маркере вместо двух."""
    return BRACKETED_RANGE_RE.sub(
        lambda span: f"[{span.group(1)}-{span.group(2)}]", text or "")


def _expand_group(group: str) -> list[int]:
    """Числа из одного маркера: `[2]`, `[1,2]`, `[1-3]` -> `[1, 2, 3]`."""
    found: list[int] = []
    for part in group.split(","):
        part = part.strip()
        span = re.match(r"^(\d+)\s*[-–]\s*(\d+)$", part)
        if span:
            numbers = range(int(span.group(1)), int(span.group(2)) + 1)
        elif part.isdigit():
            numbers = [int(part)]
        else:
            continue
        for number in numbers:
            if number not in found:
                found.append(number)
    return found


def rewrite_citations(text: str, mapping: dict[int, int]) -> str:
    """Переписать `[n]` в тексте по `mapping` (старый номер -> новый).

    Перенумерация не обязана сохранять порядок: был диапазон `[3-5]`,
    стала тройка ссылок из разных разделов — их номера идут вперемешку.
    Диапазон поэтому всегда разворачивается по возрастанию, иначе в тексте
    появляется конструкция вида «[5]–[4]».
    """
    if not text:
        return ""

    def replace(match: re.Match[str]) -> str:
        group = match.group(1)
        numbers: list[int] = []
        for number in _expand_group(group):
            new = mapping.get(number, number)
            if new not in numbers:
                numbers.append(new)
        if not numbers:
            return ""
        if "-" in group or "–" in group:
            numbers.sort()
        return "[" + ", ".join(str(n) for n in numbers) + "]"

    return CITE_RE.sub(replace, _normalize_bracketed_ranges(text))


def plan_citations(project: Project,
                   sections: Sequence[dict[str, Any]] | None = None
                   ) -> CitationPlan:
    """Сквозная нумерация статьи: текст разделов и список литературы.

    Порядок — по первому появлению источника в тексте, как это делает
    PaperQA2 в `PQASession.populate_formatted_answers_and_bib_...`
    (там ключом служит `text.name`, здесь — `dockey`).
    """
    sections = list(sections if sections is not None
                    else normalize_sections(project.sections))
    number_maps = _section_number_maps(project, sections)
    label_by_key: dict[str, str] = {}
    for version in project.versions or []:
        for entry in version.citation_map or []:
            key = str(entry.get("dockey") or "").strip()
            if key:
                label_by_key.setdefault(key, _source_label(entry))

    order: list[str] = []
    numbers_by_key: dict[str, int] = {}
    old_numbers: dict[str, list[int]] = {}
    rewrites: list[dict[int, int]] = []
    unresolved: dict[str, str] = {}
    for section in sections:
        content = section.get("content_md") or ""
        numbers = number_maps.get(str(section.get("name") or ""), {})
        rewrite: dict[int, int] = {}
        for number in parse_citations(_normalize_bracketed_ranges(content)):
            key = numbers.get(number)
            if key is None:
                # ссылка без источника: показываем её в списке явно, иначе
                # в статье появится молчаливая «дыра»
                key = f"{UNRESOLVED_PREFIX}{section.get('name')}#{number}"
                unresolved[key] = (
                    f"(источник не определён: ссылка [{number}] в разделе "
                    f"«{section.get('name')}» — проверьте генерацию)")
            if key not in numbers_by_key:
                order.append(key)
                numbers_by_key[key] = len(order)
                old_numbers[key] = []
            if number not in old_numbers[key]:
                old_numbers[key].append(number)
            rewrite[number] = numbers_by_key[key]
        rewrites.append(rewrite)

    references = [
        BibliographyEntry(
            number=numbers_by_key[key], key=key,
            label=unresolved.get(key) or label_by_key.get(key, key),
            old_numbers=old_numbers[key],
        )
        for key in order
    ]
    renumbered = [
        {**section,
         "content_md": rewrite_citations(section.get("content_md") or "",
                                         rewrite)}
        for section, rewrite in zip(sections, rewrites, strict=True)
    ]
    return CitationPlan(sections=renumbered, references=references)


def collect_references(project: Project,
                       sections: Sequence[dict[str, Any]] | None = None
                       ) -> list[BibliographyEntry]:
    """Список литературы статьи в сквозной нумерации."""
    return plan_citations(project, sections).references




def _source_label(entry: dict[str, Any]) -> str:
    """Подпись источника: у глобального — его citation, у сессионного — с категорией."""
    if entry.get("source_scope") == "global":
        label = entry.get("citation") or entry.get("title") or ""
    else:
        label = (f"{entry.get('title') or entry.get('docname')} "
                 f"({entry.get('category') or 'без категории'})")
    return str(label).strip()


def project_citation_index(project: Project) -> dict[int, str]:
    """Карта `номер -> подпись источника` из последней версии проекта."""
    index: dict[int, str] = {}
    for version in reversed(project.versions or []):
        for entry in version.citation_map or []:
            number = entry.get("index")
            if number is None:
                continue
            index[int(number)] = _source_label(entry)
    return index


# --------------------------------------------------------------------------- bibtex
def to_bibtex(entries: Sequence[dict[str, Any]]) -> str:
    """BibTeX из записей в порядке списка литературы статьи.

    PaperQA2 держит BibTeX канонической формой ссылки
    (`DocDetails.populate_bibtex_key_citation`), поэтому недостающие поля
    отмечаются как есть — выдумывать их нельзя.
    """
    types = {"article": "article", "book": "book", "inbook": "inbook",
             "inproceedings": "inproceedings", "misc": "misc",
             "report": "techreport", "techreport": "techreport",
             "dataset": "misc", "preprint": "misc"}
    out: list[str] = []
    for entry in entries:
        kind = types.get(_bibtex_entry_type(entry), "misc")
        fields: list[str] = []
        for name in ("author", "title", "journal", "year", "volume",
                     "number", "pages", "doi", "url", "publisher"):
            value = str(entry.get(name) or "").strip()
            if value:
                fields.append(f"  {name} = {{{value}}}")
        if not fields:
            fields.append("  note = {источник без метаданных}")
        out.append(f"@{kind}{{{_bibtex_key(entry)},\n" + ",\n".join(fields) + "\n}")
    return "\n\n".join(out) + ("\n" if out else "")


def render_paperqa_references(entries: Sequence[dict[str, Any]]) -> str:
    """Список литературы в оформлении PaperQA2 (`unsrtalpha`).

    PaperQA2 собирает его в `PQASession.populate_formatted_answers_and_bib_...`:
    `N. (подпись): цитата`, где цитата — рендер BibTeX через
    `paperqa.utils.format_bibtex`. Формат тот же, чтобы список из архива
    можно было сверить с тем, что выдаёт сам пакет.
    """
    if not entries:
        return ""
    from paperqa.utils import format_bibtex

    blocks: list[str] = []
    for number, entry in enumerate(entries, start=1):
        # В скобках PaperQA2 ставит имя источника (docname), а не заголовок:
        # заголовок уже идёт следом в самой цитате.
        label = str(entry.get("label") or entry.get("key") or "источник")
        citation = str(entry.get("title") or label)
        try:
            rendered = format_bibtex(to_bibtex([entry]), key=str(entry.get("key") or ""))
        except Exception:  # PaperQA2 так же не падает на кривом BibTeX
            rendered = ""
        if rendered and rendered.strip() and not rendered.startswith("Ref "):
            citation = rendered.strip()
        blocks.append(f"{number}. ({label}): {citation}")
    return "\n\n".join(blocks) + "\n"


def _bibtex_entry_type(entry: dict[str, Any]) -> str:
    """Тип записи: журнал или препринт -> `article`, остальное — по умолчанию.

    Собственные данные и черновики журнала не имеют, поэтому `@article`
    им не выдаём: BibTeX-стиль такого не подтверждает.
    """
    explicit = str(entry.get("type") or "").strip().lower()
    if explicit and explicit != "article":
        return explicit
    if entry.get("journal"):
        return "article"
    # `article` без журнала — наш дефолт, а не утверждение о типе: собственные
    # данные и черновики журнала не имеют.
    return "misc"


def _bibtex_key(entry: dict[str, Any]) -> str:
    """Ключ BibTeX по схеме PaperQA2: фамилия автора + год + слово из заголовка.

    Только ASCII: кириллица в ключе ломает часть сценариев сборки, а BibTeX
    по спецификации ограничен 7-битным набором. Русское название остаётся
    в поле `title`.
    """
    explicit = "".join(
        ch for ch in str(entry.get("key") or "") if ch.isascii() and ch.isalnum())
    if explicit:
        return explicit
    author = str(entry.get("author") or "").strip().split(",")[0]
    surname = "".join(ch for ch in author if ch.isascii() and ch.isalnum())
    year = "".join(ch for ch in str(entry.get("year") or "") if ch.isdigit())
    word = next((w for w in str(entry.get("title") or "").split()
                 if w.isascii() and w.isalnum()), "")
    key = "".join(ch for ch in f"{surname}{year}{word}" if ch.isalnum())[:48]
    return key or "source"


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

    plan = plan_citations(project)
    sections = plan.sections
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

    if plan.references:
        document.add_heading("References", level=2)
        for ref in plan.references:
            document.add_paragraph(f"[{ref.number}] {ref.label}")

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

        entries = _bibtex_entries(project, documents)
        bibtex = to_bibtex(entries)
        if bibtex:
            archive.writestr("references.bib", bibtex)
            files.append("references.bib")

        rendered = render_paperqa_references(entries)
        if rendered:
            archive.writestr("references_paperqa.txt", rendered)
            files.append("references_paperqa.txt")

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


def _plain_label(label: str) -> str:
    """Убрать хвост «(категория)» из подписи источника."""
    return re.sub(r"\s*\([^()]+\)\s*$", "", str(label or "")).strip()


def _bibtex_entries(project: Project,
                    documents: Sequence[Document] | None = None) -> list[dict[str, Any]]:
    """Записи BibTeX — по источникам списка литературы, без дублей.

    Раньше сюда попадали только глобальные источники, из-за чего у статьи,
    собранной из документов сессии, `.bib` выходил пустым. Теперь берём
    дедуплицированный `collect_references` и дополняем его метаданными
    документов реестра: карта цитат хранит только подпись, а не авторов,
    год и DOI.
    """
    entries: list[dict[str, Any]] = []
    references = collect_references(project)
    if not references:
        return entries
    by_dockey = {str(d.dockey): d for d in (documents or [])}
    used_keys: set[str] = set()
    for ref in references:
        if ref.key.startswith(UNRESOLVED_PREFIX):
            continue
        # `label` — имя источника для списка в стиле PaperQA2, без категории:
        # категория нужна в списке литературы, но не внутри скобок цитаты.
        entry: dict[str, Any] = {"label": _plain_label(ref.label),
                                 "title": ref.label, "type": "article"}
        document = by_dockey.get(ref.key)
        if document is not None:
            entry.update(_document_bibtex_fields(document))
            entry["label"] = _plain_label(
                document.title or document.docname or ref.label)
        # Ключ обязан быть уникальным: BibTeX идентифицирует запись по ключу,
        # и два одинаковых ключа — это молчаливая потеря одной из записей.
        key = _bibtex_key(entry)
        if key in used_keys:
            key = f"{key}{_bibtex_key({'title': ref.key[:8]})}"
        suffix = 2
        base_key = key
        while key in used_keys:
            key = f"{base_key}{suffix}"
            suffix += 1
        used_keys.add(key)
        entry["key"] = key
        entries.append(entry)
    return entries


def _document_bibtex_fields(document: Document) -> dict[str, Any]:
    """Поля BibTeX из реестра и шапки файла; чего нет — не выдумываем.

    Метаданные (автор, журнал, год, том, страницы, DOI) лежат в первых
    строках файла — там же, где их читает PaperQA2. Разбираем только
    заголовок: читать весь документ ради экспорта незачем, а молчаливые
    догадки в `.bib` вреднее пропуска.
    """
    fields: dict[str, Any] = {}
    title = (document.title or "").strip()
    if title:
        fields["title"] = title
    fields.update(_parse_citation_header(_document_head(document)))
    if document.url:
        fields.setdefault("url", document.url)
    return fields


def _document_head(document: Document, limit: int = 4000) -> str:
    """Первые символы файла документа; при недоступности — пустая строка."""
    path = getattr(document, "path", None)
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read(limit)
    except OSError:
        return ""


def _parse_citation_header(head: str) -> dict[str, Any]:
    """Разобрать шапку источника: автор, журнал, год, том, страницы, DOI."""
    fields: dict[str, Any] = {}
    if not head:
        return fields
    match = re.search(r"\bDOI:\s*(10\.\d{4,9}/\S+)", head, re.IGNORECASE)
    if match:
        fields["doi"] = match.group(1).rstrip(".")
    for pattern, name in (
        (r"\bVol\.\s*(\d+)", "volume"),
        (r"\bno\.\s*(\d+)", "number"),
        (r"\bP{1,2}\.\s*([\d–-]+)", "pages"),
    ):
        found = re.search(pattern, head, re.IGNORECASE)
        if found:
            fields[name] = found.group(1)
    fields.update(_parse_citation_entry(_citation_block(head)))
    return fields


def _citation_block(head: str) -> str:
    """Блок «Источник» — то, где лежит библиографическая строка.

    Без якоря автор искался бы по всему файлу и цеплял слова из текста
    статьи, поэтому блок ограничен заголовком.
    """
    match = re.search(r"^#{0,3}\s*(?:Источник|Source|Статья)\s*:?\s*$",
                     head, re.IGNORECASE | re.MULTILINE)
    if not match:
        return head
    rest = head[match.end():]
    end = re.search(r"^#{1,3}\s+\S", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


def _parse_citation_entry(block: str) -> dict[str, Any]:
    """Разобрать строку «Авторы. Название // Журнал. Год. Vol. …».

    Заголовок статьи стоит между инициалами и `//`; берём оттуда, иначе
    в `.bib` попадёт имя файла вместо названия работы.
    """
    text = " ".join(ln.strip() for ln in block.splitlines() if ln.strip())
    fields: dict[str, Any] = {}
    entry = re.match(
        r"\s*((?:[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё'’\-]+\s+){1,3})"
        r"([A-ZА-ЯЁ]\.(?:\s*[A-ZА-ЯЁ]\.)*)"
        r"\s*(.*?)\s*//", text)
    if entry:
        surname = " ".join(entry.group(1).split())
        initials = re.sub(r"\s+", " ", entry.group(2)).strip()
        fields["author"] = f"{surname}, {initials}"
        title = entry.group(3).strip().rstrip(".")
        if title:
            fields["title"] = title
    journal = re.search(r"//\s*([A-Za-zА-Яа-яЁё][^.\n]{3,60}?)\.\s*\d{4}", text)
    if journal:
        fields["journal"] = journal.group(1).strip()
    year = re.search(r"//\s*[^.\n]{3,60}\.\s*(\d{4})", text)
    if year:
        fields["year"] = year.group(1)
    return fields