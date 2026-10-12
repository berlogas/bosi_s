"""Профилирование одного вопроса: на что уходит время ответа.

Замер разбивает запрос на этапы, которые видно в интерфейсе по стадиям:
  * сводки фрагментов (по каждой коллекции отдельно, с указанием режима);
  * повтор без сводок, если LLM отверг все контексты;
  * генерация ответа;
  * постобработка (цитаты, grounding) — остаток от общего времени.

Зачем: по облачному API время ответа упирается в число сетевых вызовов
(1 вызов на фрагмент), поэтому «медленно» обычно означает «много фрагментов
и половина вызовов впустую». На GPU с локальной Ollama картина другая, и
оптимальные настройки другие же.

Запуск из каталога backend:
    ../.venv/Scripts/python.exe scripts/profile_answer.py "вопрос" --session-id ID
    ../.venv/Scripts/python.exe scripts/profile_answer.py "вопрос" --repeat 3

Ключ кэша обходится (`use_cache=False`), иначе повторные прогоны показывали бы
время чтения из кэша вместо реальной работы.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# скрипт лежит в backend/scripts/, а пакет app — в backend/; без этого
# запускать из корня нельзя
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.models import SearchMode
from app.db.session import session_scope
from app.services import rag_service as rs
from app.services.paperqa_service import PaperQA2Service
from app.services.rag_service import RagFusionService

SID_KEY = "session_id"


@dataclass
class Stage:
    """Один замер: что делали, сколько заняло, сколько объектов получили."""

    name: str
    seconds: float
    objects: int
    parallel: bool = False

    def line(self) -> str:
        note = "  (параллельно)" if self.parallel else ""
        return f"  {self.name:<38}{self.seconds:7.1f}s   -> {self.objects}{note}"


class Profiler:
    """Обёртка над сервисами PaperQA, которая запоминает время каждой стадии."""

    def __init__(self) -> None:
        self.stages: list[Stage] = []
        self._patched: list[tuple[Any, str, Any]] = []

    def install(self) -> None:
        # Стадия `evidence` измеряется целиком по стенным часам. Внутри неё
        # сводки по коллекциям идут ПАРАЛЛЕЛЬНО (asyncio.gather), поэтому их
        # времена не складываются: коллекция global заняла бы 40 с, session 30 с,
        # а весь этап — 50 с. Коллекции показываются справочно, в сумму не идут.
        self._patch(rs.RagFusionService, "_evidence", self.evidence)
        self._patch(PaperQA2Service, "get_evidence", self.get_evidence)
        self._patch(PaperQA2Service, "ask", self.ask)

    def remove(self) -> None:
        for target, name, original in reversed(self._patched):
            setattr(target, name, original)
        self._patched.clear()

    def _patch(self, target: Any, name: str, handler: Any) -> None:
        """Подменить метод класса на обёртку с замыканием.

        Обертку нельзя делать bound-методом `Profiler`: присвоенная классу
        функция получила бы экземпляр сервиса первым аргументом вместо
        оригинала. Поэтому обёртка — обычная функция, захватывающая handler.
        """
        original = target.__dict__.get(name)
        if original is None:
            original = getattr(target, name)
        self._patched.append((target, name, original))

        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await handler(original, *args, **kwargs)

        wrapper.__name__ = name
        setattr(target, name, wrapper)

    async def get_evidence(self, original: Any, *args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        result = await original(*args, **kwargs)
        scope = getattr(args[0], "collection", "")
        where = "session" if str(scope).startswith("session") else "global"
        mode = "без сводок" if kwargs.get("skip_summary") else "сводки"
        self.stages.append(Stage(
            f"сводки {where} ({mode})",
            time.perf_counter() - start,
            len(result[1].contexts),
            parallel=True,
        ))
        return result

    async def ask(self, original: Any, *args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        result = await original(*args, **kwargs)
        self.stages.append(Stage("генерация ответа", time.perf_counter() - start, 0))
        return result

    def sum_seconds(self) -> float:
        """Время для суммы: стадии не вложены и не идут параллельно.

        Стадии по коллекциям помечены `parallel=True` и не суммируются —
        они выполняются одновременно.
        """
        return sum(stage.seconds for stage in self.stages if not stage.parallel)

    async def evidence(self, original: Any, *args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        result = await original(*args, **kwargs)
        self.stages.append(Stage("evidence (сводки + rerank)",
                                 time.perf_counter() - start, len(result)))
        return result


async def profile_once(query: str, session_id: str | None, mode: SearchMode,
                       k: int, max_sources: int) -> float:
    profiler = Profiler()
    profiler.install()
    try:
        service = RagFusionService()
        start = time.perf_counter()
        with session_scope() as db:
            result = await service.answer(
                db, query=query, session_id=session_id, mode=mode,
                k=k, max_sources=max_sources, use_cache=False)
        total = time.perf_counter() - start
    finally:
        profiler.remove()

    print(f"\nВопрос: {query}")
    print(f"Режим: {mode.value}, k={k}, max_sources={max_sources}")
    for stage in profiler.stages:
        print(stage.line())
    rest = total - profiler.sum_seconds()
    print(f"  {'постобработка (цитаты, grounding)':<38}{rest:7.1f}s   -> -")
    print(f"  {'ВСЕГО':<38}{total:7.1f}s")
    print(f"Источников в ответе: {len(result.sources)} "
          f"(процитировано: {result.stats['citations']['cited']})")
    print(f"Текст: {result.answer.formatted_answer.strip()[:200]}")
    return total


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="вопрос для замера")
    parser.add_argument("--session-id", default=None,
                        help="сессия; без неё доступна только глобальная база")
    parser.add_argument("--mode", default="hybrid",
                        choices=[m.value for m in SearchMode])
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--max-sources", type=int, default=8)
    parser.add_argument("--repeat", type=int, default=1,
                        help="сколько раз замерить: LLM недетерминирован, "
                             "разброс времени бывает в разы")
    args = parser.parse_args()

    logging.basicConfig(level=logging.ERROR)
    from app.config import get_settings

    settings = get_settings()
    print(f"Модель: {settings.llm_model}")
    print(f"Сводки: evidence_skip_summary={settings.evidence_skip_summary}, "
          f"evidence_k={settings.evidence_k}, "
          f"max_concurrent_requests={settings.max_concurrent_requests}")
    print(f"Эмбеддинги: {settings.embedding_model}")

    times = []
    for attempt in range(1, args.repeat + 1):
        print(f"\n=== прогон {attempt} из {args.repeat} ===")
        times.append(await profile_once(
            args.query, args.session_id, SearchMode(args.mode),
            args.k, args.max_sources))

    if len(times) > 1:
        print(f"\nВремя по прогонам: "
              f"{', '.join(f'{t:.1f}s' for t in times)}")
        print(f"Минимум {min(times):.1f}s, максимум {max(times):.1f}s — "
              "разброс объясняет, от чего настраивать.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
