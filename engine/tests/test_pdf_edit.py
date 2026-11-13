import base64
import io

import pytest
from openpyxl import load_workbook
from PIL import Image
from pypdf import PdfReader, PdfWriter

from docsuite_engine.rpc import EngineError, call


def _png_data_url(color=(200, 30, 30, 255), size=(60, 30)):
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _pixel(pdf_path, page, x, y, width=595):
    """RGB of the rendered page at PDF-point (x, y), top-left origin."""
    url = call("pdf.render_page", {"input": str(pdf_path), "page": page, "width": width})["data_url"]
    image = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB")
    return image.getpixel((int(x), int(y)))


def test_reorder_rotate_delete(sample_pdf, tmp_path):
    out = tmp_path / "organised.pdf"
    result = call(
        "pdf.apply_edits",
        {"input": str(sample_pdf), "output": str(out), "pages": [{"source": 2, "rotate": 90}, {"source": 0}]},
    )
    assert result["pages"] == 2
    pages = PdfReader(str(out)).pages
    assert len(pages) == 2
    assert "Appendix" in pages[0].extract_text() and pages[0].rotation == 90
    assert "Quarterly Report" in pages[1].extract_text() and pages[1].rotation == 0

    for bad in ([], [{"source": 9}], [{"source": 0, "rotate": 45}]):
        with pytest.raises(EngineError):
            call("pdf.apply_edits", {"input": str(sample_pdf), "output": str(out), "pages": bad})


def test_stamps_land_where_they_were_placed(sample_pdf, tmp_path):
    out = tmp_path / "annotated.pdf"
    edits = [
        {"page": 1, "type": "text", "x": 72, "y": 400, "text": "Reviewed by QA\nsecond line", "size": 14, "color": "#0033cc"},
        {"page": 1, "type": "rect", "x": 300, "y": 500, "w": 100, "h": 60, "color": "#00aa00", "fill": "#00aa00"},
        {"page": 1, "type": "highlight", "x": 60, "y": 60, "w": 200, "h": 20},
        {"page": 1, "type": "ellipse", "x": 420, "y": 500, "w": 80, "h": 60, "color": "#aa00aa", "width": 3},
        {"page": 1, "type": "arrow", "x1": 100, "y1": 600, "x2": 200, "y2": 650, "color": "#ff0000", "width": 2},
        {"page": 1, "type": "ink", "points": [[100, 700], [150, 720], [200, 700]], "color": "#000000", "width": 2},
        {"page": 1, "type": "image", "x": 450, "y": 100, "w": 60, "h": 30, "data_url": _png_data_url()},
        {"page": 1, "type": "note", "x": 500, "y": 300, "text": "Check this figure"},
    ]
    result = call("pdf.apply_edits", {"input": str(sample_pdf), "output": str(out), "edits": edits})
    assert result["edits"] == len(edits) and result["redacted_pages"] == 0

    reader = PdfReader(str(out))
    text = reader.pages[1].extract_text()
    assert "Reviewed by QA" in text and "second line" in text
    assert "Second Section" in text                       # original content is still real text
    assert "Reviewed by QA" not in reader.pages[0].extract_text()
    notes = [a.get_object() for a in reader.pages[1]["/Annots"]]
    assert any(a["/Subtype"] == "/Text" and a["/Contents"] == "Check this figure" for a in notes)

    # Rendered pixels: filled rectangle is green, stamped image is red, both at the given points.
    r, g, b = _pixel(out, 1, 350, 530)
    assert g > 140 and r < 60 and b < 60
    r, g, b = _pixel(out, 1, 480, 115)
    assert r > 170 and g < 80 and b < 80
    assert _pixel(out, 1, 300, 300) == (255, 255, 255)  # untouched area stays blank


def test_redaction_removes_the_text_not_just_hides_it(sample_pdf, tmp_path):
    out = tmp_path / "redacted.pdf"
    edits = [{"page": 0, "type": "redact", "x": 0, "y": 0, "w": 595, "h": 150}]
    result = call("pdf.apply_edits", {"input": str(sample_pdf), "output": str(out), "edits": edits})
    assert result["redacted_pages"] == 1

    reader = PdfReader(str(out))
    assert reader.pages[0].extract_text().strip() == ""          # nothing left to copy or search
    assert b"Quarterly" not in out.read_bytes()
    assert "Second Section" in reader.pages[1].extract_text()     # other pages untouched
    assert _pixel(out, 0, 300, 75) == (0, 0, 0)                   # box is burned in
    assert sum(_pixel(out, 0, 300, 400)) > 600                    # rest of the page still visible


def test_edits_follow_the_page_own_rotation(sample_pdf, tmp_path):
    """A page stored with /Rotate 90 is edited in the orientation the viewer shows."""
    rotated = tmp_path / "rotated.pdf"
    writer = PdfWriter(clone_from=PdfReader(str(sample_pdf)))
    writer.pages[0].rotate(90)
    writer.write(str(rotated))
    info = call("pdf.info", {"input": str(rotated)})
    out = tmp_path / "rotated-edited.pdf"
    # Displayed size is landscape (842 x 595); fill a square near its top-left corner.
    edit = {"page": 0, "type": "rect", "x": 20, "y": 20, "w": 40, "h": 40, "color": "#0000ff", "fill": "#0000ff"}
    call("pdf.apply_edits", {"input": str(rotated), "output": str(out), "edits": [edit]})
    assert info["page_sizes"][0] == [841.9, 595.3] and info["page_sizes"][1] == [595.3, 841.9]
    r, g, b = _pixel(out, 0, 40, 40, width=842)
    assert b > 200 and r < 60 and g < 60


def test_bad_edits_are_rejected(sample_pdf, tmp_path):
    out = tmp_path / "x.pdf"
    for edits in (
        [{"page": 9, "type": "text", "x": 0, "y": 0, "text": "a"}],
        [{"page": 0, "type": "sparkle"}],
        [{"page": 0, "type": "rect", "x": "left", "y": 0, "w": 1, "h": 1}],
        [{"page": 0, "type": "image", "x": 0, "y": 0, "w": 1, "h": 1, "data_url": "nope"}],
    ):
        with pytest.raises(EngineError):
            call("pdf.apply_edits", {"input": str(sample_pdf), "output": str(out), "edits": edits})
    assert not out.exists()


def test_permissions_need_an_owner_password(sample_pdf, tmp_path):
    out = tmp_path / "restricted.pdf"
    base = {"input": str(sample_pdf), "output": str(out), "user_password": "open", "permissions": {"print": False}}
    with pytest.raises(EngineError):
        call("pdf.protect", base)
    call("pdf.protect", {**base, "owner_password": "owner"})
    reader = PdfReader(str(out))
    reader.decrypt("open")
    from pypdf.constants import UserAccessPermissions as P

    assert not reader.user_access_permissions & P.PRINT
    assert reader.user_access_permissions & P.EXTRACT


def test_pdf_to_xlsx_and_html(sample_pdf, tmp_path):
    xlsx = tmp_path / "out.xlsx"
    result = call("convert.run", {"input": str(sample_pdf), "output": str(xlsx)})
    assert result["tables"] == 1
    wb = load_workbook(str(xlsx))
    assert wb.sheetnames == ["Page 1", "Page 2", "Page 3"]
    rows = [[c.value for c in row] for row in wb["Page 1"].iter_rows()]
    assert rows == [["Region", "Q1", "Q2"], ["North", 120, 135], ["South", 98, 110]]   # numbers are numbers
    assert wb["Page 2"]["A1"].value == "Second Section"

    html = tmp_path / "out.html"
    call("convert.run", {"input": str(sample_pdf), "output": str(html)})
    text = html.read_text(encoding="utf-8")
    assert "<h1>Quarterly Report</h1>" in text and "<td>North</td><td>120</td>" in text
    assert "<b>noticeably</b>" in text
    assert "http" not in text                       # self-contained: no external resources
