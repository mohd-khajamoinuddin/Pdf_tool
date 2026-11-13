import base64
import io

import pytest
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches, Pt
from pypdf import PdfReader

from docsuite_engine.rpc import EngineError, call


def _png(color=(200, 40, 40), size=(80, 40)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


DECK = {
    "width": 960, "height": 540,
    "slides": [
        {
            "background": "#102a43", "notes": "Open with the number", "transition": {"type": "fade", "duration": 0.3},
            "elements": [
                {"type": "shape", "shape": "roundRect", "x": 40, "y": 60, "w": 300, "h": 120, "rotation": 15,
                 "fill": "#f0b429", "stroke": "#ffffff", "strokeWidth": 3, "opacity": 0.5},
                {"type": "text", "x": 60, "y": 220, "w": 500, "h": 90, "rotation": 0, "text": "Quarterly review\nsecond line",
                 "fontFamily": "Georgia", "fontSize": 36, "bold": True, "italic": True, "underline": False,
                 "color": "#ffffff", "align": "center", "bullets": False},
                {"type": "image", "x": 700, "y": 60, "w": 160, "h": 80, "rotation": 0, "src": _png()},
                {"type": "shape", "shape": "arrow", "x": 100, "y": 450, "w": 300, "h": -60, "rotation": 0,
                 "fill": None, "stroke": "#f0b429", "strokeWidth": 4, "opacity": 1},
            ],
        },
        {
            "background": "#ffffff", "notes": "", "transition": {"type": "none", "duration": 0.6},
            "elements": [
                {"type": "text", "x": 60, "y": 60, "w": 800, "h": 200, "rotation": 0, "text": "one\ntwo",
                 "fontFamily": "Calibri", "fontSize": 24, "bold": False, "italic": False, "underline": True,
                 "color": "#1c2128", "align": "left", "bullets": True},
                {"type": "shape", "shape": "ellipse", "x": 600, "y": 300, "w": 120, "h": 120, "rotation": 0,
                 "fill": None, "stroke": "#d92d20", "strokeWidth": 2, "opacity": 1},
                {"type": "shape", "shape": "triangle", "x": 760, "y": 300, "w": 120, "h": 120, "rotation": 0,
                 "fill": "#12b76a", "stroke": None, "strokeWidth": 0, "opacity": 1},
            ],
        },
    ],
}


def test_pptx_round_trip(tmp_path):
    path = tmp_path / "deck.pptx"
    assert call("slides.save", {"output": str(path), "deck": DECK})["slides"] == 2
    result = call("slides.open", {"input": str(path)})
    deck = result["deck"]
    assert (deck["width"], deck["height"]) == (960, 540)
    assert result["notes"] == ["theme, master and layout artwork"]

    first, second = deck["slides"]
    assert first["background"] == "#102a43" and first["notes"] == "Open with the number"
    assert first["transition"] == {"type": "fade", "duration": 0.3} and second["transition"]["type"] == "none"

    box, text, image, arrow = first["elements"]            # z-order is preserved
    assert box == {"type": "shape", "shape": "roundRect", "x": 40, "y": 60, "w": 300, "h": 120, "rotation": 15,
                   "fill": "#f0b429", "stroke": "#ffffff", "strokeWidth": 3, "opacity": 1}
    assert text == DECK["slides"][0]["elements"][1]
    assert image["type"] == "image" and (image["x"], image["y"], image["w"], image["h"]) == (700, 60, 160, 80)
    assert image["src"] == DECK["slides"][0]["elements"][2]["src"]
    assert (arrow["shape"], arrow["x"], arrow["y"], arrow["w"], arrow["h"]) == ("arrow", 100, 450, 300, -60)
    assert arrow["stroke"] == "#f0b429" and arrow["strokeWidth"] == 4

    body, ellipse, triangle = second["elements"]
    assert body["text"] == "one\ntwo" and body["underline"] is True and body["fontSize"] == 24
    assert body["bullets"] is True and text["bullets"] is False
    assert ellipse["shape"] == "ellipse" and ellipse["fill"] is None and ellipse["stroke"] == "#d92d20"
    assert triangle["shape"] == "triangle" and triangle["fill"] == "#12b76a" and triangle["stroke"] is None


def test_written_pptx_uses_native_features(tmp_path):
    path = tmp_path / "deck.pptx"
    call("slides.save", {"output": str(path), "deck": DECK})
    prs = Presentation(str(path))
    assert prs.slide_width == 960 * 12700 and prs.slide_height == 540 * 12700
    slide = prs.slides[0]
    xml = slide._element.xml
    assert '<p:transition spd="fast"><p:fade/></p:transition>' in xml.replace("\n", "").replace("  ", "")
    assert xml.index("<p:cSld") < xml.index("<p:transition")                  # schema order, or PowerPoint repairs the file
    assert 'a:alpha val="50000"' in xml                                       # 50 % opacity
    assert 'a:tailEnd type="triangle"' in xml                                 # arrow head
    assert slide.shapes[1].text_frame.paragraphs[0].runs[0].font.size == Pt(36)
    assert slide.shapes[0].rotation == 15
    bullets = prs.slides[1].shapes[0].text_frame.paragraphs
    assert all("a:buChar" in p._p.xml for p in bullets) and [p.text for p in bullets] == ["one", "two"]


def test_reads_a_deck_built_on_stock_layouts(tmp_path):
    """Placeholders inherit their position from the layout; they must not land at 0,0."""
    prs = Presentation()
    title = prs.slides.add_slide(prs.slide_layouts[0])
    title.shapes.title.text = "Kickoff"
    title.placeholders[1].text = "Subtitle here"
    content = prs.slides.add_slide(prs.slide_layouts[1])
    content.shapes.title.text = "Agenda"
    content.placeholders[1].text_frame.text = "First"
    content.placeholders[1].text_frame.add_paragraph().text = "Second"
    star = content.shapes.add_shape(MSO_SHAPE.STAR_5_POINT, Inches(7), Inches(5), Inches(1), Inches(1))
    star.fill.solid()
    star.fill.fore_color.rgb = RGBColor(0xFF, 0xAA, 0x00)
    content.shapes.add_table(2, 2, Inches(1), Inches(5), Inches(3), Inches(1))
    content.notes_slide.notes_text_frame.text = "keep it short"
    path = tmp_path / "stock.pptx"
    prs.save(str(path))

    result = call("slides.open", {"input": str(path)})
    deck = result["deck"]
    assert (deck["width"], deck["height"]) == (720, 540)                       # python-pptx default is 4:3
    s1, s2 = deck["slides"]
    kick, sub = s1["elements"]
    assert kick["text"] == "Kickoff" and kick["fontSize"] == 40 and kick["align"] == "center"
    assert kick["y"] > 100 and kick["w"] > 500 and sub["y"] > kick["y"]        # real, inherited geometry
    agenda, body, shape = s2["elements"]
    assert agenda["text"] == "Agenda" and body["text"] == "First\nSecond" and body["bullets"] is True
    assert shape["type"] == "shape" and shape["shape"] == "rect" and shape["fill"] == "#ffaa00"
    assert s2["notes"] == "keep it short"
    assert "1 × shape drawn as a rectangle" in result["notes"] and "1 × table" in result["notes"]


def test_exports(tmp_path):
    images = [_png((255, 0, 0), (96, 54)), _png((0, 0, 255), (96, 54))]
    result = call("slides.export_images", {"output_dir": str(tmp_path / "png"), "images": images, "base_name": "deck"})
    assert [p.name for p in sorted((tmp_path / "png").iterdir())] == ["deck-01.png", "deck-02.png"]
    assert Image.open(result["files"][1]).convert("RGB").getpixel((10, 10)) == (0, 0, 255)

    pdf = tmp_path / "deck.pdf"
    assert call("slides.export_pdf", {"output": str(pdf), "images": images, "width": 960, "height": 540})["pages"] == 2
    pages = PdfReader(str(pdf)).pages
    assert len(pages) == 2 and (float(pages[0].mediabox.width), float(pages[0].mediabox.height)) == (960, 540)


def test_bad_input_is_rejected_without_leaving_files(tmp_path):
    out = tmp_path / "x.pptx"
    bad_element = {"width": 960, "height": 540, "slides": [{"elements": [{"type": "video", "x": 0, "y": 0, "w": 1, "h": 1}]}]}
    bad_shape = {"slides": [{"elements": [{"type": "shape", "shape": "star", "x": 0, "y": 0, "w": 1, "h": 1}]}]}
    bad_image = {"slides": [{"elements": [{"type": "image", "x": 0, "y": 0, "w": 1, "h": 1, "src": "nope"}]}]}
    for deck in (bad_element, bad_shape, bad_image, {"slides": []}):
        with pytest.raises(EngineError):
            call("slides.save", {"output": str(out), "deck": deck})
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(EngineError) as err:
        call("slides.save", {"output": str(tmp_path / "x.key"), "deck": DECK})
    assert err.value.code == "unsupported_format"
    junk = tmp_path / "junk.pptx"
    junk.write_bytes(b"zip?")
    with pytest.raises(EngineError) as err:
        call("slides.open", {"input": str(junk)})
    assert err.value.code == "invalid_file"


def test_odp_round_trip(tmp_path):
    path = tmp_path / "deck.odp"
    result = call("slides.save", {"output": str(path), "deck": DECK})
    assert result["slides"] == 2 and "not stored in .odp" in result["warning"]

    opened = call("slides.open", {"input": str(path)})
    deck = opened["deck"]
    assert (deck["width"], deck["height"]) == (960, 540)
    assert opened["notes"] == ["master page artwork, transitions and formatting inherited from named styles"]
    first, second = deck["slides"]
    assert first["background"] == "#102a43" and first["notes"] == "Open with the number"

    box, text, image, arrow = first["elements"]            # z-order is preserved
    assert (box["shape"], box["x"], box["y"], box["w"], box["h"]) == ("roundRect", 40, 60, 300, 120)
    assert box["fill"] == "#f0b429" and box["stroke"] == "#ffffff" and box["strokeWidth"] == 3 and box["opacity"] == 0.5
    assert box["rotation"] == 0                              # .odp export drops rotation (stated in the warning)
    want = DECK["slides"][0]["elements"][1]
    for key in ("text", "x", "y", "w", "h", "fontFamily", "fontSize", "bold", "italic", "underline", "color", "align"):
        assert text[key] == want[key], key
    assert image["src"] == DECK["slides"][0]["elements"][2]["src"] and (image["w"], image["h"]) == (160, 80)
    assert (arrow["shape"], arrow["x"], arrow["y"], arrow["w"], arrow["h"]) == ("line", 100, 450, 300, -60)
    assert arrow["stroke"] == "#f0b429" and arrow["strokeWidth"] == 4

    body, ellipse, triangle = second["elements"]
    assert body["text"] == "one\ntwo" and body["underline"] is True and body["fontSize"] == 24 and body["align"] == "left"
    assert ellipse["shape"] == "ellipse" and ellipse["fill"] is None and ellipse["stroke"] == "#d92d20"
    assert triangle["shape"] == "triangle" and triangle["fill"] == "#12b76a" and triangle["stroke"] is None

    # The opened deck can go straight back out as .pptx: the two formats share one model.
    pptx = tmp_path / "from-odp.pptx"
    assert call("slides.save", {"output": str(pptx), "deck": deck})["slides"] == 2
    assert call("slides.open", {"input": str(pptx)})["deck"]["slides"][0]["elements"][1]["text"] == "Quarterly review\nsecond line"


def test_odp_is_a_valid_package(tmp_path):
    import zipfile

    path = tmp_path / "deck.odp"
    call("slides.save", {"output": str(path), "deck": DECK})
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        assert names[0] == "mimetype" and zf.read("mimetype") == b"application/vnd.oasis.opendocument.presentation"
        assert zf.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
        content = zf.read("content.xml").decode("utf-8")
    assert content.count("<draw:page ") == 2 and "Quarterly review" in content and any(n.startswith("Pictures/") for n in names)
    assert 'svg:width="300.00pt"' in content and "<presentation:notes" in content
