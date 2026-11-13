"""Small shared helpers: path handling, page-range parsing, atomic writes."""

from __future__ import annotations

import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List

from .rpc import EngineError


# PDFium is not thread-safe: two threads inside it at once corrupt glyph caches
# or crash the process. Every pypdfium2 call (including pdfplumber's
# page.to_image, which uses it) must hold this lock. Take it per page, not per
# document, so a long export does not starve the preview.
PDFIUM_LOCK = threading.RLock()


def in_path(params: dict, key: str = "input") -> Path:
    p = Path(str(params[key]))
    if not p.is_file():
        raise EngineError("not_found", f"File not found: {p}")
    return p


def out_dir(params: dict, key: str = "output_dir") -> Path:
    p = Path(str(params[key]))
    p.mkdir(parents=True, exist_ok=True)
    return p


@contextmanager
def atomic_output(target: "str | os.PathLike[str]") -> Iterator[Path]:
    """Write to a temp file beside ``target`` and rename on success.

    A crash or a failed conversion therefore never leaves a truncated file
    where the user's document should be, and never clobbers an existing one.
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.stem}.", suffix=target.suffix + ".tmp", dir=target.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        yield tmp
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


def open_plumber(src: "str | os.PathLike[str]", password: "str | None" = None):
    """pdfplumber.open with failures mapped to EngineError codes."""
    import pdfplumber

    try:
        return pdfplumber.open(str(src), password=password or None)
    except Exception as exc:  # pdfplumber wraps pdfminer errors in a generic type
        detail = f"{type(exc).__name__} {exc!r}"
        if "Password" in detail or "Encrypt" in detail:
            raise EngineError("password_required", "This PDF is password protected") from exc
        raise EngineError("invalid_pdf", f"Could not open PDF: {exc or type(exc).__name__}") from exc


def parse_page_ranges(spec: str, page_count: int) -> List[List[int]]:
    """``"1-3, 5, 8-"`` -> ``[[0, 1, 2], [4], [7, ..., n-1]]`` (zero-based)."""
    groups: List[List[int]] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                a, b = part.split("-", 1)
                start = int(a) if a.strip() else 1
                end = int(b) if b.strip() else page_count
            else:
                start = end = int(part)
        except ValueError:
            raise EngineError("bad_params", f"Invalid page range: '{part}'") from None
        if start < 1 or end > page_count or start > end:
            raise EngineError("bad_params", f"Page range '{part}' is outside 1-{page_count}")
        groups.append(list(range(start - 1, end)))
    if not groups:
        raise EngineError("bad_params", "No page ranges given")
    return groups
