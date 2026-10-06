"""Чтение документов в UTF-8, а не в кодировке локали.

`paperqa.readers.parse_text()` открывает файл **без** указания кодировки
(`path.open()`), то есть в `locale.getpreferredencoding(False)`. На Windows
это cp1251: UTF-8-кириллица читается как «Р‘РёРѕРјР°ССЃР°» и **без
исключения** — байты русского текста в cp1251 определены, поэтому ошибка
всплывает лишь на части файлов. Так баг выглядит как «иногда в индексе
кракозябры»: документ попадает в выдачу, но ни поиск, ни grounding по нему
не работают (эталон Фазы 10 поймал именно это: `bm-03`, `bm-05`).

Функция :func:`parse_text_utf8` повторяет `parse_text()` апстрима с явным
UTF-8, а не-UTF-8 файлы откатывает на кодировку локали (как и апстрим).
:func:`install_utf8_parser` подменяет функцию в `paperqa.readers` — одной
строкой в `paperqa_service`, чтобы чат и эталон читали документы одинаково.
"""

from __future__ import annotations

import locale
import os
from pathlib import Path

from html2text import __version__ as html2text_version
from html2text import html2text
from paperqa.readers import ParsedMetadata, ParsedText
from paperqa.utils import ImpossibleParsingError
from paperqa.version import __version__ as pqa_version

_installed = False


def parse_text_utf8(
    path: str | os.PathLike,
    html: bool = False,
    split_lines: bool = False,
    page_size_limit: int | None = None,
    **_: object,
) -> ParsedText:
    """Как `paperqa.readers.parse_text`, но файл читается в UTF-8."""
    file_path = Path(path)
    raw = file_path.read_bytes()
    try:
        text: str | list[str] = raw.decode("utf-8")
    except UnicodeDecodeError:
        # файл не в UTF-8: кодировка локали, как в апстриме
        text = raw.decode(locale.getpreferredencoding(False), errors="ignore")

    parsing_libraries: list[str] = []
    if split_lines and isinstance(text, str):
        # `list(f)` в апстриме: строки с сохранённым переводом строки
        text = text.splitlines(keepends=True)

    if html:
        if not isinstance(text, str):
            raise NotImplementedError(
                "HTML parsing is not yet set up to work with split_lines."
            )
        text = html2text(text)
        parsing_libraries.append(f"html2text ({html2text_version})")
        summary = "html"
    else:
        summary = "txt"

    if isinstance(text, str):
        total_length = len(text)
    else:
        total_length = sum(len(t) for t in text)
        for i, t in enumerate(text):
            if page_size_limit and len(text) > page_size_limit:
                raise ImpossibleParsingError(
                    f"The {summary} on page {i} of {len(text)} was {len(t)} chars "
                    f"long, which exceeds the {page_size_limit} char limit at "
                    f"path {file_path}"
                )

    return ParsedText(
        content=text,
        metadata=ParsedMetadata(
            parsing_libraries=parsing_libraries,
            paperqa_version=pqa_version,
            total_parsed_text_length=total_length,
            name=f"{summary}|split-lines={split_lines}",
        ),
    )


def install_utf8_parser() -> None:
    """Подменить `parse_text` внутри paperqa (идемпотентно).

    `read_doc()` берёт функцию из globals своего модуля в момент вызова,
    поэтому подмена действует на весь дальнейший парсинг.
    """
    global _installed
    if _installed:
        return
    import paperqa.readers as pqa_readers

    pqa_readers.parse_text = parse_text_utf8  # type: ignore[assignment]
    _installed = True
