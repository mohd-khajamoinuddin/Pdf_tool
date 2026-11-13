"""PDF Studio: inspect, render, merge, split, reorder, protect, watermark."""

from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import List, Optional

import pypdfium2 as pdfium
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError

from ..convert.basic import render_page
from ..rpc import EngineError, method
from ..util import PDFIUM_LOCK, atomic_output, in_path, out_dir, parse_page_ranges

MAX_RENDER_SIDE = 4000  # px - bounds memory for a single preview render


def _reader(path: Path, password: Optional[str] = None) -> PdfReader:
    try:
        reader = PdfReader(str(path))
    except PdfReadError as exc:
        raise EngineError("invalid_pdf", f"Could not read PDF: {exc}") from exc
    if reader.is_encrypted:
        # An empty user password is common (owner-password-only files).
        if not reader.decrypt(password or ""):
            raise EngineError("password_required", "This PDF is password protected")
    return reader


def _pdfium(path: Path, password: Optional[str] = None) -> "pdfium.PdfDocument":
    try:
        with PDFIUM_LOCK:
            return pdfium.PdfDocument(str(path), password=password or None)
    except pdfium.PdfiumError as exc:
        if "password" in str(exc).lower():
            raise EngineError("password_required", "This PDF is password protected") from exc
        raise EngineError("invalid_pdf", f"Could not open PDF: {exc}") from exc


@method("pdf.info")
def pdf_info(params, ctx):
    path = in_path(params)
    reader = _reader(path, params.get("password"))
    meta = reader.metadata or {}
    sizes = []
    for page in reader.pages[:500]:
        # Size as a viewer displays it: the visible (crop) box, turned by the page's own /Rotate.
        box = page.cropbox
        w, h = round(float(box.width), 1), round(float(box.height), 1)
        sizes.append([h, w] if page.rotation % 180 else [w, h])
    return {
        "path": str(path),
        "name": path.name,
        "bytes": path.stat().st_size,
        "pages": len(reader.pages),
        "encrypted": bool(reader.is_encrypted),
        "page_sizes": sizes,
        "metadata": {
            "title": meta.get("/Title"),
            "author": meta.get("/Author"),
            "subject": meta.get("/Subject"),
            "creator": meta.get("/Creator"),
            "producer": meta.get("/Producer"),
        },
    }


@method("pdf.render_page")
def pdf_render_page(params, ctx):
    """{input, page (0-based), width?: px, password?} -> PNG data URL for the viewer."""
    path = in_path(params)
    index = int(params.get("page", 0))
    width = min(int(params.get("width", 900)), MAX_RENDER_SIDE)
    with PDFIUM_LOCK:
        pdf = _pdfium(path, params.get("password"))
        try:
            if not 0 <= index < len(pdf):
                raise EngineError("bad_params", f"Page {index + 1} is out of range")
            page = pdf[index]
            scale = width / page.get_width()
            if page.get_height() * scale > MAX_RENDER_SIDE:
                scale = MAX_RENDER_SIDE / page.get_height()
            image = page.render(scale=scale).to_pil()
        finally:
            pdf.close()
    buf = io.BytesIO()
    image.save(buf, "PNG")
    return {
        "page": index,
        "width": image.width,
        "height": image.height,
        "data_url": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii"),
    }


@method("pdf.to_images")
def pdf_to_images(params, ctx):
    """{input, output_dir, format?: png|jpg, dpi?} -> one image file per page."""
    path = in_path(params)
    folder = out_dir(params)
    fmt = "jpg" if str(params.get("format", "png")).lower() in ("jpg", "jpeg") else "png"
    dpi = float(params.get("dpi", 150))
    if not 36 <= dpi <= 600:
        raise EngineError("bad_params", "dpi must be between 36 and 600")
    pdf = _pdfium(path, params.get("password"))
    files: List[str] = []
    try:
        with PDFIUM_LOCK:
            total = len(pdf)
        for i in range(total):
            ctx.progress(i / total, f"page {i + 1}/{total}")
            target = folder / f"{path.stem}-{i + 1:04d}.{fmt}"
            image = render_page(pdf, i, dpi)
            with atomic_output(target) as tmp:
                if fmt == "jpg":
                    image.convert("RGB").save(tmp, "JPEG", quality=90)
                else:
                    image.save(tmp, "PNG")
            files.append(str(target))
    finally:
        with PDFIUM_LOCK:
            pdf.close()
    return {"output_dir": str(folder), "files": files, "pages": len(files)}


@method("pdf.merge")
def pdf_merge(params, ctx):
    """{inputs, output} - concatenate in the given order."""
    inputs = [in_path({"input": p}) for p in params["inputs"]]
    if len(inputs) < 2:
        raise EngineError("bad_params", "Select at least two PDFs to merge")
    output = Path(str(params["output"]))
    writer = PdfWriter()
    for i, path in enumerate(inputs):
        ctx.progress(i / len(inputs), path.name)
        writer.append(_reader(path))
    pages = len(writer.pages)
    with atomic_output(output) as tmp:
        writer.write(str(tmp))
    writer.close()
    return {"output": str(output), "pages": pages, "sources": len(inputs)}


@method("pdf.split")
def pdf_split(params, ctx):
    """{input, output_dir, ranges?: "1-3,5,8-"} - one file per range, or per page."""
    path = in_path(params)
    folder = out_dir(params)
    reader = _reader(path, params.get("password"))
    count = len(reader.pages)
    spec = str(params.get("ranges") or "").strip()
    groups = parse_page_ranges(spec, count) if spec else [[i] for i in range(count)]
    files = []
    for n, group in enumerate(groups):
        ctx.progress(n / len(groups), f"part {n + 1}/{len(groups)}")
        label = f"{group[0] + 1}" if len(group) == 1 else f"{group[0] + 1}-{group[-1] + 1}"
        target = folder / f"{path.stem}_p{label}.pdf"
        writer = PdfWriter()
        for index in group:
            writer.add_page(reader.pages[index])
        with atomic_output(target) as tmp:
            writer.write(str(tmp))
        writer.close()
        files.append(str(target))
    return {"output_dir": str(folder), "files": files}


@method("pdf.reorder")
def pdf_reorder(params, ctx):
    """{input, output, order: [0-based page indexes]} - also deletes (omit) and duplicates."""
    path = in_path(params)
    output = Path(str(params["output"]))
    reader = _reader(path, params.get("password"))
    order = [int(i) for i in params["order"]]
    if not order:
        raise EngineError("bad_params", "Page order is empty")
    if any(not 0 <= i < len(reader.pages) for i in order):
        raise EngineError("bad_params", "Page order references a page that does not exist")
    writer = PdfWriter()
    for index in order:
        writer.add_page(reader.pages[index])
    with atomic_output(output) as tmp:
        writer.write(str(tmp))
    writer.close()
    return {"output": str(output), "pages": len(order)}


@method("pdf.protect")
def pdf_protect(params, ctx):
    """{input, output, user_password, owner_password?, permissions?} - AES-256 encryption.

    ``permissions`` = {print, copy, modify, annotate} booleans (default: all allowed).
    Readers honour these only by convention; they are not a security boundary.
    """
    from pypdf.constants import UserAccessPermissions as P
    path = in_path(params)
    output = Path(str(params["output"]))
    user_password = str(params.get("user_password") or "")
    if not user_password:
        raise EngineError("bad_params", "A password is required")
    reader = _reader(path, params.get("password"))
    writer = PdfWriter(clone_from=reader)
    wanted = params.get("permissions") or {}
    flags = P.all()
    denied = {
        "print": P.PRINT | P.PRINT_TO_REPRESENTATION,
        "copy": P.EXTRACT | P.EXTRACT_TEXT_AND_GRAPHICS,
        "modify": P.MODIFY | P.ASSEMBLE_DOC,
        "annotate": P.ADD_OR_MODIFY | P.FILL_FORM_FIELDS,
    }
    for name, bits in denied.items():
        if wanted.get(name) is False:
            flags &= ~bits
    owner_password = str(params.get("owner_password") or "")
    if flags != P.all() and (not owner_password or owner_password == user_password):
        # With one shared password every reader opens the file as its owner and
        # the restrictions would silently not apply.
        raise EngineError("bad_params", "Restricting permissions needs a separate owner password")
    writer.encrypt(
        user_password=user_password,
        owner_password=owner_password or user_password,
        permissions_flag=flags,
        algorithm="AES-256",
    )
    with atomic_output(output) as tmp:
        writer.write(str(tmp))
    writer.close()
    return {"output": str(output), "algorithm": "AES-256"}


@method("pdf.watermark")
def pdf_watermark(params, ctx):
    """{input, output, text, opacity?, font_size?, angle?} - diagonal text on every page."""
    from reportlab.lib.colors import Color
    from reportlab.pdfgen import canvas

    path = in_path(params)
    output = Path(str(params["output"]))
    text = str(params.get("text") or "").strip()
    if not text:
        raise EngineError("bad_params", "Watermark text is required")
    opacity = min(max(float(params.get("opacity", 0.18)), 0.02), 1.0)
    font_size = float(params.get("font_size", 54))
    angle = float(params.get("angle", 45))

    reader = _reader(path, params.get("password"))
    writer = PdfWriter(clone_from=reader)
    stamps = {}  # one overlay per distinct page size
    total = len(writer.pages)
    for i, page in enumerate(writer.pages):
        ctx.progress(i / total, f"page {i + 1}/{total}")
        w, h = float(page.mediabox.width), float(page.mediabox.height)
        key = (round(w), round(h))
        if key not in stamps:
            buf = io.BytesIO()
            c = canvas.Canvas(buf, pagesize=(w, h))
            c.setFillColor(Color(0.35, 0.35, 0.35, alpha=opacity))
            c.setFont("Helvetica-Bold", font_size)
            c.translate(w / 2, h / 2)
            c.rotate(angle)
            c.drawCentredString(0, -font_size / 3, text)
            c.save()
            buf.seek(0)
            stamps[key] = PdfReader(buf).pages[0]
        page.merge_page(stamps[key])
    with atomic_output(output) as tmp:
        writer.write(str(tmp))
    writer.close()
    return {"output": str(output), "pages": total}
