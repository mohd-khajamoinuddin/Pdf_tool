"""PDF -> Excel (.xlsx) and PDF -> HTML."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any, Dict, List

from ..rpc import Context
from ..util import open_plumber
from . import converter
from .pdf_to_docx import _body_size, _heading_level, _inside, _is_bold, _is_italic, _line_size, _lines, _paragraphs


def _typed(text: str) -> Any:
    """Table cell text -> number when it is unambiguously one ("1,234.50", "12%")."""
    raw = text.strip()
    if not raw or (len(raw) > 1 and raw[0] == "0" and raw[1].isdigit()):
        return raw
    candidate = raw.replace(",", "")
    percent = candidate.endswith("%")
    try:
        value = float(candidate[:-1] if percent else candidate)
    except ValueError:
        return raw
    if percent:
        return value / 100
    return int(value) if value.is_integer() and "." not in candidate else value


@converter("pdf", "xlsx")
def pdf_to_xlsx(src: Path, dst: Path, options: Dict[str, Any], ctx: Context) -> Dict[str, Any]:
    """One sheet per page: detected tables as typed cells, otherwise the page's text lines."""
    from openpyxl import Workbook

    wb = Workbook(write_only=True)
    stats = {"pages": 0, "tables": 0}
    with open_plumber(src, options.get("password")) as pdf:
        total = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            ctx.progress(i / total, f"page {i + 1}/{total}")
            ws = wb.create_sheet(title=f"Page {i + 1}")
            tables = [t.extract() for t in page.find_tables()]
            tables = [[r for r in t if r and any(c for c in r)] for t in tables]
            tables = [t for t in tables if t]
            if tables:
                for n, rows in enumerate(tables):
                    if n:
                        ws.append([])
                    for row in rows:
                        ws.append([_typed((c or "").replace("\n", " ")) for c in row])
                stats["tables"] += len(tables)
            else:
                for line in (page.extract_text() or "").splitlines():
                    ws.append([line])
            page.flush_cache()
            stats["pages"] += 1
    wb.save(str(dst))
    if stats["tables"] == 0:
        stats["warning"] = "No tables were detected; page text was exported one line per row."
    return stats


_HTML_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
body {{ font: 16px/1.55 system-ui, sans-serif; max-width: 50rem; margin: 2rem auto; padding: 0 1rem; color: #1c2128; }}
section {{ border-bottom: 1px solid #dcdfe5; padding-bottom: 1.5rem; margin-bottom: 1.5rem; }}
table {{ border-collapse: collapse; margin: 1rem 0; }}
td, th {{ border: 1px solid #b9bec8; padding: 4px 10px; text-align: left; vertical-align: top; }}
</style>
</head>
<body>
"""


def _para_html(para: List[List[dict]], body: float) -> str:
    words = [w for line in para for w in line]
    text = " ".join(w["text"] for w in words)
    level = _heading_level(_line_size(para[0]), body, text, all(_is_bold(w["fontname"]) for w in words))
    if level:
        return f"<h{level}>{escape(text)}</h{level}>"
    parts: List[str] = []
    for w in words:
        t = escape(w["text"])
        if _is_bold(w["fontname"]):
            t = f"<b>{t}</b>"
        if _is_italic(w["fontname"]):
            t = f"<i>{t}</i>"
        parts.append(t)
    # Collapse the per-word tags that the loop above produced for adjacent words.
    html = " ".join(parts).replace("</b> <b>", " ").replace("</i> <i>", " ")
    return f"<p>{html}</p>"


@converter("pdf", "html")
def pdf_to_html(src: Path, dst: Path, options: Dict[str, Any], ctx: Context) -> Dict[str, Any]:
    """Self-contained HTML (inline CSS, no external resources): headings, paragraphs, tables."""
    stats = {"pages": 0, "tables": 0}
    with open_plumber(src, options.get("password")) as pdf, open(dst, "w", encoding="utf-8") as fh:
        fh.write(_HTML_HEAD.format(title=escape(src.stem)))
        body = _body_size(pdf)
        total = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            ctx.progress(i / total, f"page {i + 1}/{total}")
            tables = page.find_tables()
            boxes = [t.bbox for t in tables]
            words = [
                w
                for w in page.extract_words(extra_attrs=["fontname", "size"], keep_blank_chars=False)
                if not any(_inside(w, b) for b in boxes)
            ]
            items = [(p[0][0]["top"], _para_html(p, body)) for p in _paragraphs(_lines(words))]
            for t in tables:
                rows = [r for r in t.extract() if r and any(c for c in r)]
                cells = "".join(
                    "<tr>" + "".join(f"<td>{escape((c or '').strip())}</td>" for c in row) + "</tr>" for row in rows
                )
                items.append((t.bbox[1], f"<table>{cells}</table>"))
                stats["tables"] += 1
            fh.write(f'<section data-page="{i + 1}">\n')
            fh.write("\n".join(html for _, html in sorted(items, key=lambda it: it[0])))
            fh.write("\n</section>\n")
            page.flush_cache()
            stats["pages"] += 1
        fh.write("</body>\n</html>\n")
    return stats
