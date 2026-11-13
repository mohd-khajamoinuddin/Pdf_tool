"""OpenDocument Presentation (.odp) read/write for the slide designer.

Converts the same deck model that presentation.py describes.

Carried both ways: slide size, per-slide background colour, text boxes (font,
size, bold / italic / underline, colour, alignment), rectangles, rounded
rectangles, ellipses, triangles, lines, images, speaker notes.

Not carried: rotation, transitions, arrow heads (an arrow is saved as a line)
and bullets (bulleted text is saved as plain lines). Reading an .odp made in
another program resolves direct formatting only; text sizes and colours that
come from its master page or named styles fall back to defaults.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..rpc import EngineError

_UNITS = {"pt": 1.0, "cm": 72 / 2.54, "mm": 72 / 25.4, "in": 72.0, "px": 0.75}
ALIGN_ODF = {"left": "start", "center": "center", "right": "end"}
ALIGN_FROM_ODF = {"start": "left", "left": "left", "center": "center", "end": "right", "right": "right"}


def _pt(value: Any, default: float = 0.0) -> float:
    match = re.fullmatch(r"\s*(-?[\d.]+)\s*(pt|cm|mm|in|px)\s*", str(value or ""))
    return round(float(match.group(1)) * _UNITS[match.group(2)], 2) if match else default


def _len(points: Any) -> str:
    return f"{float(points or 0):.2f}pt"


def _local(node: Any) -> str:
    return getattr(node, "qname", ("", ""))[1]


def style_name(el: Any) -> Optional[str]:
    """The element's style reference.

    Several ODF elements allow more than one `*:style-name` attribute (draw, presentation,
    text, table). odfpy's getAttribute("stylename") picks whichever it meets first, so ask
    for each namespace explicitly instead.
    """
    from odf.namespaces import DRAWNS, PRESENTATIONNS, TABLENS, TEXTNS

    for namespace in (DRAWNS, PRESENTATIONNS, TEXTNS, TABLENS):
        try:
            value = el.getAttrNS(namespace, "style-name")
        except (ValueError, KeyError, AttributeError):
            continue
        if value:
            return str(value)
    return None


def _attr(el: Any, name: str) -> Any:
    """getAttribute that answers None for attributes the element type does not define (odfpy raises)."""
    try:
        return el.getAttribute(name)
    except ValueError:
        return None


# ====================================================================== write

class _OdpWriter:
    def __init__(self, deck: dict):
        from odf.opendocument import OpenDocumentPresentation
        from odf.style import MasterPage, PageLayout, PageLayoutProperties

        self.doc = OpenDocumentPresentation()
        self.width, self.height = float(deck.get("width") or 960), float(deck.get("height") or 540)
        self.styles: Dict[tuple, str] = {}
        layout = PageLayout(name="Layout")
        layout.addElement(PageLayoutProperties(
            margin="0pt", pagewidth=_len(self.width), pageheight=_len(self.height), printorientation="landscape"))
        self.doc.automaticstyles.addElement(layout)
        self.doc.masterstyles.addElement(MasterPage(name="Default", pagelayoutname="Layout"))
        self.style_objects: Dict[str, Any] = {}

    def style(self, family: str, prefix: str, element_factory, **props: str) -> str:
        """One automatic style per distinct set of properties."""
        from odf.style import Style

        key = (family, tuple(sorted(props.items())))
        if key not in self.styles:
            name = f"{prefix}{len(self.styles) + 1}"
            style = Style(name=name, family=family)
            style.addElement(element_factory(**props))
            self.doc.automaticstyles.addElement(style)
            self.styles[key] = name
            self.style_objects[name] = style
        return self.styles[key]

    def drawing(self, name: str) -> Any:
        """odfpy's drawing elements want the Style object itself, not its name."""
        return self.style_objects[name]

    def graphic(self, el: dict, text_box: bool = False) -> str:
        from odf.style import GraphicProperties

        if text_box:
            return self.style("graphic", "gr", GraphicProperties, fill="none", stroke="none",
                              paddingtop="0pt", paddingbottom="0pt", paddingleft="0pt", paddingright="0pt",
                              autogrowheight="false", textareaverticalalign="top")
        props = {"fill": "solid" if el.get("fill") else "none", "stroke": "none"}
        if el.get("fill"):
            props["fillcolor"] = str(el["fill"])
            if float(el.get("opacity", 1) or 1) < 0.999:
                props["opacity"] = f"{round(float(el['opacity']) * 100)}%"
        if el.get("stroke") and float(el.get("strokeWidth") or 0) > 0:
            props.update(stroke="solid", strokecolor=str(el["stroke"]), strokewidth=_len(el["strokeWidth"]))
        return self.style("graphic", "gr", GraphicProperties, **props)

    def text(self, page: Any, el: dict) -> None:
        from odf.draw import Frame, TextBox
        from odf.style import ParagraphProperties, TextProperties
        from odf.text import P, Span

        text_props = {"fontsize": _len(el.get("fontSize") or 18), "fontfamily": str(el.get("fontFamily") or "Calibri"),
                      "color": str(el.get("color") or "#000000"),
                      "fontweight": "bold" if el.get("bold") else "normal",
                      "fontstyle": "italic" if el.get("italic") else "normal"}
        if el.get("underline"):
            text_props.update(textunderlinestyle="solid", textunderlinewidth="auto", textunderlinecolor="font-color")
        span_style = self.style("text", "T", TextProperties, **text_props)
        para_style = self.style("paragraph", "P", ParagraphProperties, textalign=ALIGN_ODF.get(el.get("align"), "start"))
        frame = Frame(stylename=self.drawing(self.graphic(el, text_box=True)), x=_len(el["x"]), y=_len(el["y"]),
                      width=_len(el["w"]), height=_len(el["h"]))
        box = TextBox()
        for line in str(el.get("text", "")).split("\n"):
            p = P(stylename=para_style)
            p.addElement(Span(stylename=span_style, text=line))
            box.addElement(p)
        frame.addElement(box)
        page.addElement(frame)

    def shape(self, page: Any, el: dict) -> None:
        from odf.draw import Ellipse, Line, Polygon, Rect

        kind = el.get("shape")
        x, y, w, h = float(el["x"]), float(el["y"]), float(el["w"]), float(el["h"])
        if kind in ("line", "arrow"):
            style = self.graphic({"stroke": el.get("stroke") or "#000000", "strokeWidth": max(float(el.get("strokeWidth") or 0), 0.75)})
            page.addElement(Line(stylename=self.drawing(style), x1=_len(x), y1=_len(y), x2=_len(x + w), y2=_len(y + h)))
            return
        box = {"stylename": self.drawing(self.graphic(el)), "x": _len(x), "y": _len(y), "width": _len(w), "height": _len(h)}
        if kind == "ellipse":
            page.addElement(Ellipse(**box))
        elif kind == "triangle":
            page.addElement(Polygon(viewbox="0 0 100 100", points="50,0 100,100 0,100", **box))
        elif kind == "roundRect":
            page.addElement(Rect(cornerradius=_len(min(w, h) * 0.16), **box))
        elif kind == "rect":
            page.addElement(Rect(**box))
        else:
            raise EngineError("bad_params", f"Unknown shape: {kind}")

    def image(self, page: Any, el: dict) -> None:
        from odf.draw import Frame, Image

        from .pdf_edit import decode_data_url

        src = str(el.get("src", ""))
        decode_data_url(src)                              # validates; raises EngineError on junk
        media = src[5 : src.index(";")]
        href = self.doc.addPictureFromString(base64.b64decode(src.split(",", 1)[1]), media)
        frame = Frame(x=_len(el["x"]), y=_len(el["y"]), width=_len(el["w"]), height=_len(el["h"]))
        frame.addElement(Image(href=href))
        page.addElement(frame)

    def slide(self, index: int, data: dict) -> None:
        from odf.draw import Frame, Page, TextBox
        from odf.presentation import Notes
        from odf.style import DrawingPageProperties
        from odf.text import P

        page_style = self.style("drawing-page", "dp", DrawingPageProperties, fill="solid",
                                fillcolor=str(data.get("background") or "#ffffff"), backgroundvisible="true",
                                backgroundobjectsvisible="true")
        page = Page(name=f"Slide {index + 1}", stylename=self.drawing(page_style), masterpagename="Default")
        for el in data.get("elements") or []:
            kind = el.get("type")
            if kind == "text":
                self.text(page, el)
            elif kind == "shape":
                self.shape(page, el)
            elif kind == "image":
                self.image(page, el)
            else:
                raise EngineError("bad_params", f"Unknown element type: {kind}")
        if str(data.get("notes") or "").strip():
            notes = Notes()
            frame = Frame(x="36pt", y=_len(self.height), width=_len(self.width - 72), height="200pt")
            box = TextBox()
            for line in str(data["notes"]).split("\n"):
                box.addElement(P(text=line))
            frame.addElement(box)
            notes.addElement(frame)
            page.addElement(notes)
        self.doc.presentation.addElement(page)


def write_odp(target: Path, deck: dict) -> int:
    slides = deck.get("slides") or []
    if not slides:
        raise EngineError("bad_params", "A presentation needs at least one slide")
    writer = _OdpWriter(deck)
    for index, slide in enumerate(slides):
        writer.slide(index, slide)
    writer.doc.save(str(target))
    return len(slides)


# ====================================================================== read

class _OdpReader:
    def __init__(self, document: Any):
        self.doc = document
        self.styles: Dict[str, Any] = {}
        for holder in (document.styles, document.automaticstyles):
            for style in holder.childNodes:
                name = style.getAttribute("name") if hasattr(style, "getAttribute") else None
                if name:
                    self.styles[name] = style
        self.skipped: Dict[str, int] = {}

    def skip(self, what: str) -> None:
        self.skipped[what] = self.skipped.get(what, 0) + 1

    def props(self, style_name: Optional[str], kind: str) -> Any:
        style = self.styles.get(style_name or "")
        if style is None:
            return None
        return next((c for c in style.childNodes if _local(c) == kind), None)

    def box(self, el: Any) -> Dict[str, float]:
        if _attr(el, "transform"):
            self.skip("rotated or transformed object (placed unrotated)")
        return {"x": _pt(el.getAttribute("x")), "y": _pt(el.getAttribute("y")),
                "w": _pt(el.getAttribute("width")), "h": _pt(el.getAttribute("height")), "rotation": 0}

    def shape_style(self, el: Any) -> Dict[str, Any]:
        props = self.props(style_name(el), "graphic-properties")
        get = props.getAttribute if props is not None else (lambda _name: None)
        fill = str(get("fillcolor")).lower() if get("fill") == "solid" and get("fillcolor") else None
        if props is None or get("fill") is None:
            fill = "#729fcf"                                # the usual default fill of an unstyled shape
        stroke = str(get("strokecolor")).lower() if get("stroke") == "solid" and get("strokecolor") else None
        opacity = 1.0
        if get("opacity") and str(get("opacity")).endswith("%"):
            opacity = round(float(str(get("opacity"))[:-1]) / 100, 2)
        return {"fill": fill, "stroke": stroke, "strokeWidth": _pt(get("strokewidth"), 1.0) if stroke else 0, "opacity": opacity}

    def text(self, frame: Any, box_el: Any) -> Optional[dict]:
        from odf import teletype

        paragraphs = [p for p in box_el.childNodes if _local(p) in ("p", "h")]
        for lst in (n for n in box_el.childNodes if _local(n) == "list"):       # outline placeholders nest text in lists
            for node in _descendants(lst):
                if _local(node) == "p":
                    paragraphs.append(node)
        lines = [teletype.extractText(p) for p in paragraphs]
        if not "".join(lines).strip():
            return None
        role = _attr(frame, "class")
        is_title = role == "title"
        el: Dict[str, Any] = {
            **self.box(frame), "type": "text", "text": "\n".join(lines),
            "fontFamily": "Calibri", "fontSize": 40 if is_title else 24 if role else 18,
            "bold": False, "italic": False, "underline": False, "color": "#1c2128",
            "align": "center" if is_title else "left", "bullets": role in ("outline", "subtitle") and len(lines) > 1,
        }
        first_p = paragraphs[0]
        para = self.props(style_name(first_p), "paragraph-properties")
        if para is not None and para.getAttribute("textalign") in ALIGN_FROM_ODF:
            el["align"] = ALIGN_FROM_ODF[para.getAttribute("textalign")]
        span = next((n for n in _descendants(first_p) if _local(n) == "span" and style_name(n)), None)
        for source in (first_p, span):
            props = self.props(style_name(source), "text-properties") if source is not None else None
            if props is None:
                continue
            get = props.getAttribute
            if get("fontsize") and str(get("fontsize")).endswith("pt"):
                el["fontSize"] = float(str(get("fontsize"))[:-2])
            if get("fontfamily") or get("fontname"):
                el["fontFamily"] = str(get("fontfamily") or get("fontname")).strip("'\"")
            if get("color"):
                el["color"] = str(get("color")).lower()
            if get("fontweight"):
                el["bold"] = get("fontweight") == "bold"
            if get("fontstyle"):
                el["italic"] = get("fontstyle") == "italic"
            if get("textunderlinestyle"):
                el["underline"] = get("textunderlinestyle") != "none"
        return el

    def slide(self, page: Any) -> dict:
        from odf import teletype

        elements: List[dict] = []
        notes = ""
        for el in page.childNodes:
            kind = _local(el)
            if kind == "frame":
                inner = next((c for c in el.childNodes if _local(c) in ("text-box", "image", "object", "plugin")), None)
                inner_kind = _local(inner) if inner is not None else ""
                if inner_kind == "text-box":
                    text = self.text(el, inner)
                    if text:
                        elements.append(text)
                elif inner_kind == "image":
                    picture = self.doc.Pictures.get(inner.getAttribute("href"))
                    if picture:
                        _, data, media = picture
                        src = f"data:{media};base64," + base64.b64encode(data).decode("ascii")
                        elements.append({**self.box(el), "type": "image", "src": src})
                    else:
                        self.skip("linked picture")
                else:
                    self.skip("embedded object (chart, table, media)")
            elif kind in ("rect", "ellipse", "polygon", "custom-shape"):
                shape = {"rect": "roundRect" if _attr(el, "cornerradius") else "rect", "ellipse": "ellipse",
                         "polygon": "triangle", "custom-shape": "rect"}[kind]
                if kind == "custom-shape":
                    self.skip("shape drawn as a rectangle")
                elements.append({**self.box(el), "type": "shape", "shape": shape, **self.shape_style(el)})
                label = teletype.extractText(el).strip()
                if label:
                    elements.append({**self.box(el), "type": "text", "text": label, "fontFamily": "Calibri", "fontSize": 18,
                                     "bold": False, "italic": False, "underline": False, "color": "#1c2128",
                                     "align": "center", "bullets": False})
            elif kind == "line":
                x1, y1 = _pt(el.getAttribute("x1")), _pt(el.getAttribute("y1"))
                style = self.shape_style(el)
                elements.append({"x": x1, "y": y1, "w": round(_pt(el.getAttribute("x2")) - x1, 2),
                                 "h": round(_pt(el.getAttribute("y2")) - y1, 2), "rotation": 0, "type": "shape", "shape": "line",
                                 "fill": None, "stroke": style["stroke"] or "#1c2128", "strokeWidth": style["strokeWidth"] or 1.5,
                                 "opacity": 1})
            elif kind == "notes":
                notes = "\n".join(teletype.extractText(p) for p in _descendants(el) if _local(p) == "p").strip()
            elif kind in ("g", "connector", "path", "table"):
                self.skip({"g": "group", "connector": "connector", "path": "freeform path", "table": "table"}[kind])

        background = "#ffffff"
        page_props = self.props(style_name(page), "drawing-page-properties")
        if page_props is not None and page_props.getAttribute("fill") == "solid" and page_props.getAttribute("fillcolor"):
            background = str(page_props.getAttribute("fillcolor")).lower()
        return {"background": background, "notes": notes, "transition": {"type": "none", "duration": 0.6}, "elements": elements}


def _descendants(node: Any):
    for child in getattr(node, "childNodes", []):
        yield child
        yield from _descendants(child)


def read_odp(path: Path) -> dict:
    from odf.draw import Page
    from odf.opendocument import load
    from odf.style import PageLayoutProperties

    try:
        document = load(str(path))
    except Exception as exc:  # noqa: BLE001
        raise EngineError("invalid_file", f"Could not read presentation: {exc}") from exc
    width, height = 960.0, 540.0
    for layout in document.automaticstyles.getElementsByType(PageLayoutProperties):
        if layout.getAttribute("pagewidth") and layout.getAttribute("pageheight"):
            width, height = _pt(layout.getAttribute("pagewidth"), 960), _pt(layout.getAttribute("pageheight"), 540)
            break
    reader = _OdpReader(document)
    slides = [reader.slide(page) for page in document.presentation.getElementsByType(Page)]
    if not slides:
        raise EngineError("invalid_file", "The presentation has no slides")
    notes = [f"{count} × {what}" for what, count in reader.skipped.items()]
    notes.append("master page artwork, transitions and formatting inherited from named styles")
    return {"deck": {"width": width, "height": height, "slides": slides}, "notes": notes}
