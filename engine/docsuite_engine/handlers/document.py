"""Document I/O for the word processor (doc.open / doc.save / mail merge).

The editor is TipTap; its document model is ProseMirror JSON:

    {"type": "doc", "content": [block, ...]}
    blocks : paragraph, heading{level}, bulletList, orderedList, listItem, table,
             tableRow, tableCell{colspan,rowspan}, tableHeader, blockquote,
             codeBlock, horizontalRule, pageBreak
    inline : text{marks}, hardBreak, image{src (data URL), width, height}
    marks  : bold, italic, underline, strike, highlight{color},
             textStyle{color, fontSize ("12pt"), fontFamily}

Formats: .docx, .odt, .md and .txt read/write · .rtf write, and read as plain text.
(.odt and .rtf live in odf_text.py.)
"""

from __future__ import annotations

import base64
import copy
import io
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..rpc import EngineError, method
from ..util import atomic_output, in_path, out_dir

PX_PER_INCH = 96
EMU_PER_PX = 9525
MAX_IMAGE_WIDTH_PX = 624        # 6.5 in: the text width of a default Word page
MAX_MERGE_RECORDS = 5000
ALIGN_IN = {0: "left", 1: "center", 2: "right", 3: "justify"}
ALIGN_OUT = {v: k for k, v in ALIGN_IN.items()}
# Word's fixed highlighter palette (WD_COLOR_INDEX value -> colour).
HIGHLIGHTS = {
    7: "#ffff00", 4: "#00ff00", 3: "#00ffff", 5: "#ff00ff", 2: "#0000ff", 6: "#ff0000", 9: "#000080",
    10: "#008080", 11: "#008000", 12: "#800080", 13: "#800000", 14: "#808000", 15: "#808080", 16: "#c0c0c0",
}
MC_ALTERNATE = "{http://schemas.openxmlformats.org/markup-compatibility/2006}AlternateContent"
PLACEHOLDER = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


# =================================================================== docx -> JSON

class _DocxReader:
    def __init__(self, doc: Any):
        from docx.oxml.ns import qn

        self.doc = doc
        self.qn = qn
        self.notes: Dict[str, int] = {}
        try:
            self.numbering = doc.part.numbering_part.element
        except Exception:  # noqa: BLE001 - a document without lists has no numbering part
            self.numbering = None

    def note(self, what: str, count: int = 1) -> None:
        if count:
            self.notes[what] = self.notes.get(what, 0) + count

    # ---- lists
    def _ordered(self, num_id: int, level: int, style_name: str) -> bool:
        qn = self.qn
        if self.numbering is not None:
            for num in self.numbering.findall(qn("w:num")):
                if num.get(qn("w:numId")) != str(num_id):
                    continue
                ref = num.find(qn("w:abstractNumId"))
                for abstract in self.numbering.findall(qn("w:abstractNum")):
                    if ref is None or abstract.get(qn("w:abstractNumId")) != ref.get(qn("w:val")):
                        continue
                    for lvl in abstract.findall(qn("w:lvl")):
                        if lvl.get(qn("w:ilvl")) == str(level):
                            fmt = lvl.find(qn("w:numFmt"))
                            return fmt is not None and fmt.get(qn("w:val")) != "bullet"
        return "number" in style_name.lower()

    def list_info(self, paragraph: Any) -> Optional[Tuple[bool, int]]:
        """(ordered, level) when the paragraph is a list item."""
        qn = self.qn
        style = paragraph.style
        style_name = (style.name if style is not None else "") or ""
        ppr = paragraph._p.pPr
        num_pr = ppr.numPr if ppr is not None else None
        while num_pr is None and style is not None:          # numbering can come from the style chain
            sppr = style.element.pPr
            num_pr = sppr.numPr if sppr is not None else None
            style = style.base_style
        if num_pr is None or num_pr.numId is None or num_pr.numId.val == 0:
            return None
        level = num_pr.ilvl.val if num_pr.ilvl is not None else 0
        # Word's built-in "List Bullet 2" / "List Number 3" styles carry their depth in the
        # name: each has its own numbering definition whose level 0 is already indented.
        named = re.fullmatch(r"List (?:Bullet|Number) (\d)", style_name)
        if named:
            level = max(level, int(named.group(1)) - 1)
        return self._ordered(num_pr.numId.val, level, style_name), max(0, level)

    # ---- inline content
    def _marks(self, run: Any) -> List[dict]:
        qn = self.qn
        marks: List[dict] = []
        font = run.font
        if run.bold:
            marks.append({"type": "bold"})
        if run.italic:
            marks.append({"type": "italic"})
        if run.underline:
            marks.append({"type": "underline"})
        if font.strike:
            marks.append({"type": "strike"})
        style: Dict[str, str] = {}
        if font.color is not None and font.color.type is not None and font.color.rgb is not None:
            style["color"] = "#" + str(font.color.rgb).lower()
        if font.size is not None:
            style["fontSize"] = f"{font.size.pt:g}pt"
        if font.name:
            style["fontFamily"] = font.name
        if style:
            marks.append({"type": "textStyle", "attrs": style})
        fill = None
        rpr = run._r.rPr
        shd = rpr.find(qn("w:shd")) if rpr is not None else None
        if shd is not None and shd.get(qn("w:fill")) not in (None, "auto"):
            fill = "#" + shd.get(qn("w:fill")).lower()
        elif font.highlight_color is not None:
            fill = HIGHLIGHTS.get(int(font.highlight_color))
        if fill:
            marks.append({"type": "highlight", "attrs": {"color": fill}})
        return marks

    def _image(self, drawing: Any) -> Optional[dict]:
        qn = self.qn
        blip = drawing.find(".//" + qn("a:blip"))
        embed = blip.get(qn("r:embed")) if blip is not None else None
        if not embed:
            self.note("linked or unsupported drawing")
            return None
        try:
            part = self.doc.part.related_parts[embed]
        except KeyError:
            return None
        attrs: Dict[str, Any] = {
            "src": f"data:{part.content_type};base64," + base64.b64encode(part.blob).decode("ascii")
        }
        extent = drawing.find(".//" + qn("wp:extent"))
        if extent is not None:
            attrs["width"] = round(int(extent.get("cx")) / EMU_PER_PX)
            attrs["height"] = round(int(extent.get("cy")) / EMU_PER_PX)
        return {"type": "image", "attrs": attrs}

    def inline(self, paragraph: Any) -> Tuple[List[dict], bool]:
        """-> (inline nodes, paragraph contains a page break)."""
        from docx.text.run import Run

        qn = self.qn
        nodes: List[dict] = []
        page_break = False

        def text(value: str, marks: List[dict]) -> None:
            if not value:
                return
            if nodes and nodes[-1]["type"] == "text" and nodes[-1].get("marks", []) == marks:
                nodes[-1]["text"] += value            # merge runs that share formatting
                return
            node: Dict[str, Any] = {"type": "text", "text": value}
            if marks:
                node["marks"] = marks
            nodes.append(node)

        def run(r_el: Any) -> None:
            nonlocal page_break
            marks = self._marks(Run(r_el, paragraph))
            for child in r_el:
                tag = child.tag
                if tag == qn("w:t"):
                    text(child.text or "", marks)
                elif tag == qn("w:tab"):
                    text("\t", marks)
                elif tag == qn("w:br"):
                    if child.get(qn("w:type")) == "page":
                        page_break = True
                    else:
                        nodes.append({"type": "hardBreak"})
                elif tag == qn("w:drawing"):
                    image = self._image(child)
                    if image:
                        nodes.append(image)
                elif tag in (qn("w:footnoteReference"), qn("w:endnoteReference")):
                    self.note("footnote/endnote")
                elif tag == qn("w:commentReference"):
                    self.note("comment")
                elif tag == qn("w:fldChar"):
                    self.note("field (page number, TOC, …)", 1 if child.get(qn("w:fldCharType")) == "begin" else 0)
                elif tag in (qn("w:pict"), MC_ALTERNATE):
                    self.note("shape or text box")

        for child in paragraph._p:
            if child.tag == qn("w:r"):
                run(child)
            elif child.tag == qn("w:hyperlink"):
                self.note("hyperlink target (text kept)")
                for r_el in child.findall(qn("w:r")):
                    run(r_el)
            elif child.tag == qn("w:ins"):               # tracked insertions are accepted
                self.note("tracked change (accepted)")
                for r_el in child.findall(qn("w:r")):
                    run(r_el)
            elif child.tag == qn("w:del"):
                self.note("tracked change (accepted)")
            elif child.tag == qn("w:fldSimple"):
                self.note("field (page number, TOC, …)")
                for r_el in child.findall(qn("w:r")):
                    run(r_el)
        return nodes, page_break

    # ---- blocks
    def _paragraph(self, paragraph: Any) -> Tuple[List[dict], Optional[Tuple[bool, int]]]:
        content, page_break = self.inline(paragraph)
        style_name = (paragraph.style.name if paragraph.style is not None else "") or ""
        attrs: Dict[str, Any] = {}
        if paragraph.alignment is not None and int(paragraph.alignment) in ALIGN_IN:
            attrs["textAlign"] = ALIGN_IN[int(paragraph.alignment)]

        info = self.list_info(paragraph)
        if style_name == "Title" or style_name.startswith("Heading"):
            digits = re.search(r"(\d+)$", style_name)
            node: Dict[str, Any] = {"type": "heading", "attrs": {"level": min(int(digits.group(1)) if digits else 1, 6), **attrs}}
            info = None
        else:
            node = {"type": "paragraph"}
            if attrs:
                node["attrs"] = attrs
        if content:
            node["content"] = content
        out = [node] if content or not page_break else []
        if page_break:
            out.append({"type": "pageBreak"})
        return out, info

    def _table(self, tbl: Any, depth: int) -> dict:
        from docx.table import _Cell

        qn = self.qn
        rows: List[dict] = []
        origin: Dict[int, dict] = {}       # grid column -> the cell a vertical merge started in
        for tr in tbl.findall(qn("w:tr")):
            cells: List[dict] = []
            column = 0
            for tc in tr.findall(qn("w:tc")):
                span = tc.grid_span or 1
                if tc.vMerge == "continue" and column in origin:
                    origin[column]["attrs"]["rowspan"] += 1
                else:
                    cell = {
                        "type": "tableCell",
                        "attrs": {"colspan": span, "rowspan": 1},
                        "content": self.blocks(_Cell(tc, self.doc._body), depth + 1) or [{"type": "paragraph"}],
                    }
                    cells.append(cell)
                    for c in range(column, column + span):
                        origin.pop(c, None)
                    if tc.vMerge == "restart":
                        origin[column] = cell
                column += span
            if cells:
                rows.append({"type": "tableRow", "content": cells})
        return {"type": "table", "content": rows}

    def blocks(self, container: Any, depth: int = 0) -> List[dict]:
        from docx.text.paragraph import Paragraph

        qn = self.qn
        out: List[dict] = []
        pending: List[Tuple[bool, int, dict]] = []   # consecutive list items, nested once the run ends

        def flush() -> None:
            if pending:
                out.extend(_nest(pending))
                pending.clear()

        for child in container._element.iterchildren():
            if child.tag == qn("w:p"):
                nodes, info = self._paragraph(Paragraph(child, container))
                if info and nodes and nodes[0]["type"] == "paragraph":
                    pending.append((info[0], info[1], nodes[0]))
                    nodes = nodes[1:]
                if nodes:
                    flush()
                    out.extend(nodes)
            elif child.tag == qn("w:tbl"):
                flush()
                if depth >= 1:
                    self.note("nested table (flattened to text)")
                    text = " ".join(t.text or "" for t in child.iter(qn("w:t")))
                    out.append({"type": "paragraph", "content": [{"type": "text", "text": text}]} if text else {"type": "paragraph"})
                else:
                    out.append(self._table(child, depth))
            elif child.tag == qn("w:sdt"):
                self.note("content control")
        flush()
        return out


def _nest(items: List[Tuple[bool, int, dict]]) -> List[dict]:
    """Flat (ordered, level, paragraph) list items -> nested bulletList / orderedList nodes."""
    root: List[dict] = []
    stack: List[Tuple[int, dict]] = []
    for ordered, level, paragraph in items:
        kind = "orderedList" if ordered else "bulletList"
        while stack and stack[-1][0] > level:
            stack.pop()
        if stack and stack[-1][0] == level and stack[-1][1]["type"] != kind:
            stack.pop()
        if not stack or stack[-1][0] < level:
            node = {"type": kind, "content": []}
            if stack:
                stack[-1][1]["content"][-1]["content"].append(node)
            else:
                root.append(node)
            stack.append((level, node))
        stack[-1][1]["content"].append({"type": "listItem", "content": [paragraph]})
    return root


def _read_docx(path: Path) -> dict:
    from docx import Document

    try:
        doc = Document(str(path))
    except Exception as exc:  # noqa: BLE001
        raise EngineError("invalid_file", f"Could not read document: {exc}") from exc
    reader = _DocxReader(doc)
    content = reader.blocks(doc._body)      # the body proxy: its element holds the paragraphs and tables
    section = doc.sections[0]
    if len(doc.sections) > 1:
        reader.note("extra section layout", len(doc.sections) - 1)
    notes = [f"{count} × {what}" for what, count in reader.notes.items()]
    return {
        "content": {"type": "doc", "content": content or [{"type": "paragraph"}]},
        "header": "\n".join(p.text for p in section.header.paragraphs if p.text.strip()),
        "footer": "\n".join(p.text for p in section.footer.paragraphs if p.text.strip()),
        "notes": notes,
    }


# =================================================================== JSON -> docx

def _hex(value: Any) -> Optional[str]:
    """CSS colour ('#abc', '#aabbcc', 'rgb(r, g, b)') -> 'AABBCC'."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if value.startswith("#"):
        value = value[1:]
        if len(value) == 3:
            value = "".join(ch * 2 for ch in value)
        return value.upper() if re.fullmatch(r"[0-9a-fA-F]{6}", value) else None
    match = re.match(r"rgba?\(([^)]+)\)", value)
    if match:
        try:
            parts = [max(0, min(255, int(float(p)))) for p in match.group(1).split(",")[:3]]
            return "".join(f"{p:02X}" for p in parts)
        except ValueError:
            return None
    return None


def _points(value: Any) -> Optional[float]:
    match = re.fullmatch(r"\s*([\d.]+)\s*(pt|px)?\s*", str(value or ""))
    if not match:
        return None
    number = float(match.group(1))
    return number * 0.75 if match.group(2) == "px" else number


class _DocxWriter:
    def __init__(self) -> None:
        from docx import Document

        self.doc = Document()
        self.fresh_cells: set = set()      # cells whose built-in empty paragraph is still unused

    # ---- helpers
    def paragraph(self, container: Any, style: Optional[str] = None) -> Any:
        if id(container) in self.fresh_cells:
            self.fresh_cells.discard(id(container))
            p = container.paragraphs[0]
            if style:
                p.style = style
            return p
        return container.add_paragraph(style=style)

    def align(self, p: Any, node: dict) -> None:
        value = (node.get("attrs") or {}).get("textAlign")
        if value in ALIGN_OUT:
            p.alignment = ALIGN_OUT[value]

    def restart_numbering(self, style_name: str) -> Optional[int]:
        """A fresh numbering instance, so each numbered list starts again at 1."""
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn

        try:
            numbering = self.doc.part.numbering_part.element
            style_ppr = self.doc.styles[style_name].element.pPr
            base = style_ppr.numPr.numId.val
        except (KeyError, AttributeError):
            return None
        abstract = None
        for num in numbering.findall(qn("w:num")):
            if num.get(qn("w:numId")) == str(base):
                abstract = num.find(qn("w:abstractNumId")).get(qn("w:val"))
        if abstract is None:
            return None
        new_id = max(int(n.get(qn("w:numId"))) for n in numbering.findall(qn("w:num"))) + 1
        num = OxmlElement("w:num")
        num.set(qn("w:numId"), str(new_id))
        ref = OxmlElement("w:abstractNumId")
        ref.set(qn("w:val"), abstract)
        num.append(ref)
        override = OxmlElement("w:lvlOverride")
        override.set(qn("w:ilvl"), "0")
        start = OxmlElement("w:startOverride")
        start.set(qn("w:val"), "1")
        override.append(start)
        num.append(override)
        numbering.append(num)
        return new_id

    # ---- inline
    def run(self, p: Any, node: dict, force_bold: bool = False, mono: bool = False) -> None:
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.shared import Pt, RGBColor

        run = p.add_run(node.get("text", ""))
        if force_bold:
            run.bold = True
        if mono:
            run.font.name = "Courier New"
        for mark in node.get("marks") or []:
            kind, attrs = mark.get("type"), mark.get("attrs") or {}
            if kind == "bold":
                run.bold = True
            elif kind == "italic":
                run.italic = True
            elif kind == "underline":
                run.underline = True
            elif kind == "strike":
                run.font.strike = True
            elif kind == "code":
                run.font.name = "Courier New"
            elif kind == "textStyle":
                color = _hex(attrs.get("color"))
                if color:
                    run.font.color.rgb = RGBColor.from_string(color)
                size = _points(attrs.get("fontSize"))
                if size:
                    run.font.size = Pt(size)
                family = str(attrs.get("fontFamily") or "").split(",")[0].strip().strip("'\"")
                if family:
                    run.font.name = family
                    run._r.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), family)
            elif kind == "highlight":
                fill = _hex(attrs.get("color")) or "FFFF00"
                shd = OxmlElement("w:shd")       # shading takes any colour; w:highlight only 16 fixed ones
                shd.set(qn("w:val"), "clear")
                shd.set(qn("w:color"), "auto")
                shd.set(qn("w:fill"), fill)
                run._r.get_or_add_rPr().append(shd)

    def image(self, p: Any, node: dict) -> None:
        from docx.shared import Emu

        from .pdf_edit import decode_data_url

        attrs = node.get("attrs") or {}
        image = decode_data_url(attrs.get("src", ""))
        raw = base64.b64decode(str(attrs["src"]).split(",", 1)[1])
        width = attrs.get("width")
        try:
            width = float(str(width).replace("px", "")) if width else float(image.width)
        except ValueError:
            width = float(image.width)
        width = max(8.0, min(width, MAX_IMAGE_WIDTH_PX))
        p.add_run().add_picture(io.BytesIO(raw), width=Emu(int(width * EMU_PER_PX)))

    def inline(self, p: Any, nodes: Iterable[dict], force_bold: bool = False, mono: bool = False) -> None:
        for node in nodes or []:
            kind = node.get("type")
            if kind == "text":
                self.run(p, node, force_bold, mono)
            elif kind == "hardBreak":
                p.add_run().add_break()
            elif kind == "image":
                self.image(p, node)

    # ---- blocks
    def list(self, node: dict, container: Any, level: int) -> None:
        ordered = node.get("type") == "orderedList"
        style = ("List Number" if ordered else "List Bullet") + ("" if level == 0 else f" {min(level + 1, 3)}")
        num_id = self.restart_numbering(style) if ordered else None
        for item in node.get("content") or []:
            first = True
            for child in item.get("content") or []:
                if child.get("type") in ("bulletList", "orderedList"):
                    self.list(child, container, level + 1)
                    continue
                # A second paragraph inside one item continues it without a new bullet.
                p = self.paragraph(container, style if first else "List Continue")
                if first and num_id is not None:
                    num_pr = p._p.get_or_add_pPr().get_or_add_numPr()
                    num_pr.get_or_add_ilvl().val = 0
                    num_pr.get_or_add_numId().val = num_id
                self.align(p, child)
                self.inline(p, child.get("content"))
                first = False

    def table(self, node: dict, container: Any) -> None:
        rows = [r.get("content") or [] for r in node.get("content") or []]
        if not rows:
            return

        def span(cell: dict, key: str) -> int:
            return max(1, int((cell.get("attrs") or {}).get(key) or 1))

        # Lay cells out on a grid, skipping positions covered by a rowspan from above.
        taken: set = set()
        placed: List[Tuple[int, int, dict]] = []
        for r, cells in enumerate(rows):
            c = 0
            for cell in cells:
                while (r, c) in taken:
                    c += 1
                placed.append((r, c, cell))
                for dr in range(span(cell, "rowspan")):
                    for dc in range(span(cell, "colspan")):
                        taken.add((r + dr, c + dc))
                c += span(cell, "colspan")
        n_rows = max(r for r, _ in taken) + 1
        n_cols = max(c for _, c in taken) + 1
        table = container.add_table(rows=n_rows, cols=n_cols)
        table.style = "Table Grid"
        for r, c, cell in placed:
            target = table.cell(r, c)
            rs, cs = span(cell, "rowspan"), span(cell, "colspan")
            if rs > 1 or cs > 1:
                target = target.merge(table.cell(r + rs - 1, c + cs - 1))
            self.fresh_cells.add(id(target))
            self.blocks(cell.get("content") or [], target, header=cell.get("type") == "tableHeader")
            self.fresh_cells.discard(id(target))

    def blocks(self, nodes: Iterable[dict], container: Any, header: bool = False) -> None:
        from docx.enum.text import WD_BREAK
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn

        nodes = list(nodes or [])
        for index, node in enumerate(nodes):
            kind = node.get("type")
            following = nodes[index + 1].get("type") if index + 1 < len(nodes) else None
            if kind == "paragraph":
                p = self.paragraph(container)
                self.align(p, node)
                self.inline(p, node.get("content"), force_bold=header)
            elif kind == "heading":
                level = min(max(int((node.get("attrs") or {}).get("level") or 1), 1), 6)
                p = self.paragraph(container, f"Heading {level}")
                self.align(p, node)
                self.inline(p, node.get("content"))
            elif kind in ("bulletList", "orderedList"):
                self.list(node, container, 0)
            elif kind == "table":
                self.fresh_cells.discard(id(container))
                self.table(node, container)
                # Word merges adjacent tables and requires a cell to end with a paragraph.
                if following == "table" or (following is None and container is not self.doc):
                    container.add_paragraph()
            elif kind == "blockquote":
                for child in node.get("content") or []:
                    p = self.paragraph(container, "Quote")
                    self.inline(p, child.get("content"))
            elif kind == "codeBlock":
                for i, line in enumerate("".join(t.get("text", "") for t in node.get("content") or []).split("\n")):
                    self.inline(self.paragraph(container), [{"type": "text", "text": line}], mono=True)
            elif kind == "pageBreak":
                self.paragraph(container).add_run().add_break(WD_BREAK.PAGE)
            elif kind == "horizontalRule":
                p = self.paragraph(container)
                border = OxmlElement("w:pBdr")
                bottom = OxmlElement("w:bottom")
                for key, value in (("val", "single"), ("sz", "6"), ("space", "1"), ("color", "auto")):
                    bottom.set(qn(f"w:{key}"), value)
                border.append(bottom)
                p._p.get_or_add_pPr().append(border)
            elif kind == "image":
                self.image(self.paragraph(container), node)


def _write_docx(target: Path, content: dict, header: str = "", footer: str = "") -> None:
    writer = _DocxWriter()
    writer.blocks(content.get("content") or [], writer.doc)
    section = writer.doc.sections[0]
    if header:
        section.header.paragraphs[0].text = header
    if footer:
        section.footer.paragraphs[0].text = footer
    writer.doc.save(str(target))


# =================================================================== plain formats

def _text_of(node: dict) -> str:
    if node.get("type") == "text":
        return node.get("text", "")
    if node.get("type") == "hardBreak":
        return "\n"
    return "".join(_text_of(c) for c in node.get("content") or [])


def _md_inline(nodes: Iterable[dict]) -> str:
    out = []
    for node in nodes or []:
        if node.get("type") == "hardBreak":
            out.append("  \n")
        elif node.get("type") == "image":
            out.append("![image]()")
        elif node.get("type") == "text":
            text = node.get("text", "")
            kinds = {m.get("type") for m in node.get("marks") or []}
            if "code" in kinds:
                text = f"`{text}`"
            if "bold" in kinds:
                text = f"**{text}**"
            if "italic" in kinds:
                text = f"*{text}*"
            if "strike" in kinds:
                text = f"~~{text}~~"
            out.append(text)
    return "".join(out)


def _to_text(nodes: Iterable[dict], markdown: bool, indent: int = 0) -> List[str]:
    """Blocks -> lines of plain text or Markdown."""
    lines: List[str] = []
    pad = "  " * indent
    for node in nodes or []:
        kind = node.get("type")
        inline = _md_inline(node.get("content")) if markdown else _text_of(node)
        if kind == "heading":
            level = int((node.get("attrs") or {}).get("level") or 1)
            lines += [("#" * level + " " if markdown else "") + inline, ""]
        elif kind == "paragraph":
            lines += [pad + inline, ""]
        elif kind in ("bulletList", "orderedList"):
            for i, item in enumerate(node.get("content") or []):
                bullet = f"{i + 1}. " if kind == "orderedList" else "- "
                children = item.get("content") or []
                head = children[0] if children else {}
                lines.append(pad + bullet + (_md_inline(head.get("content")) if markdown else _text_of(head)))
                lines += [ln for ln in _to_text(children[1:], markdown, indent + 1) if ln != ""]
            lines.append("")
        elif kind == "table":
            rows = [[" ".join(_text_of(c).split()) for c in r.get("content") or []] for r in node.get("content") or []]
            if markdown and rows:
                width = max(len(r) for r in rows)
                rows = [r + [""] * (width - len(r)) for r in rows]
                lines.append("| " + " | ".join(rows[0]) + " |")
                lines.append("|" + " --- |" * width)
                lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
            else:
                lines += ["\t".join(r) for r in rows]
            lines.append("")
        elif kind == "blockquote":
            lines += [("> " if markdown else "") + ln for ln in _to_text(node.get("content"), markdown) if ln] + [""]
        elif kind == "codeBlock":
            lines += (["```", _text_of(node), "```", ""] if markdown else [_text_of(node), ""])
        elif kind == "horizontalRule":
            lines += ["---" if markdown else "-" * 40, ""]
        elif kind == "pageBreak":
            lines += ["\f" if not markdown else "", ""]
    return lines


def _para(text: str) -> dict:
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]} if text else {"type": "paragraph"}


def _md_marks(text: str) -> List[dict]:
    """**bold**, *italic*, `code` -> text nodes with marks."""
    nodes: List[dict] = []
    for part in re.split(r"(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)", text):
        if not part:
            continue
        if part.startswith("**") and len(part) > 4:
            nodes.append({"type": "text", "text": part[2:-2], "marks": [{"type": "bold"}]})
        elif part.startswith("*") and len(part) > 2:
            nodes.append({"type": "text", "text": part[1:-1], "marks": [{"type": "italic"}]})
        elif part.startswith("`") and len(part) > 2:
            nodes.append({"type": "text", "text": part[1:-1], "marks": [{"type": "code"}]})
        else:
            nodes.append({"type": "text", "text": part})
    return nodes


def _read_markdown(text: str) -> List[dict]:
    """The common subset: #-headings, - and 1. lists, --- rules, paragraphs, inline marks."""
    blocks: List[dict] = []
    items: List[Tuple[bool, int, dict]] = []
    buffer: List[str] = []

    def flush() -> None:
        if buffer:
            blocks.append({"type": "paragraph", "content": _md_marks(" ".join(buffer))})
            buffer.clear()
        if items:
            blocks.extend(_nest(items))
            items.clear()

    for line in text.replace("\r\n", "\n").split("\n"):
        heading = re.match(r"(#{1,6})\s+(.*)", line)
        item = re.match(r"(\s*)([-*+]|\d+[.)])\s+(.*)", line)
        if heading:
            flush()
            blocks.append({"type": "heading", "attrs": {"level": len(heading.group(1))}, "content": _md_marks(heading.group(2))})
        elif re.fullmatch(r"\s*(-{3,}|\*{3,})\s*", line):
            flush()
            blocks.append({"type": "horizontalRule"})
        elif item:
            if buffer:
                flush()
            ordered = item.group(2)[0].isdigit()
            items.append((ordered, len(item.group(1)) // 2, {"type": "paragraph", "content": _md_marks(item.group(3))}))
        elif not line.strip():
            flush()
        else:
            if items:
                flush()
            buffer.append(line.strip())
    flush()
    return blocks


@method("doc.open")
def doc_open(params, ctx):
    """{input} -> {content: <ProseMirror JSON>, header, footer, notes: [str], format}"""
    path = in_path(params)
    ext = path.suffix.lower()
    header = footer = ""
    notes: List[str] = []
    if ext == ".docx":
        data = _read_docx(path)
        content, header, footer, notes = data["content"], data["header"], data["footer"], data["notes"]
    elif ext in (".txt", ".md", ".rtf", ".odt"):
        if ext == ".odt":
            from .odf_text import read_odt

            blocks = read_odt(path)
            notes = ["OpenDocument: formatting inherited from named styles, headers/footers and drawings are not imported"]
        else:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            if ext == ".rtf":
                from striprtf.striprtf import rtf_to_text

                text = rtf_to_text(text, errors="ignore")
                notes = ["RTF: text only - formatting is not imported"]
            if ext == ".md":
                blocks = _read_markdown(text)
            else:
                blocks = [_para(p.replace("\n", " ").strip()) for p in re.split(r"\n\s*\n", text.replace("\r\n", "\n")) if p.strip()]
        content = {"type": "doc", "content": blocks or [{"type": "paragraph"}]}
    else:
        raise EngineError("unsupported_format", f"Cannot open {ext or 'this file'} as a document")
    return {"path": str(path), "format": ext[1:], "content": content, "header": header, "footer": footer, "notes": notes}


def _write(target: Path, ext: str, content: dict, header: str = "", footer: str = "") -> None:
    if ext == ".docx":
        _write_docx(target, content, header, footer)
    elif ext in (".txt", ".md"):
        lines = _to_text(content.get("content"), markdown=ext == ".md")
        target.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    elif ext == ".odt":
        from .odf_text import write_odt

        write_odt(target, content)
    elif ext == ".rtf":
        from .odf_text import write_rtf

        write_rtf(target, content)
    else:
        raise EngineError("unsupported_format", f"Cannot save a document as {ext or 'this type'}")


@method("doc.save")
def doc_save(params, ctx):
    """{output, content, header?, footer?} -> .docx / .odt / .rtf / .md / .txt by extension.

    Header and footer text is written to .docx only.
    """
    output = Path(str(params["output"]))
    content = params["content"]
    if not isinstance(content, dict) or content.get("type") != "doc":
        raise EngineError("bad_params", "content must be a document")
    ext = output.suffix.lower()
    if ext not in (".docx", ".odt", ".rtf", ".txt", ".md"):
        raise EngineError("unsupported_format", f"Cannot save a document as {ext or 'this type'}")
    with atomic_output(output) as tmp:
        _write(tmp, ext, content, str(params.get("header") or ""), str(params.get("footer") or ""))
    return {"output": str(output)}


@method("doc.image_data_url")
def doc_image_data_url(params, ctx):
    """{input} -> {data_url, width, height} for inserting a user-picked image."""
    from ..rpc import call

    return call("pdf.image_data_url", {"input": params["input"]}, ctx)


# =================================================================== mail merge

def _records(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    """First row = field names; every later row = one record."""
    from ..rpc import call

    sheet = call("sheet.read", {"input": str(path), "max_rows": MAX_MERGE_RECORDS + 1})["sheets"][0]
    rows = sheet.get("values") or sheet["rows"]      # cached results for formula cells
    if not rows:
        raise EngineError("bad_params", "The data file is empty")
    fields = [str(f).strip() for f in rows[0]]
    if not any(fields):
        raise EngineError("bad_params", "The first row of the data file must hold the field names")
    records = []
    for row in rows[1:]:
        if not any(str(v).strip() for v in row):
            continue
        record = {}
        for name, value in zip(fields, row):
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            record[name] = str(value)
        records.append(record)
    return [f for f in fields if f], records


def _fill(node: Any, record: Dict[str, str], missing: set) -> Any:
    if isinstance(node, list):
        return [_fill(n, record, missing) for n in node]
    if not isinstance(node, dict):
        return node
    out = dict(node)
    if node.get("type") == "text":
        def swap(match: "re.Match[str]") -> str:
            name = match.group(1)
            if name in record:
                return record[name]
            missing.add(name)
            return match.group(0)

        out["text"] = PLACEHOLDER.sub(swap, node.get("text", ""))
    elif "content" in node:
        out["content"] = _fill(node["content"], record, missing)
    return out


@method("doc.merge_fields")
def doc_merge_fields(params, ctx):
    """{input: csv/xlsx} -> {fields, records, sample: first record}"""
    fields, records = _records(in_path(params))
    return {"fields": fields, "records": len(records), "sample": records[0] if records else {}}


@method("doc.mail_merge")
def doc_mail_merge(params, ctx):
    """{content, input: data file, output_dir, base_name?, combined?, header?, footer?}

    Replaces {{field}} placeholders; one .docx per record, or one combined file
    with a page break between records.
    """
    content = params["content"]
    if not isinstance(content, dict) or content.get("type") != "doc":
        raise EngineError("bad_params", "content must be a document")
    fields, records = _records(in_path(params))
    if not records:
        raise EngineError("bad_params", "The data file has field names but no records")
    folder = out_dir(params)
    base = re.sub(r'[<>:"/\\|?*]', "_", str(params.get("base_name") or "merged")).strip() or "merged"
    header, footer = str(params.get("header") or ""), str(params.get("footer") or "")
    missing: set = set()
    files: List[str] = []

    def free(name: str) -> Path:
        target, n = folder / f"{name}.docx", 1
        while target.exists():          # never overwrite silently
            n += 1
            target = folder / f"{name} ({n}).docx"
        return target

    if params.get("combined"):
        merged: List[dict] = []
        for i, record in enumerate(records):
            ctx.progress(i / len(records), f"record {i + 1}/{len(records)}")
            if i:
                merged.append({"type": "pageBreak"})
            merged.extend(_fill(copy.deepcopy(content.get("content") or []), record, missing))
        target = free(base)
        with atomic_output(target) as tmp:
            _write_docx(tmp, {"type": "doc", "content": merged}, header, footer)
        files.append(str(target))
    else:
        width = len(str(len(records)))
        for i, record in enumerate(records):
            ctx.progress(i / len(records), f"record {i + 1}/{len(records)}")
            target = free(f"{base}-{i + 1:0{width}d}")
            with atomic_output(target) as tmp:
                _write_docx(tmp, _fill(content, record, missing), header, footer)
            files.append(str(target))

    result: Dict[str, Any] = {"output_dir": str(folder), "files": files, "records": len(records)}
    if missing:
        result["warning"] = "No such field in the data file: " + ", ".join(sorted(missing))
    return result
