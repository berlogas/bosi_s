"""Фаза 10 — парсинг документов в UTF-8 вместо кодировки локали.

Регрессия Windows: `paperqa.readers.parse_text()` открывал файл без
кодировки, и UTF-8-кириллица читалась как cp1251 («Р‘РёРѕРјР°ССЃР°») —
такой документ попадал в индекс, но не находится поиском. Проверяем и свою
функцию, и то, что подмена реально установлена в paperqa.
"""

from __future__ import annotations

from pathlib import Path

import paperqa.readers as pqa_readers

from app.services.pqa_readers import parse_text_utf8


def test_utf8_file_is_read_without_mojibake(tmp_path: Path) -> None:
    path = tmp_path / "doc.md"
    path.write_text("# Биомасса в Баренцевом море\n\nХлорофилл-а 1,495.\n",
                    encoding="utf-8")

    parsed = parse_text_utf8(path, split_lines=True)

    text = "".join(parsed.content)
    assert "Биомасса" in text
    assert "Хлорофилл" in text
    assert "Р‘" not in text  # след cp1251-чтения UTF-8
    assert parsed.metadata.name == "txt|split-lines=True"
    assert parsed.metadata.total_parsed_text_length == len(text)


def test_split_lines_keeps_newlines_like_upstream(tmp_path: Path) -> None:
    path = tmp_path / "doc.md"
    path.write_bytes("строка\nещё\n".encode())  # LF, без перевода Windows

    parsed = parse_text_utf8(path, split_lines=True)

    assert parsed.content == ["строка\n", "ещё\n"]


def test_non_utf8_file_falls_back_without_crash(tmp_path: Path) -> None:
    # байты, не являющиеся UTF-8: откат на кодировку локали, как в апстриме
    path = tmp_path / "legacy.txt"
    path.write_bytes(b"data caf\xe9 end")

    parsed = parse_text_utf8(path)

    assert "data" in "".join(parsed.content)


def test_parser_is_installed_in_paperqa() -> None:
    """Чат и эталон должны читать документы одинаково — подмена активна."""
    from app.services import paperqa_service  # noqa: F401  (импорт ставит подмену)

    assert pqa_readers.parse_text is parse_text_utf8


def test_real_document_parses_clean() -> None:
    """Живой документ из эталона (тот самый, что ловился mojibake)."""
    doc = (Path(__file__).resolve().parents[2]
           / "backend/scripts/eval/docs/barents_biomass.md")
    if not doc.exists():
        import pytest

        pytest.skip("нет документа эталона")

    parsed = parse_text_utf8(doc, split_lines=True)
    text = "".join(parsed.content)

    assert "Биомасса" in text
    assert "батернет" in text
    assert "Р‘Р" not in text
