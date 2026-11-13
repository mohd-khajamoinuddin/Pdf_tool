"""PDF editing: organise pages and stamp annotations, text, images and redactions.

One method, ``pdf.apply_edits``, produces a new file from:

* ``pages``  - the new page order, ``[{source, rotate}]`` (omit a page to delete it);
* ``edits``  - things drawn on *source* pages, so they follow a page when it moves.

Edit coordinates are PDF points with the origin at the TOP-LEFT of the page as
it is displayed (i.e. after the page's own /Rotate), matching what the viewer
shows. Types: text, highlight, rect, ellipse, line, arrow, ink, image, note,
redact.

Editing existing text: a `text` edit may carry `replaces: {x, y, w, h}`, the box
of a line reported by `pdf.text_lines`. The original line is then deleted from
the page's content stream and the new text drawn in its place. If the line
cannot be removed cleanly (it lives inside a nested form, or removing it would
also take neighbouring text), the edit falls back to painting over it and the
result says so - the old text is then hidden, not gone.

Redaction is real: the page is rasterised and the boxes are burned into the
pixels, so the text underneath no longer exists in the file. A black rectangle
drawn over live text would only hide it, which is why "rect" is not redaction.
"""

from __future__ import annotations

import base64
import io
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pypdfium2 as pdfium
from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Text as TextAnnotation
from reportlab.lib.colors import Color
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from ..rpc import EngineError, method
from ..util import PDFIUM_LOCK, atomic_output, in_path, open_plumber
from .pdf import _reader

REDACT_DPI = 200
MAX_EDITS = 5000
MAX_IMAGE_SIDE = 2400
EDIT_TYPES = {"text", "highlight", "rect", "ellipse", "line", "arrow", "ink", "image", "note", "redact"}

# Fonts with broad Unicode coverage, tried in order; Helvetica (Latin-1 only) is the fallback.
_FONT_CANDIDATES = [
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf"),
    ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
]
_fonts: Optional[Tuple[str, str]] = None


def _font_names() -> Tuple[str, str]:
    """(regular, bold) font names registered with reportlab."""
    global _fonts
    if _fonts is None:
        _fonts = ("Helvetica", "Helvetica-Bold")
        for regular, bold in _FONT_CANDIDATES:
            if Path(regular).is_file() and Path(bold).is_file():
                try:
                    pdfmetrics.registerFont(TTFont("DocSuiteSans", regular))
                    pdfmetrics.registerFont(TTFont("DocSuiteSans-Bold", bold))
                    _fonts = ("DocSuiteSans", "DocSuiteSans-Bold")
                    break
                except Exception:  # noqa: BLE001 - an unreadable font just means "try the next"
                    continue
    return _fonts


_STANDARD = {
    "sans": ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique"),
    "serif": ("Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic"),
    "mono": ("Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique"),
}


def _text_font(text: str, family: str, bold: bool, italic: bool) -> str:
    """A font that can draw `text`: a standard PDF font for Latin-1, otherwise a Unicode TrueType font."""
    try:
        text.encode("latin-1")
    except UnicodeEncodeError:
        regular, heavy = _font_names()
        if not regular.startswith("Helvetica"):
            return heavy if bold else regular
    return _STANDARD.get(family, _STANDARD["sans"])[(1 if bold else 0) + (2 if italic else 0)]


def _color(value: Any, alpha: float = 1.0, default: str = "#000000") -> Color:
    text = str(value or default).lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    try:
        r, g, b = (int(text[i : i + 2], 16) / 255 for i in (0, 2, 4))
    except (ValueError, IndexError):
        raise EngineError("bad_params", f"Invalid colour: {value}") from None
    return Color(r, g, b, alpha=alpha)


def _num(edit: dict, key: str, default: Optional[float] = None) -> float:
    value = edit.get(key, default)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise EngineError("bad_params", f"Edit '{edit.get('type')}' needs a numeric '{key}'")
    return float(value)


def decode_data_url(data_url: str) -> Image.Image:
    try:
        header, payload = str(data_url).split(",", 1)
        if not header.startswith("data:image/") or ";base64" not in header:
            raise ValueError
        image = Image.open(io.BytesIO(base64.b64decode(payload)))
        image.load()
        return image
    except Exception:  # noqa: BLE001
        raise EngineError("bad_params", "Image data is not a valid base64 image") from None


def _draw(c: "canvas.Canvas", edit: dict, height: float) -> None:
    """Draw one edit; `height` flips our top-left origin to PDF's bottom-left."""
    kind = edit["type"]
    stroke = _num(edit, "width", 1.5) if kind != "image" else 0.0

    if kind == "text":
        size = _num(edit, "size", 12)
        text = str(edit.get("text", ""))
        font = _text_font(text, str(edit.get("family") or "sans"), bool(edit.get("bold")), bool(edit.get("italic")))
        c.setFillColor(_color(edit.get("color")))
        c.setFont(font, size)
        x, y = _num(edit, "x"), _num(edit, "y")
        for i, line in enumerate(text.split("\n")):
            c.drawString(x, height - (y + size * 0.8 + i * size * 1.2), line)
        return

    if kind == "ink":
        points = edit.get("points") or []
        if len(points) < 2:
            return
        c.setStrokeColor(_color(edit.get("color")))
        c.setLineWidth(stroke)
        c.setLineCap(1)
        c.setLineJoin(1)
        path = c.beginPath()
        path.moveTo(float(points[0][0]), height - float(points[0][1]))
        for px, py in points[1:]:
            path.lineTo(float(px), height - float(py))
        c.drawPath(path, stroke=1, fill=0)
        return

    if kind in ("line", "arrow"):
        x1, y1, x2, y2 = _num(edit, "x1"), height - _num(edit, "y1"), _num(edit, "x2"), height - _num(edit, "y2")
        color = _color(edit.get("color"))
        c.setStrokeColor(color)
        c.setFillColor(color)
        c.setLineWidth(stroke)
        c.setLineCap(1)
        c.line(x1, y1, x2, y2)
        if kind == "arrow":
            angle = math.atan2(y2 - y1, x2 - x1)
            head = max(8.0, stroke * 4)
            path = c.beginPath()
            path.moveTo(x2, y2)
            for side in (math.radians(155), math.radians(-155)):
                path.lineTo(x2 + head * math.cos(angle + side), y2 + head * math.sin(angle + side))
            path.close()
            c.drawPath(path, stroke=0, fill=1)
        return

    x, y, w, h = _num(edit, "x"), _num(edit, "y"), _num(edit, "w"), _num(edit, "h")
    bottom = height - y - h

    if kind == "highlight":
        c.setFillColor(_color(edit.get("color"), alpha=0.35, default="#ffe600"))
        c.rect(x, bottom, w, h, stroke=0, fill=1)
    elif kind in ("rect", "ellipse"):
        c.setStrokeColor(_color(edit.get("color")))
        c.setLineWidth(stroke)
        fill = edit.get("fill")
        if fill:
            c.setFillColor(_color(fill))
        draw = c.rect if kind == "rect" else c.ellipse
        if kind == "rect":
            draw(x, bottom, w, h, stroke=1, fill=1 if fill else 0)
        else:
            draw(x, bottom, x + w, bottom + h, stroke=1, fill=1 if fill else 0)
    elif kind == "image":
        image = decode_data_url(edit.get("data_url", ""))
        if max(image.size) > MAX_IMAGE_SIDE:
            image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA")
        c.drawImage(ImageReader(image), x, bottom, w, h, mask="auto")


def _overlay(edits: List[dict], width: float, height: float):
    """A one-page PDF holding the vector edits, or None when there is nothing to draw."""
    drawable = [e for e in edits if e["type"] not in ("redact", "note")]
    if not drawable:
        return None
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))
    for edit in drawable:
        if edit.get("_cover"):                        # original text could not be removed: paint over it
            box = edit["replaces"]
            c.setFillColor(Color(1, 1, 1))
            c.rect(_num(box, "x") - 0.5, height - _num(box, "y") - _num(box, "h") - 0.5, _num(box, "w") + 1, _num(box, "h") + 1, stroke=0, fill=1)
    for edit in drawable:
        c.saveState()
        _draw(c, edit, height)
        c.restoreState()
    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]


def _redacted_page(path: Path, password: Optional[str], index: int, boxes: List[dict]):
    """Rasterise the page with the boxes burned in -> (single-page PDF page, width, height)."""
    with PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(str(path), password=password or None)
        try:
            page = pdf[index]
            width, height = page.get_width(), page.get_height()
            image = page.render(scale=REDACT_DPI / 72.0).to_pil().convert("RGB")
        finally:
            pdf.close()
    k = REDACT_DPI / 72.0
    draw = ImageDraw.Draw(image)
    for b in boxes:
        x, y, w, h = _num(b, "x"), _num(b, "y"), _num(b, "w"), _num(b, "h")
        draw.rectangle([x * k, y * k, (x + w) * k, (y + h) * k], fill=(0, 0, 0))
    jpeg = io.BytesIO()
    image.save(jpeg, "JPEG", quality=88)
    jpeg.seek(0)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))
    c.drawImage(ImageReader(jpeg), 0, 0, width, height)
    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0], width, height


# --------------------------------------------------------------- editing existing text

def _mul(m: tuple, n: tuple) -> tuple:
    """Affine matrices as (a, b, c, d, e, f); the result applies m first, then n."""
    a, b, c, d, e, f = m
    g, h, i, j, k, l = n
    return (a * g + b * i, a * h + b * j, c * g + d * i, c * h + d * j, e * g + f * i + k, e * h + f * j + l)


_IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _strip_text(operations: list, boxes: List[tuple]) -> Tuple[list, int]:
    """Drop text-showing operators that start inside any (x0, y0, x1, y1) box (PDF user space).

    Tracks just enough graphics state to know where each run of text starts: the
    transformation matrix (q / Q / cm) and the text line matrix (BT, Td, TD, Tm, T*, ', ").
    Glyph advances are not tracked, so several operators that continue one another on a
    line all report the line's start - which is exactly what removing a whole line needs.
    """
    out: list = []
    removed = 0
    ctm, stack = _IDENTITY, []
    line = _IDENTITY
    leading = 0.0

    def inside() -> bool:
        x, y = _mul(line, ctm)[4:6]
        return any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in boxes)

    def numbers(operands: list, count: int) -> Optional[List[float]]:
        try:
            return [float(v) for v in operands[:count]] if len(operands) >= count else None
        except (TypeError, ValueError):
            return None

    for operands, operator in operations:
        op = operator if isinstance(operator, bytes) else str(operator).encode("latin-1")
        if op == b"q":
            stack.append(ctm)
        elif op == b"Q":
            ctm = stack.pop() if stack else ctm
        elif op == b"cm":
            m = numbers(operands, 6)
            if m:
                ctm = _mul(tuple(m), ctm)
        elif op == b"BT":
            line = _IDENTITY
        elif op in (b"Td", b"TD"):
            t = numbers(operands, 2)
            if t:
                line = _mul((1, 0, 0, 1, t[0], t[1]), line)
                if op == b"TD":
                    leading = -t[1]
        elif op == b"TL":
            t = numbers(operands, 1)
            if t:
                leading = t[0]
        elif op == b"Tm":
            m = numbers(operands, 6)
            if m:
                line = tuple(m)
        elif op == b"T*":
            line = _mul((1, 0, 0, 1, 0, -leading), line)
        elif op in (b"Tj", b"TJ"):
            if inside():
                removed += 1
                continue
        elif op in (b"'", b'"'):
            line = _mul((1, 0, 0, 1, 0, -leading), line)
            if inside():
                removed += 1
                # Keep the side effects of the operator (spacing, move to next line) without the text.
                if op == b'"' and len(operands) >= 3:
                    out.append(([operands[0]], b"Tw"))
                    out.append(([operands[1]], b"Tc"))
                out.append(([], b"T*"))
                continue
        out.append((operands, operator))
    return out, removed


def _words_of(page_object: Any) -> List[Tuple[str, float, float]]:
    """(text, centre x, centre y from top) of every word on a single page, via a throw-away PDF."""
    import pdfplumber

    buf = io.BytesIO()
    probe = PdfWriter()
    probe.add_page(page_object)
    probe.write(buf)
    probe.close()
    buf.seek(0)
    with pdfplumber.open(buf) as pdf:
        return [(w["text"], (w["x0"] + w["x1"]) / 2, (w["top"] + w["bottom"]) / 2) for w in pdf.pages[0].extract_words()]


def _replace_text(writer: PdfWriter, page: Any, replacements: List[dict], width: float, height: float, left: float, bottom: float) -> int:
    """Remove the original lines for `replacements` from the page. Returns how many had to be covered instead.

    The removal is verified by re-reading the page: the words inside the boxes must be gone
    and every other word must still be there. If not, the page content is put back and the
    edits are marked to be painted over.
    """
    from pypdf.generic import ContentStream, NameObject

    def in_box(cx: float, cy: float, pad: float = 0.0) -> bool:
        for r in replacements:
            b = r["replaces"]
            if b["x"] - pad <= cx <= b["x"] + b["w"] + pad and b["y"] - pad <= cy <= b["y"] + b["h"] + pad:
                return True
        return False

    def cover_all() -> int:
        for r in replacements:
            r["_cover"] = True
        return len(replacements)

    try:
        before = _words_of(page)
        content = page.get_contents()
        if content is None:
            return cover_all()
        if not isinstance(content, ContentStream):
            content = ContentStream(content, writer)
        original = list(content.operations)
        # Boxes in PDF user space (origin bottom-left), slightly widened: a line's start point
        # sits on its baseline at its left edge.
        boxes = []
        for r in replacements:
            b = r["replaces"]
            top = bottom + height - b["y"]
            boxes.append((left + b["x"] - 1.5, top - b["h"] - 2.0, left + b["x"] + b["w"] + 1.5, top + 2.0))
        stripped, removed = _strip_text(original, boxes)
        if removed == 0:
            return cover_all()
        content.operations = stripped
        page[NameObject("/Contents")] = writer._add_object(content)

        after = _words_of(page)
        kept_before = sorted((t, round(x), round(y)) for t, x, y in before if not in_box(x, y))
        kept_after = sorted((t, round(x), round(y)) for t, x, y in after if not in_box(x, y))
        still_there = any(in_box(x, y) for _t, x, y in after)
        if kept_before != kept_after or still_there:
            content.operations = original                 # put the page back exactly as it was
            page[NameObject("/Contents")] = writer._add_object(content)
            return cover_all()
        return 0
    except EngineError:
        raise
    except Exception:  # noqa: BLE001 - an unusual content stream must not lose the user's edit
        return cover_all()


def _hex_color(value: Any) -> str:
    """pdfminer colour (gray, RGB or CMYK components in 0..1) -> '#rrggbb'."""
    try:
        parts = [float(v) for v in (value if isinstance(value, (list, tuple)) else [value])]
    except (TypeError, ValueError):
        return "#000000"
    if len(parts) == 1:
        r = g = b = parts[0]
    elif len(parts) == 3:
        r, g, b = parts
    elif len(parts) == 4:
        c, m, y, k = parts
        r, g, b = (1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k)
    else:
        return "#000000"
    return "#" + "".join(f"{max(0, min(255, round(v * 255))):02x}" for v in (r, g, b))


@method("pdf.text_lines")
def pdf_text_lines(params, ctx):
    """{input, page, password?} -> {editable, lines: [{x, y, w, h, text, size, family, bold, italic, color}]}

    One entry per run of text on a visual line (a wide gap, as between table cells, starts a
    new run). Coordinates are points from the top-left of the displayed page.
    """
    path = in_path(params)
    index = int(params.get("page", 0))
    with open_plumber(path, params.get("password")) as pdf:
        if not 0 <= index < len(pdf.pages):
            raise EngineError("bad_params", f"Page {index + 1} is out of range")
        page = pdf.pages[index]
        if (page.rotation or 0) % 360 != 0:
            return {"editable": False, "reason": "Text on a rotated page cannot be edited in place yet.", "lines": []}
        colors = {(round(ch["x0"], 1), round(ch["top"], 1)): ch.get("non_stroking_color") for ch in page.chars}
        words = page.extract_words(extra_attrs=["fontname", "size"], keep_blank_chars=False)
    words.sort(key=lambda w: (round(w["top"]), w["x0"]))

    lines: List[dict] = []
    current: List[dict] = []

    def flush() -> None:
        if not current:
            return
        first = current[0]
        font = str(first["fontname"]).lower()
        x0, x1 = min(w["x0"] for w in current), max(w["x1"] for w in current)
        top, bottom = min(w["top"] for w in current), max(w["bottom"] for w in current)
        lines.append({
            "x": round(x0, 2), "y": round(top, 2), "w": round(x1 - x0, 2), "h": round(bottom - top, 2),
            "text": " ".join(w["text"] for w in current),
            "size": round(float(first["size"]), 2),
            "family": "mono" if ("courier" in font or "mono" in font or "consol" in font)
            else "serif" if ("times" in font or "serif" in font or "georgia" in font or "garamond" in font or "cambria" in font)
            else "sans",
            "bold": "bold" in font or "black" in font or "heavy" in font,
            "italic": "italic" in font or "oblique" in font,
            "color": _hex_color(colors.get((round(first["x0"], 1), round(first["top"], 1)))),
        })
        current.clear()

    for word in words:
        if current:
            prev = current[-1]
            same_line = abs(word["top"] - prev["top"]) <= 3.0
            gap = word["x0"] - prev["x1"]
            same_style = prev["fontname"] == word["fontname"] and abs(prev["size"] - word["size"]) < 0.5
            if not (same_line and same_style and gap <= max(0.9 * float(word["size"]), 6.0)):
                flush()
        current.append(word)
    flush()
    return {"editable": True, "lines": lines}


@method("pdf.apply_edits")
def pdf_apply_edits(params, ctx):
    """{input, output, pages?: [{source, rotate?}], edits?: [{page, type, ...}], password?}"""
    path = in_path(params)
    output = Path(str(params["output"]))
    password = params.get("password")
    reader = _reader(path, password)
    count = len(reader.pages)

    specs = params.get("pages")
    if specs is None:
        specs = [{"source": i} for i in range(count)]
    if not specs:
        raise EngineError("bad_params", "A PDF must keep at least one page")
    edits = params.get("edits") or []
    if len(edits) > MAX_EDITS:
        raise EngineError("bad_params", f"Too many edits (limit {MAX_EDITS})")

    by_page: Dict[int, List[dict]] = defaultdict(list)
    for edit in edits:
        if not isinstance(edit, dict) or edit.get("type") not in EDIT_TYPES:
            raise EngineError("bad_params", f"Unknown edit type: {edit.get('type') if isinstance(edit, dict) else edit}")
        index = edit.get("page")
        if not isinstance(index, int) or not 0 <= index < count:
            raise EngineError("bad_params", "An edit references a page that does not exist")
        if edit.get("replaces") is not None:
            box = edit["replaces"]
            if edit["type"] != "text" or not isinstance(box, dict):
                raise EngineError("bad_params", "Only a text edit can replace existing text")
            for key in ("x", "y", "w", "h"):
                _num(box, key)
        by_page[index].append(dict(edit))               # copied: edits get private flags while being applied

    writer = PdfWriter()
    stats = {"pages": 0, "redacted_pages": 0, "edits": 0, "text_replaced": 0, "text_covered": 0}
    for n, spec in enumerate(specs):
        ctx.progress(n / len(specs), f"page {n + 1}/{len(specs)}")
        source = spec.get("source")
        if not isinstance(source, int) or not 0 <= source < count:
            raise EngineError("bad_params", "Page order references a page that does not exist")
        rotate = int(spec.get("rotate") or 0) % 360
        if rotate % 90:
            raise EngineError("bad_params", "Pages can only be rotated in 90 degree steps")
        page_edits = by_page.get(source, [])
        boxes = [e for e in page_edits if e["type"] == "redact"]
        replacements = [e for e in page_edits if e.get("replaces")]
        for r in replacements:
            r.pop("_cover", None)                         # decided afresh for every copy of the page

        if boxes:
            raster, width, height = _redacted_page(path, password, source, boxes)
            page = writer.add_page(raster)
            left = bottom = 0.0
            stats["redacted_pages"] += 1
        else:
            page = writer.add_page(reader.pages[source])
            # Bake the page's own /Rotate into its content so that our top-left
            # coordinates line up with what the viewer displayed.
            page.transfer_rotation_to_content()
            box = page.cropbox
            width, height = float(box.width), float(box.height)
            left, bottom = float(box.left), float(box.bottom)
            if replacements:
                covered = _replace_text(writer, page, replacements, width, height, left, bottom)
                stats["text_covered"] += covered
                stats["text_replaced"] += len(replacements) - covered

        overlay = _overlay(page_edits, width, height)
        if overlay is not None:
            page.merge_translated_page(overlay, left, bottom)
        for note in (e for e in page_edits if e["type"] == "note"):
            x, y = _num(note, "x"), _num(note, "y")
            top = bottom + height - y
            writer.add_annotation(
                page, TextAnnotation(rect=(left + x, top - 20, left + x + 20, top), text=str(note.get("text", "")))
            )
        if rotate:
            page.rotate(rotate)
        stats["pages"] += 1
        stats["edits"] += len(page_edits)

    with atomic_output(output) as tmp:
        writer.write(str(tmp))
    writer.close()
    result: Dict[str, Any] = {"output": str(output), **stats}
    if stats["text_covered"]:
        result["warning"] = (
            f"{stats['text_covered']} text change(s) were painted over rather than removed: "
            "the original text is hidden but still present in the file."
        )
    return result


@method("pdf.image_data_url")
def pdf_image_data_url(params, ctx):
    """{input} -> PNG data URL of a user-picked image, for stamping onto a page."""
    path = in_path(params)
    try:
        image = Image.open(path)
        image.load()
    except Exception as exc:  # noqa: BLE001
        raise EngineError("unsupported_format", f"Could not read image: {path.name}") from exc
    if max(image.size) > MAX_IMAGE_SIDE:
        image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA")
    buf = io.BytesIO()
    image.save(buf, "PNG")
    return {
        "width": image.width,
        "height": image.height,
        "data_url": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii"),
    }
