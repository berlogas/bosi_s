"""Стили журналов: внешние шаблоны промптов, сгруппированные по признакам.

Журналы не пишут сами за себя — их объединяет то, *как* они требуют писать.
Nature и PLOS ONE — это не «два разных журнала», а два разных способа
изложить результат; PRL и Nature Medicine — третий и четвёртый. Поэтому
в справочнике не журналы, а группы стилей, а журналы внутри группы
перечислены списком.

Промпты лежат файлами в `app/prompts/journal_styles/<группа>/`:

    meta.toml            группа: заголовок, журналы, список шаблонов
    <шаблон>.md          сам промпт на английском

Файлы, а не код, потому что промпт правится редактором статьи, а не
разработчиком, и новая группа добавляется копированием каталога — без
правки питона. Шаблоны намеренно на английском: академический английский у
моделей заметно лучше русского, а язык статьи задаётся отдельно.

Каждый шаблон — только указания: роль, аудитория, структура, тон и запреты.
Никаких мест под данные в нём нет — материалом служат задача, указания
автора и источники, и `apply_style` дописывает их в конец. Если редактору
нужно поставить блок данных в середину промпта, он вставляет маркер
`CONTEXT_MARKER` в нужное место, и данные встанут туда.

Стиль, который не нашёлся, — не ошибка: `style_prompt` вернёт пустую строку,
и генерация пойдёт по общим правилам. Справочник из статей не должен
блокировать работу из-за нового журнала.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts" / "journal_styles"

# Куда в шаблоне вставляется контекст генерации. Обычно он не нужен:
# контекст дописывается в конец промпта. Маркер существует для случая,
# когда блок данных нужен в середине — так пишут отдельные авторы.
CONTEXT_MARKER = "{{CONTEXT}}"

# Строки-характеристики стиля в начале промпта: «TONE: ...»,
# «TARGET AUDIENCE: ...». По ним интерфейс показывает, что именно получит
# модель, не заставляя редактора дублировать текст в meta.toml.
_HIGHLIGHT_LABELS = ("TARGET AUDIENCE", "TONE", "AUDIENCE", "ЦЕЛЕВАЯ АУДИТОРИЯ")
_HIGHLIGHT_RE = re.compile(
    r"^(" + "|".join(_HIGHLIGHT_LABELS) + r")\s*:\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class StyleTemplate:
    """Один промпт группы: под какой раздел и с каким заголовком."""

    file: str
    label: str
    sections: tuple[str, ...]
    prompt: str
    path: Path

    def matches(self, section: str) -> bool:
        """Подходит ли шаблон разделу — по вхождению слова в название.

        Сравнение по вхождению, а не равенству: раздел приходит от
        пользователя («Введение», «Related work», «Методы исследования»), и
        точное совпадение здесь было бы источником молчаливых промахов.
        """
        clean = (section or "").strip().lower()
        if not clean:
            return False
        return any(word in clean for word in self.sections)


@dataclass(frozen=True)
class JournalStyle:
    """Группа журналов с общим способом изложения."""

    key: str
    title: str
    summary: str
    journals: tuple[str, ...]
    default_template: str
    templates: tuple[StyleTemplate, ...] = field(default_factory=tuple)

    def template_for(self, section: str) -> StyleTemplate | None:
        """Шаблон под раздел; иначе — шаблон по умолчанию."""
        for template in self.templates:
            if template.matches(section):
                return template
        return self.template_by_file(self.default_template)

    def template_by_file(self, name: str) -> StyleTemplate | None:
        for template in self.templates:
            if template.file == name:
                return template
        return self.templates[0] if self.templates else None

    def highlights(self) -> list[str]:
        """Что этот стиль обещает модели: тон и читатель, словами промпта.

        Берётся из шаблона по умолчанию, потому что он и есть визитная
        карточка группы; дублировать этот текст в `meta.toml` нельзя —
        копия разъедется с промптом при первой же правке.
        """
        template = self.template_by_file(self.default_template)
        if template is None:
            return []
        return [f"{match.group(1).upper()}: {match.group(2)}"
                for match in _HIGHLIGHT_RE.finditer(template.prompt)]


# --------------------------------------------------------------------------- загрузка
def _signature(root: Path) -> tuple[tuple[str, int], ...]:
    """Отпечаток файлов: (путь, mtime) — меняется при правке промпта на диске."""
    return tuple(
        (str(path), path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*")) if path.is_file())


@lru_cache(maxsize=8)
def _load_cached(signature: tuple[tuple[str, int], ...]) -> tuple[JournalStyle, ...]:
    """Читает справочник. Кэш по отпечатку: правка файла пересобирает его."""
    del signature  # нужен только как ключ кэша
    styles: list[JournalStyle] = []
    if not PROMPTS_ROOT.is_dir():
        return ()
    for directory in sorted(p for p in PROMPTS_ROOT.iterdir() if p.is_dir()):
        meta_path = directory / "meta.toml"
        if not meta_path.is_file():
            continue
        try:
            meta: dict[str, Any] = tomllib.loads(
                meta_path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError):
            # Битый meta.toml не должен ронять сервис: без него группа просто
            # не появляется в справочнике.
            continue
        style = _build_style(meta, directory)
        if style is not None:
            styles.append(style)
    return tuple(styles)


def _build_style(meta: dict[str, Any], directory: Path) -> JournalStyle | None:
    key = str(meta.get("key") or directory.name).strip()
    title = str(meta.get("title") or key).strip()
    summary = str(meta.get("summary") or "").strip()
    journals = tuple(str(name).strip() for name in meta.get("journals", [])
                     if str(name).strip())
    default = str(meta.get("default_template") or "").strip()

    templates: list[StyleTemplate] = []
    for item in meta.get("templates", []):
        if not isinstance(item, dict):
            continue
        file_name = str(item.get("file") or "").strip()
        path = directory / file_name
        if not file_name or not path.is_file():
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        prompt = raw.strip()
        templates.append(StyleTemplate(
            file=file_name,
            label=str(item.get("label") or file_name).strip(),
            sections=tuple(str(word).strip().lower()
                           for word in item.get("sections", []) if str(word).strip()),
            prompt=prompt,
            path=path))
    if not templates:
        return None
    return JournalStyle(key=key, title=title, summary=summary, journals=journals,
                        default_template=default, templates=tuple(templates))


def styles() -> tuple[JournalStyle, ...]:
    """Все группы стилей с диска (кэш сбрасывается при правке файлов)."""
    if not PROMPTS_ROOT.is_dir():
        return ()
    return _load_cached(_signature(PROMPTS_ROOT))


def find_style(name: str | None) -> JournalStyle | None:
    """Группа по её ключу или по названию журнала из списка группы.

    Пользователь привык вводить журнал («Nature», «PLOS ONE»), а хранить
    надо ключ группы: журнал — это подпись, группа — это поведение.
    """
    clean = (name or "").strip().lower()
    if not clean:
        return None
    for style in styles():
        if clean == style.key.lower():
            return style
    for style in styles():
        if any(clean == journal.lower() for journal in style.journals):
            return style
    return None


def style_prompt(name: str | None, section: str) -> str:
    """Текст шаблона под раздел; пустая строка, если стиля или шаблона нет."""
    style = find_style(name)
    if style is None:
        return ""
    template = style.template_for(section)
    return template.prompt if template else ""


def style_options() -> list[dict[str, Any]]:
    """Справочник для интерфейса: группы, их журналы и разделы."""
    return [
        {
            "key": style.key,
            "title": style.title,
            "summary": style.summary,
            "journals": list(style.journals),
            "highlights": style.highlights(),
            "templates": [
                {"label": template.label, "sections": list(template.sections)}
                for template in style.templates
            ],
        }
        for style in styles()
    ]


def reload_styles() -> None:
    """Сбросить кэш — нужно после правки файлов в тестах."""
    _load_cached.cache_clear()


__all__ = [
    "CONTEXT_MARKER",
    "JournalStyle",
    "StyleTemplate",
    "find_style",
    "reload_styles",
    "style_options",
    "style_prompt",
    "styles",
]