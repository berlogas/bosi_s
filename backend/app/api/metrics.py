"""Метрики в формате Prometheus (`/metrics`) — Фаза 9.

Зависимость `prometheus_client` не тянем: платформа локальная, а нужны
 gauges-счётчики домена и несколько гистограмм. Формат текстовый, поэтому
Prometheus (или любой scraper) читает результат без агента на стороне Python.

Метрики:
  * доменные gauge из БД — сессии по статусам, документы, сообщения, версии;
  * задачи — активные, завершённые, ошибки (из реестра Фазы 8);
  * время выполнения задач — гистограмма;
  * uptime процесса.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Document, Message, ProjectVersion, ResearchSession
from app.db.session import get_db
from app.services.tasks import TaskStatus, tasks

router = APIRouter(prefix="/api", tags=["metrics"])

STARTED_AT = time.time()


def _gauge(name: str, value: Any, labels: dict[str, str] | None = None,
           help_text: str = "") -> str:
    label_str = ""
    if labels:
        parts = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        label_str = "{" + parts + "}"
    head = f"# HELP {name} {help_text}\n" if help_text else ""
    return f"{head}# TYPE {name} gauge\n{name}{label_str} {value}\n"


def _count_gauge(name: str, rows: Iterable[tuple[Any, int]],
                 label: str, help_text: str) -> list[str]:
    out = [f"# HELP {name} {help_text}", f"# TYPE {name} gauge"]
    for key, value in rows:
        out.append(f'{name}{{{label}="{key}"}} {value}')
    out.append("")
    return out


def _histogram(name: str, values: list[float],
               help_text: str = "") -> list[str]:
    """Простая гистограмма с фиксированными границами (секунды)."""
    buckets = [1, 5, 15, 60, 180, 600, 1800, 3600]
    out = [f"# HELP {name} {help_text}", f"# TYPE {name} histogram"]
    for bound in buckets:
        count = sum(1 for v in values if v <= bound)
        out.append(f'{name}_bucket{{le="{bound}"}} {count}')
    out.append(f'{name}_bucket{{le="+Inf"}} {len(values)}')
    total = sum(values)
    out.append(f"{name}_sum {total:.2f}")
    out.append(f"{name}_count {len(values)}")
    out.append("")
    return out


def collect(db: Session) -> str:
    lines: list[str] = []

    lines.append(_gauge("boasi_uptime_seconds", int(time.time() - STARTED_AT),
                        help_text="Время работы процесса backend"))

    sessions_by_status = db.execute(
        select(ResearchSession.status, func.count())
        .group_by(ResearchSession.status)).all()
    lines += _count_gauge(
        "boasi_sessions", [(getattr(s, "value", str(s)), int(c))
                           for s, c in sessions_by_status],
        "status", "Количество исследовательских сессий по статусам")

    lines.append(_gauge(
        "boasi_documents_total",
        int(db.scalar(select(func.count()).select_from(Document)) or 0),
        help_text="Документы в реестре (сессии + глобальная база)"))

    documents_by_category = db.execute(
        select(Document.category, func.count())
        .where(Document.session_id.is_not(None))
        .group_by(Document.category)).all()
    lines += _count_gauge(
        "boasi_session_documents",
        [(getattr(c, "value", str(c)), int(n)) for c, n in documents_by_category],
        "category", "Документы сессий по категориям")

    lines.append(_gauge("boasi_doc_chunks_total",
                        int(db.scalar(select(func.coalesce(
                            func.sum(Document.chunks_count), 0))) or 0),
                        help_text="Суммарное число чанков в реестре"))
    lines.append(_gauge("boasi_messages_total",
                        int(db.scalar(select(func.count())
                                      .select_from(Message)) or 0),
                        help_text="Сообщения в истории чата"))
    lines.append(_gauge("boasi_project_versions_total",
                        int(db.scalar(select(func.count())
                                      .select_from(ProjectVersion)) or 0),
                        help_text="Снапшоты генераций статей"))

    all_tasks = tasks.list(limit=1000)
    by_status: dict[str, int] = {}
    for task in all_tasks:
        by_status[task.status.value] = by_status.get(task.status.value, 0) + 1
    lines.append(_gauge("boasi_tasks_active", tasks.active_count(),
                        help_text="Активные фоновые задачи"))
    lines += _count_gauge("boasi_tasks", sorted(by_status.items()), "status",
                          "Фоновые задачи по статусам")

    durations = [t.seconds for t in all_tasks
                 if t.seconds is not None and t.status is TaskStatus.done]
    if durations:
        lines += _histogram("boasi_task_duration_seconds", durations,
                            "Длительность выполненных фоновых задач")

    return "\n".join(lines)


@router.get("/metrics", include_in_schema=False)
def metrics(db: Session = Depends(get_db)) -> Response:
    """Prometheus-совместимый текст. Не требует аутентификации (локальный контур)."""
    return Response(content=collect(db), media_type="text/plain; version=0.0.4")


@router.get("/metrics.json")
def metrics_json(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Тот же срез в JSON — для быстрой проверки глазами."""
    return {
        "uptime_seconds": int(time.time() - STARTED_AT),
        "tasks_active": tasks.active_count(),
        "documents": int(db.scalar(select(func.count())
                                    .select_from(Document)) or 0),
        "chunks": int(db.scalar(select(func.coalesce(
            func.sum(Document.chunks_count), 0))) or 0),
        "messages": int(db.scalar(select(func.count())
                                    .select_from(Message)) or 0),
        "project_versions": int(db.scalar(select(func.count())
                                             .select_from(ProjectVersion)) or 0),
    }