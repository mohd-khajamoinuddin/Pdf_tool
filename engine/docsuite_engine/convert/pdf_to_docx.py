"""PDF -> Word (.docx) using pdfplumber (MIT) + python-docx (MIT).

A PDF has no paragraphs, headings or tables - only positioned glyphs and
lines - so this is a reconstruction, in four passes per page:

1. find tables (ruling-line detection) and set their regions aside;
2. group the remaining words into lines, then lines into paragraphs using
   vertical gaps and font changes;
3. classify paragraphs as headings by font size relative to the document's
   dominant body size;
4. emit paragraphs, tables and images in top-to-bottom reading order.

The result is an *editable, reflowable* document, not a pixel-exact replica.
Known limits (tracked in docs/TECH_STACK.md): multi-column pages are read
across columns, scanned PDFs need OCR first, and vector drawings are dropped.
"""

from __future__ import annotations

import io
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

import pdfplumber
from docx import Document
from docx.enum.text import WD_BREAK
from docx.shared import Pt

from ..rpc import Context, EngineError
from ..util import PDFIUM_LOCK, open_plumber
from . import converter

LINE_TOLERANCE = 3.0       # pt: words whose tops differ by less share a line
PARA_GAP_FACTOR = 0.75     # gap > factor * font size starts a new paragraph
MIN_IMAGE_SIDE = 24.0      # pt: ignore tiny decorative images
IMAGE_DPI = 150


def _inside(word: dict, bbox: tuple) -> bool:
    x0, top, x1, bottom = bbox
    cx = (word["x0"] + word["x1"]) / 2
    cy = (word["top"] + word["bottom"]) / 2
    return x0 <= cx <= x1 and top <= cy <= bottom


def _is_bold(fontname: str) -> bool:
    f = fontname.lower()
    return "bold" in f or "black" in f or "heavy" in f


def _is_italic(fontname: str) -> bool:
    f = fontname.lower()
    return "italic" in f or "oblique" in f


def _lines(words: List[dict]) -> List[List[dict]]:
    lines: List[List[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(w["top"] - lines[-1][0]["top"]) <= LINE_TOLERANCE:
            lines[-1].append(w)
        else:
            lines.append([w])
    for line in lines:
        line.sort(key=lambda w: w["x0"])
    return lines


def _line_size(line: List[dict]) -> float:
    return max(w["size"] for w in line)


def _paragraphs(lines: List[List[dict]]) -> List[List[List[dict]]]:
    paras: List[List[List[dict]]] = []
    for line in lines:
        if paras:
            prev = paras[-1][-1]
            gap = line[0]["top"] - max(w["bottom"] for w in prev)
            size = _line_size(line)
            same_style = abs(size - _line_size(prev)) < 0.6 and _is_bold(line[0]["fontname"]) == _is_bold(
                prev[0]["fontname"]
            )
            if same_style and gap <= PARA_GAP_FACTOR * size:
                paras[-1].append(line)
                continue
        paras.append([line])
    return paras


def _body_size(pdf: "pdfplumber.PDF", sample_pages: int = 20) -> float:
    counts: Counter = Counter()
    for page in pdf.pages[:sample_pages]:
        for ch in page.chars:
            counts[round(ch["size"] * 2) / 2] += 1
    return counts.most_common(1)[0][0] if counts else 11.0


def _heading_level(size: float, body: float, text: str, bold: bool) -> int:
    if len(text) > 200:
        return 0
    ratio = size / body if body else 1.0
    if ratio >= 1.6:
        return 1
    if ratio >= 1.3:
        return 2
    if ratio >= 1.12 or (bold and ratio >= 1.0 and len(text) < 80 and not text.endswith((".", ",", ";"))):
        return 3
    return 0


def _add_paragraph(doc: "Document", para: List[List[dict]], body: float) -> None:
    words = [w for line in para for w in line]
    text = " ".join(w["text"] for w in words)
    size = _line_size(para[0])
    all_bold = all(_is_bold(w["fontname"]) for w in words)
    level = _heading_level(size, body, text, all_bold)
    if level:
        doc.add_heading(text, level=level)
        return

    p = doc.add_paragraph()
    # Merge consecutive words that share formatting into one run.
    run_words: List[str] = []
    run_style = None
    for w in words:
        style = (_is_bold(w["fontname"]), _is_italic(w["fontname"]), round(w["size"] * 2) / 2)
        if style != run_style and run_words:
            _flush_run(p, run_words, run_style, body)
            run_words = []
        run_style = style
        run_words.append(w["text"])
    if run_words:
        _flush_run(p, run_words, run_style, body, last=True)


def _flush_run(p, words: List[str], style, body: float, last: bool = False) -> None:
    bold, italic, size = style
    run = p.add_run(" ".join(words) + ("" if last else " "))
    run.bold = bold or None
    run.italic = italic or None
    if abs(size - body) >= 1.0:
        run.font.size = Pt(size)


def _add_table(doc: "Document", rows: List[List[Any]]) -> None:
    rows = [r for r in rows if r and any(c for c in r)]
    if not rows:
        return
    n_cols = max(len(r) for r in rows)
    table = doc.add_table(rows=len(rows), cols=n_cols)
    table.style = "Table Grid"
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            table.cell(r, c).text = (value or "").strip()
    doc.add_paragraph()


def _add_image(doc: "Document", page, img: dict, usable_width_pt: float) -> bool:
    bbox = (
        max(img["x0"], 0),
        max(img["top"], 0),
        min(img["x1"], page.width),
        min(img["bottom"], page.height),
    )
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    if w < MIN_IMAGE_SIDE or h < MIN_IMAGE_SIDE:
        return False
    buf = io.BytesIO()
    with PDFIUM_LOCK:  # pdfplumber rasterises through pypdfium2
        page.crop(bbox).to_image(resolution=IMAGE_DPI).original.save(buf, format="PNG")
    buf.seek(0)
    doc.add_picture(buf, width=Pt(min(w, usable_width_pt)))
    return True


@converter("pdf", "docx", backend="pdfplumber")
def pdf_to_docx(src: Path, dst: Path, options: Dict[str, Any], ctx: Context) -> Dict[str, Any]:
    include_images = bool(options.get("images", True))
    stats = {"pages": 0, "paragraphs": 0, "tables": 0, "images": 0, "pages_without_text": 0}

    with open_plumber(src, options.get("password")) as pdf:
        if not pdf.pages:
            raise EngineError("invalid_pdf", "PDF has no pages")
        doc = Document()
        first = pdf.pages[0]
        section = doc.sections[0]
        section.page_width, section.page_height = Pt(first.width), Pt(first.height)
        usable = first.width - (section.left_margin.pt + section.right_margin.pt)
        body = _body_size(pdf)
        doc.styles["Normal"].font.size = Pt(body)
        total = len(pdf.pages)

        for index, page in enumerate(pdf.pages):
            ctx.progress(index / total, f"page {index + 1}/{total}")
            tables = page.find_tables()
            table_boxes = [t.bbox for t in tables]
            words = [
                w
                for w in page.extract_words(extra_attrs=["fontname", "size"], keep_blank_chars=False)
                if not any(_inside(w, b) for b in table_boxes)
            ]

            # Everything on the page as (top, kind, payload), then emit in order.
            items: List[tuple] = [(p[0][0]["top"], "para", p) for p in _paragraphs(_lines(words))]
            items += [(t.bbox[1], "table", t.extract()) for t in tables]
            if include_images:
                items += [(im["top"], "image", im) for im in page.images]
            if not words and not tables:
                stats["pages_without_text"] += 1

            for _, kind, payload in sorted(items, key=lambda it: it[0]):
                if kind == "para":
                    _add_paragraph(doc, payload, body)
                    stats["paragraphs"] += 1
                elif kind == "table":
                    _add_table(doc, payload)
                    stats["tables"] += 1
                else:
                    try:
                        stats["images"] += _add_image(doc, page, payload, usable)
                    except Exception:  # noqa: BLE001 - a bad image must not fail the document
                        pass

            if index < total - 1:
                doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
            page.flush_cache()  # keep memory flat on large files
            stats["pages"] += 1

        doc.save(str(dst))

    if stats["pages_without_text"] == stats["pages"]:
        stats["warning"] = "No extractable text found - this looks like a scanned PDF and needs OCR."
    return stats
