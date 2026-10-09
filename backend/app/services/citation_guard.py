"""Маркеры цитат в ответах чата: проверка и починка (Фаза 6).

PaperQA требует от LLM ключи вида `(pqac-xxxxxxxx)`, но слабая офлайн-модель
(`qwen2.5:3b`) часто выдумывает собственные обозначения — `(степень 1)`,
`(уровень 2)`, `(источник 3)` — а номера уводит за пределы выдачи
(`(степень 7)` при 5 источниках). Такие маркеры:

* не разрешаются ни в один источник — в ответе остаётся мусор;
* вводят в заблуждение: `[n]` в интерфейсе — это номер источника
  (см. `boasi_ui.components.ui.source_list`), и «степень 7» на такой
  номер не ссылается.

`repair_markers()` делает две вещи:

1. **чинит**: скобка, целиком состоящая из повторов «метка + число»,
   превращается в нормальную ссылку `[n]`, номера берутся только из
   диапазона выдачи `1..source_count`; ссылки на несуществующие номера
   удаляются целиком. То же с маркерами paperqa вида
   «(docname lines 47-77)» — если передать `sources`, они резолвятся
   в номер источника (см. `repair_markers(sources=...)`);
2. **ругается**: отчёт `CitationReport` попадает в лог и в `stats["citations"]`
   ответа API, поэтому сломанное цитирование видно, а не «тихо работает».

Что НЕ трогаем: обычные скобки с числами (`(1)`, `(2024)`) и скобки, где
после числа идут слова — `(степень 2 полинома)`, `(см. источник 3)`.
Иначе математические и бытовые формулировки превратились бы в цитаты.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.services.generation import parse_citations

# «Метка» выдуманного маркера: русские слова со склонениями + английские
# эквиваленты (модель отвечает и по-русски, и по-английски).
_LABELS = (
    r"степен[ьиейямиях]"
    r"|уров[а-я]*"
    r"|источник[а-я]*"
    r"|цитат[а-я]*"
    r"|source[s]?|level[s]?|degree[s]?|citation[s]?"
)

_UNIT_RE = re.compile(rf"(?:{_LABELS})\s*(\d+)", re.IGNORECASE)
_PAREN_RE = re.compile(r"\(([^()]*)\)")
# Всё, что допустимо между «меткой и числом»: пробелы и разделители.
_GAP_RE = re.compile(r"[\s,;:.]*")
# Хвост имени фрагмента paperqa: «docname lines 47-77» / «docname pages 1-3».
# Так называются куски документа (`paperqa.readers.chunk_code_text`), и именно
# в так виде LLM повторяет их как цитаты и как блок References.
_MARK_SUFFIX_RE = re.compile(r"\s+(?:lines|pages)\s+\d+\s*-\s*\d+\s*$",
                             re.IGNORECASE)
# Строка блока источников: «1. (docname lines 0-0): цитата», «2) (степень 7)».
_REF_LINE_RE = re.compile(r"^\s*(?:\d+\s*[.)]|[-*•])\s*\(")
# Заголовок такого блока — удаляется, когда записей под ним не осталось.
_HEADING_RE = re.compile(
    r"^\s*(?:references|источники|литература|список\s+источников)\s*:?\s*$",
    re.IGNORECASE)
# То же имя фрагмента, но БЕЗ скобок: «… см. 2b_context lines 47-77 …».
_BARE_RE = re.compile(
    r"(?<![\w()])(?<!\( )"       # не внутри слова и не сразу после скобки
    r"([^\s()[\],;:]+)"          # docname одним токеном
    r"\s+(?:lines|pages)\s+\d+\s*-\s*\d+\b",
    re.IGNORECASE)


def _norm(value: str) -> str:
    """Нормализация для сравнения имён: пробелы и регистр не должны мешать."""
    return re.sub(r"\s+", " ", value or "").strip().casefold()


def _source_lookup(
    sources: list[dict[str, Any]] | None,
) -> tuple[dict[str, int], dict[str, list[int]]]:
    """Индекс источников: по полному имени фрагмента и по имени документа.

    `pages` — точное совпадение `sources[i]["page"]` (это и есть имя
    фрагмента); `by_doc` — все номера одного документа, чтобы отличить
    «документ единственный» от «четыре фрагмента — какой?».
    """
    pages: dict[str, int] = {}
    by_doc: dict[str, list[int]] = {}
    for source in sources or []:
        index = int(source.get("index") or 0)
        if not index:
            continue
        page = _norm(str(source.get("page") or ""))
        if page:
            pages.setdefault(page, index)   # первый фрагмент выигрывает
        docname = _norm(str(source.get("docname") or ""))
        if docname:
            by_doc.setdefault(docname, []).append(index)
    return pages, by_doc


def _marker_numbers(content: str) -> list[int] | None:
    """Числа маркера или `None`, если скобка — не маркер.

    Маркером считается только скобка, где «метка + число» идут подряд,
    а между ними (и по краям) — лишь пробелы/разделители. Любое лишнее
    слово означает, что перед нами обычный текст, а не цитата.
    """
    matches = list(_UNIT_RE.finditer(content))
    if not matches:
        return None

    numbers: list[int] = []
    pos = 0
    for match in matches:
        if not _GAP_RE.fullmatch(content[pos:match.start()]):
            return None
        numbers.append(int(match.group(1)))
        pos = match.end()
    return numbers if _GAP_RE.fullmatch(content[pos:]) else None


def _cleanup(text: str) -> str:
    """Убрать следы удалённых скобок и строк: пробелы, точка, пустые строки."""
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+(?=[.,;:!?])", "", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text)


# Запись блока References вида «1. [2]: doc (…)» — двоеточие превращает
# строку в определение ссылки-сноски для markdown, и она исчезает при
# рендере (в ответе остаются голые «1. 2.»).
_REF_ENTRY_RE = re.compile(r"^([ \t]*\d+\.)[ \t]+\[([0-9]+)\]:",
                           re.MULTILINE)


def _reflow_reference_entries(text: str,
                              report: CitationReport) -> str:
    """«1. [2]: doc» → «1. [2] doc»: иначе markdown съедает строку.

    Формат выдаёт сама LLM (привычка paperqa), наш guard номера уже
    починил — убираем только двоеточие, нумерация и текст не меняются.
    """
    def _sub(match: re.Match[str]) -> str:
        original = match.group(0).strip()
        fixed = f"{match.group(1)} [{match.group(2)}]"
        report.reflowed.append(f"{original} → {fixed}")
        return fixed
    return _REF_ENTRY_RE.sub(_sub, text)


@dataclass
class CitationReport:
    """Отчёт о цитировании ответа чата — контракт для логов и API `stats`."""

    repaired: list[str] = field(default_factory=list)   # «(степень 1)» -> «[1]»
    dropped: list[str] = field(default_factory=list)    # удалённые маркеры
    reflowed: list[str] = field(default_factory=list)   # «1. [2]:» -> «1. [2]»
    cited: list[int] = field(default_factory=list)      # номера [n] в тексте
    dangling: list[int] = field(default_factory=list)   # [9] при 5 источниках
    # источники нашлись, а в тексте нет ни одного [n]
    uncited: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        """Текст ответа был исправлен."""
        return bool(self.repaired or self.dropped or self.reflowed)

    @property
    def ok(self) -> bool:
        """Цитаты не оставляют мусора: ничего не удалено и всё разрешимо."""
        return not (self.dropped or self.dangling)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "changed": self.changed,
            "repaired": list(self.repaired),
            "dropped": list(self.dropped),
            "reflowed": list(self.reflowed),
            "cited": list(self.cited),
            "dangling": list(self.dangling),
            "uncited": self.uncited,
            "warnings": list(self.warnings),
        }


def repair_markers(
    text: str,
    source_count: int,
    sources: list[dict[str, Any]] | None = None,
) -> tuple[str, CitationReport]:
    """Починить выдуманные LLM маркеры цитат в `text`.

    `source_count` — сколько источников показано пользователю: ровно столько
    номеров `[n]` имеет смысл. `sources` — словари источников ответа (нужны
    `index`, `docname`, `page`): с ними резолвятся и маркеры paperqa
    «(docname lines 47-77)» → `[n]`.

    Три прохода, от грубого к точному:

    1. строки блока References, где ни одна ссылка не разрешилась,
       удаляются целиком (запись вида «2.: цитата» выглядит поломкой);
    2. маркеры в скобках: и «(docname lines 47-77)», и «(степень 1)»;
    3. имя фрагмента без скобок в прозе — переписывается только если
       документ однозначно опознан, чужие слова остаются как есть.
    """
    report = CitationReport()
    if not text:
        return text, report

    text = _drop_broken_reference_lines(text, source_count, sources, report)
    if sources:
        text = _repair_named_markers(text, sources, report)
        text = _repair_bare_markers(text, sources, report)

    def _sub(match: re.Match[str]) -> str:
        numbers = _marker_numbers(match.group(1))
        if numbers is None:
            return match.group(0)
        original = match.group(0)
        valid = sorted({n for n in numbers if 1 <= n <= source_count})
        if valid:
            fixed = "[" + ", ".join(str(n) for n in valid) + "]"
            if fixed != original:
                report.repaired.append(f"{original} → {fixed}")
            return fixed
        # Ни одного реального источника — маркер бесполезен, удаляем.
        report.dropped.append(original)
        return ""

    fixed = _PAREN_RE.sub(_sub, text)
    if report.dropped:
        fixed = _cleanup(fixed)
    fixed = _reflow_reference_entries(fixed, report)

    report.cited = parse_citations(fixed)
    report.dangling = [n for n in report.cited if not 1 <= n <= source_count]
    _fill_warnings(report, source_count)
    return fixed, report


def _repair_named_markers(text: str, sources: list[dict[str, Any]],
                          report: CitationReport) -> str:
    """«(docname lines 47-77)» → `[n]`: номер источника вместо имени файла.

    Правила, от строгого к простому:

    1. имя фрагмента совпало с `page` какого-то источника → его номер;
    2. имя документа известно и он в выдаче один → его номер (реиндекс мог
       сдвинуть номера строк);
    3. имя документа известно, но фрагментов несколько → непонятно, на какой
       ссылается ответ, маркер удаляется с предупреждением;
    4. документ не из выдачи → удаляется (ссылка в никуда).

    Обычные скобки с дефисами — `(1772-1795)`, `(см. раздел lines)` — не
    трогаются: без хвоста «lines/pages N-M» это не маркер.
    """
    pages, by_doc = _source_lookup(sources)

    def _sub(match: re.Match[str]) -> str:
        content = match.group(1).strip()
        if not _MARK_SUFFIX_RE.search(content):
            return match.group(0)
        original = match.group(0)

        index, reason = _named_index(content, pages, by_doc)
        if index is not None:
            fixed = f"[{index}]"
            report.repaired.append(f"{original} → {fixed}")
            return fixed
        if reason == "ambiguous":
            report.warnings.append(
                f"Ссылка неоднозначна (фрагментов документа в выдаче "
                f"несколько), удалена: {original}")
        report.dropped.append(original)
        return ""

    return _PAREN_RE.sub(_sub, text)


def _named_index(content: str, pages: dict[str, int],
                  by_doc: dict[str, list[int]]) -> tuple[int | None, str | None]:
    """Номер источника под маркер либо причина отказа.

    Причина — `"ambiguous"` (документ в выдаче, но фрагментов несколько) или
    `"unknown"` (документа в выдаче нет).
    """
    index = pages.get(_norm(content))
    if index is not None:
        return index, None
    found = by_doc.get(_norm(_MARK_SUFFIX_RE.sub("", content))) or []
    if len(found) == 1:
        return found[0], None
    if found:
        return None, "ambiguous"
    return None, "unknown"


def _reference_line_broken(line: str, source_count: int,
                           sources: list[dict[str, Any]] | None,
                           pages: dict[str, int],
                           by_doc: dict[str, list[int]]) -> bool:
    """Есть ли в строке-записи ссылка, которую не с чем разрешить.

    Строка считается негодной, только если разрешимой ссылки в ней НЕТ:
    одна валидная ссылка спасает строку, а мусорную часть удалит основной
    проход.
    """
    broken = False
    for match in _PAREN_RE.finditer(line):
        content = match.group(1).strip()
        if _MARK_SUFFIX_RE.search(content):
            if not sources:
                continue   # без списка источников резолвить нечего
            index, _ = _named_index(content, pages, by_doc)
            if index is not None:
                return False
            broken = True
            continue
        numbers = _marker_numbers(content)
        if numbers is None:
            continue
        if any(1 <= n <= source_count for n in numbers):
            return False
        broken = True
    return broken


def _drop_broken_reference_lines(
    text: str,
    source_count: int,
    sources: list[dict[str, Any]] | None,
    report: CitationReport,
) -> str:
    """Удалить строки блока References, где ни одна ссылка не разрешилась.

    Запись вида «2.: цитата» выглядит поломкой — хуже, чем отсутствие
    записи. Строка уходит целиком вместе с заголовком, если под ним не
    осталось ни одной записи.
    """
    pages, by_doc = _source_lookup(sources)
    kept: list[str] = []
    removed = 0
    for line in text.split("\n"):
        if _REF_LINE_RE.match(line) and _reference_line_broken(
                line, source_count, sources, pages, by_doc):
            for match in _PAREN_RE.finditer(line):
                content = match.group(1).strip()
                if (_MARK_SUFFIX_RE.search(content)
                        or _marker_numbers(content) is not None):
                    report.dropped.append(match.group(0))
            removed += 1
            continue
        kept.append(line)

    if not removed:
        return text

    result: list[str] = []
    for position, line in enumerate(kept):
        has_entries = any(_REF_LINE_RE.match(other)
                          for other in kept[position + 1:])
        if _HEADING_RE.match(line) and not has_entries:
            continue   # «References» остался без единой записи
        result.append(line)
    report.warnings.append(
        "Удалены целые строки блока источников с неразрешимой ссылкой: "
        f"{removed}")
    return "\n".join(result)


def _repair_bare_markers(text: str, sources: list[dict[str, Any]],
                         report: CitationReport) -> str:
    """Имя фрагмента БЕЗ скобок → `[n]` (осторожно: это проза).

    Переписывается только однозначно опознанный документ — чужое имя в
    предложении трогать нельзя, это может быть и не цитата.
    """
    _, by_doc = _source_lookup(sources)

    def _sub(match: re.Match[str]) -> str:
        found = by_doc.get(_norm(match.group(1))) or []
        if len(found) != 1:
            return match.group(0)
        original = match.group(0)
        fixed = f"[{found[0]}]"
        report.repaired.append(f"{original} → {fixed}")
        return fixed

    return _BARE_RE.sub(_sub, text)


def _fill_warnings(report: CitationReport, source_count: int) -> None:
    if report.repaired:
        report.warnings.append(
            f"Выдуманные маркеры цитат исправлены на [n]: "
            f"{', '.join(report.repaired)}")
    if report.dropped:
        report.warnings.append(
            "Удалены ссылки на несуществующие источники: "
            + ", ".join(report.dropped))
    if report.dangling:
        available = f"1..{source_count}" if source_count else "источников нет"
        report.warnings.append(
            "Ссылки без источника (" + available + "): "
            + ", ".join(f"[{n}]" for n in report.dangling))
    # Источники нашлись, а ссылок в тексте нет вообще. Раньше этот случай
    # считался нормой, и пользователь видел голый ответ с «Источники» внизу,
    # не понимая, что проверять ему надо всё.
    if source_count and not report.cited:
        report.uncited = True
        report.warnings.append(
            f"Ответ без ссылок на источники, хотя найдено {source_count}. "
            "Факты нужно сверить с источниками вручную.")
