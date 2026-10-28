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
from typing import Any

from html2text import __version__ as html2text_version
from html2text import html2text
from paperqa.readers import ParsedMetadata, ParsedText
from paperqa.utils import ImpossibleParsingError
from paperqa.version import __version__ as pqa_version

_installed = False

# unstructured.partition.auto.partition падает с Segmentation fault на некоторых
# офисных файлах (.xlsx, .docx, .pptx). Прямые partition_xlsx/docx/pptx работают
# нормально. Подменяем auto-partitioner, чтобы для офисных файлов вызывать
# соответствующий конкретный partitioner.
def _install_office_partition_patch() -> None:
    """Заменить `parse_office_doc` в paperqa на версию без `partition_auto`.

    `paperqa.readers.parse_office_doc` вызывает `unstructured.partition.auto.partition`,
    который падает с Segmentation fault на некоторых офисных файлах (.xlsx).
    Прямые partition_xlsx/docx/pptx работают нормально. Подменяем функцию
    в модуле paperqa.readers, чтобы для офисных файлов использовать
    конкретный partitioner вместо auto.
    """
    try:
        import unstructured  # noqa: F401
    except ImportError:
        return

    from importlib.metadata import version as _dist_version

    from paperqa.readers import ParsedMedia, ParsedMetadata, ParsedText
    from paperqa.version import __version__ as pqa_version
    from unstructured.documents.elements import (
        Element,  # noqa: F401
        Image,
        Table,
    )
    from unstructured.partition.docx import partition_docx
    from unstructured.partition.pptx import partition_pptx
    from unstructured.partition.xlsx import partition_xlsx

    def parse_office_doc_boasi(path: str | os.PathLike, **kwargs: Any) -> ParsedText:
        """Parse office documents using specific unstructured partitioners (no auto)."""
        UNSTRUCTURED_VERSION = _dist_version("unstructured")
        ext = Path(str(path)).suffix.lower()
        if ext == ".xlsx":
            elements = partition_xlsx(str(path), **kwargs)
        elif ext == ".docx":
            elements = partition_docx(str(path), **kwargs)
        elif ext == ".pptx":
            elements = partition_pptx(str(path), **kwargs)
        else:
            # fallback к auto для неизвестных расширений
            from unstructured.partition.auto import partition as _auto_partition
            elements = _auto_partition(str(path), **kwargs)

        content_dict: dict[str, Any] = {}
        media_list: list[Any] = []
        current_text = ""
        media_index = 0

        for el in elements:
            if isinstance(el, Image):
                image_data = el.metadata.image_data
                parsed_media = ParsedMedia(
                    index=media_index,
                    data=image_data,
                    info={"suffix": el.metadata.image_mime_type},
                )
                media_list.append(parsed_media)
                media_index += 1
            elif isinstance(el, Table):
                if el.metadata.text_as_html:
                    current_text += el.metadata.text_as_html + "\n\n"
            else:
                current_text += str(el) + "\n\n"

        content_dict["1"] = (current_text, media_list)

        return ParsedText(
            content=content_dict,
            metadata=ParsedMetadata(
                parsing_libraries=[f"unstructured ({UNSTRUCTURED_VERSION})"],
                paperqa_version=pqa_version,
                total_parsed_text_length=len(current_text),
                count_parsed_media=len(media_list),
                name=f"office_doc|path={path}",
            ),
        )

    import paperqa.readers as _pqa_readers

    _pqa_readers.parse_office_doc = parse_office_doc_boasi  # type: ignore[assignment]


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
    _install_office_partition_patch()
    _installed = True
