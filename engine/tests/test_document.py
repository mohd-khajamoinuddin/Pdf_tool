import base64
import io

import pytest
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.shared import Pt, RGBColor
from PIL import Image

from docsuite_engine.rpc import EngineError, call


def _png(size=(120, 60), color=(20, 120, 220)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _text(node):
    if node.get("type") == "text":
        return node["text"]
    return "".join(_text(c) for c in node.get("content", []))


def T(text, *marks):
    node = {"type": "text", "text": text}
    if marks:
        node["marks"] = list(marks)
    return node


def P(*inline, **attrs):
    node = {"type": "paragraph", "content": list(inline)}
    if attrs:
        node["attrs"] = attrs
    return node


RICH = {
    "type": "doc",
    "content": [
        {"type": "heading", "attrs": {"level": 2, "textAlign": "center"}, "content": [T("Project plan")]},
        P(
            T("Ship "),
            T("soon", {"type": "bold"}, {"type": "italic"}),
            T(" and "),
            T("styled", {"type": "underline"}, {"type": "strike"},
              {"type": "textStyle", "attrs": {"color": "#cc0000", "fontSize": "18pt", "fontFamily": "Georgia"}},
              {"type": "highlight", "attrs": {"color": "#aaffee"}}),
            textAlign="right",
        ),
        {"type": "bulletList", "content": [
            {"type": "listItem", "content": [P(T("fruit")), {"type": "orderedList", "content": [
                {"type": "listItem", "content": [P(T("apple"))]},
                {"type": "listItem", "content": [P(T("pear"))]},
            ]}]},
            {"type": "listItem", "content": [P(T("veg"))]},
        ]},
        {"type": "orderedList", "content": [{"type": "listItem", "content": [P(T("first"))]}]},
        {"type": "table", "content": [
            {"type": "tableRow", "content": [
                {"type": "tableHeader", "attrs": {"colspan": 2, "rowspan": 1}, "content": [P(T("Totals"))]},
                {"type": "tableHeader", "attrs": {"colspan": 1, "rowspan": 2}, "content": [P(T("Tall"))]},
            ]},
            {"type": "tableRow", "content": [
                {"type": "tableCell", "attrs": {"colspan": 1, "rowspan": 1}, "content": [P(T("a"))]},
                {"type": "tableCell", "attrs": {"colspan": 1, "rowspan": 1}, "content": [P(T("b")), P(T("b2"))]},
            ]},
        ]},
        P(T("line one"), {"type": "hardBreak"}, T("line two")),
        P({"type": "image", "attrs": {"src": "data:image/png;base64," + base64.b64encode(_png()).decode(), "width": 120}}),
        {"type": "pageBreak"},
        {"type": "horizontalRule"},
        P(T("The end")),
    ],
}


def test_docx_round_trip_keeps_structure_and_formatting(tmp_path):
    path = tmp_path / "rich.docx"
    call("doc.save", {"output": str(path), "content": RICH, "header": "Confidential", "footer": "Page footer"})
    result = call("doc.open", {"input": str(path)})
    blocks = result["content"]["content"]
    assert result["notes"] == [] and result["header"] == "Confidential" and result["footer"] == "Page footer"

    kinds = [b["type"] for b in blocks]
    assert kinds[:6] == ["heading", "paragraph", "bulletList", "orderedList", "table", "paragraph"]
    assert "pageBreak" in kinds and _text(blocks[-1]) == "The end"

    assert blocks[0]["attrs"] == {"level": 2, "textAlign": "center"} and _text(blocks[0]) == "Project plan"

    para = blocks[1]
    assert para["attrs"] == {"textAlign": "right"}
    runs = para["content"]
    assert [r["text"] for r in runs] == ["Ship ", "soon", " and ", "styled"]
    assert {m["type"] for m in runs[1]["marks"]} == {"bold", "italic"}
    styled = {m["type"]: m.get("attrs") for m in runs[3]["marks"]}
    assert set(styled) == {"underline", "strike", "textStyle", "highlight"}
    assert styled["textStyle"] == {"color": "#cc0000", "fontSize": "18pt", "fontFamily": "Georgia"}
    assert styled["highlight"] == {"color": "#aaffee"}

    # Nested list: bullets containing a numbered list, then a second top-level bullet.
    bullets = blocks[2]["content"]
    assert [_text(i["content"][0]) for i in bullets] == ["fruit", "veg"]
    nested = bullets[0]["content"][1]
    assert nested["type"] == "orderedList" and [_text(i) for i in nested["content"]] == ["apple", "pear"]
    assert blocks[3]["type"] == "orderedList" and _text(blocks[3]) == "first"

    rows = blocks[4]["content"]
    assert [(c["attrs"]["colspan"], c["attrs"]["rowspan"], _text(c)) for c in rows[0]["content"]] == [(2, 1, "Totals"), (1, 2, "Tall")]
    assert [_text(c) for c in rows[1]["content"]] == ["a", "bb2"]
    assert len(rows[1]["content"][1]["content"]) == 2                  # two paragraphs in one cell survive

    assert [n["type"] for n in blocks[5]["content"]] == ["text", "hardBreak", "text"]
    image = blocks[6]["content"][0]
    assert image["type"] == "image" and image["attrs"]["width"] == 120 and image["attrs"]["height"] == 60
    assert base64.b64decode(image["attrs"]["src"].split(",", 1)[1]) == _png()


def test_written_docx_uses_real_word_features(tmp_path):
    path = tmp_path / "rich.docx"
    call("doc.save", {"output": str(path), "content": RICH})
    doc = Document(str(path))
    styles = [p.style.name for p in doc.paragraphs]
    assert styles[0] == "Heading 2"
    assert styles[2:7] == ["List Bullet", "List Number 2", "List Number 2", "List Bullet", "List Number"]   # real lists, not typed bullets
    run = doc.paragraphs[1].runs[3]
    assert run.font.size == Pt(18) and run.font.color.rgb == RGBColor(0xCC, 0, 0) and run.font.name == "Georgia"
    table = doc.tables[0]
    assert table.cell(0, 0)._tc is table.cell(0, 1)._tc and table.cell(0, 2)._tc is table.cell(1, 2)._tc   # merged
    assert table.cell(0, 0).paragraphs[0].runs[0].bold                                                 # header row
    assert len(doc.inline_shapes) == 1


def test_numbered_lists_restart(tmp_path):
    one = {"type": "orderedList", "content": [{"type": "listItem", "content": [P(T("a"))]}, {"type": "listItem", "content": [P(T("b"))]}]}
    path = tmp_path / "lists.docx"
    call("doc.save", {"output": str(path), "content": {"type": "doc", "content": [one, P(T("between")), one]}})
    doc = Document(str(path))
    ids = [p._p.pPr.numPr.numId.val for p in doc.paragraphs if p.style.name == "List Number"]
    assert len(ids) == 4 and ids[0] == ids[1] and ids[2] == ids[3] and ids[0] != ids[2]


def test_reads_a_document_made_in_word_style(tmp_path):
    """Built with python-docx the way Word structures it: styles, real breaks, alignment."""
    doc = Document()
    doc.add_heading("Report", level=0)                      # the Title style
    p = doc.add_paragraph("Intro ")
    p.add_run("bold").bold = True
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    doc.add_paragraph("one", style="List Bullet")
    doc.add_paragraph("two", style="List Bullet")
    doc.add_paragraph("sub", style="List Bullet 2")
    doc.add_paragraph("step", style="List Number")
    doc.add_paragraph("before").add_run().add_break(WD_BREAK.PAGE)
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "h1", "h2"
    table.cell(1, 0).merge(table.cell(1, 1)).text = "wide"
    doc.add_picture(io.BytesIO(_png()), width=Pt(90))
    path = tmp_path / "word.docx"
    doc.save(str(path))

    blocks = call("doc.open", {"input": str(path)})["content"]["content"]
    kinds = [b["type"] for b in blocks]
    assert kinds == ["heading", "paragraph", "bulletList", "orderedList", "paragraph", "pageBreak", "table", "paragraph"]
    assert blocks[0]["attrs"]["level"] == 1
    assert blocks[1]["attrs"] == {"textAlign": "justify"} and blocks[1]["content"][1]["marks"] == [{"type": "bold"}]
    items = blocks[2]["content"]
    assert [_text(i["content"][0]) for i in items] == ["one", "two"]
    assert items[1]["content"][1]["type"] == "bulletList" and _text(items[1]["content"][1]) == "sub"
    wide = blocks[6]["content"][1]["content"]
    assert len(wide) == 1 and wide[0]["attrs"]["colspan"] == 2 and _text(wide[0]) == "wide"
    assert blocks[7]["content"][0]["type"] == "image" and blocks[7]["content"][0]["attrs"]["width"] == 120


def test_text_markdown_and_other_formats(tmp_path):
    md = tmp_path / "out.md"
    call("doc.save", {"output": str(md), "content": RICH})
    text = md.read_text(encoding="utf-8")
    assert "## Project plan" in text and "Ship ***soon*** and" in text
    assert "- fruit\n  1. apple\n  2. pear\n- veg" in text
    assert "| Totals | Tall |" in text

    back = call("doc.open", {"input": str(md)})["content"]["content"]
    assert back[0] == {"type": "heading", "attrs": {"level": 2}, "content": [T("Project plan")]}
    assert back[2]["type"] == "bulletList" and back[2]["content"][0]["content"][1]["type"] == "orderedList"

    txt = tmp_path / "out.txt"
    call("doc.save", {"output": str(txt), "content": RICH})
    assert "Project plan" in txt.read_text(encoding="utf-8") and "**" not in txt.read_text(encoding="utf-8")
    plain = tmp_path / "in.txt"
    plain.write_text("first para\nwrapped\n\nsecond", encoding="utf-8")
    assert [_text(b) for b in call("doc.open", {"input": str(plain)})["content"]["content"]] == ["first para wrapped", "second"]

    rtf = tmp_path / "in.rtf"
    rtf.write_text(r"{\rtf1\ansi Hello \b bold\b0  world\par Second}", encoding="utf-8")
    result = call("doc.open", {"input": str(rtf)})
    assert "Hello bold world" in _text(result["content"]) and result["notes"]

    for bad in ("x.pdf", "x.doc"):
        with pytest.raises(EngineError) as err:
            call("doc.save", {"output": str(tmp_path / bad), "content": RICH})
        assert err.value.code == "unsupported_format"
    broken = tmp_path / "broken.docx"
    broken.write_bytes(b"nope")
    with pytest.raises(EngineError) as err:
        call("doc.open", {"input": str(broken)})
    assert err.value.code == "invalid_file"


def test_unsupported_word_content_is_reported(tmp_path):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    doc = Document()
    p = doc.add_paragraph("See note")
    ref = OxmlElement("w:footnoteReference")
    ref.set(qn("w:id"), "1")
    p.add_run()._r.append(ref)
    doc.add_section()
    path = tmp_path / "notes.docx"
    doc.save(str(path))
    notes = call("doc.open", {"input": str(path)})["notes"]
    assert notes == ["1 × footnote/endnote", "1 × extra section layout"]


def test_mail_merge(tmp_path):
    data = tmp_path / "people.csv"
    data.write_text("name,amount,city\nAda,120,London\nGrace,75.5,New York\n\n", encoding="utf-8")
    assert call("doc.merge_fields", {"input": str(data)}) == {
        "fields": ["name", "amount", "city"], "records": 2, "sample": {"name": "Ada", "amount": "120", "city": "London"},
    }
    template = {"type": "doc", "content": [
        {"type": "heading", "attrs": {"level": 1}, "content": [T("Invoice for {{name}}")]},
        P(T("Amount due: "), T("{{ amount }}", {"type": "bold"}), T(" - {{unknown}}")),
    ]}
    out = tmp_path / "letters"
    result = call("doc.mail_merge", {"content": template, "input": str(data), "output_dir": str(out), "base_name": "invoice"})
    assert [f.name for f in sorted(out.iterdir())] == ["invoice-1.docx", "invoice-2.docx"]
    assert result["records"] == 2 and result["warning"] == "No such field in the data file: unknown"
    second = Document(str(out / "invoice-2.docx"))
    assert second.paragraphs[0].text == "Invoice for Grace"
    assert second.paragraphs[1].text == "Amount due: 75.5 - {{unknown}}" and second.paragraphs[1].runs[1].bold

    # Running again never overwrites; combined mode puts every record in one file.
    call("doc.mail_merge", {"content": template, "input": str(data), "output_dir": str(out), "base_name": "invoice"})
    assert (out / "invoice-1 (2).docx").is_file()
    call("doc.mail_merge", {"content": template, "input": str(data), "output_dir": str(out), "base_name": "all", "combined": True})
    combined = "\n".join(p.text for p in Document(str(out / "all.docx")).paragraphs)
    assert "Invoice for Ada" in combined and "Invoice for Grace" in combined

    empty = tmp_path / "empty.csv"
    empty.write_text("name\n", encoding="utf-8")
    with pytest.raises(EngineError):
        call("doc.mail_merge", {"content": template, "input": str(empty), "output_dir": str(out)})


def test_odt_round_trip(tmp_path):
    path = tmp_path / "rich.odt"
    call("doc.save", {"output": str(path), "content": RICH})
    result = call("doc.open", {"input": str(path)})
    blocks = result["content"]["content"]
    kinds = [b["type"] for b in blocks]
    assert kinds == ["heading", "paragraph", "bulletList", "orderedList", "table", "paragraph", "paragraph",
                     "pageBreak", "horizontalRule", "paragraph"]

    assert blocks[0]["attrs"] == {"level": 2, "textAlign": "center"} and _text(blocks[0]) == "Project plan"
    para = blocks[1]
    assert para["attrs"] == {"textAlign": "right"} and [r["text"] for r in para["content"]] == ["Ship ", "soon", " and ", "styled"]
    assert {m["type"] for m in para["content"][1]["marks"]} == {"bold", "italic"}
    styled = {m["type"]: m.get("attrs") for m in para["content"][3]["marks"]}
    assert set(styled) == {"underline", "strike", "textStyle", "highlight"}
    assert styled["textStyle"] == {"color": "#cc0000", "fontSize": "18pt", "fontFamily": "Georgia"}
    assert styled["highlight"] == {"color": "#aaffee"}

    bullets = blocks[2]["content"]
    assert [_text(i["content"][0]) for i in bullets] == ["fruit", "veg"]
    nested = bullets[0]["content"][1]
    assert nested["type"] == "orderedList" and [_text(i) for i in nested["content"]] == ["apple", "pear"]
    assert blocks[3]["type"] == "orderedList"

    rows = blocks[4]["content"]
    assert [(c["type"], c["attrs"]["colspan"], c["attrs"]["rowspan"], _text(c)) for c in rows[0]["content"]] == [
        ("tableHeader", 2, 1, "Totals"), ("tableHeader", 1, 2, "Tall")]
    assert [_text(c) for c in rows[1]["content"]] == ["a", "bb2"]
    assert "marks" not in rows[0]["content"][0]["content"][0]["content"][0]      # header bold is not doubled up

    assert [n["type"] for n in blocks[5]["content"]] == ["text", "hardBreak", "text"]
    image = blocks[6]["content"][0]
    assert image["type"] == "image" and image["attrs"]["width"] == 120 and image["attrs"]["height"] == 60
    assert base64.b64decode(image["attrs"]["src"].split(",", 1)[1]) == _png()
    assert _text(blocks[-1]) == "The end"

    # A second trip is stable.
    again = tmp_path / "again.odt"
    call("doc.save", {"output": str(again), "content": result["content"]})
    assert call("doc.open", {"input": str(again)})["content"] == result["content"]


def test_odt_is_a_valid_package_other_tools_can_read(tmp_path):
    import zipfile

    from odf import teletype
    from odf.opendocument import load
    from odf.text import H

    path = tmp_path / "rich.odt"
    call("doc.save", {"output": str(path), "content": RICH})
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        assert names[0] == "mimetype" and zf.read("mimetype") == b"application/vnd.oasis.opendocument.text"
        assert zf.getinfo("mimetype").compress_type == zipfile.ZIP_STORED          # required by the ODF spec
        assert "content.xml" in names and "META-INF/manifest.xml" in names and any(n.startswith("Pictures/") for n in names)
    headings = [teletype.extractText(h) for h in load(str(path)).getElementsByType(H)]
    assert headings == ["Project plan"]


def test_rtf_write(tmp_path):
    from striprtf.striprtf import rtf_to_text

    content = {"type": "doc", "content": RICH["content"] + [P(T("Unicode: café — 日本 😀 {braces} back\\slash"))]}
    path = tmp_path / "rich.rtf"
    call("doc.save", {"output": str(path), "content": content})
    raw = path.read_text(encoding="ascii")                 # pure 7-bit, as RTF requires
    assert raw.startswith("{\\rtf1") and raw.count("{") == raw.count("}") + raw.count("\\{") - raw.count("\\}")
    assert "\\b" in raw and "\\i" in raw and "\\ul" in raw and "\\strike" in raw and "\\fs36" in raw
    assert "\\red204\\green0\\blue0" in raw and "Georgia" in raw           # colour and font tables
    assert "\\trowd" in raw and "\\pngblip" in raw and "\\page" in raw
    assert "\\u-10179?\\u-8704?" in raw                                    # 😀 as a UTF-16 surrogate pair

    text = rtf_to_text(raw)
    for expected in ("Project plan", "Ship soon and styled", "apple", "Totals", "line one", "The end", "café — 日本", "{braces} back\\slash"):
        assert expected in text, expected

    # And the app itself can open what it wrote (as text).
    assert "Project plan" in _text(call("doc.open", {"input": str(path)})["content"])
