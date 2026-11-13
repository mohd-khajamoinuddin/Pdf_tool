"""Conversion pipeline.

A converter is a function ``fn(src: Path, dst: Path, options: dict, ctx)``
registered for a ``(source_ext, target_ext)`` pair. ``run`` resolves the pair
from the file names, writes through a temp file, and returns a summary.

Adding a format is one decorated function; nothing else needs to change. A
second backend for an existing pair (say a LibreOffice-based docx->pdf) is
registered under a different ``backend`` name and chosen via
``options["backend"]``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..rpc import Context, EngineError
from ..util import atomic_output

Converter = Callable[[Path, Path, Dict[str, Any], Context], Optional[Dict[str, Any]]]

# (src_ext, dst_ext) -> {backend_name: converter}; first registered is default.
_REGISTRY: Dict[Tuple[str, str], Dict[str, Converter]] = {}

_ALIASES = {"jpeg": "jpg", "htm": "html", "markdown": "md", "tif": "tiff"}


def norm_ext(ext: str) -> str:
    ext = ext.lower().lstrip(".")
    return _ALIASES.get(ext, ext)


def converter(src: "str | List[str]", dst: str, backend: str = "builtin") -> Callable[[Converter], Converter]:
    sources = [src] if isinstance(src, str) else src

    def deco(fn: Converter) -> Converter:
        for s in sources:
            _REGISTRY.setdefault((norm_ext(s), norm_ext(dst)), {})[backend] = fn
        return fn

    return deco


def supported() -> List[Dict[str, Any]]:
    return [
        {"from": s, "to": d, "backends": list(backends)}
        for (s, d), backends in sorted(_REGISTRY.items())
    ]


def run(src: Path, dst: Path, options: Optional[Dict[str, Any]] = None, ctx: Optional[Context] = None) -> Dict[str, Any]:
    options = options or {}
    ctx = ctx or Context()
    pair = (norm_ext(src.suffix), norm_ext(dst.suffix))
    backends = _REGISTRY.get(pair)
    if not backends:
        raise EngineError("unsupported_conversion", f"No converter for .{pair[0]} -> .{pair[1]}")
    name = options.get("backend") or next(iter(backends))
    fn = backends.get(name)
    if fn is None:
        raise EngineError("bad_params", f"Unknown backend '{name}' for .{pair[0]} -> .{pair[1]}")
    if src.resolve() == dst.resolve():
        raise EngineError("bad_params", "Output file must differ from the input file")

    with atomic_output(dst) as tmp:
        details = fn(src, tmp, options, ctx) or {}
    ctx.progress(1.0, "done")
    return {"output": str(dst), "bytes": dst.stat().st_size, "backend": name, **details}


# Importing the modules registers their converters.
from . import pdf_to_docx, basic, pdf_export  # noqa: E402,F401
