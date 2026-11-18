"""Пути файлов в БД: хранение относительно DATA_DIR.

Зачем. Каталог данных один и тот же, но путь к нему в разных средах разный:
на машине разработчика это `./data` (Windows: `N:\\...\\data`), в контейнере —
`/data`. Если в БД лежит абсолютный путь, то запись, сделанная в одной среде,
в другой не находится: документ «исчезает», экспорт не может прочитать файл,
reaper не удалит его при purge.

Поэтому в БД путь хранится относительно `DATA_DIR` (`documents/uploads/a.md`),
а наружу отдаётся абсолютный — собранный из текущего `DATA_DIR`. Меняется
каталог данных (хост ↔ контейнер) — база едет вместе с ним.

Путь за пределами `DATA_DIR` (импорт с внешнего диска при
`ALLOW_EXTERNAL_IMPORT_PATHS=true`) хранится как есть: он не переносим и
переносить его нельзя.

Разделитель в БД — всегда «/», чтобы одна запись читалась и в Windows, и в
Linux. Сравнение префиксов регистронезависимое на Windows и регистрозависимое
в Linux: это соответствует файловой системе, где лежит файл.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from app.config import get_settings

# Windows-путь вида `C:\...` или `N:/...` — абсолютный в любой системе.
_WIN_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")


def norm_path(text: str) -> str:
    """Привести разделители к «/» — в БД путь хранится только так."""
    return text.replace("\\", "/")


def is_absolute_path(text: str) -> bool:
    """Абсолютен ли путь — с учётом чужих систем.

    `os.path.isabs` на Windows считает `/data/x` относительным, а на Linux
    `N:\\data\\x` — абсолютным. Путь в БД мог прийти из другой среды, поэтому
    проверяем оба вида явно.
    """
    if os.path.isabs(text):
        return True
    if text.startswith("/") and not text.startswith("\\"):
        return True  # posix-вид: /data/documents/x.md
    # windows-вид: N:\data\documents\x.md
    return bool(_WIN_DRIVE.match(text))


def _same_prefix(left: str, right: str) -> bool:
    """Сравнить два префикса по правилам файловой системы текущей ОС."""
    if os.name == "nt":
        return left.lower() == right.lower()
    return left == right


def data_root() -> Path | None:
    """Каталог данных текущей среды (None — настройки недоступны)."""
    try:
        return get_settings().data_dir
    except Exception:  # пути не должны ронять приложение
        return None


def relativize(text: str, root: str) -> str | None:
    """Относительный путь внутри `root` (None — файл не внутри каталога)."""
    if not root:
        return None
    norm_path_text = norm_path(text)
    norm_root = norm_path(root).rstrip("/")
    if not norm_root:
        return None
    if _same_prefix(norm_path_text, norm_root):
        return ""
    prefix = norm_root + "/"
    head = norm_path_text[:len(prefix)]
    if _same_prefix(head, prefix):
        return norm_path_text[len(prefix):]
    return None


def relativize_any(text: str, roots: list[str]) -> str | None:
    """Относительный путь по первому подходящему корню из `roots`.

    Нужен миграции: путь мог быть записан в другой среде (`/data/...` на
    хосте, `N:\\...\\data\\...` в контейнере), а корни известны заранее.
    """
    for root in roots:
        if not root:
            continue
        relative = relativize(text, root)
        if relative is not None:
            return relative
    return None


def to_stored_path(value: str | Path | None) -> str:
    """Привести путь к виду, пригодному для хранения в БД.

    Внутри `DATA_DIR` → относительный путь со слэшами. Вне — абсолютный,
    как есть.
    """
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""

    if not is_absolute_path(text):
        return norm_path(text)

    root = data_root()
    if root is None:
        return text
    relative = relativize(text, str(root))
    if relative is None:
        return text
    return relative


def from_stored_path(value: str | Path | None) -> str:
    """Развернуть сохранённый в БД путь в абсолютный для текущей среды.

    Абсолютные значения (в т.ч. старые записи и внешние файлы) не трогаем.
    """
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""

    if is_absolute_path(text):
        return text

    root = data_root()
    if root is None:
        return text
    return str(root / Path(norm_path(text)))
