"""Справочник требований журналов.

Стиль статьи — не абстракция, а конкретные числа: у журнала свой предел на
объём, своя структура разделов и свои правила ссылок. Модель их не знает,
а PaperQA2 тем более: у него в `PromptSettings` есть только шаблоны
цитирования, понятия журнала или стиля там нет вообще.

Поэтому требования хранятся здесь и подставляются текстом в промпт
генерации (`style_block`). Каждая запись выписана по официальному гайду
журнала, ссылка на который лежит в поле `source`: требования журналов
меняются, и молчаливая правка здесь опаснее её отсутствия.

Журнал, которого в справочнике нет, не блокирует работу: `journal_profile`
вернёт `None`, промпт соберётся как раньше, а в интерфейсе останется
свободный ввод.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class JournalProfile:
    """Требования одного журнала к рукописи."""

    key: str
    title: str
    publisher: str
    article_type: str
    aliases: tuple[str, ...] = ()
    abstract_words: int | None = None
    body_words: int | None = None
    references_limit: int | None = None
    style_notes: tuple[str, ...] = ()
    required_blocks: tuple[str, ...] = ()
    citation_style: str = ""
    section_notes: tuple[str, ...] = ()
    source: str = ""

    def limits(self) -> str:
        """Строкой о лимитах — их чаще всего и хотят увидеть."""
        parts: list[str] = []
        if self.abstract_words:
            parts.append(f"abstract до {self.abstract_words} слов")
        if self.body_words:
            parts.append(f"основной текст до {self.body_words} слов")
        if self.references_limit:
            parts.append(f"до {self.references_limit} источников")
        return ", ".join(parts)


NATURE = JournalProfile(
    key="nature",
    title="Nature",
    publisher="Nature Portfolio",
    article_type="Article",
    aliases=("nature", "природа"),
    abstract_words=200,
    body_words=2500,
    references_limit=50,
    citation_style=(
        "Нумерация по порядку появления; в тексте номер надстрочный, "
        "в квадратных скобках — только если его можно спутать с надстрочным"
    ),
    style_notes=(
        "Писать ясно и просто: статья рассчитана на читателя из другой области, "
        "жаргон и нестандартные сокращения — по минимуму",
        "Саммари-параграф до 200 слов: 2-3 предложения о поле, предпосылки, "
        "«Here we show…» с главным выводом и 2-3 предложения о том, как "
        "результаты двигают область",
        "Заголовки разделов — не длиннее 40 символов",
        "Методические детали уходят в Methods или в Supplementary Information, "
        "в тексте их быть не должно",
        "Технические подробности, уже опубликованные, пересказывать не нужно — "
        "достаточно ссылки на источник",
    ),
    required_blocks=(
        "Data Availability и Code Availability",
        "Author Contributions",
        "Competing Interests",
        "Acknowledgements",
        "Funding",
    ),
    section_notes=(
        "Порядок: заголовок, авторы, саммари-параграф, основной текст, "
        "подписи к рисункам, Methods, ссылки, благодарности",
        "Раздел Methods идёт после подписей к рисункам, в печатном выпуске "
        "не публикуется",
    ),
    source="https://www.nature.com/nature/for-authors/formatting-guide",
)

SCIENCE = JournalProfile(
    key="science",
    title="Science",
    publisher="AAAS",
    article_type="Research Article",
    aliases=("science", "сайенс"),
    abstract_words=125,
    body_words=2500,
    citation_style=(
        "Нумерация по порядку появления, номера в круглых скобках "
        "(1), (2) либо вверху страницы — по требованиям редактора"
    ),
    style_notes=(
        "Начинать с краткого введения о значимости работы: проблема и её важность",
        "Первое предложение должно уместить главный результат",
        "Язык простой, детали вынесены в Supplementary Materials",
        "Ограничение объёма жёсткое: за превышение пришлось бы сокращать "
        "работу перед приёмкой",
    ),
    required_blocks=(
        "Summary",
        "Materials and Methods / Supplementary Materials",
        "Acknowledgments",
        "References",
    ),
    section_notes=(
        "Research Article: Summary → Introduction → Results → Discussion "
        "→ Methods → Supplementary Materials → References",
        "Methods выносится в Supplementary Materials и в основном тексте "
        "только упоминается",
    ),
    source="https://www.science.org/content/page/instructions-authors-new-research-articles",
)

PLOS_ONE = JournalProfile(
    key="plos_one",
    title="PLOS ONE",
    publisher="Public Library of Science",
    article_type="Research Article",
    aliases=("plos one", "plos", "plosone"),
    abstract_words=300,
    body_words=None,  # ограничения нет
    citation_style=(
        "Стиль Vancouver (ICMJE): источники пронумерованы по порядку появления, "
        "в тексте номер в квадратных скобках, первые шесть авторов, далее et al."
    ),
    style_notes=(
        "Не переоценивать выводы: редакция оценивает корректность, "
        "а не значимость, поэтому «доказывает» и «впервые» — плохие слова",
        "Язык ясный и сжатый, но объём не ограничен",
        "Сокращения определять при первом появлении, нестандартные — "
        "только если встречаются не менее трёх раз",
        "Вид называется Results and Discussion, если разделы объединены",
    ),
    required_blocks=(
        "Title page",
        "Abstract",
        "Acknowledgments",
        "References",
    ),
    section_notes=(
        "Порядок: титульный лист, Abstract, Introduction, Materials and Methods, "
        "Results, Discussion, Conclusions (необязателен), Acknowledgments, References",
        "Разделы не более трёх уровней вложенности",
    ),
    source="https://journals.plos.org/plosone/s/submission-guidelines",
)

SCIENTIFIC_REPORTS = JournalProfile(
    key="scientific_reports",
    title="Scientific Reports",
    publisher="Nature Portfolio",
    article_type="Article",
    aliases=("scientific reports", "sci rep", "sr"),
    abstract_words=200,
    body_words=4500,
    references_limit=60,
    citation_style="Нумерация по порядку появления, номера в квадратных скобках",
    style_notes=(
        "Основной текст без Abstract, Methods, References и подписей к рисункам — "
        "не более 4500 слов",
        "В Abstract нельзя включать ссылки и рисунки",
        "Идеально не более 11 вёрстанных страниц",
        "Ключевые слова — 3-5 слов, определяют поиск статьи",
    ),
    required_blocks=(
        "Abstract",
        "Keywords",
        "References",
        "Data availability",
    ),
    section_notes=(
        "Порядок: Abstract → Introduction → Results → Discussion → Methods "
        "→ References",
        "Methods — отдельный раздел в конце, а не приложение",
    ),
    source="https://www.nature.com/srep/author-instructions/submission-guidelines",
)

GENERIC = JournalProfile(
    key="generic",
    title="Без требований",
    publisher="—",
    article_type="Research Article",
    aliases=("generic", "обычный", "по умолчанию"),
    style_notes=(
        "Ясный научный стиль без воды; каждое утверждение о фактах "
        "подкреплено ссылкой на источник"
    ),
    source="",
)

JOURNALS: tuple[JournalProfile, ...] = (
    NATURE,
    SCIENCE,
    PLOS_ONE,
    SCIENTIFIC_REPORTS,
    GENERIC,
)

# Поиск по ключу, названию и псевдонимам: поле в интерфейсе заполняют
# руками, «Nature», «nature» и «Nature  » должны найти одно и то же.
_BY_NAME: dict[str, JournalProfile] = {}
for _profile in JOURNALS:
    for _name in (_profile.key, _profile.title, *_profile.aliases):
        _BY_NAME.setdefault(_name.strip().lower(), _profile)


def journal_profile(name: str | None) -> JournalProfile | None:
    """Профиль журнала по названию; `None`, если журнала нет в справочнике."""
    clean = (name or "").strip().lower()
    return _BY_NAME.get(clean) if clean else None


def journal_options() -> list[dict[str, str]]:
    """Список для селектора: ключ, название и краткий лимит объёма."""
    return [
        {"key": profile.key,
         "title": profile.title,
         "article_type": profile.article_type,
         "limits": profile.limits(),
         "source": profile.source}
        for profile in JOURNALS
        if profile.key != "generic"
    ]


def style_block(profile: JournalProfile | None) -> str:
    """Требования журнала текстом для промпта — пустая строка, если нет."""
    if profile is None:
        return ""
    lines = [f"ТРЕБОВАНИЯ ЖУРНАЛА {profile.title.upper()} "
             f"({profile.article_type}, {profile.publisher}):"]
    if profile.limits():
        lines.append(f"- Лимиты: {profile.limits()}.")
    if profile.citation_style:
        lines.append(f"- Ссылки: {profile.citation_style}.")
    for note in profile.style_notes:
        lines.append(f"- {note}.")
    for note in profile.section_notes:
        lines.append(f"- Структура: {note}.")
    if profile.required_blocks:
        lines.append("- Обязательные блоки в конце работы: "
                     + ", ".join(profile.required_blocks) + ".")
    return "\n".join(lines)


__all__ = [
    "GENERIC",
    "JOURNALS",
    "JournalProfile",
    "journal_options",
    "journal_profile",
    "style_block",
]