"""Справочник стилей журналов: файлы на диске, подстановка в промпт.

Тесты ходят по настоящим файлам из `app/prompts/journal_styles`, а не по
фикстуре: смысл этих шаблонов в том, что их правят руками, и если тест
проверяет копию, он перестанет ловить ошибку в реальном шаблоне.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.services import journal_styles as js
from app.services.generation import apply_style, build_prompt
from app.services.journal_styles import CONTEXT_MARKER

SOURCES = [{"index": 1, "title": "Doc A", "text": "текст",
            "source_scope": "global", "category": "pdf"}]


def test_все_группы_читаются_с_диска() -> None:
    styles = js.styles()

    assert styles, "справочник пуст: файлы стилей не прочитались"
    keys = {style.key for style in styles}
    assert {"multidisciplinary_breakthrough", "specialized_top", "sound_science",
            "review_articles", "engineering_cs"} <= keys


def test_у_каждой_группы_есть_журналы_и_шаблоны() -> None:
    for style in js.styles():
        assert style.journals, f"{style.key}: группа без журналов"
        assert style.templates, f"{style.key}: группа без шаблонов"
        for template in style.templates:
            assert template.prompt.strip(), f"{style.key}/{template.file}: пусто"


def test_шаблон_по_разделу_выбирается_по_слову() -> None:
    """«Methods» берёт шаблон методов, а не шаблон по умолчанию."""
    methods = js.style_prompt("PLOS ONE", "Materials and Methods")

    assert "Materials and Methods" in methods
    assert "Methods" in methods
    # Шаблон по умолчанию у группы — тот же, но проверка должна отличать
    # именно выбор по разделу: в default-шаблоне нет слов про репликацию.
    assert "replicate" in methods


def test_журнал_ищется_по_названию_а_не_только_по_ключу() -> None:
    """Пользователь вводит журнал, хранить надо ключ группы."""
    assert js.find_style("Nature").key == "multidisciplinary_breakthrough"
    assert js.find_style(" nature ").key == "multidisciplinary_breakthrough"
    assert js.find_style("PLOS ONE").key == "sound_science"
    assert js.find_style("NeurIPS").key == "engineering_cs"
    assert js.find_style("Journal of Marine Biology") is None
    assert js.find_style(None) is None
    assert js.find_style("  ") is None


def test_неизвестный_журнал_не_ломает_генерацию() -> None:
    """Справочник статей не должен блокировать работу из-за нового журнала."""
    assert js.style_prompt("Journal of Marine Biology", "Introduction") == ""
    prompt = build_prompt("Introduction", "тема", SOURCES,
                          style=js.style_prompt("Journal of Marine Biology",
                                                "Introduction"))
    assert "ЖЁСТКИЕ ПРАВИЛА" in prompt


def test_контекст_подставляется_в_шаблон() -> None:
    prompt = build_prompt("Introduction", "о чём работа", SOURCES,
                          notes="использовать станции A и B",
                          style=js.style_prompt("Nature", "Introduction"))

    assert CONTEXT_MARKER not in prompt
    # В шаблоне не должно остаться мест под данные: их занимает контекст.
    assert "[ВСТАВЬТЕ" not in prompt
    assert "о чём работа" in prompt
    assert "станции A и B" in prompt
    assert "ИСТОЧНИКИ (1)" in prompt


def test_правила_цитирования_идут_после_стиля() -> None:
    """Шаблон задаёт тон, наши правила цитирования — жёстче и не теряются."""
    prompt = build_prompt("Introduction", "тема", SOURCES,
                          style=js.style_prompt("Nature", "Introduction"))

    assert prompt.index("Act as a senior scientific editor") < \
        prompt.index("ЖЁСТКИЕ ПРАВИЛА ЦИТИРОВАНИЯ")


def test_подстановка_работает_даже_без_заглушки() -> None:
    """Автор может удалить строку-заглушку — контекст всё равно уходит."""
    assert apply_style("Короткий шаблон.", "КОНТЕКСТ") == \
        "Короткий шаблон.\n\nКОНТЕКСТ"
    assert apply_style(f"До\n{CONTEXT_MARKER}\nПосле", "К") == \
        "До\nК\nПосле"


def test_описание_стиля_берётся_из_промпта() -> None:
    """Что покажет интерфейс — должно совпадать с текстом промпта.

    Описание не дублируется в `meta.toml`: иначе первая же правка тона в
    шаблоне разъедет его с подписью в интерфейсе.
    """
    nature = js.find_style("Nature")

    highlights = nature.highlights()
    prompt = nature.template_for("Introduction").prompt
    assert highlights
    for line in highlights:
        assert line.split(":", 1)[1].strip() in prompt
    assert any(line.startswith("TONE:") for line in highlights)


def test_у_группы_без_аудитории_остаётся_тон() -> None:
    """Не у каждого промпта есть TARGET AUDIENCE — это не повод падать."""
    engineering = js.find_style("NeurIPS")

    assert [line.split(":", 1)[0] for line in engineering.highlights()] \
        == ["TONE"]


def test_справочник_для_интерфейса_собран_из_файлов() -> None:
    options = js.style_options()

    assert options
    for item in options:
        assert item["key"] and item["title"] and item["journals"]
        assert item["highlights"]
        assert item["templates"]
        assert all(tpl["label"] and tpl["sections"] for tpl in item["templates"])


def test_правка_файла_пересобирает_кэш(tmp_path: Path, monkeypatch) -> None:
    """Справочник перечитывается без перезапуска — точечный кэш по mtime."""
    monkeypatch.setattr(js, "PROMPTS_ROOT", tmp_path)
    group = tmp_path / "demo"
    group.mkdir()
    (group / "meta.toml").write_text(
        'key = "demo"\ntitle = "Демо"\ndefault_template = "a.md"\n'
        '[[templates]]\nfile = "a.md"\nlabel = "A"\nsections = ["a"]\n',
        encoding="utf-8")
    (group / "a.md").write_text("Первый текст.\n", encoding="utf-8")
    js.reload_styles()

    assert js.style_prompt("demo", "a").startswith("Первый текст")

    # Правка шаблона видна без перезапуска процесса.
    path = group / "a.md"
    path.write_text("Второй текст.\n", encoding="utf-8")
    os.utime(path, (0, 0))

    assert js.style_prompt("demo", "a").startswith("Второй текст")
    js.reload_styles()


def test_в_загруженных_шаблонах_нет_мест_под_данные() -> None:
    """Шаблон — только указания; данные приходят из источников, не из файла."""
    for style in js.styles():
        for template in style.templates:
            assert "[ВСТАВЬТЕ" not in template.prompt, template.file
            assert "[PASTE" not in template.prompt, template.file