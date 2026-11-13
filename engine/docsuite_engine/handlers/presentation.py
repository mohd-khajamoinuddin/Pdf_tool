"""Presentation I/O for the slide designer (slides.open / slides.save / exports).

.pptx is handled here; .odp is delegated to odf_slides.py.

Deck model (all lengths in points; a 16:9 slide is 960 x 540):

    {width, height, slides: [{background: "#rrggbb", notes, transition: {type, duration},
                              elements: [element, ...]}]}

    element = {type, x, y, w, h, rotation, ...}
      text  : text, fontFamily, fontSize, bold, italic, underline, color, align, bullets
      shape : shape (rect | roundRect | ellipse | triangle | line | arrow), fill, stroke, strokeWidth, opacity
      image : src (data URL)

For `line` / `arrow`, (x, y) is the start and (x + w, y + h) the end, so w and h may be negative.
A text box has one format for all of its text; mixed formatting inside a box is flattened on import.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..rpc import EngineError, method
from ..util import atomic_output, in_path, out_dir

EMU_PER_PT = 12700
TRANSITIONS = ("none", "fade", "push", "wipe", "split", "cover")
SHAPES = ("rect", "roundRect", "ellipse", "triangle", "line", "arrow")
P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _pt(emu: Optional[int]) -> float:
    return round((emu or 0) / EMU_PER_PT, 2)


def _emu(points: Any) -> int:
    return int(round(float(points or 0) * EMU_PER_PT))


def _rgb(color_format: Any) -> Optional[str]:
    """python-pptx colour -> '#rrggbb'; theme colours are not resolved (None)."""
    try:
        if color_format is not None and color_format.type is not None and color_format.rgb is not None:
            return "#" + str(color_format.rgb).lower()
    except (AttributeError, TypeError, ValueError):
        pass
    return None


# ================================================================== reading

def _transition_in(slide: Any) -> dict:
    node = slide._element.find(f"{{{P_NS}}}transition")
    if node is None:
        # PowerPoint 2010+ wraps it in mc:AlternateContent; look anywhere below the slide root.
        node = next(iter(slide._element.iter(f"{{{P_NS}}}transition")), None)
    if node is None or len(node) == 0:
        return {"type": "none", "duration": 0.6}
    kind = node[0].tag.rsplit("}", 1)[-1]
    speed = {"slow": 1.0, "med": 0.6, "fast": 0.3}.get(node.get("spd", "med"), 0.6)
    return {"type": kind if kind in TRANSITIONS else "fade", "duration": speed}


def _text_element(shape: Any, box: dict, notes: Dict[str, int]) -> Optional[dict]:
    from pptx.enum.text import PP_ALIGN

    frame = shape.text_frame
    paragraphs = [p for p in frame.paragraphs]
    text = "\n".join("".join(r.text for r in p.runs) or p.text for p in paragraphs).strip("\n")
    if not text.strip():
        return None
    runs = [r for p in paragraphs for r in p.runs]
    first = runs[0].font if runs else None
    if len({(r.font.bold, r.font.italic, r.font.size, _rgb(r.font.color)) for r in runs}) > 1:
        notes["text box with mixed formatting (flattened)"] = notes.get("text box with mixed formatting (flattened)", 0) + 1

    is_title = False
    is_body = False
    if shape.is_placeholder:
        kind = str(shape.placeholder_format.type)
        is_title = "TITLE" in kind and "SUB" not in kind
        is_body = "BODY" in kind or "OBJECT" in kind
    size = first.size.pt if first is not None and first.size is not None else (40 if is_title else 24 if shape.is_placeholder else 18)
    align = "left"
    if paragraphs and paragraphs[0].alignment is not None:
        align = {PP_ALIGN.CENTER: "center", PP_ALIGN.RIGHT: "right"}.get(paragraphs[0].alignment, "left")
    elif is_title:
        align = "center"
    return {
        **box,
        "type": "text",
        "text": text,
        "fontFamily": (first.name if first is not None and first.name else "Calibri"),
        "fontSize": size,
        "bold": bool(first.bold) if first is not None else False,
        "italic": bool(first.italic) if first is not None else False,
        "underline": bool(first.underline) if first is not None else False,
        "color": (_rgb(first.color) if first is not None else None) or "#1c2128",
        "align": align,
        "bullets": is_body or any(p._p.find(f".//{{{A_NS}}}buChar") is not None for p in paragraphs),
    }


def _shape_element(shape: Any, box: dict, notes: Dict[str, int]) -> Optional[dict]:
    from pptx.enum.dml import MSO_FILL
    from pptx.enum.shapes import MSO_SHAPE

    kinds = {
        MSO_SHAPE.RECTANGLE: "rect", MSO_SHAPE.ROUNDED_RECTANGLE: "roundRect",
        MSO_SHAPE.OVAL: "ellipse", MSO_SHAPE.ISOSCELES_TRIANGLE: "triangle",
    }
    try:
        auto = shape.auto_shape_type
    except (ValueError, AttributeError):
        return None                                   # a plain text box, not a drawn shape
    kind = kinds.get(auto)
    if kind is None:
        kind = "rect"
        notes["shape drawn as a rectangle"] = notes.get("shape drawn as a rectangle", 0) + 1
    fill = None
    try:
        if shape.fill.type == MSO_FILL.SOLID:
            fill = _rgb(shape.fill.fore_color) or "#4472c4"
        elif shape.fill.type is None:
            fill = "#4472c4"                          # inherits the theme's accent fill
    except (AttributeError, TypeError):
        fill = "#4472c4"
    stroke, width = None, 0.0
    try:
        if shape.line.fill.type == MSO_FILL.SOLID:
            stroke = _rgb(shape.line.color) or "#2f528f"
            width = shape.line.width.pt if shape.line.width else 1.0
    except (AttributeError, TypeError):
        pass
    return {**box, "type": "shape", "shape": kind, "fill": fill, "stroke": stroke, "strokeWidth": width, "opacity": 1}


def _read_slide(slide: Any, notes: Dict[str, int]) -> dict:
    from pptx.enum.dml import MSO_FILL
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    def skipped(what: str) -> None:
        notes[what] = notes.get(what, 0) + 1

    elements: List[dict] = []
    for shape in slide.shapes:
        if shape.width is None or shape.height is None:
            skipped("placeholder without a size")
            continue
        box = {
            "x": _pt(shape.left), "y": _pt(shape.top), "w": _pt(shape.width), "h": _pt(shape.height),
            "rotation": round(float(getattr(shape, "rotation", 0) or 0), 2),
        }
        kind = shape.shape_type
        if kind == MSO_SHAPE_TYPE.PICTURE:
            try:
                image = shape.image
                src = f"data:{image.content_type};base64," + base64.b64encode(image.blob).decode("ascii")
                elements.append({**box, "type": "image", "src": src})
            except Exception:  # noqa: BLE001 - linked (not embedded) pictures have no blob
                skipped("linked picture")
        elif kind == MSO_SHAPE_TYPE.LINE:
            flip_h = shape._element.spPr.find(f"{{{A_NS}}}xfrm")
            fh = flip_h is not None and flip_h.get("flipH") == "1"
            fv = flip_h is not None and flip_h.get("flipV") == "1"
            line = {**box, "rotation": 0}
            if fh:
                line["x"], line["w"] = box["x"] + box["w"], -box["w"]
            if fv:
                line["y"], line["h"] = box["y"] + box["h"], -box["h"]
            has_head = shape._element.find(f".//{{{A_NS}}}tailEnd") is not None or shape._element.find(f".//{{{A_NS}}}headEnd") is not None
            stroke = _rgb(shape.line.color) if shape.line.fill.type == MSO_FILL.SOLID else None
            elements.append({
                **line, "type": "shape", "shape": "arrow" if has_head else "line", "fill": None,
                "stroke": stroke or "#1c2128", "strokeWidth": shape.line.width.pt if shape.line.width else 1.5, "opacity": 1,
            })
        elif kind in (MSO_SHAPE_TYPE.GROUP, MSO_SHAPE_TYPE.CHART, MSO_SHAPE_TYPE.TABLE, MSO_SHAPE_TYPE.MEDIA,
                      MSO_SHAPE_TYPE.EMBEDDED_OLE_OBJECT, MSO_SHAPE_TYPE.DIAGRAM, MSO_SHAPE_TYPE.FREEFORM):
            skipped(str(kind).split(".")[-1].split(" ")[0].lower().replace("_", " "))
        elif getattr(shape, "has_chart", False) or getattr(shape, "has_table", False):
            skipped("chart" if getattr(shape, "has_chart", False) else "table")
        else:
            drawn = None if shape.is_placeholder else _shape_element(shape, box, notes)
            if drawn:
                elements.append(drawn)
            if shape.has_text_frame:
                text = _text_element(shape, box, notes)
                if text:
                    if drawn:                          # label inside a drawn shape: centre it like PowerPoint does
                        text["align"] = "center"
                    elements.append(text)

    background = "#ffffff"
    try:
        if slide.background.fill.type == MSO_FILL.SOLID:
            background = _rgb(slide.background.fill.fore_color) or background
    except (AttributeError, TypeError):
        pass
    speaker = ""
    if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
        speaker = slide.notes_slide.notes_text_frame.text.strip()
    if slide._element.find(f"{{{P_NS}}}timing") is not None:
        skipped("animation timeline")
    return {"background": background, "notes": speaker, "transition": _transition_in(slide), "elements": elements}


@method("slides.open")
def slides_open(params, ctx):
    """{input} -> {deck, notes: [str]}"""
    path = in_path(params)
    ext = path.suffix.lower()
    if ext == ".odp":
        from .odf_slides import read_odp

        return {"path": str(path), **read_odp(path)}
    if ext != ".pptx":
        raise EngineError("unsupported_format", f"Cannot open {path.suffix or 'this file'} as a presentation")
    from pptx import Presentation

    try:
        prs = Presentation(str(path))
    except Exception as exc:  # noqa: BLE001
        raise EngineError("invalid_file", f"Could not read presentation: {exc}") from exc
    skipped: Dict[str, int] = {}
    slides = []
    for i, slide in enumerate(prs.slides):
        ctx.progress(i / max(len(prs.slides), 1), f"slide {i + 1}/{len(prs.slides)}")
        slides.append(_read_slide(slide, skipped))
    notes = [f"{count} × {what}" for what, count in skipped.items()]
    notes.append("theme, master and layout artwork")      # never carried over: slides are rebuilt from elements
    deck = {"width": _pt(prs.slide_width), "height": _pt(prs.slide_height), "slides": slides}
    return {"path": str(path), "deck": deck, "notes": notes}


# ================================================================== writing

def _color(value: Any, default: str = "000000"):
    from pptx.dml.color import RGBColor

    text = str(value or "").lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    try:
        return RGBColor.from_string(text.upper() if len(text) == 6 else default)
    except ValueError:
        return RGBColor.from_string(default)


def _set_alpha(shape: Any, opacity: float) -> None:
    from lxml import etree

    if opacity >= 0.999:
        return
    for clr in shape._element.spPr.iter(f"{{{A_NS}}}srgbClr"):
        alpha = etree.SubElement(clr, f"{{{A_NS}}}alpha")
        alpha.set("val", str(int(max(0.0, min(1.0, opacity)) * 100000)))


def _add_text(slide: Any, el: dict) -> None:
    from lxml import etree
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Pt

    box = slide.shapes.add_textbox(_emu(el["x"]), _emu(el["y"]), _emu(el["w"]), _emu(el["h"]))
    box.rotation = float(el.get("rotation") or 0)
    frame = box.text_frame
    frame.word_wrap = True
    frame.vertical_anchor = MSO_ANCHOR.TOP
    align = {"center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}.get(el.get("align"), PP_ALIGN.LEFT)
    for i, line in enumerate(str(el.get("text", "")).split("\n")):
        para = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        para.alignment = align
        run = para.add_run()
        run.text = line
        font = run.font
        font.size = Pt(float(el.get("fontSize") or 18))
        font.name = str(el.get("fontFamily") or "Calibri")
        font.bold = bool(el.get("bold"))
        font.italic = bool(el.get("italic"))
        font.underline = bool(el.get("underline"))
        font.color.rgb = _color(el.get("color"))
        if el.get("bullets") and line.strip():
            ppr = para._p.get_or_add_pPr()
            ppr.set("marL", str(_emu(18)))
            ppr.set("indent", str(-_emu(18)))
            bullet = etree.SubElement(ppr, f"{{{A_NS}}}buChar")
            bullet.set("char", "•")


def _add_shape(slide: Any, el: dict) -> None:
    from lxml import etree
    from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
    from pptx.util import Pt

    kind = el.get("shape")
    if kind not in SHAPES:
        raise EngineError("bad_params", f"Unknown shape: {kind}")
    stroke_width = float(el.get("strokeWidth") or 0)
    if kind in ("line", "arrow"):
        x1, y1 = float(el["x"]), float(el["y"])
        line = slide.shapes.add_connector(
            MSO_CONNECTOR.STRAIGHT, _emu(x1), _emu(y1), _emu(x1 + float(el["w"])), _emu(y1 + float(el["h"]))
        )
        line.line.color.rgb = _color(el.get("stroke"))
        line.line.width = Pt(max(stroke_width, 0.75))
        if kind == "arrow":
            ln = line.line._get_or_add_ln()
            etree.SubElement(ln, f"{{{A_NS}}}tailEnd").set("type", "triangle")
        return
    auto = {"rect": MSO_SHAPE.RECTANGLE, "roundRect": MSO_SHAPE.ROUNDED_RECTANGLE,
            "ellipse": MSO_SHAPE.OVAL, "triangle": MSO_SHAPE.ISOSCELES_TRIANGLE}[kind]
    shape = slide.shapes.add_shape(auto, _emu(el["x"]), _emu(el["y"]), _emu(el["w"]), _emu(el["h"]))
    shape.rotation = float(el.get("rotation") or 0)
    shape.shadow.inherit = False
    if el.get("fill"):
        shape.fill.solid()
        shape.fill.fore_color.rgb = _color(el["fill"])
    else:
        shape.fill.background()
    if el.get("stroke") and stroke_width > 0:
        shape.line.color.rgb = _color(el["stroke"])
        shape.line.width = Pt(stroke_width)
    else:
        shape.line.fill.background()
    _set_alpha(shape, float(el.get("opacity", 1) if el.get("opacity") is not None else 1))


def _add_image(slide: Any, el: dict) -> None:
    from .pdf_edit import decode_data_url

    decode_data_url(el.get("src", ""))                 # validates; raises EngineError on junk
    raw = base64.b64decode(str(el["src"]).split(",", 1)[1])
    picture = slide.shapes.add_picture(io.BytesIO(raw), _emu(el["x"]), _emu(el["y"]), _emu(el["w"]), _emu(el["h"]))
    picture.rotation = float(el.get("rotation") or 0)


def _set_transition(slide: Any, transition: dict) -> None:
    from lxml import etree

    kind = (transition or {}).get("type") or "none"
    if kind == "none":
        return
    if kind not in TRANSITIONS:
        raise EngineError("bad_params", f"Unknown transition: {kind}")
    duration = float((transition or {}).get("duration") or 0.6)
    node = etree.Element(f"{{{P_NS}}}transition")
    node.set("spd", "fast" if duration <= 0.4 else "slow" if duration >= 0.9 else "med")
    etree.SubElement(node, f"{{{P_NS}}}{kind}")
    # Schema order inside <p:sld>: cSld, clrMapOvr, transition, timing.
    root = slide._element
    anchor = root.find(f"{{{P_NS}}}clrMapOvr")
    if anchor is None:
        anchor = root.find(f"{{{P_NS}}}cSld")
    anchor.addnext(node)


def _write_pptx(target: Path, deck: dict) -> int:
    from pptx import Presentation

    slides = deck.get("slides") or []
    if not slides:
        raise EngineError("bad_params", "A presentation needs at least one slide")
    prs = Presentation()
    prs.slide_width, prs.slide_height = _emu(deck.get("width") or 960), _emu(deck.get("height") or 540)
    blank = prs.slide_layouts[6]
    for data in slides:
        slide = prs.slides.add_slide(blank)
        fill = slide.background.fill
        fill.solid()
        fill.fore_color.rgb = _color(data.get("background"), "FFFFFF")
        for el in data.get("elements") or []:           # list order is z-order, back to front
            kind = el.get("type")
            if kind == "text":
                _add_text(slide, el)
            elif kind == "shape":
                _add_shape(slide, el)
            elif kind == "image":
                _add_image(slide, el)
            else:
                raise EngineError("bad_params", f"Unknown element type: {kind}")
        if str(data.get("notes") or "").strip():
            slide.notes_slide.notes_text_frame.text = str(data["notes"])
        _set_transition(slide, data.get("transition") or {})
    prs.save(str(target))
    return len(slides)


@method("slides.save")
def slides_save(params, ctx):
    """{output, deck} -> .pptx or .odp by extension."""
    output = Path(str(params["output"]))
    ext = output.suffix.lower()
    if ext not in (".pptx", ".odp"):
        raise EngineError("unsupported_format", "Presentations are saved as .pptx or .odp")
    deck = params["deck"]
    if not isinstance(deck, dict):
        raise EngineError("bad_params", "deck must be an object")
    with atomic_output(output) as tmp:
        if ext == ".odp":
            from .odf_slides import write_odp

            count = write_odp(tmp, deck)
            return {"output": str(output), "slides": count,
                    "warning": "Saved as OpenDocument: rotation, transitions, bullets and arrow heads are not stored in .odp"}
        count = _write_pptx(tmp, deck)
    return {"output": str(output), "slides": count}


# ================================================================== exports

def _png_bytes(data_url: str) -> bytes:
    from .pdf_edit import decode_data_url

    image = decode_data_url(data_url)
    buf = io.BytesIO()
    image.save(buf, "PNG")
    return buf.getvalue()


@method("slides.export_images")
def slides_export_images(params, ctx):
    """{output_dir, images: [data URL per slide], base_name?} -> one PNG per slide."""
    folder = out_dir(params)
    images = params["images"]
    if not images:
        raise EngineError("bad_params", "Nothing to export")
    base = "".join("_" if ch in '<>:"/\\|?*' else ch for ch in str(params.get("base_name") or "slide")).strip() or "slide"
    width = max(2, len(str(len(images))))
    files = []
    for i, data_url in enumerate(images):
        ctx.progress(i / len(images), f"slide {i + 1}/{len(images)}")
        target = folder / f"{base}-{i + 1:0{width}d}.png"
        with atomic_output(target) as tmp:
            tmp.write_bytes(_png_bytes(data_url))
        files.append(str(target))
    return {"output_dir": str(folder), "files": files}


@method("slides.export_pdf")
def slides_export_pdf(params, ctx):
    """{output, images: [data URL per slide], width, height} -> PDF, one slide per page."""
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    output = Path(str(params["output"]))
    images = params["images"]
    if not images:
        raise EngineError("bad_params", "Nothing to export")
    width, height = float(params.get("width") or 960), float(params.get("height") or 540)
    with atomic_output(output) as tmp:
        pdf = canvas.Canvas(str(tmp), pagesize=(width, height))
        for i, data_url in enumerate(images):
            ctx.progress(i / len(images), f"slide {i + 1}/{len(images)}")
            pdf.drawImage(ImageReader(io.BytesIO(_png_bytes(data_url))), 0, 0, width, height)
            pdf.showPage()
        pdf.save()
    return {"output": str(output), "pages": len(images)}


@method("slides.image_data_url")
def slides_image_data_url(params, ctx):
    """{input} -> {data_url, width, height} for placing a user-picked image."""
    from ..rpc import call

    return call("pdf.image_data_url", {"input": params["input"]}, ctx)
