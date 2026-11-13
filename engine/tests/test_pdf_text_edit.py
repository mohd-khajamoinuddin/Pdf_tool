import pytest
from pypdf import PdfReader
from reportlab.pdfgen import canvas

from docsuite_engine.rpc import EngineError, call


def _line(lines, text):
    return next(l for l in lines if l["text"] == text)


def test_text_lines_describe_what_is_on_the_page(sample_pdf):
    result = call("pdf.text_lines", {"input": str(sample_pdf), "page": 0})
    assert result["editable"] is True
    lines = result["lines"]
    texts = [l["text"] for l in lines]
    assert "Quarterly Report" in texts
    assert "Revenue grew steadily across both regions during the first half." in texts
    assert {"Region", "Q1", "Q2", "North", "120", "135"} <= set(texts)        # table cells are separate runs

    title = _line(lines, "Quarterly Report")
    assert title["bold"] is True and title["size"] == 18 and title["family"] == "sans" and title["color"] == "#000000"
    assert 200 < title["x"] < 260 and 70 < title["y"] < 100 and title["w"] > 100 and 10 < title["h"] < 30
    # A line with a bold word in the middle is split where the style changes.
    assert "noticeably" in texts and _line(lines, "noticeably")["bold"] is True

    with pytest.raises(EngineError):
        call("pdf.text_lines", {"input": str(sample_pdf), "page": 9})


def test_replacing_a_line_removes_the_original(sample_pdf, tmp_path):
    lines = call("pdf.text_lines", {"input": str(sample_pdf), "page": 0})["lines"]
    title = _line(lines, "Quarterly Report")
    cell = _line(lines, "120")
    box = lambda l: {k: l[k] for k in ("x", "y", "w", "h")}  # noqa: E731
    edits = [
        {"page": 0, "type": "text", "x": title["x"], "y": title["y"], "text": "Annual Summary", "size": title["size"],
         "color": "#aa0000", "bold": True, "family": "sans", "replaces": box(title)},
        {"page": 0, "type": "text", "x": cell["x"], "y": cell["y"], "text": "999", "size": cell["size"],
         "color": "#000000", "replaces": box(cell)},
    ]
    out = tmp_path / "edited.pdf"
    result = call("pdf.apply_edits", {"input": str(sample_pdf), "output": str(out), "edits": edits})
    assert result["text_replaced"] == 2 and result["text_covered"] == 0 and "warning" not in result

    text = PdfReader(str(out)).pages[0].extract_text()
    assert "Annual Summary" in text and "999" in text
    assert "Quarterly Report" not in text and "120" not in text                # gone from the file, not just hidden
    for untouched in ("Revenue grew steadily across both regions", "noticeably", "Region", "North", "135", "South", "98", "110"):
        assert untouched in text, untouched
    assert "Second Section" in PdfReader(str(out)).pages[1].extract_text()

    # The new title sits where the old one was, and reports its new look.
    new = _line(call("pdf.text_lines", {"input": str(out), "page": 0})["lines"], "Annual Summary")
    assert abs(new["x"] - title["x"]) < 1 and abs(new["y"] - title["y"]) < 4
    assert new["bold"] is True and new["color"] == "#aa0000" and new["size"] == 18


def test_deleting_a_line(sample_pdf, tmp_path):
    lines = call("pdf.text_lines", {"input": str(sample_pdf), "page": 1})["lines"]
    target = _line(lines, "Details for page two live here.")
    edit = {"page": 1, "type": "text", "x": target["x"], "y": target["y"], "text": "", "size": target["size"],
            "replaces": {k: target[k] for k in ("x", "y", "w", "h")}}
    out = tmp_path / "deleted.pdf"
    assert call("pdf.apply_edits", {"input": str(sample_pdf), "output": str(out), "edits": [edit]})["text_replaced"] == 1
    text = PdfReader(str(out)).pages[1].extract_text()
    assert "Details for page two" not in text and "Second Section" in text


def test_falls_back_to_covering_when_removal_would_hit_other_text(tmp_path):
    """Two words drawn by ONE operator but far apart: removing one would remove both."""
    src = tmp_path / "one-op.pdf"
    c = canvas.Canvas(str(src), pagesize=(400, 200))
    c.setFont("Helvetica", 12)
    text = c.beginText(40, 150)
    text._code.append("[(Name:) -20000 (Value)] TJ")          # a single TJ with a large internal gap
    c.drawText(text)
    c.drawString(40, 100, "Keep me")
    c.save()

    lines = call("pdf.text_lines", {"input": str(src), "page": 0})["lines"]
    value = _line(lines, "Value")
    edit = {"page": 0, "type": "text", "x": value["x"], "y": value["y"], "text": "Changed", "size": 12,
            "replaces": {k: value[k] for k in ("x", "y", "w", "h")}}
    out = tmp_path / "covered.pdf"
    result = call("pdf.apply_edits", {"input": str(src), "output": str(out), "edits": [edit]})
    assert result["text_covered"] == 1 and result["text_replaced"] == 0 and "painted over" in result["warning"]
    text = PdfReader(str(out)).pages[0].extract_text()
    assert "Name:" in text and "Keep me" in text and "Changed" in text      # nothing else was lost

    # Editing the first word instead must not take "Value" with it either.
    name = _line(lines, "Name:")
    edit = {"page": 0, "type": "text", "x": name["x"], "y": name["y"], "text": "Label:", "size": 12,
            "replaces": {k: name[k] for k in ("x", "y", "w", "h")}}
    result = call("pdf.apply_edits", {"input": str(src), "output": str(out), "edits": [edit]})
    text = PdfReader(str(out)).pages[0].extract_text()
    assert result["text_covered"] == 1 and "Value" in text and "Label:" in text and "Keep me" in text


def test_replaces_is_validated(sample_pdf, tmp_path):
    out = tmp_path / "x.pdf"
    for edit in (
        {"page": 0, "type": "rect", "x": 0, "y": 0, "w": 5, "h": 5, "replaces": {"x": 0, "y": 0, "w": 1, "h": 1}},
        {"page": 0, "type": "text", "x": 0, "y": 0, "text": "a", "replaces": {"x": 0, "y": 0}},
        {"page": 0, "type": "text", "x": 0, "y": 0, "text": "a", "replaces": "everything"},
    ):
        with pytest.raises(EngineError):
            call("pdf.apply_edits", {"input": str(sample_pdf), "output": str(out), "edits": [edit]})
    assert not out.exists()
