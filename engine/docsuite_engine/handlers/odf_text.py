"""OpenDocument Text (.odt) read/write and RTF (.rtf) write for the word processor.

Both convert the same ProseMirror document JSON that document.py describes.

.odt  read + write: headings, paragraphs with alignment, bold / italic /
      underline / strike / colour / size / font / highlight, nested lists,
      tables with merged cells, images, line and page breaks.
.rtf  write: the same text formatting, headings, tables and images. Lists are
      written as indented paragraphs with a bullet or number typed in front, and
      merged table cells are split - RTF's native forms of both are far more
      involved than the result is worth.

Reading resolves formatting applied directly to text (which is what this app
and most editors write for bold, colour, etc.); formatting that an .odt
inherits from named styles is not followed.
"""

from __future__ import annotations

import base64
import io
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..rpc import EngineError
from .odf_slides import style_name

PX_PER_PT = 96 / 72
ALIGN_ODF = {"left": "start", "center": "center", "right": "end", "justify": "justify"}
ALIGN_FROM_ODF = {"start": "left", "left": "left", "center": "center", "end": "right", "right": "right", "justify": "justify"}
HEADING_PT = {1: 20, 2: 16, 3: 13, 4: 11, 5: 11, 6: 11}


def _points(value: Any) -> Optional[float]:
    match = re.fullmatch(r"\s*([\d.]+)\s*(pt|px)?\s*", str(value or ""))
    if not match:
        return None
    number = float(match.group(1))
    return number * 0.75 if match.group(2) == "px" else number


def _mark_props(marks: Iterable[dict]) -> Dict[str, str]:
    """ProseMirror marks -> a flat, hashable description of the text formatting."""
    props: Dict[str, str] = {}
    for mark in marks or []:
        kind, attrs = mark.get("type"), mark.get("attrs") or {}
        if kind in ("bold", "italic", "underline", "strike"):
            props[kind] = "1"
        elif kind == "code":
            props["font"] = "Courier New"
        elif kind == "highlight":
            props["highlight"] = str(attrs.get("color") or "#ffff00")
        elif kind == "textStyle":
            if attrs.get("color"):
                props["color"] = str(attrs["color"])
            size = _points(attrs.get("fontSize"))
            if size:
                props["size"] = f"{size:g}"
            family = str(attrs.get("fontFamily") or "").split(",")[0].strip().strip("'\"")
            if family:
                props["font"] = family
    return props


def _image_bytes(node: dict) -> Tuple[bytes, str, float, float]:
    """-> (raw bytes, media type, width px, height px)."""
    from .pdf_edit import decode_data_url

    attrs = node.get("attrs") or {}
    src = str(attrs.get("src", ""))
    image = decode_data_url(src)
    raw = base64.b64decode(src.split(",", 1)[1])
    media = src[5 : src.index(";")] if ";" in src else "image/png"
    try:
        width = float(str(attrs.get("width")).replace("px", "")) if attrs.get("width") else float(image.width)
    except ValueError:
        width = float(image.width)
    width = max(8.0, min(width, 624.0))
    return raw, media, width, width * image.height / image.width


# ====================================================================== .odt write

class _OdtWriter:
    def __init__(self) -> None:
        from odf.opendocument import OpenDocumentText
        from odf.style import ListLevelProperties, ParagraphProperties, Style, TableCellProperties, TextProperties
        from odf.text import ListLevelStyleBullet, ListLevelStyleNumber, ListStyle

        self.doc = OpenDocumentText()
        self.text_styles: Dict[tuple, str] = {}
        self.para_styles: Dict[tuple, str] = {}

        for level, size in HEADING_PT.items():
            style = Style(name=f"Heading_20_{level}", displayname=f"Heading {level}", family="paragraph", defaultoutlinelevel=str(level))
            style.addElement(TextProperties(fontsize=f"{size}pt", fontweight="bold"))
            style.addElement(ParagraphProperties(margintop="0.4cm", marginbottom="0.2cm", keepwithnext="always"))
            self.doc.styles.addElement(style)

        for name, ordered in (("LBullet", False), ("LNumber", True)):
            lst = ListStyle(name=name)
            for level in range(1, 7):
                item = (ListLevelStyleNumber(level=str(level), numformat="1", numsuffix=".") if ordered
                        else ListLevelStyleBullet(level=str(level), bulletchar="•"))
                item.addElement(ListLevelProperties(spacebefore=f"{0.6 * level:.1f}cm", minlabelwidth="0.6cm"))
                lst.addElement(item)
            self.doc.automaticstyles.addElement(lst)

        for name, head in (("Cell", False), ("CellHead", True)):
            cell = Style(name=name, family="table-cell")
            cell.addElement(TableCellProperties(border="0.5pt solid #808080", padding="0.1cm",
                                                **({"backgroundcolor": "#f2f4f7"} if head else {})))
            self.doc.automaticstyles.addElement(cell)

    def text_style(self, props: Dict[str, str]) -> Optional[str]:
        from odf.style import Style, TextProperties

        if not props:
            return None
        key = tuple(sorted(props.items()))
        if key not in self.text_styles:
            name = f"T{len(self.text_styles) + 1}"
            args: Dict[str, str] = {}
            if "bold" in props:
                args["fontweight"] = "bold"
            if "italic" in props:
                args["fontstyle"] = "italic"
            if "underline" in props:
                args.update(textunderlinestyle="solid", textunderlinewidth="auto", textunderlinecolor="font-color")
            if "strike" in props:
                args["textlinethroughstyle"] = "solid"
            if "color" in props:
                args["color"] = props["color"]
            if "size" in props:
                args["fontsize"] = f"{props['size']}pt"
            if "font" in props:
                args["fontfamily"] = props["font"]
            if "highlight" in props:
                args["backgroundcolor"] = props["highlight"]
            style = Style(name=name, family="text")
            style.addElement(TextProperties(**args))
            self.doc.automaticstyles.addElement(style)
            self.text_styles[key] = name
        return self.text_styles[key]

    def para_style(self, align: Optional[str], parent: str = "Standard", page_break: bool = False, rule: bool = False) -> Optional[str]:
        from odf.style import ParagraphProperties, Style

        if not align and not page_break and not rule:
            return None if parent == "Standard" else parent
        key = (align, parent, page_break, rule)
        if key not in self.para_styles:
            name = f"P{len(self.para_styles) + 1}"
            args: Dict[str, str] = {}
            if align in ALIGN_ODF:
                args["textalign"] = ALIGN_ODF[align]
            if page_break:
                args["breakbefore"] = "page"
            if rule:
                args["borderbottom"] = "0.5pt solid #808080"
            style = Style(name=name, family="paragraph", parentstylename=parent)
            style.addElement(ParagraphProperties(**args))
            self.doc.automaticstyles.addElement(style)
            self.para_styles[key] = name
        return self.para_styles[key]

    def inline(self, parent: Any, nodes: Iterable[dict], extra: Optional[Dict[str, str]] = None) -> None:
        from odf.draw import Frame, Image
        from odf.text import LineBreak, Span

        for node in nodes or []:
            kind = node.get("type")
            if kind == "text":
                props = {**_mark_props(node.get("marks")), **(extra or {})}
                style = self.text_style(props)
                text = node.get("text", "")
                parent.addElement(Span(stylename=style, text=text) if style else Span(text=text))
            elif kind == "hardBreak":
                parent.addElement(LineBreak())
            elif kind == "image":
                raw, media, width, height = _image_bytes(node)
                href = self.doc.addPictureFromString(raw, media)
                frame = Frame(width=f"{width / PX_PER_PT:.2f}pt", height=f"{height / PX_PER_PT:.2f}pt", anchortype="as-char")
                frame.addElement(Image(href=href))
                parent.addElement(frame)

    def list(self, node: dict, top: bool = True) -> Any:
        from odf.text import List, ListItem, P

        ordered = node.get("type") == "orderedList"
        lst = List(stylename="LNumber" if ordered else "LBullet") if top else List()
        for item in node.get("content") or []:
            entry = ListItem()
            for child in item.get("content") or []:
                if child.get("type") in ("bulletList", "orderedList"):
                    # A nested list of the other kind needs its own style; same kind inherits.
                    nested = self.list(child, top=(child.get("type") == "orderedList") != ordered)
                    entry.addElement(nested)
                else:
                    p = P(stylename=self.para_style((child.get("attrs") or {}).get("textAlign")) or "Standard")
                    self.inline(p, child.get("content"))
                    entry.addElement(p)
            lst.addElement(entry)
        return lst

    def table(self, node: dict) -> Any:
        from odf.table import CoveredTableCell, Table, TableCell, TableColumn, TableRow

        rows = [r.get("content") or [] for r in node.get("content") or []]

        def span(cell: dict, key: str) -> int:
            return max(1, int((cell.get("attrs") or {}).get(key) or 1))

        taken: Dict[Tuple[int, int], Optional[dict]] = {}     # grid position -> cell that starts there, or None if covered
        for r, cells in enumerate(rows):
            c = 0
            for cell in cells:
                while (r, c) in taken:
                    c += 1
                for dr in range(span(cell, "rowspan")):
                    for dc in range(span(cell, "colspan")):
                        taken[(r + dr, c + dc)] = cell if (dr, dc) == (0, 0) else None
                c += span(cell, "colspan")
        if not taken:
            return None
        n_rows = max(r for r, _ in taken) + 1
        n_cols = max(c for _, c in taken) + 1
        table = Table()
        table.addElement(TableColumn(numbercolumnsrepeated=str(n_cols)))
        for r in range(n_rows):
            row = TableRow()
            for c in range(n_cols):
                cell = taken.get((r, c))
                if cell is None:
                    row.addElement(CoveredTableCell())
                    continue
                head = cell.get("type") == "tableHeader"
                args = {"stylename": "CellHead" if head else "Cell", "valuetype": "string"}
                if span(cell, "colspan") > 1:
                    args["numbercolumnsspanned"] = str(span(cell, "colspan"))
                if span(cell, "rowspan") > 1:
                    args["numberrowsspanned"] = str(span(cell, "rowspan"))
                target = TableCell(**args)
                self.blocks(cell.get("content") or [{"type": "paragraph"}], target, bold=head)
                row.addElement(target)
            table.addElement(row)
        return table

    def blocks(self, nodes: Iterable[dict], parent: Any, bold: bool = False) -> None:
        from odf.text import H, P

        break_next = False
        for node in nodes or []:
            kind = node.get("type")
            align = (node.get("attrs") or {}).get("textAlign")
            pending, break_next = break_next, False
            if kind == "pageBreak":
                break_next = True
                continue
            if pending and kind not in ("paragraph", "heading", "horizontalRule"):
                parent.addElement(P(stylename=self.para_style(None, page_break=True)))
            if kind == "paragraph":
                p = P(stylename=self.para_style(align, page_break=pending) or "Standard")
                self.inline(p, node.get("content"), {"bold": "1"} if bold else None)
                parent.addElement(p)
            elif kind == "heading":
                level = min(max(int((node.get("attrs") or {}).get("level") or 1), 1), 6)
                h = H(outlinelevel=str(level), stylename=self.para_style(align, f"Heading_20_{level}", pending))
                self.inline(h, node.get("content"))
                parent.addElement(h)
            elif kind in ("bulletList", "orderedList"):
                parent.addElement(self.list(node))
            elif kind == "table":
                table = self.table(node)
                if table is not None:
                    parent.addElement(table)
            elif kind == "blockquote":
                for child in node.get("content") or []:
                    p = P(stylename="Standard")
                    self.inline(p, child.get("content"), {"italic": "1"})
                    parent.addElement(p)
            elif kind == "codeBlock":
                text = "".join(t.get("text", "") for t in node.get("content") or [])
                for line in text.split("\n"):
                    p = P(stylename="Standard")
                    self.inline(p, [{"type": "text", "text": line}], {"font": "Courier New"})
                    parent.addElement(p)
            elif kind == "horizontalRule":
                parent.addElement(P(stylename=self.para_style(None, page_break=pending, rule=True)))
            elif kind == "image":
                p = P(stylename="Standard")
                self.inline(p, [node])
                parent.addElement(p)
        if break_next:                                    # a trailing page break still needs a paragraph to carry it
            parent.addElement(P(stylename=self.para_style(None, page_break=True)))


def write_odt(target: Path, content: dict) -> None:
    writer = _OdtWriter()
    writer.blocks(content.get("content") or [], writer.doc.text)
    writer.doc.save(str(target))


# ====================================================================== .odt read

def _local(node: Any) -> str:
    return getattr(node, "qname", ("", ""))[1]


class _OdtReader:
    def __init__(self, document: Any):
        self.doc = document
        self.styles: Dict[str, Any] = {}
        self.ordered_lists: set = set()
        for holder in (document.styles, document.automaticstyles):
            for style in holder.childNodes:
                name = style.getAttribute("name") if hasattr(style, "getAttribute") else None
                if not name:
                    continue
                self.styles[name] = style
                if _local(style) == "list-style":
                    first = next((c for c in style.childNodes if _local(c).startswith("list-level-style")), None)
                    if first is not None and _local(first) == "list-level-style-number":
                        self.ordered_lists.add(name)

    def _props(self, style_name: Optional[str], kind: str) -> Any:
        style = self.styles.get(style_name or "")
        if style is None:
            return None
        return next((c for c in style.childNodes if _local(c) == kind), None)

    def _marks(self, style_name: Optional[str]) -> List[dict]:
        props = self._props(style_name, "text-properties")
        if props is None:
            return []
        get = props.getAttribute
        marks: List[dict] = []
        if get("fontweight") == "bold":
            marks.append({"type": "bold"})
        if get("fontstyle") == "italic":
            marks.append({"type": "italic"})
        if get("textunderlinestyle") not in (None, "none"):
            marks.append({"type": "underline"})
        if get("textlinethroughstyle") not in (None, "none"):
            marks.append({"type": "strike"})
        style: Dict[str, str] = {}
        if get("color"):
            style["color"] = str(get("color")).lower()
        if get("fontsize") and str(get("fontsize")).endswith("pt"):
            style["fontSize"] = f"{float(str(get('fontsize'))[:-2]):g}pt"
        family = get("fontfamily") or get("fontname")
        if family:
            style["fontFamily"] = str(family).strip("'\"")
        if style:
            marks.append({"type": "textStyle", "attrs": style})
        if get("backgroundcolor") and get("backgroundcolor") != "transparent":
            marks.append({"type": "highlight", "attrs": {"color": str(get("backgroundcolor")).lower()}})
        return marks

    def _length_px(self, value: Any) -> Optional[int]:
        match = re.fullmatch(r"([\d.]+)(pt|cm|mm|in|px)", str(value or ""))
        if not match:
            return None
        factor = {"pt": PX_PER_PT, "cm": 96 / 2.54, "mm": 96 / 25.4, "in": 96.0, "px": 1.0}[match.group(2)]
        return round(float(match.group(1)) * factor)

    def inline(self, element: Any, marks: Optional[List[dict]] = None) -> List[dict]:
        nodes: List[dict] = []

        def text(value: str, with_marks: List[dict]) -> None:
            if not value:
                return
            if nodes and nodes[-1]["type"] == "text" and nodes[-1].get("marks", []) == with_marks:
                nodes[-1]["text"] += value
                return
            node: Dict[str, Any] = {"type": "text", "text": value}
            if with_marks:
                node["marks"] = with_marks
            nodes.append(node)

        def walk(el: Any, current: List[dict]) -> None:
            for child in el.childNodes:
                if child.nodeType == child.TEXT_NODE:
                    text(child.data, current)
                    continue
                name = _local(child)
                if name == "span":
                    own = self._marks(style_name(child))
                    kinds = {m["type"] for m in own}
                    walk(child, [m for m in current if m["type"] not in kinds] + own)
                elif name == "line-break":
                    nodes.append({"type": "hardBreak"})
                elif name == "s":
                    text(" " * int(child.getAttribute("c") or 1), current)
                elif name == "tab":
                    text("\t", current)
                elif name == "frame":
                    image = next((c for c in child.childNodes if _local(c) == "image"), None)
                    href = image.getAttribute("href") if image is not None else None
                    picture = self.doc.Pictures.get(href) if href else None
                    if picture:
                        _, data, media = picture
                        attrs: Dict[str, Any] = {"src": f"data:{media};base64," + base64.b64encode(data).decode("ascii")}
                        width, height = self._length_px(child.getAttribute("width")), self._length_px(child.getAttribute("height"))
                        if width:
                            attrs["width"] = width
                        if height:
                            attrs["height"] = height
                        nodes.append({"type": "image", "attrs": attrs})
                elif name in ("a", "bookmark-ref", "note-body"):
                    walk(child, current)

        walk(element, list(marks or []))
        return nodes

    def paragraph(self, element: Any, heading: bool) -> List[dict]:
        props = self._props(style_name(element), "paragraph-properties")
        out: List[dict] = []
        attrs: Dict[str, Any] = {}
        if props is not None:
            if props.getAttribute("breakbefore") == "page":
                out.append({"type": "pageBreak"})
            if props.getAttribute("textalign") in ALIGN_FROM_ODF:
                attrs["textAlign"] = ALIGN_FROM_ODF[props.getAttribute("textalign")]
            if props.getAttribute("borderbottom") and not heading:
                rule_only = not self.inline(element)
                if rule_only:
                    return out + [{"type": "horizontalRule"}]
        content = self.inline(element)
        if heading:
            level = min(int(element.getAttribute("outlinelevel") or 1), 6)
            node: Dict[str, Any] = {"type": "heading", "attrs": {"level": level, **attrs}}
        else:
            node = {"type": "paragraph"}
            if attrs:
                node["attrs"] = attrs
        if content:
            node["content"] = content
        elif out and not heading:
            return out                                    # an empty paragraph that only carried a page break
        return out + [node]

    def list(self, element: Any, inherited: bool = False) -> dict:
        name = style_name(element)
        ordered = (name in self.ordered_lists) if name else inherited
        items: List[dict] = []
        for item in element.childNodes:
            if _local(item) != "list-item":
                continue
            content: List[dict] = []
            for child in item.childNodes:
                kind = _local(child)
                if kind in ("p", "h"):
                    content.extend(n for n in self.paragraph(child, False) if n["type"] != "pageBreak")
                elif kind == "list":
                    content.append(self.list(child, ordered))
            items.append({"type": "listItem", "content": content or [{"type": "paragraph"}]})
        return {"type": "orderedList" if ordered else "bulletList", "content": items}

    def table(self, element: Any) -> dict:
        rows: List[dict] = []
        for row in element.childNodes:
            holder = [row] if _local(row) == "table-row" else [r for r in row.childNodes if _local(r) == "table-row"]
            for tr in holder:
                cells: List[dict] = []
                for cell in tr.childNodes:
                    if _local(cell) != "table-cell":
                        continue
                    head = style_name(cell) == "CellHead"
                    cells.append({
                        "type": "tableHeader" if head else "tableCell",
                        "attrs": {"colspan": int(cell.getAttribute("numbercolumnsspanned") or 1),
                                  "rowspan": int(cell.getAttribute("numberrowsspanned") or 1)},
                        "content": self.blocks(cell) or [{"type": "paragraph"}],
                    })
                if cells:
                    rows.append({"type": "tableRow", "content": cells})
        return {"type": "table", "content": rows}

    def blocks(self, parent: Any) -> List[dict]:
        out: List[dict] = []
        for element in parent.childNodes:
            kind = _local(element)
            if kind == "h":
                out.extend(self.paragraph(element, True))
            elif kind == "p":
                out.extend(self.paragraph(element, False))
            elif kind == "list":
                out.append(self.list(element))
            elif kind == "table":
                out.append(self.table(element))
            elif kind == "section":
                out.extend(self.blocks(element))
        return out


def read_odt(path: Path) -> List[dict]:
    from odf.opendocument import load

    try:
        document = load(str(path))
    except Exception as exc:  # noqa: BLE001
        raise EngineError("invalid_file", f"Could not read document: {exc}") from exc
    reader = _OdtReader(document)
    blocks = reader.blocks(document.text)
    # Header cells written by this app repeat "bold" on their text; the cell type already says it.
    for block in blocks:
        if block["type"] != "table":
            continue
        for row in block["content"]:
            for cell in row["content"]:
                if cell["type"] == "tableHeader":
                    _strip_mark(cell, "bold")
    return blocks


def _strip_mark(node: dict, kind: str) -> None:
    if node.get("type") == "text" and node.get("marks"):
        node["marks"] = [m for m in node["marks"] if m["type"] != kind]
        if not node["marks"]:
            del node["marks"]
    for child in node.get("content") or []:
        _strip_mark(child, kind)


# ====================================================================== .rtf write

def _rtf_text(text: str) -> str:
    out = []
    for ch in text:
        code = ord(ch)
        if ch in "\\{}":
            out.append("\\" + ch)
        elif ch == "\n":
            out.append("\\line ")
        elif ch == "\t":
            out.append("\\tab ")
        elif code < 128:
            out.append(ch)
        else:
            # RTF Unicode escapes are signed 16-bit; characters beyond the BMP become a surrogate pair.
            data = ch.encode("utf-16-le")
            for i in range(0, len(data), 2):
                value = int.from_bytes(data[i : i + 2], "little")
                out.append(f"\\u{value - 65536 if value > 32767 else value}?")
    return "".join(out)


class _RtfWriter:
    def __init__(self) -> None:
        self.fonts: List[str] = ["Calibri"]
        self.colors: List[str] = []
        self.body: List[str] = []

    def font(self, name: str) -> int:
        if name not in self.fonts:
            self.fonts.append(name)
        return self.fonts.index(name)

    def color(self, value: str) -> int:
        text = value.strip().lstrip("#")
        if len(text) == 3:
            text = "".join(ch * 2 for ch in text)
        if not re.fullmatch(r"[0-9a-fA-F]{6}", text):
            return 0
        text = text.lower()
        if text not in self.colors:
            self.colors.append(text)
        return self.colors.index(text) + 1               # index 0 is "auto"

    def run(self, node: dict, extra: Optional[Dict[str, str]] = None) -> str:
        props = {**_mark_props(node.get("marks")), **(extra or {})}
        codes = []
        if "bold" in props:
            codes.append("\\b")
        if "italic" in props:
            codes.append("\\i")
        if "underline" in props:
            codes.append("\\ul")
        if "strike" in props:
            codes.append("\\strike")
        if "color" in props:
            codes.append(f"\\cf{self.color(props['color'])}")
        if "highlight" in props:
            codes.append(f"\\highlight{self.color(props['highlight'])}")
        if "size" in props:
            codes.append(f"\\fs{round(float(props['size']) * 2)}")
        if "font" in props:
            codes.append(f"\\f{self.font(props['font'])}")
        # The space ends the last control word; without any control word it would be literal text.
        return "{" + "".join(codes) + (" " if codes else "") + _rtf_text(node.get("text", "")) + "}"

    def inline(self, nodes: Iterable[dict], extra: Optional[Dict[str, str]] = None) -> str:
        parts = []
        for node in nodes or []:
            kind = node.get("type")
            if kind == "text":
                parts.append(self.run(node, extra))
            elif kind == "hardBreak":
                parts.append("\\line ")
            elif kind == "image":
                from PIL import Image

                raw, _media, width, height = _image_bytes(node)
                png = io.BytesIO()
                Image.open(io.BytesIO(raw)).convert("RGBA").save(png, "PNG")       # \pngblip needs PNG whatever came in
                twips_w, twips_h = round(width * 15), round(height * 15)
                parts.append(f"{{\\pict\\pngblip\\picwgoal{twips_w}\\pichgoal{twips_h} {png.getvalue().hex()}}}")
        return "".join(parts)

    def para(self, content: str, align: Optional[str] = None, prefix: str = "") -> None:
        code = {"center": "\\qc", "right": "\\qr", "justify": "\\qj"}.get(align or "", "\\ql")
        self.body.append(f"{{\\pard{code}{prefix}\\sa160 {content}\\par}}\n")

    def list(self, node: dict, level: int) -> None:
        ordered = node.get("type") == "orderedList"
        indent = 360 * (level + 1)
        number = 0
        for item in node.get("content") or []:
            first = True
            for child in item.get("content") or []:
                if child.get("type") in ("bulletList", "orderedList"):
                    self.list(child, level + 1)
                    continue
                label = ""
                if first:
                    number += 1
                    label = f"{number}.\\tab " if ordered else "\\bullet\\tab "
                self.para(label + self.inline(child.get("content")), prefix=f"\\li{indent}\\fi-360\\tx{indent}")
                first = False

    def table(self, node: dict) -> None:
        for row in node.get("content") or []:
            cells = row.get("content") or []
            if not cells:
                continue
            width = 9000 // len(cells)
            line = "{\\trowd\\trgaph108"
            for i in range(len(cells)):
                line += "\\clbrdrt\\brdrs\\brdrw10\\clbrdrl\\brdrs\\brdrw10\\clbrdrb\\brdrs\\brdrw10\\clbrdrr\\brdrs\\brdrw10" + f"\\cellx{width * (i + 1)}"
            for cell in cells:
                extra = {"bold": "1"} if cell.get("type") == "tableHeader" else None
                paragraphs = [self.inline(p.get("content"), extra) for p in cell.get("content") or []]
                line += "\\pard\\intbl " + "\\line ".join(paragraphs) + "\\cell "
            self.body.append(line + "\\row}\n")
        self.body.append("{\\pard\\par}\n")

    def blocks(self, nodes: Iterable[dict]) -> None:
        for node in nodes or []:
            kind = node.get("type")
            align = (node.get("attrs") or {}).get("textAlign")
            if kind == "paragraph":
                self.para(self.inline(node.get("content")), align)
            elif kind == "heading":
                level = min(max(int((node.get("attrs") or {}).get("level") or 1), 1), 6)
                self.para(self.inline(node.get("content"), {"bold": "1", "size": str(HEADING_PT[level])}), align, "\\sb240\\keepn")
            elif kind in ("bulletList", "orderedList"):
                self.list(node, 0)
            elif kind == "table":
                self.table(node)
            elif kind == "blockquote":
                for child in node.get("content") or []:
                    self.para(self.inline(child.get("content"), {"italic": "1"}), prefix="\\li720")
            elif kind == "codeBlock":
                text = "".join(t.get("text", "") for t in node.get("content") or [])
                self.para(self.inline([{"type": "text", "text": text}], {"font": "Courier New"}))
            elif kind == "pageBreak":
                self.body.append("\\page\n")
            elif kind == "horizontalRule":
                self.body.append("{\\pard\\brdrb\\brdrs\\brdrw10\\brsp20 \\par}\n")
            elif kind == "image":
                self.para(self.inline([node]))

    def render(self) -> str:
        fonts = "".join(f"{{\\f{i} {name};}}" for i, name in enumerate(self.fonts))
        colors = ";" + "".join(f"\\red{int(c[0:2], 16)}\\green{int(c[2:4], 16)}\\blue{int(c[4:6], 16)};" for c in self.colors)
        head = f"{{\\rtf1\\ansi\\ansicpg1252\\deff0\\uc1{{\\fonttbl{fonts}}}{{\\colortbl{colors}}}\\f0\\fs22\n"
        return head + "".join(self.body) + "}\n"


def write_rtf(target: Path, content: dict) -> None:
    writer = _RtfWriter()
    writer.blocks(content.get("content") or [])
    target.write_text(writer.render(), encoding="ascii")
