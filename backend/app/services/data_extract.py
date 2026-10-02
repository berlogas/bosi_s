"""Извлечение сводки из табличных данных (Фаза 7).

Нужно для сравнения своих данных с литературой: LLM не умеет считать, а в
контексте лежит сырой CSV. Поэтому числа считаем сами, а модель получает уже
готовую сводку (минимум/максимум/среднее/количество) и текст задачи.

Поддерживаются CSV/TSV с разделителем, определяемым по расширению и по
содержимому. Нечитаемый или нечисловой файл не роняет генерацию — возвращается
сводка без статистики.
"""

from __future__ import annotations

import csv
import io
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("boasi.services.data_extract")

TABULAR_SUFFIXES = (".csv", ".tsv", ".txt")
MAX_ROWS_TO_SCAN = 20000
MAX_SAMPLE_ROWS = 3


def looks_tabular(path: str | Path) -> bool:
    return Path(path).suffix.lower() in TABULAR_SUFFIXES


def _delimiter(sample: str, suffix: str) -> str:
    if suffix == ".tsv":
        return "\t"
    try:
        return csv.Sniffer().sniff(sample, delimiters=";,\t|").delimiter
    except csv.Error:
        # русские выгрузки часто с «;» — дефолт csv не угадывает
        return ";" if sample.count(";") > sample.count(",") else ","


def _to_number(raw: str) -> float | None:
    text = (raw or "").strip().replace("\xa0", "").replace(" ", "")
    if not text:
        return None
    # запятая как десятичный разделитель: «1,85»
    if text.count(",") == 1 and "." not in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


@dataclass
class ColumnStats:
    name: str
    numbers: int = 0
    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None
    total: float | None = None

    def describe(self) -> str:
        if not self.numbers:
            return f"{self.name}: нет числовых значений"
        parts = [f"n={self.numbers}",
                 f"min={_round(self.minimum)}",
                 f"max={_round(self.maximum)}",
                 f"среднее={_round(self.mean)}"]
        if self.total is not None:
            parts.append(f"сумма={_round(self.total)}")
        return f"{self.name}: " + ", ".join(parts)


@dataclass
class DataSummary:
    """Сводка по таблице: то, что модель не сможет посчитать сама."""

    document_id: str | None = None
    title: str = ""
    filename: str = ""
    rows: int = 0
    columns: list[str] = field(default_factory=list)
    stats: list[ColumnStats] = field(default_factory=list)
    sample_rows: list[dict[str, str]] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.rows > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "title": self.title,
            "filename": self.filename,
            "rows": self.rows,
            "columns": self.columns,
            "stats": [{"name": s.name, "n": s.numbers, "min": s.minimum,
                       "max": s.maximum, "mean": s.mean, "total": s.total}
                      for s in self.stats],
            "sample_rows": self.sample_rows,
            "error": self.error,
        }

    def render(self) -> str:
        """Текст для промпта: компактно, но с числами."""
        if not self.ok:
            return (f"Данные «{self.title or self.filename}» не читаются "
                    f"как таблица: {self.error or 'нет строк'}")

        lines = [f"Таблица «{self.title or self.filename}»: строк {self.rows}, "
                 f"колонки: {', '.join(self.columns)}"]
        lines += ["  " + s.describe() for s in self.stats if s.numbers]
        if self.sample_rows:
            lines.append("  примеры строк:")
            for row in self.sample_rows:
                lines.append("    " + "; ".join(
                    f"{k}={v}" for k, v in row.items()))
        return "\n".join(lines)


def _round(value: float | None) -> str | None:
    if value is None:
        return None
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.4g}"


def summarize_file(path: str | Path, *, document_id: str | None = None,
                   title: str | None = None, max_rows: int = MAX_ROWS_TO_SCAN
                   ) -> DataSummary:
    """Сводка по CSV/TSV-файлу. Ошибки не поднимаются, а попадают в `.error`."""
    file = Path(path)
    summary = DataSummary(
        document_id=document_id,
        title=title or file.stem,
        filename=file.name,
    )
    try:
        raw = file.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        summary.error = f"{type(exc).__name__}: {exc}"
        return summary

    if not raw.strip():
        summary.error = "файл пуст"
        return summary

    delimiter = _delimiter(raw[:4096], file.suffix.lower())
    reader = csv.reader(io.StringIO(raw), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        summary.error = "нет строки заголовков"
        return summary

    summary.columns = [h.strip() for h in header]
    accumulators = [ColumnStats(name=h.strip() or f"col{i}")
                    for i, h in enumerate(summary.columns)]
    rows: list[dict[str, str]] = []
    total_rows = 0
    truncated = False

    for index, row in enumerate(reader):
        if index >= max_rows:
            truncated = True
            break
        if not any((cell or "").strip() for cell in row):
            continue
        total_rows += 1
        if len(rows) < MAX_SAMPLE_ROWS:
            rows.append({summary.columns[i] if i < len(summary.columns)
                         else f"col{i}": (row[i] if i < len(row) else "")
                         for i in range(len(summary.columns))})
        for i, column in enumerate(accumulators):
            value = _to_number(row[i]) if i < len(row) else None
            if value is None:
                continue
            column.numbers += 1
            column.minimum = value if column.minimum is None \
                else min(column.minimum, value)
            column.maximum = value if column.maximum is None \
                else max(column.maximum, value)
            column.total = (column.total or 0.0) + value

    summary.rows = total_rows
    summary.sample_rows = rows
    for column in accumulators:
        if column.numbers:
            column.mean = (column.total or 0.0) / column.numbers
        if column.numbers:
            summary.stats.append(column)

    if truncated:
        log.info("summarize_file: %s прочитан частично (%d строк)",
                 file.name, max_rows)
        summary.error = f"прочитано только {max_rows} строк"
    return summary


def summarize_documents(documents: Sequence[Any], *, limit: int = 5
                        ) -> list[DataSummary]:
    """Сводки по документам с ролью `data` (у них есть `path` на диске)."""
    summaries: list[DataSummary] = []
    for document in documents:
        path = getattr(document, "path", None)
        if not path or not looks_tabular(path):
            continue
        summaries.append(summarize_file(
            path, document_id=getattr(document, "id", None),
            title=getattr(document, "title", None)))
        if len(summaries) >= limit:
            break
    return summaries


def render_summaries(summaries: Sequence[DataSummary]) -> str:
    return "\n\n".join(s.render() for s in summaries) if summaries else ""