from __future__ import annotations

import platform
import sys
from importlib import metadata

from .. import __version__, convert
from ..rpc import method, methods

_LIBS = ["pypdf", "pdfplumber", "pypdfium2", "reportlab", "Pillow", "python-docx", "openpyxl", "python-pptx"]


@method("system.ping")
def ping(params, ctx):
    return {"ok": True, "version": __version__}


@method("system.info")
def info(params, ctx):
    libs = {}
    for name in _LIBS:
        try:
            libs[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            libs[name] = None
    return {
        "version": __version__,
        "python": platform.python_version(),
        "platform": sys.platform,
        "frozen": bool(getattr(sys, "frozen", False)),
        "libraries": libs,
        "methods": sorted(methods()),
        "conversions": convert.supported(),
    }
