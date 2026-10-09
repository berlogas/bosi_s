"""Массовая загрузка файлов из inbox: скан, индексация, перенос в библиотеку.

Зачем так сложно. Основной режим — Docker, где внутрь контейнера нельзя
просто «положить папку»: наружу торчит только то, что смонтировано в
`docker-compose.yml`. Поэтому вводится папка-приёмник:

    /data/inbox      ← монтируется на хост, человек кладёт сюда файлы
    /data/documents/library/YYYY-MM/  ← постоянное хранилище, на него ссылается БД
    /data/rejected/  ← нечитаемое (битый PDF, неподдерживаемый тип), чистит человек

Один прогон = один абзац БД в `inbox_runs` и по строке на файл в
`inbox_files` (конечный автомат: discovered → parsed → indexed → archived).
Отчёт живёт в БД, а не в логе: если процесс упал посреди прогона, это видно
(`status='running'` после рестарта) и повторяемо, а не теряется в stdout.

**Протокол безопасной записи.** Ключевой момент — файл нельзя удалять из
inbox раньше, чем в БД появится новый путь. Порядок:

    index (файл ещё в inbox)
      → move во временное имя в библиотеке
      → UPDATE documents.path
      → unlink из inbox

Обрыв между шагами даёт один из двух исходов: файл ещё в inbox (следующий
скан его подхватит) или уже в библиотеке с валидным путём в БД. Состояний
«файла нет нигде, а БД на него ссылается» не возникает. Для сбора мусора
после обрыва есть `reconcile_interrupted()`: временные файлы в библиотеке
удаляются, незакрытые прогоны закрываются с причиной.

**Замена файла.** Считается, что новый файл с тем же именем — это исправленная
или более качественная версия: старый документ удаляется вместе с индексом,
новый индексируется, в журнале остаётся запись с `reason_code='replaced'`.

Автоматического скана по расписанию нет намеренно: срабатывание без
человека опасно (кто-то положил файлы и ждёт ответа), а «проверить rejected»
должен оставаться ручным действием.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.errors import AppError, ConflictError, NotFoundError
from app.db.models import (
    Document,
    InboxFile,
    InboxFileStatus,
    InboxRun,
    InboxRunStatus,
    User,
)
from app.db.repositories import documents as docs_repo

log = logging.getLogger("boasi.inbox")

# Коды причин: машиночитаемо для UI/логов, reason_text — для человека.
REASON_UNSUPPORTED = "unsupported_extension"
REASON_TOO_LARGE = "too_large"
REASON_PARSE = "parse_error"
REASON_DISK = "disk_error"
REASON_REPLACED = "replaced"
REASON_INTERRUPTED = "interrupted"

_TEMP_SUFFIX = ".inbox-partial"


class InboxBusyError(ConflictError):
    """Прогон уже идёт: два скана одновременно запускать нельзя."""


def _now() -> datetime:
    return datetime.now(UTC)


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def _within(child: Path, parent: Path) -> bool:
    """Путь внутри каталога (после resolve — симлинки и «..» учтены)."""
    try:
        child.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _unique_path(target: Path) -> Path:
    """Не перетирать существующий файл: `report.pdf` → `report (2).pdf`."""
    if not target.exists():
        return target
    stem, suffix, parent = target.stem, target.suffix, target.parent
    for n in range(2, 1000):
        candidate = parent / f"{stem} ({n}){suffix}"
        if not candidate.exists():
            return candidate
    raise AppError(f"Слишком много файлов с именем {target.name}")


def discover(inbox_dir: Path, settings: Settings) -> list[Path]:
    """Все файлы под inbox, рекурсивно, без служебных и скрытых."""
    if not inbox_dir.exists():
        return []
    found: list[Path] = []
    for path in sorted(inbox_dir.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(inbox_dir).parts
        if any(part.startswith(".") or part == "__pycache__" for part in rel_parts):
            continue
        if path.suffix == _TEMP_SUFFIX:
            continue
        found.append(path)
    return found


class InboxService:
    """Сканер inbox. Живёт в БД, поэтому переживает рестарт процесса."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.app = settings or get_settings()
        # Ссылка на сервис глобальной коллекции: нужна, чтобы при замене
        # файла убрать прежний документ из индекса PaperQA, а не только из БД.
        self._service: Any | None = None

    def bind(self, service: Any) -> InboxService:
        self._service = service
        return self

    # ------------------------------------------------------------- свойства
    @property
    def inbox_dir(self) -> Path:
        return self.app.resolved_inbox_dir

    @property
    def library_dir(self) -> Path:
        return self.app.resolved_library_dir

    @property
    def rejected_dir(self) -> Path:
        return self.app.resolved_rejected_dir

    def peek(self, db: Session | None = None) -> dict[str, Any]:
        """Что лежит в inbox сейчас — для включения кнопки в UI.

        Считаем только поддерживаемые расширения: кнопка «Запустить массовое
        добавление» должна гореть ради файлов, которые вообще можно принять.
        """
        allowed = {e.lower() for e in self.app.allowed_extensions}
        files = discover(self.inbox_dir, self.app)
        usable = [p for p in files if p.suffix.lower() in allowed]
        return {
            "inbox_dir": str(self.inbox_dir),
            "exists": self.inbox_dir.exists(),
            "files": len(files),
            "usable_files": len(usable),
            "unsupported_files": len(files) - len(usable),
            "bytes": sum(p.stat().st_size for p in files),
            "busy": self._running_run(db) is not None,
        }

    def _running_run(self, db: Session | None = None) -> InboxRun | None:
        from app.db.session import get_session_factory

        factory = get_session_factory()
        if factory is None:
            # вне приложения (тесты, CLI) фабрики нет — прогонов не бывает
            return None
        own = db is None
        session = db or factory()
        try:
            return session.scalar(
                select(InboxRun).where(InboxRun.status == InboxRunStatus.running))
        finally:
            if own:
                session.close()

    # ------------------------------------------------------------- прогоны
    def start_run(self, db: Session, actor: User) -> InboxRun:
        """Открыть прогон. Если уже есть незакрытый — это обрыв, а не запрет.

        Прерванный прогон закрывается с причиной (файлы получают
        `interrupted`), чтобы «повторить» можно было осознанно, а файл не
        потерялся молча.
        """
        running = db.scalar(select(InboxRun).where(InboxRun.status == InboxRunStatus.running))
        if running is not None:
            self._fail_run(db, running, "Прогон прерван (процесс перезапущен).")
        run = InboxRun(
            trigger="manual",
            status=InboxRunStatus.running,
            inbox_dir=str(self.inbox_dir),
            started_at=_now(),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        log.info("inbox: начат прогон %s актором %s", run.id, actor.username)
        return run

    def finish_run(self, db: Session, run: InboxRun, error: str | None = None) -> InboxRun:
        run.status = InboxRunStatus.failed if error else InboxRunStatus.done
        run.error = error
        run.finished_at = _now()
        db.commit()
        db.refresh(run)
        return run

    def _fail_run(self, db: Session, run: InboxRun, error: str) -> None:
        for row in db.scalars(
            select(InboxFile).where(
                InboxFile.run_id == run.id,
                InboxFile.status.in_([
                    InboxFileStatus.discovered,
                    InboxFileStatus.parsed,
                    InboxFileStatus.indexed,
                ]),
            )
        ):
            row.status = InboxFileStatus.failed
            row.reason_code = REASON_INTERRUPTED
            row.reason_text = error
        run.status = InboxRunStatus.failed
        run.error = error
        run.finished_at = _now()
        db.commit()

    def reconcile_interrupted(self, db: Session) -> int:
        """Закрыть прогоны, оставшиеся `running` после рестарта, и убрать
        временные файлы `*.inbox-partial` из библиотеки."""
        closed = 0
        for run in db.scalars(
            select(InboxRun).where(InboxRun.status == InboxRunStatus.running)
        ):
            self._fail_run(db, run, "Прогон прерван: процесс был перезапущен.")
            closed += 1
        for leftover in self.library_dir.rglob(f"*{_TEMP_SUFFIX}"):
            leftover.unlink(missing_ok=True)
            log.warning("inbox: убран незавершённый файл %s", leftover)
        return closed

    # ------------------------------------------------------------- обработка
    async def scan(self, db: Session, service: Any, actor: User) -> InboxRun:
        """Полный цикл: разбор папки → индекс → перенос в библиотеку.

        `service` — `PaperQA2Service` глобальной коллекции: индексация
        блокирующая (чанки + эмбеддинги), поэтому выполняется в фоне
        задачи, а не в HTTP-запросе.
        """
        run = self.start_run(db, actor)
        self._service = service
        if not self.inbox_dir.exists():
            run.scanned = 0
            return self.finish_run(db, run)

        try:
            for path in discover(self.inbox_dir, self.app):
                await self._process_file(db, run, path, service, actor)
        except Exception as exc:  # прогон не должен молча «успеть»
            log.exception("inbox: прогон %s прерван", run.id)
            return self.finish_run(db, run, error=f"{type(exc).__name__}: {exc}")
        return self.finish_run(db, run)

    def _probe(self, path: Path) -> tuple[str, int, str | None]:
        """Относительный путь, размер и sha256. Ошибка чтения не фатальна:
        файл без хэша всё равно можно отправить на индексацию."""
        rel = str(path.relative_to(self.inbox_dir)).replace("\\", "/")
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        try:
            digest = sha256_of(path)
        except OSError as exc:
            log.warning("inbox: не удалось посчитать хэш %s: %s", path, exc)
            digest = None
        return rel, size, digest

    async def _process_file(
        self, db: Session, run: InboxRun, path: Path, service: Any, actor: User
    ) -> None:
        # Хэш и размер считаем в потоке: файлы бывают на сотни мегабайт,
        # а scan идёт в фоновой задаче и не должен блокировать event loop.
        rel, size_bytes, digest = await anyio.to_thread.run_sync(self._probe, path)
        row = InboxFile(
            run_id=run.id,
            rel_path=rel,
            abs_path=str(path),
            size_bytes=size_bytes,
            sha256=digest,
        )
        db.add(row)
        run.scanned += 1
        db.commit()

        # ---- 0. приём по типу и размеру
        if path.suffix.lower() not in {e.lower() for e in self.app.allowed_extensions}:
            self._reject(db, run, row, REASON_UNSUPPORTED,
                         f"Неподдерживаемый тип файла: {path.suffix or '(без расширения)'}")
            return
        limit_bytes = self.app.upload_max_mb * 1024 * 1024
        if row.size_bytes > limit_bytes:
            self._reject(db, run, row, REASON_TOO_LARGE,
                         f"Файл больше {self.app.upload_max_mb} МБ")
            return

        # ---- 1. замена одноимённого документа
        replaced = await self._replace_existing(db, path)
        if replaced is not None:
            row.reason_code = REASON_REPLACED
            # `document_id` намеренно не заполняем: прежний документ удалён,
            # ссылка на него была бы нарушением FK. След замены остаётся
            # в reason_text — этого достаточно для отчёта.
            row.reason_text = (
                f"Заменён прежний документ «{replaced.filename}»: "
                "файл с тем же именем считается исправленной версией")
            run.replaced += 1
            db.commit()

        # ---- 2. индексация
        try:
            ref = await service.add_file(str(path), title=path.stem)
        except Exception as exc:
            self._fail(db, run, row, REASON_PARSE,
                       f"Не удалось проиндексировать: {type(exc).__name__}: {exc}")
            return
        if ref is None:
            # Точное совпадение содержимого с уже загруженным — это не ошибка.
            row.status = InboxFileStatus.archived
            row.stage = "archived"
            row.reason_code = REASON_REPLACED
            row.reason_text = "Такой файл уже есть в библиотеке — повторно не индексируем"
            run.archived += 1
            db.commit()
            self._archive_file(db, row, path, keep_in_inbox=False)
            return

        document = docs_repo.upsert_document(
            db,
            dockey=ref.dockey,
            docname=ref.docname or path.stem,
            title=ref.title or path.stem,
            filename=path.name,
            path=ref.path,
            size_bytes=ref.size_bytes or row.size_bytes,
            pages=ref.pages,
            chunk_count=ref.chunk_count,
            citation=ref.citation,
            content_hash=ref.content_hash,
            source="inbox",
            owner_user_id=actor.id,
            added_by=actor.id,
        )
        row.document_id = document.id
        row.status = InboxFileStatus.indexed
        row.stage = "indexed"
        run.indexed += 1
        db.commit()

        # ---- 3. безопасный перенос в библиотеку
        final = self._archive_file(db, row, path, document=document)
        if final is not None:
            run.archived += 1
        db.commit()

    def _reject(self, db: Session, run: InboxRun, row: InboxFile,
                code: str, text: str) -> None:
        row.status = InboxFileStatus.rejected
        row.stage = "rejected"
        row.reason_code = code
        row.reason_text = text
        run.rejected += 1
        db.commit()
        target = self._move_to_rejected(row)
        row.final_path = str(target) if target else None
        db.commit()

    def _move_to_rejected(self, row: InboxFile) -> Path | None:
        """Унести брак в `rejected/<дата>/` — чтобы inbox действительно опустел.

        Копирование, а не перенос: файл может оказаться полезным после
        починки, а unlink безвозвратен. Если места нет — файл остаётся в
        inbox, причина уже записана в журнал.
        """
        source = Path(row.abs_path)
        if not source.exists():
            return None
        stamp = _now().strftime("%Y-%m-%d")
        target_dir = self.rejected_dir / stamp
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            target = _unique_path(target_dir / source.name)
            shutil.copy2(source, target)
            source.unlink()
        except OSError as exc:
            log.warning("inbox: не удалось унести брак %s: %s", source, exc)
            row.reason_text = f"{row.reason_text}; перенос в rejected не удался: {exc}"
            return None
        return target

    def _archive_file(self, db: Session, row: InboxFile, source: Path,
                      document: Document | None = None,
                      keep_in_inbox: bool = False) -> Path | None:
        """Перенести файл в постоянную библиотеку и обновить `documents.path`.

        Порядок именно такой (см. модуль-строку): сначала move, потом UPDATE,
        и только потом удаление из inbox. Обрыв на любом шаге безопасен.
        """
        stamp = _now().strftime("%Y-%m")
        target_dir = self.library_dir / stamp
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            final = _unique_path(target_dir / source.name)
            staging = final.with_suffix(final.suffix + _TEMP_SUFFIX)
            shutil.move(str(source), str(staging))
        except OSError as exc:
            self._fail(db, row.run, row, REASON_DISK,
                       f"Не удалось перенести в библиотеку: {exc}")
            return None

        if document is not None:
            document.path = str(final)
            document.filename = final.name
            db.commit()

        staging.replace(final)  # атомарно «публикуем» файл
        row.final_path = str(final)
        row.status = InboxFileStatus.archived
        row.stage = "archived"
        if keep_in_inbox:
            pass
        return final

    async def _replace_existing(self, db: Session, path: Path) -> Document | None:
        """Удалить прежний документ с тем же именем файла.

        Новая версия считается исправленной: старый документ уходит и из БД,
        и из индекса PaperQA. Удаление только из БД было бы недостаточно —
        `Docs.aadd` дедуплицирует по dockey и молча вернул бы «уже есть»,
        то есть в базу попал бы старый текст.

        Порядок именно такой: сначала индекс, потом строка в БД. Обрыв между
        шагами даёт «строка есть, документа в индексе нет» — такой случай
        чинится кнопкой «Переиндексировать всё», обратное (документ в индексе,
        строки нет) привело бы к «документу без источника».
        """
        old = db.scalar(
            select(Document).where(
                Document.session_id.is_(None),
                Document.filename == path.name,
            )
        )
        if old is None:
            return None
        try:
            if old.dockey and self._service is not None:
                await self._service.delete_document(dockey=old.dockey)
        except Exception as exc:
            log.warning("inbox: не удалось убрать прежний документ из индекса: %s", exc)
        try:
            db.delete(old)
            db.commit()
        except Exception as exc:  # не мешаем новому файлу из-за старого
            db.rollback()
            log.warning("inbox: не удалось удалить прежний документ %s: %s", old.id, exc)
            return None
        self._drop_stale_file(old)
        return old

    def _drop_stale_file(self, old: Document) -> None:
        """Удалить прежний файл из библиотеки.

        Иначе он остался бы навсегда: новая версия получила бы имя
        «report (2).txt», и в папке копились бы superseded-версии, на которые
        больше никто не ссылается.
        """
        if not old.path:
            return
        path = Path(old.path)
        if not _within(path, self.library_dir) or not path.is_file():
            return
        try:
            path.unlink()
            log.info("inbox: удалён прежний файл %s", path.name)
        except OSError as exc:
            log.warning("inbox: не удалось удалить прежний файл %s: %s", path, exc)

    def _fail(self, db: Session, run: InboxRun, row: InboxFile,
              code: str, text: str) -> None:
        row.status = InboxFileStatus.failed
        row.stage = "failed"
        row.reason_code = code
        row.reason_text = text
        row.attempts += 1
        run.failed += 1
        db.commit()

    # ------------------------------------------------------------- отчёты
    def runs(self, db: Session, limit: int = 20) -> list[InboxRun]:
        return list(db.scalars(
            select(InboxRun).order_by(InboxRun.started_at.desc()).limit(limit)))

    def files_of(self, db: Session, run_id: str) -> list[InboxFile]:
        return list(db.scalars(
            select(InboxFile).where(InboxFile.run_id == run_id)
            .order_by(InboxFile.rel_path)))

    def get_run(self, db: Session, run_id: str) -> InboxRun:
        run = db.get(InboxRun, run_id)
        if not run:
            raise NotFoundError("Прогон не найден")
        return run

    def clear_rejected(self, db: Session) -> int:
        """Очистить каталог rejected (файлы уже записаны в жур��ал)."""
        removed = 0
        if self.rejected_dir.exists():
            for path in sorted(self.rejected_dir.rglob("*"), reverse=True):
                try:
                    if path.is_file():
                        path.unlink()
                        removed += 1
                    else:
                        path.rmdir()
                except OSError as exc:
                    log.warning("inbox: не удалось удалить %s: %s", path, exc)
        return removed
