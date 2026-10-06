"""Проверка обоснованности ответа: утверждения без поддержки в контексте.

PaperQA валидирует только **ключи** цитат (`pqac-…`), но не то, что само
утверждение следует из найденного фрагмента. Именно поэтому ответ может
быть красиво «процитирован» и при этом содержать выдуманную родословную.

Здесь — дешёвая эвристика без LLM и без сети:

1. из ответа вырезаются «сущности»: именованные последовательности
   (`Пётр Фёдорович`, `Наполеон I`, `Смольный институт`), годы и числа
   от двух разрядов;
2. каждая сущность сверяется с найденным контекстом: точное вхождение
   либо совпадение основ слов (длина ≥ 4) — это терпит склонения
   (`Екатерина` / `Екатерины`) и перестановки (`Григорий Орлов` против
   `Григорий Григорьевич Орлов`). Цифры и римские разряды (`1762`,
   `Пётр I`) требуют точного совпадения токена: основа слова тут не
   поможет, а именно такие конструкции чаще всего выдумываются;
3. то, чего нет в контексте, попадает в `ungrounded` и в `warnings`
   для лога, `stats["grounding"]` и интерфейса.

Эвристика консервативна: одиночное заглавное слово в начале предложения
(`Я`, `Она`, `Её`) — это оформление, а не сущность, поэтому ложные
срабатывания редки. Она **не доказывает** истинность — она ловит самый
частый класс ошибок: факты, которых в источниках просто нет.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Разделение на предложения: [.!?] + пробел либо перевод строки.
_SENT_RE = re.compile(r"[.!?]+[\s]+|\n+")
# Именованная последовательность: заглавное слово + заглавные/римские/цифры.
# Римские — перед CAP_WORD и с отрицательным смотром на строчные: иначе «II»
# читается как «I», а «Cisco» — как «C».
_CAP_WORD = r"[А-ЯЁA-Z][а-яёa-z]*"
_ROMAN = r"[IVXLC]+"
_TAIL = rf"(?:{_ROMAN}(?![а-яёa-z])|{_CAP_WORD}|\d+)"
_SEQ_RE = re.compile(rf"{_CAP_WORD}(?:\s+{_TAIL})*")
# Годы и числа от двух разрядов (одиночные цифры — слишком шумны).
_NUM_RE = re.compile(r"\b\d{2,}(?:[.,]\d+)?\b|\b\d+[.,]\d+\b")
PREFIX_LEN = 4
_MAX_ITEMS = 20
# Хвост строки «Question: …» — служебный префикс formatted_answer paperqa.
_QUESTION_PREFIX_RE = re.compile(r"\A\s*Question:.*?\n\n", re.DOTALL)
# Токены, которым нужно точное совпадение: цифры и римские числа.
_DIGIT_TOKEN_RE = re.compile(r"^[0-9]+([.,][0-9]+)?$")
_ROMAN_TOKENS = {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x",
                 "xi", "xii", "xiii", "xiv", "xv", "xvi", "xvii", "xviii",
                 "xix", "xx"}


def _normalize(text: str) -> str:
    text = (text or "").lower().replace("ё", "е")
    text = re.sub(r"[^\wа-я]", " ", text)
    return " ".join(_fold_mixed_script(word) for word in text.split())


# Латиница → кириллица по транслитерации: модель иногда пишет имя
# частично латиницей («Гриgorия»), и такое слово не находится в
# контексте — проверка обоснованности даёт ложное срабатывание.
_LATIN_TO_CYR = str.maketrans({
    "a": "а", "b": "б", "c": "с", "d": "д", "e": "е", "f": "ф",
    "g": "г", "h": "х", "i": "и", "j": "й", "k": "к", "l": "л",
    "m": "м", "n": "н", "o": "о", "p": "р", "q": "к", "r": "р",
    "s": "с", "t": "т", "u": "у", "v": "в", "w": "в", "x": "х",
    "y": "у", "z": "з",
})
_CYRILLIC_RE = re.compile(r"[а-я]")
_LATIN_RE = re.compile(r"[a-z]")


def _fold_mixed_script(word: str) -> str:
    """Слово с кириллицей И латиницей → чистая кириллица (обе стороны одинаково).

    Чисто латинские слова не трогаем: римские цифры (`I`, `IV`) и
    названия вида `CTD` обязаны остаться как есть.
    """
    if _CYRILLIC_RE.search(word) and _LATIN_RE.search(word):
        return word.translate(_LATIN_TO_CYR)
    return word


def normalize_text(text: str) -> str:
    """Публичная нормализация для сопоставления (её же использует evalset)."""
    return _normalize(text)


def _context_index(contexts: list[str]) -> tuple[str, set[str], set[str]]:
    """(нормализованный текст, основы слов, точные токены) по контексту."""
    joined = " ".join(_normalize(part) for part in contexts if part)
    tokens = joined.split()
    stems = {w[:PREFIX_LEN] for w in tokens if len(w) >= PREFIX_LEN}
    return joined, stems, set(tokens)


def _grounded(entity: str, haystack: str, stems: set[str],
              tokens: set[str]) -> bool:
    norm = _normalize(entity).strip()
    if not norm:
        return True
    if norm in haystack:
        return True
    words = norm.split()
    for word in words:
        if len(word) >= PREFIX_LEN:
            if word[:PREFIX_LEN] not in stems:
                return False
        elif ((_DIGIT_TOKEN_RE.match(word) or word in _ROMAN_TOKENS)
              and word not in tokens):
            # «1762», «1,85», «I» — только точное совпадение.
            return False
        # короткие служебные токены не проверяем
    return True


def extract_mentions(text: str) -> list[str]:
    """Сущности ответа: именованные последовательности, годы, числа.

    Одиночное заглавное слово в начале предложения пропускается — это
    обычная заглавная (`Я родилась…`), а не имя собственное.
    """
    body = _QUESTION_PREFIX_RE.sub("", text or "").strip()
    mentions: list[str] = []
    seen: set[str] = set()

    def _add(value: str) -> None:
        key = _normalize(value).strip()
        if key and key not in seen:
            seen.add(key)
            mentions.append(value.strip())

    for sentence in _SENT_RE.split(body):
        if not sentence:
            continue
        stripped = sentence.lstrip("\"'«»()—- \t")
        for match in _SEQ_RE.finditer(stripped):
            if len(match.group(0).split()) == 1 and match.start() == 0:
                continue  # заглавная в начале предложения — не сущность
            _add(match.group(0))
        for match in _NUM_RE.finditer(sentence):
            _add(match.group(0))
    return mentions


def check_grounding(answer: str, contexts: list[str],
                    *, max_items: int = _MAX_ITEMS) -> GroundingReport:
    """Сверить сущности ответа с найденным контекстом."""
    report = GroundingReport()
    haystack, stems, tokens = _context_index(contexts)
    if not haystack:
        report.warnings.append(
            "Проверка обоснованности пропущена: нет найденного контекста")
        return report

    for mention in extract_mentions(answer):
        report.checked += 1
        if _grounded(mention, haystack, stems, tokens):
            report.grounded += 1
        elif len(report.ungrounded) < max_items:
            report.ungrounded.append(mention)
        else:
            report.overflow += 1

    if report.ungrounded:
        shown = ", ".join(report.ungrounded)
        extra = f" и ещё {report.overflow}" if report.overflow else ""
        report.warnings.append(
            "Утверждения не подтверждены найденными источниками: "
            f"{shown}{extra}")
    return report


@dataclass
class GroundingReport:
    """Отчёт обоснованности — контракт для логов, `stats` и интерфейса."""

    checked: int = 0
    grounded: int = 0
    ungrounded: list[str] = field(default_factory=list)
    overflow: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Все сущности ответа найдены в контексте (или проверять нечего)."""
        return not self.ungrounded

    @property
    def ratio(self) -> float:
        """Доля подтверждённых сущностей: 1.0, если нечего проверять."""
        if not self.checked:
            return 1.0
        return round(self.grounded / self.checked, 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checked": self.checked,
            "grounded": self.grounded,
            "ratio": self.ratio,
            "ungrounded": list(self.ungrounded),
            "warnings": list(self.warnings),
        }
