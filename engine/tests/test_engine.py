import io
import json
import zipfile

import pytest
from docx import Document
from pypdf import PdfReader

from docsuite_engine.rpc import Context, EngineError, call, serve
from docsuite_engine.util import parse_page_ranges


# ------------------------------------------------------------- pdf -> docx

def test_pdf_to_docx_reconstructs_structure(sample_pdf, tmp_path):
    out = tmp_path / "out.docx"
    events = []
    ctx = Context(events.append, 1)
    result = call("convert.run", {"input": str(sample_pdf), "output": str(out)}, ctx)

    assert result["pages"] == 3 and result["tables"] == 1 and result["images"] == 1
    assert "warning" not in result
    assert events and events[-1]["value"] == 1.0

    doc = Document(str(out))
    headings = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
    assert headings == ["Quarterly Report", "Second Section", "Appendix"]
    body = "\n".join(p.text for p in doc.paragraphs)
    assert "Revenue grew steadily across both regions" in body
    assert "Closing remarks on page three." in body
    # Inline bold survives as a run-level property.
    assert any(r.bold and "noticeably" in r.text for p in doc.paragraphs for r in p.runs)
    # Table cells land in a real table, not in body text.
    assert [c.text for c in doc.tables[0].rows[1].cells] == ["North", "120", "135"]
    assert "North" not in body
    assert len(doc.inline_shapes) == 1


def test_failed_conversion_leaves_no_output(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"this is not a pdf")
    out = tmp_path / "out.docx"
    with pytest.raises(EngineError) as err:
        call("convert.run", {"input": str(bad), "output": str(out)})
    assert err.value.code == "invalid_pdf"
    assert list(tmp_path.iterdir()) == [bad]  # no output, no stray temp file


def test_unsupported_pair_and_missing_file(sample_pdf, tmp_path):
    with pytest.raises(EngineError) as err:
        call("convert.run", {"input": str(sample_pdf), "output": str(tmp_path / "x.pptx")})
    assert err.value.code == "unsupported_conversion"
    with pytest.raises(EngineError) as err:
        call("convert.run", {"input": str(tmp_path / "nope.pdf"), "output": str(tmp_path / "x.docx")})
    assert err.value.code == "not_found"


# -------------------------------------------------------- other converters

def test_pdf_to_markdown_and_text(sample_pdf, tmp_path):
    md = tmp_path / "out.md"
    call("convert.run", {"input": str(sample_pdf), "output": str(md)})
    text = md.read_text(encoding="utf-8")
    assert "| Region | Q1 | Q2 |" in text and "| North | 120 | 135 |" in text
    assert "Quarterly Report" in text

    txt = tmp_path / "out.txt"
    call("convert.run", {"input": str(sample_pdf), "output": str(txt)})
    assert "Details for page two" in txt.read_text(encoding="utf-8")


def test_docx_roundtrip_to_pdf(sample_pdf, tmp_path):
    docx = tmp_path / "a.docx"
    pdf = tmp_path / "b.pdf"
    call("convert.run", {"input": str(sample_pdf), "output": str(docx)})
    call("convert.run", {"input": str(docx), "output": str(pdf)})
    text = "\n".join(p.extract_text() for p in PdfReader(str(pdf)).pages)
    assert "Quarterly Report" in text and "South" in text


def test_images_and_tables_to_pdf(sample_pdf, tmp_path):
    images = call("pdf.to_images", {"input": str(sample_pdf), "output_dir": str(tmp_path / "img"), "dpi": 72})
    assert images["pages"] == 3
    out = tmp_path / "from_images.pdf"
    call("convert.images_to_pdf", {"inputs": images["files"], "output": str(out)})
    assert len(PdfReader(str(out)).pages) == 3

    csv_path = tmp_path / "t.csv"
    csv_path.write_text("name,qty\nwidget,4\n", encoding="utf-8")
    out = tmp_path / "t.pdf"
    call("convert.run", {"input": str(csv_path), "output": str(out)})
    assert "widget" in PdfReader(str(out)).pages[0].extract_text()

    archive = tmp_path / "pages.zip"
    call("convert.run", {"input": str(sample_pdf), "output": str(archive), "options": {"dpi": 50}})
    assert len(zipfile.ZipFile(archive).namelist()) == 3


def test_batch_reports_per_file_and_never_overwrites(sample_pdf, tmp_path):
    out_dir = tmp_path / "batch"
    out_dir.mkdir()
    (out_dir / "sample.docx").write_text("existing")
    result = call(
        "convert.batch",
        {"inputs": [str(sample_pdf), str(tmp_path / "missing.pdf")], "output_dir": str(out_dir), "target": "docx"},
    )
    assert (result["succeeded"], result["failed"]) == (1, 1)
    assert (out_dir / "sample.docx").read_text() == "existing"
    assert (out_dir / "sample (2).docx").is_file()


# -------------------------------------------------------------- pdf studio

def test_info_and_render(sample_pdf):
    info = call("pdf.info", {"input": str(sample_pdf)})
    assert info["pages"] == 3 and info["encrypted"] is False
    assert info["page_sizes"][0] == [595.3, 841.9]
    page = call("pdf.render_page", {"input": str(sample_pdf), "page": 1, "width": 200})
    assert page["width"] == 200 and page["data_url"].startswith("data:image/png;base64,")
    with pytest.raises(EngineError):
        call("pdf.render_page", {"input": str(sample_pdf), "page": 9})


def test_merge_split_reorder(sample_pdf, tmp_path):
    merged = tmp_path / "merged.pdf"
    call("pdf.merge", {"inputs": [str(sample_pdf), str(sample_pdf)], "output": str(merged)})
    assert len(PdfReader(str(merged)).pages) == 6

    parts = call("pdf.split", {"input": str(merged), "output_dir": str(tmp_path / "parts"), "ranges": "1-2, 5-"})
    assert [len(PdfReader(f).pages) for f in parts["files"]] == [2, 2]
    every = call("pdf.split", {"input": str(sample_pdf), "output_dir": str(tmp_path / "each")})
    assert len(every["files"]) == 3

    reordered = tmp_path / "reordered.pdf"
    call("pdf.reorder", {"input": str(sample_pdf), "output": str(reordered), "order": [2, 0]})
    pages = PdfReader(str(reordered)).pages
    assert len(pages) == 2 and "Appendix" in pages[0].extract_text()
    with pytest.raises(EngineError):
        call("pdf.reorder", {"input": str(sample_pdf), "output": str(reordered), "order": [7]})


def test_protect_requires_password_to_open(sample_pdf, tmp_path):
    locked = tmp_path / "locked.pdf"
    call("pdf.protect", {"input": str(sample_pdf), "output": str(locked), "user_password": "s3cret"})
    with pytest.raises(EngineError) as err:
        call("pdf.info", {"input": str(locked)})
    assert err.value.code == "password_required"
    with pytest.raises(EngineError) as err:
        call("pdf.render_page", {"input": str(locked), "page": 0})
    assert err.value.code == "password_required"
    with pytest.raises(EngineError) as err:
        call("convert.run", {"input": str(locked), "output": str(tmp_path / "l.docx")})
    assert err.value.code == "password_required"
    assert call("pdf.info", {"input": str(locked), "password": "s3cret"})["pages"] == 3
    encrypt = PdfReader(str(locked)).trailer["/Encrypt"]
    assert encrypt["/V"] == 5 and encrypt["/Length"] == 256  # V5 = AES-256


def test_watermark_adds_text_to_every_page(sample_pdf, tmp_path):
    out = tmp_path / "wm.pdf"
    call("pdf.watermark", {"input": str(sample_pdf), "output": str(out), "text": "CONFIDENTIAL"})
    pages = PdfReader(str(out)).pages
    assert len(pages) == 3 and all("CONFIDENTIAL" in p.extract_text() for p in pages)


def test_page_ranges():
    assert parse_page_ranges("1-3,5", 6) == [[0, 1, 2], [4]]
    assert parse_page_ranges("4-", 6) == [[3, 4, 5]]
    for bad in ("0", "3-2", "9", "a-b", ""):
        with pytest.raises(EngineError):
            parse_page_ranges(bad, 6)


# ---------------------------------------------------------------- protocol

def test_stdio_protocol(sample_pdf):
    requests = [
        {"id": 1, "method": "system.ping"},
        {"id": 2, "method": "nope"},
        {"id": 3, "method": "pdf.info", "params": {}},
    ]
    stdin = io.StringIO("\n".join(json.dumps(r) for r in requests) + "\nnot json\n")
    stdout = io.StringIO()
    serve(stdin, stdout, workers=1)
    messages = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert messages[0]["event"] == "ready" and "convert.run" in messages[0]["methods"]
    by_id = {m["id"]: m for m in messages[1:]}
    assert by_id[1]["result"]["ok"] is True
    assert by_id[2]["error"]["code"] == "unknown_method"
    assert by_id[3]["error"] == {"code": "bad_params", "message": "Missing parameter: input"}
    assert by_id[None]["error"]["code"] == "bad_request"


def test_concurrent_renders_are_serialised(sample_pdf):
    """PDFium is not thread-safe; parallel previews must not corrupt output or crash."""
    from concurrent.futures import ThreadPoolExecutor

    expected = [call("pdf.render_page", {"input": str(sample_pdf), "page": p, "width": 300})["data_url"] for p in range(3)]

    def render(i):
        return call("pdf.render_page", {"input": str(sample_pdf), "page": i % 3, "width": 300})["data_url"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(render, range(60)))
    assert all(results[i] == expected[i % 3] for i in range(60))
