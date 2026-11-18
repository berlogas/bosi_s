"""Стили журналов: конфигурация через внешний TOML файл.

Стили хранятся в `app/prompts/journal_styles/styles.toml` — это позволяет
добавлять новые стили и шаблоны без правки кода, просто редактируя файл.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field

from pathlib import Path
from typing import Any

PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts" / "journal_styles"
STYLES_TOML = PROMPTS_ROOT / "styles.toml"

# Куда в шаблоне вставляется контекст генерации. Обычно он не нужен:
# контекст дописывается в конец промпта. Маркер существует для случая,
# когда блок данных нужен в середине — так пишут отдельные авторы.
CONTEXT_MARKER = "{{CONTEXT}}"

# Строки-характеристики стиля в начале промпта: «TONE: ...»,
# «TARGET AUDIENCE: ...». По ним интерфейс показывает, что именно получит
# модель, не заставляя редактора дублировать текст в конфиге.
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
    description: str
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
        карточка группы; дублировать этот текст в конфиге нельзя —
        копия разъедется с промптом при первой же правке.
        """
        template = self.template_by_file(self.default_template)
        if template is None:
            return []
        return [f"{match.group(1).upper()}: {match.group(2)}"
                for match in _HIGHLIGHT_RE.finditer(template.prompt)]

    def description_lines(self) -> list[str]:
        """Строки описания для интерфейса: русский текст из конфига."""
        return [line for line in self.description.splitlines() if line.strip()]


# --------------------------------------------------------------------------- загрузка из TOML
def _load_styles_from_toml() -> tuple[JournalStyle, ...]:
    """Читает справочник стилей из styles.toml."""
    if not STYLES_TOML.is_file():
        return ()

    try:
        meta = tomllib.loads(STYLES_TOML.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as e:
        # Битый TOML не должен ронять сервис
        return ()

    styles: list[JournalStyle] = []
    for style_meta in meta.get("styles", []):
        style = _build_style(style_meta)
        if style is not None:
            styles.append(style)
    return tuple(styles)


def _build_style(meta: dict[str, Any]) -> JournalStyle | None:
    key = str(meta.get("key") or "").strip()
    title = str(meta.get("title") or "").strip()
    summary = str(meta.get("summary") or "").strip()
    description = str(meta.get("description") or "").strip()
    journals = tuple(str(name).strip() for name in meta.get("journals", [])
                     if str(name).strip())
    default = str(meta.get("default_template") or "").strip()

    templates: list[StyleTemplate] = []
    for item in meta.get("templates", []):
        if not isinstance(item, dict):
            continue
        file_name = str(item.get("file") or "").strip()
        path = PROMPTS_ROOT / file_name
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
    return JournalStyle(key=key, title=title, summary=summary,
                        description=description, journals=journals,
                        default_template=default, templates=tuple(templates))


# Кэш стилей с инвалидацией по mtime файла styles.toml и шаблонов
_styles_cache: tuple[JournalStyle, ...] | None = None
_styles_mtime: float = 0.0


def _compute_signature() -> float:
    """Вычисляет сигнатуру на основе mtime всех соответствующих файлов."""
    mtime = 0.0
    if STYLES_TOML.is_file():
        mtime = max(mtime, STYLES_TOML.stat().st_mtime)
    for template_path in PROMPTS_ROOT.rglob("*.md"):
        if template_path.is_file():
            mtime = max(mtime, template_path.stat().st_mtime)
    return mtime


def styles() -> tuple[JournalStyle, ...]:
    """Все группы стилей из TOML (кэш сбрасывается при правке файла)."""
    global _styles_cache, _styles_mtime
    
    if not STYLES_TOML.is_file():
        return ()
    
    current_signature = _compute_signature()
    if _styles_cache is not None and current_signature == _styles_mtime:
        return _styles_cache
    
    _styles_cache = _load_styles_from_toml()
    _styles_mtime = current_signature
    return _styles_cache


def find_style(name: str | None) -> JournalStyle | None:
    """Группа по её ключу или по названию журнала из списка группы."""
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


def get_suggested_section_plan(style_key: str | None) -> list[dict[str, Any]]:
    """Получить предложенный план разделов для стиля журнала."""
    style = find_style(style_key)
    if not style or not style.templates:
        return []

    seen = set()
    ordered_sections = []
    order = 1

    for template in style.templates:
        for section_name in template.sections:
            clean = section_name.strip().lower()
            if clean and clean not in seen:
                seen.add(clean)
                kind = "standard"
                if clean in ("literature review", "review", "related work", "background"):
                    kind = "literature_review"
                elif clean in ("methods", "materials", "materials and methods", "methodology"):
                    kind = "standard"
                elif clean in ("results", "findings"):
                    kind = "standard"
                elif clean in ("discussion", "conclusions", "conclusion"):
                    kind = "discussion"
                elif clean in ("abstract", "summary"):
                    kind = "standard"
                elif clean in ("introduction", "background"):
                    kind = "standard"

                ordered_sections.append({
                    "name": section_name.strip().title(),
                    "kind": kind,
                    "order": order,
                    "word_target": 500,
                    "notes": "",
                    "required": True,
                    "language": "ru",
                    "depends_on": [],
                })
                order += 1

    return ordered_sections


def style_options() -> list[dict[str, Any]]:
    """Справочник для интерфейса: группы, их журналы и разделы."""
    return [
        {
            "key": style.key,
            "title": style.title,
            "summary": style.summary,
            "journals": list(style.journals),
            "highlights": style.highlights(),
            "description": style.description,
            "description_lines": style.description_lines(),
            "templates": [
                {"label": template.label, "sections": list(template.sections)}
                for template in style.templates
            ],
        }
        for style in styles()
    ]


def reload_styles() -> None:
    """Сбросить кэш — нужно после правки styles.toml или шаблонов."""
    global _styles_cache, _styles_mtime
    _styles_cache = None
    _styles_mtime = 0.0


__all__ = [
    "CONTEXT_MARKER",
    "JournalStyle",
    "StyleTemplate",
    "find_style",
    "reload_styles",
    "style_options",
    "style_prompt",
    "styles",
    "get_suggested_section_plan",
]