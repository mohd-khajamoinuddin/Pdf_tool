import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import docsuite_engine.handlers  # noqa: E402,F401 - registers RPC methods


@pytest.fixture()
def sample_pdf(tmp_path):
    """A 3-page PDF with a title, body text, a ruled table and an image."""
    from PIL import Image
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Image as RLImage
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    img_path = tmp_path / "logo.png"
    Image.new("RGB", (200, 100), (30, 90, 200)).save(img_path)

    styles = getSampleStyleSheet()
    path = tmp_path / "sample.pdf"
    table = Table([["Region", "Q1", "Q2"], ["North", "120", "135"], ["South", "98", "110"]])
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    story = [
        Paragraph("Quarterly Report", styles["Title"]),
        Paragraph("Revenue grew steadily across both regions during the first half.", styles["BodyText"]),
        Paragraph("Costs were flat, so margin improved <b>noticeably</b> quarter on quarter.", styles["BodyText"]),
        Spacer(1, 12),
        table,
        Spacer(1, 12),
        RLImage(str(img_path), width=200, height=100),
        PageBreak(),
        Paragraph("Second Section", styles["Heading1"]),
        Paragraph("Details for page two live here.", styles["BodyText"]),
        PageBreak(),
        Paragraph("Appendix", styles["Heading1"]),
        Paragraph("Closing remarks on page three.", styles["BodyText"]),
    ]
    SimpleDocTemplate(str(path), pagesize=A4).build(story)
    return path
