"""Перенумерация и починка цитат в ответах PaperQA.

Маркеры цитат: слабая LLM пишет «(степень 1)» вместо ключей pqac.
Чиним в ссылки [n] (нумерация источников в интерфейсе), удаляем
номера за пределами выдачи и прогоняем отчёт в лог/stats.

Служебные заголовки paperqa и повтор вопроса. Делаем после починки
цитат: citation_guard оперирует номерами [n], но текст на выходе
должен быть ровно таким, каким его увидит человек.
"""

from __future__ import annotations

import re

from paperqa.prompts import CANNOT_ANSWER_PHRASE

# Дружелюбный отказ вместо англоязычной заглушки paperqa («I cannot answer»).
# Формулировка совпадает с тем, что обещает system-промпт: ответа в
# источниках нет — говорим об этом прямо, а не подаём выдумку.
REFUSAL_TEXT = (
    "В предоставленных источниках нет информации, чтобы ответить на этот "
    "вопрос. Уточните запрос или загрузите документы с нужными данными."
)

# Заголовки, которые paperqa жёстко вписывает в formatted_answer
# (paperqa/types.py: `f"Question: {question}..."` и `f"\n\nReferences\n\n..."`).
# Приложение русскоязычное, поэтому переводим их на выходе. Правка самого
# ответа делается до repair_markers — тот работает по номерам [n] и заголовки
# не трогает, но текст меняется уже после починки, чтобы отчёт о починке
# показывал то, что видит пользователь.
_HEADER_LABELS = {
    "ru": (("References", "Ссылки"),),
    "en": (),
}


def localize_headers(text: str, language: str) -> str:
    """Перевести служебный заголовок paperqa «References» на язык приложения.

    Без `\s*$` в шаблоне: `\\s` съел бы и перевод строки, склеив заголовок с
    текстом ответа. Пустые строки вокруг сохраняем — по ним Markdown режет
    абзацы, без них ответ и список ссылок слипаются в одну строку.
    """
    if not text:
        return text
    for english, russian in _HEADER_LABELS.get((language or "ru").lower(), ()):
        text = re.sub(rf"(?m)^{re.escape(english)}$", russian, text)
    return text


def strip_question_header(text: str, question: str) -> str:
    """Убрать повтор вопроса в начале ответа.

    paperqa начинает `formatted_answer` со строки «Question: <вопрос>», но в чате
    вопрос и так уже написан пользователем над ответом — в ответе он лишний.
    Удаляем только если это действительно наш вопрос (совпадение по тексту):
    иначе рискуем срезать первую строку содержательного ответа.
    """
    if not text or not question:
        return text
    lines = text.splitlines()
    if not lines:
        return text
    first = lines[0].strip()
    if not first.startswith("Question:"):
        return text
    echoed = first[len("Question:"):].strip()
    if echoed != question.strip():
        return text
    rest = lines[1:]
    while rest and not rest[0].strip():
        rest.pop(0)
    return "\n".join(rest)


def renumber_citations(text: str, used: list[int]) -> str:
    """Сдвинуть маркеры `[old]` в `[new]` по порядку номеров `used`.

    Учитывается и многoисточниковый формат «[4, 7]» — citation_guard собирает
    именно его, когда модель ссылается на несколько документов одним маркером.

    Замена делается одной регуляркой с подстановкой по словарю, а не цепочкой
    `str.replace`: при последовательных заменах («4→1», затем «1→2») старые
    номера затирали бы друг друга.
    """
    mapping = {old: new for new, old in enumerate(used, start=1)}

    def _sub(match: re.Match[str]) -> str:
        numbers = [int(part) for part in re.findall(r"\d{1,3}", match.group(1))]
        if not all(number in mapping for number in numbers):
            return match.group(0)
        # «[4, 7]» — несколько источников в одном маркере: переносим вместе.
        return "[" + ", ".join(str(mapping[number]) for number in numbers) + "]"

    return re.sub(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]", _sub, text)


def strip_references_block(text: str) -> str:
    """Убрать служебный список литературы в конце ответа paperqa.

    PaperQA дописывает в `formatted_answer` блок «References» со списком ключей
    (types.py:522). В интерфейсе тот же список показывается отдельным блоком
    «Источники» — и он полнее: с областью хранения, категорией и
    релевантностью. Дубликат убираем, экономя место; маркеры `[n]` внутри
    самого ответа остаются, они и нужны для связи утверждения с источником.
    """
    for heading in ("References", "Ссылки"):
        match = re.search(rf"(?m)^{heading}\s*$", text)
        if match and match.start() > 0:
            return text[:match.start()].rstrip() + "\n"
    return text


def apply_refusal(text: str) -> str | None:
    """Русский текст отказа, если paperqa ответил отказом; иначе `None`."""
    return REFUSAL_TEXT if CANNOT_ANSWER_PHRASE in (text or "") else None


__all__ = [
    "REFUSAL_TEXT",
    "apply_refusal",
    "localize_headers",
    "renumber_citations",
    "strip_question_header",
    "strip_references_block",
]
