"""The simpler converters: PDF -> text/markdown/images, images/docx/csv/xlsx -> PDF."""

from __future__ import annotations

import csv
import zipfile
from pathlib import Path
from typing import Any, Dict, List
from xml.sax.saxutils import escape

import pypdfium2 as pdfium
from PIL import Image

from ..rpc import Context, EngineError
from ..util import PDFIUM_LOCK, open_plumber
from . import converter

IMAGE_EXTS = ["png", "jpg", "bmp", "tiff", "gif", "webp"]
MAX_PDF_TABLE_ROWS = 5000


# ---------------------------------------------------------------- PDF -> text

def _page_markdown(page) -> str:
    out: List[str] = []
    tables = page.find_tables()
    boxes = [t.bbox for t in tables]
    body = page
    for box in boxes:
        body = body.outside_bbox(box)
    text = (body.extract_text() or "").strip()
    if text:
        out.append(text)
    for t in tables:
        rows = [[(c or "").replace("\n", " ").replace("|", "\\|").strip() for c in r] for r in t.extract() if r]
        if not rows:
            continue
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
        lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
        out.append("\n".join(lines))
    return "\n\n".join(out)


@converter("pdf", "md")
def pdf_to_markdown(src: Path, dst: Path, options: Dict[str, Any], ctx: Context) -> Dict[str, Any]:
    with open_plumber(src, options.get("password")) as pdf, open(dst, "w", encoding="utf-8") as fh:
        total = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            ctx.progress(i / total, f"page {i + 1}/{total}")
            fh.write(f"<!-- page {i + 1} -->\n\n{_page_markdown(page)}\n\n")
            page.flush_cache()
    return {"pages": total}


@converter("pdf", "txt")
def pdf_to_text(src: Path, dst: Path, options: Dict[str, Any], ctx: Context) -> Dict[str, Any]:
    with open_plumber(src, options.get("password")) as pdf, open(dst, "w", encoding="utf-8") as fh:
        total = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            ctx.progress(i / total, f"page {i + 1}/{total}")
            fh.write((page.extract_text() or "") + "\n\f")
            page.flush_cache()
    return {"pages": total}


# -------------------------------------------------------------- PDF -> images

def render_page(pdf: "pdfium.PdfDocument", index: int, dpi: float) -> Image.Image:
    with PDFIUM_LOCK:
        return pdf[index].render(scale=dpi / 72.0).to_pil()


def _pdf_to_image_archive(src: Path, dst: Path, options: Dict[str, Any], ctx: Context, fmt: str) -> Dict[str, Any]:
    """Single-file target: a zip of page images (use pdf.to_images for a folder)."""
    import io

    dpi = float(options.get("dpi", 150))
    with PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(str(src), password=options.get("password") or None)
        total = len(pdf)
    try:
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_STORED) as zf:
            for i in range(total):
                ctx.progress(i / total, f"page {i + 1}/{total}")
                img = render_page(pdf, i, dpi)
                buf = io.BytesIO()
                if fmt == "jpg":
                    img.convert("RGB").save(buf, "JPEG", quality=90)
                else:
                    img.save(buf, "PNG")
                zf.writestr(f"{src.stem}-{i + 1:04d}.{fmt}", buf.getvalue())
    finally:
        with PDFIUM_LOCK:
            pdf.close()
    return {"pages": total}


@converter("pdf", "zip")
def pdf_to_png_zip(src: Path, dst: Path, options: Dict[str, Any], ctx: Context) -> Dict[str, Any]:
    fmt = "jpg" if str(options.get("format", "png")).lower() in ("jpg", "jpeg") else "png"
    return _pdf_to_image_archive(src, dst, options, ctx, fmt)


# -------------------------------------------------------------- images -> PDF

def images_to_pdf(sources: List[Path], dst: Path, ctx: Context) -> Dict[str, Any]:
    if not sources:
        raise EngineError("bad_params", "No images given")
    pages: List[Image.Image] = []
    try:
        for i, path in enumerate(sources):
            ctx.progress(i / len(sources), path.name)
            img = Image.open(path)
            if img.mode in ("RGBA", "LA", "P"):
                rgba = img.convert("RGBA")
                flat = Image.new("RGB", rgba.size, "white")
                flat.paste(rgba, mask=rgba.split()[-1])
                img = flat
            elif img.mode != "RGB":
                img = img.convert("RGB")
            pages.append(img)
        pages[0].save(dst, "PDF", save_all=True, append_images=pages[1:], resolution=150.0)
    finally:
        for img in pages:
            img.close()
    return {"pages": len(pages)}


@converter(IMAGE_EXTS, "pdf")
def image_to_pdf(src: Path, dst: Path, options: Dict[str, Any], ctx: Context) -> Dict[str, Any]:
    return images_to_pdf([src], dst, ctx)


# ------------------------------------------------- docx / tables / text -> PDF
# Content-preserving, not layout-preserving: text, headings and tables carry
# over; exact fonts, floating objects and section layout do not. A LibreOffice
# backend (docs/TECH_STACK.md) is the route to layout fidelity.

def _styles():
    from reportlab.lib.styles import getSampleStyleSheet

    return getSampleStyleSheet()


def _rl_table(rows: List[List[str]], styles):
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Table, TableStyle

    cell = styles["BodyText"]
    data = [[Paragraph(escape(str(c)), cell) for c in row] for row in rows]
    table = Table(data, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


def _build_pdf(dst: Path, story: list, landscape_mode: bool = False) -> None:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate

    size = landscape(A4) if landscape_mode else A4
    SimpleDocTemplate(
        str(dst), pagesize=size, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm
    ).build(story)


@converter("docx", "pdf", backend="reportlab")
def docx_to_pdf(src: Path, dst: Path, options: Dict[str, Any], ctx: Context) -> Dict[str, Any]:
    from docx import Document
    from docx.table import Table as DocxTable
    from docx.text.paragraph import Paragraph as DocxParagraph
    from reportlab.platypus import Paragraph, Spacer

    doc = Document(str(src))
    styles = _styles()
    story: list = []
    counts = {"paragraphs": 0, "tables": 0}

    for block in doc.element.body.iterchildren():
        tag = block.tag.rsplit("}", 1)[-1]
        if tag == "p":
            para = DocxParagraph(block, doc)
            style_name = (para.style.name if para.style is not None else "") or ""
            parts = []
            for run in para.runs:
                t = escape(run.text)
                if run.bold:
                    t = f"<b>{t}</b>"
                if run.italic:
                    t = f"<i>{t}</i>"
                if run.underline:
                    t = f"<u>{t}</u>"
                parts.append(t)
            markup = "".join(parts) or escape(para.text)
            if not markup.strip():
                story.append(Spacer(1, 6))
                continue
            if style_name.startswith("Heading") or style_name == "Title":
                level = "".join(ch for ch in style_name if ch.isdigit()) or "1"
                style = styles.get(f"Heading{min(int(level), 6)}", styles["Heading1"])
            elif style_name.startswith("List"):
                style = styles["BodyText"]
                markup = "&bull; " + markup
            else:
                style = styles["BodyText"]
            story.append(Paragraph(markup, style))
            counts["paragraphs"] += 1
        elif tag == "tbl":
            table = DocxTable(block, doc)
            rows = [[cell.text for cell in row.cells] for row in table.rows]
            if rows:
                story.append(_rl_table(rows, styles))
                story.append(Spacer(1, 8))
                counts["tables"] += 1

    if not story:
        story.append(Spacer(1, 1))
    _build_pdf(dst, story)
    return {**counts, "fidelity": "content"}


def _read_table(src: Path) -> List[tuple]:
    """-> [(sheet_name, rows)] for csv / xlsx."""
    if src.suffix.lower() == ".csv":
        with open(src, newline="", encoding="utf-8-sig") as fh:
            return [(src.stem, [row for _, row in zip(range(MAX_PDF_TABLE_ROWS), csv.reader(fh))])]
    from openpyxl import load_workbook

    wb = load_workbook(str(src), read_only=True, data_only=True)
    try:
        sheets = []
        for ws in wb.worksheets:
            rows = []
            for row in ws.iter_rows(values_only=True, max_row=MAX_PDF_TABLE_ROWS):
                rows.append(["" if v is None else str(v) for v in row])
            while rows and not any(rows[-1]):
                rows.pop()
            sheets.append((ws.title, rows))
        return sheets
    finally:
        wb.close()


@converter(["xlsx", "csv"], "pdf", backend="reportlab")
def table_to_pdf(src: Path, dst: Path, options: Dict[str, Any], ctx: Context) -> Dict[str, Any]:
    from reportlab.platypus import PageBreak, Paragraph

    styles = _styles()
    story: list = []
    sheets = _read_table(src)
    for i, (name, rows) in enumerate(sheets):
        ctx.progress(i / max(len(sheets), 1), name)
        if i:
            story.append(PageBreak())
        story.append(Paragraph(escape(name), styles["Heading2"]))
        if rows:
            width = max(len(r) for r in rows)
            story.append(_rl_table([list(r) + [""] * (width - len(r)) for r in rows], styles))
    _build_pdf(dst, story, landscape_mode=True)
    return {"sheets": len(sheets), "fidelity": "content"}


@converter(["txt", "md"], "pdf", backend="reportlab")
def text_to_pdf(src: Path, dst: Path, options: Dict[str, Any], ctx: Context) -> Dict[str, Any]:
    """Plain text, plus the Markdown basics (#-headings, bullets, blank-line paragraphs)."""
    from reportlab.platypus import Paragraph, Spacer

    styles = _styles()
    story: list = []
    is_md = src.suffix.lower() == ".md"
    for block in src.read_text(encoding="utf-8-sig").replace("\r\n", "\n").split("\n\n"):
        block = block.strip("\n")
        if not block.strip():
            continue
        if is_md and block.lstrip().startswith("#"):
            hashes = len(block) - len(block.lstrip("#"))
            story.append(Paragraph(escape(block.lstrip("#").strip()), styles[f"Heading{min(max(hashes, 1), 6)}"]))
            continue
        for line in block.split("\n") if is_md and block.lstrip()[:2] in ("- ", "* ") else [block]:
            text = escape(line)
            if is_md and line.lstrip()[:2] in ("- ", "* "):
                text = "&bull; " + escape(line.lstrip()[2:])
            story.append(Paragraph(text.replace("\n", "<br/>"), styles["BodyText"]))
        story.append(Spacer(1, 4))
    if not story:
        story.append(Spacer(1, 1))
    _build_pdf(dst, story)
    return {"fidelity": "content"}
