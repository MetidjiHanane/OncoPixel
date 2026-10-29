"""PDF research report (ReportLab)."""
from __future__ import annotations

import io
from typing import Any, Dict, List

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (BaseDocTemplate, Frame, Image, KeepTogether, PageTemplate, Paragraph, Spacer, Table,
                                TableStyle)

from .. import config
from . import report as R
from .strings import tr

MINT = colors.HexColor("#0FA89A")
INK = colors.HexColor("#14202B")
MUTED = colors.HexColor("#5B6B78")
LINE = colors.HexColor("#D5DEE4")
WARN = colors.HexColor("#B42318")


def _esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def to_pdf(data: Dict[str, Any]) -> bytes:
    lang = data["language"]
    s = tr(lang)
    buf = io.BytesIO()
    W, H = A4
    logo = config.ASSETS_DIR / "logo-light.png"

    def decorate(canvas, doc):
        canvas.saveState()
        if logo.exists():
            iw, ih = ImageReader(str(logo)).getSize()
            h = 9 * mm
            canvas.drawImage(str(logo), 18 * mm, H - 18 * mm, width=h * iw / ih, height=h, mask="auto")
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawRightString(W - 18 * mm, H - 14 * mm, f"{s['generated']} {data['generated_at'][:16].replace('T', ' ')} UTC")
        canvas.drawRightString(W - 18 * mm, H - 18 * mm, f"{config.APP_NAME} {config.VERSION}")
        canvas.setStrokeColor(LINE)
        canvas.line(18 * mm, H - 21 * mm, W - 18 * mm, H - 21 * mm)
        canvas.line(18 * mm, 17 * mm, W - 18 * mm, 17 * mm)
        canvas.setFont("Helvetica-Oblique", 7)
        words, lines, cur = s["disclaimer"].split(), [], ""
        for wd in words:
            if len(cur) + len(wd) + 1 > 135:
                lines.append(cur)
                cur = wd
            else:
                cur = f"{cur} {wd}".strip()
        lines.append(cur)
        for i, ln in enumerate(lines[:2]):
            canvas.drawString(18 * mm, 12 * mm - i * 3 * mm, ln)
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(W - 18 * mm, 12 * mm, str(doc.page))
        canvas.restoreState()

    doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=26 * mm, bottomMargin=22 * mm,
                          title=s["title"], author=config.APP_NAME)
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="p", frames=[frame], onPage=decorate)])

    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=18, textColor=INK, alignment=TA_LEFT, spaceAfter=2)
    sub = ParagraphStyle("sub", parent=ss["Normal"], fontSize=9, textColor=MUTED, spaceAfter=8)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=11, textColor=MINT, spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("body", parent=ss["Normal"], fontSize=9, leading=12, textColor=INK)
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=10.5, textColor=MUTED)
    banner = ParagraphStyle("banner", parent=body, fontName="Helvetica-Bold", textColor=WARN)

    def table(rows: List, widths=(55 * mm, None)) -> Table:
        cells = [[Paragraph(_esc(a), small), Paragraph(_esc(b), body)] for a, b in rows]
        t = Table(cells, colWidths=[widths[0], doc.width - widths[0]])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.3, LINE),
                               ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        return t

    flow: List = [Paragraph(_esc(s["title"]), h1), Paragraph(_esc(s["tagline"]), sub)]
    if data["test_fixture"]:
        flow += [Paragraph(_esc(s["test_model"]), banner), Spacer(1, 4)]
    flow += [Paragraph(s["section_patient"], h2), table(R.patient_rows(data, lang)),
             Paragraph(s["section_study"], h2), table(R.study_rows(data, lang)),
             Paragraph(s["section_result"], h2), table(R.result_lines(data, lang)),
             Paragraph(_esc(s["confidence_note"]), small)]

    imgs = data.get("images", {})
    if imgs:
        from PIL import Image as PILImage

        order = [("original", s["original"]), ("overlay", s["overlay"]), ("gradcam", s["gradcam"]), ("uncertainty", s["uncertainty"])]
        cells = []
        for key, cap in order:
            if key in imgs:
                im = PILImage.open(io.BytesIO(imgs[key]))
                w, h = im.size
                box = (doc.width / 2 - 4 * mm)
                scale = min(box / w, 62 * mm / h)
                img = Image(io.BytesIO(imgs[key]), width=w * scale, height=h * scale)
                cells.append([img, Paragraph(_esc(cap), small)])
        grid = []
        for i in range(0, len(cells), 2):
            grid.append([c for c in cells[i:i + 2]] + ([""] if len(cells[i:i + 2]) == 1 else []))
        if grid:
            rows = []
            for pair in grid:
                rows.append([[p[0], p[1]] if p else "" for p in pair])
            t = Table(rows, colWidths=[doc.width / 2] * 2)
            t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
            flow += [KeepTogether([Paragraph(s["section_images"], h2), t])]

    m_rows = R.measurement_rows(data["measurements"], lang)
    if m_rows:
        flow += [KeepTogether([Paragraph(s["section_measure"], h2), table(m_rows)])]
        g = data["segmentation"]
        flow.append(Paragraph(_esc(s["mask_edited"] if g and g["edited"] else s["mask_model"]), small))
        if g and g.get("uncertainty"):
            flow.append(Paragraph(_esc(f"{s['uncertainty_stats']}: {g['uncertainty']['stability_dice_mean']:.3f}"), small))
    flow += [KeepTogether([Paragraph(s["section_models"], h2), table(R.model_rows(data, lang))])]

    st = data["study"]
    rev = R.clinician_rows(data, lang) + [(s["status"], s["statuses"].get(st["status"], st["status"]))]
    if st["status"] == "reviewed":
        rev += [(s["reviewed_by"], st["reviewed_by"] or "-"), (s["reviewed_at"], (st["reviewed_at"] or "")[:16].replace("T", " ")),
                (s["review_note"], st["review_note"] or "-")]
    else:
        rev.append(("", s["not_reviewed"]))
    flow += [KeepTogether([Paragraph(s["section_review"], h2), table(rev)])]

    warns = R.warning_texts(data, lang) + [s["limits"]]
    flow += [KeepTogether([Paragraph(s["section_warnings"], h2)] + [Paragraph("• " + _esc(w), body) for w in warns])]
    doc.build(flow)
    return buf.getvalue()
