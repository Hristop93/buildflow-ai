"""PDF report — the dd 'доклад' (SPEC 5.2 Експорт, with the SPEC 8 disclaimer).

Built from the latest snapshot with reportlab. Cyrillic needs an embedded
TrueType font; we resolve one at runtime (env override -> common Linux DejaVu
paths -> Windows Arial) so no binary font is committed and it works on both the
dev box and a Linux deploy. The resolved font is embedded, so the PDF renders
anywhere regardless of the reader's installed fonts.
"""
from __future__ import annotations

import os
from datetime import date
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
)
from sqlalchemy.orm import Session

from backend.services.sections import latest_snapshot

NAVY = colors.HexColor("#1F4E78")
AMBER = colors.HexColor("#C55A11")
LIGHT = colors.HexColor("#EEF1F5")

_FONT_CANDIDATES = [
    os.getenv("BUILDFLOW_PDF_FONT", ""),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
]
_FONT_CANDIDATES_BOLD = [
    os.getenv("BUILDFLOW_PDF_FONT_BOLD", ""),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\segoeuib.ttf",
]
_REGISTERED = False
FONT, FONT_BOLD = "BF", "BF-Bold"


def _first_existing(paths):
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


def _ensure_fonts():
    """Register a Unicode TTF once. Raises if none is available (deploy must
    install a Cyrillic font or set BUILDFLOW_PDF_FONT)."""
    global _REGISTERED
    if _REGISTERED:
        return
    reg = _first_existing(_FONT_CANDIDATES)
    if reg is None:
        raise RuntimeError(
            "No Cyrillic TTF font found for PDF export. Install DejaVu fonts "
            "or set BUILDFLOW_PDF_FONT to a .ttf path."
        )
    bold = _first_existing(_FONT_CANDIDATES_BOLD) or reg
    pdfmetrics.registerFont(TTFont(FONT, reg))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, bold))
    _REGISTERED = True


def _money(v):
    try:
        return f"{float(v):,.0f} лв".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def _styles():
    ss = getSampleStyleSheet()
    base = ParagraphStyle("body", parent=ss["Normal"], fontName=FONT, fontSize=9, leading=12)
    h1 = ParagraphStyle("h1", parent=base, fontName=FONT_BOLD, fontSize=18, textColor=NAVY, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=base, fontName=FONT_BOLD, fontSize=12, textColor=NAVY, spaceBefore=10, spaceAfter=4)
    small = ParagraphStyle("small", parent=base, fontSize=8, textColor=colors.HexColor("#647082"))
    return base, h1, h2, small


def _table(data, col_widths, head=True):
    t = Table(data, colWidths=col_widths, repeatRows=1 if head else 0)
    style = [
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#E1E6EC")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if head:
        style += [
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ]
    t.setStyle(TableStyle(style))
    return t


def build_pdf(snapshot: dict, project_name: str) -> bytes:
    _ensure_fonts()
    base, h1, h2, small = _styles()
    summary = snapshot.get("summary", {})
    econ = snapshot.get("economics", {})

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"Buildflow AI — {project_name}",
    )
    flow = []

    flow.append(Paragraph("Buildflow AI", h1))
    flow.append(Paragraph(f"Доклад за проект: <b>{project_name}</b> · версия {snapshot.get('version_no', '?')}", base))
    flow.append(Spacer(1, 8))

    # Резюме
    flow.append(Paragraph("Резюме", h2))
    flow.append(_table([
        ["Показател", "Стойност"],
        ["Брой процедури", str(summary.get("procedure_count", "—"))],
        ["Срок (критичен път)", f"{summary.get('total_days', '—')} дни"],
        ["Общо такси", _money(summary.get("total_fees"))],
        ["CAPEX", _money(econ.get("capex"))],
        ["IRR", f"{econ.get('irr', 0) * 100:.1f}%" if econ.get("irr") is not None else "—"],
        ["NPV", _money(econ.get("npv"))],
        ["Присъда", str(econ.get("verdict", "—"))],
    ], [80 * mm, 80 * mm]))

    # Маршрут
    route = snapshot.get("route", [])
    if route:
        flow.append(Paragraph("Маршрут", h2))
        rows = [["Процедура", "Институция", "Основание", "Дни"]]
        for s in route:
            rows.append([s.get("name", ""), s.get("institution", "") or "", s.get("act", "") or "—", str(s.get("duration_days", ""))])
        flow.append(_table(rows, [70 * mm, 55 * mm, 25 * mm, 14 * mm]))

    # Такси
    fees = snapshot.get("fees", {})
    if fees.get("items"):
        flow.append(Paragraph("Такси", h2))
        rows = [["Такса", "Акт / член", "Сума"]]
        for f in fees["items"]:
            cit = f.get("citation") or {}
            act = f"{cit.get('title', '')} {cit.get('article', '') or ''}".strip() or "—"
            rows.append([f.get("description", ""), act, _money(f.get("amount"))])
        rows.append(["ОБЩО", "", _money(fees.get("total"))])
        flow.append(_table(rows, [78 * mm, 56 * mm, 30 * mm]))

    # Икономика — verdict callout
    flow.append(Paragraph("Икономика", h2))
    verdict = str(econ.get("verdict", "—"))
    vcolor = {"relevant": colors.HexColor("#2E7D4F"), "resilient": colors.HexColor("#2E7D4F"),
              "risky": colors.HexColor("#C0392B")}.get(verdict, AMBER)
    callout = _table([[
        f"IRR {econ.get('irr', 0) * 100:.1f}%   ·   NPV {_money(econ.get('npv'))}   ·   "
        f"LCOE {econ.get('lcoe', 0):.1f} лв/MWh   ·   изплащане {econ.get('payback_years', 0):.1f} г.   ·   {verdict.upper()}"
    ]], [160 * mm], head=False)
    callout.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
        ("BACKGROUND", (0, 0), (-1, -1), vcolor),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
    ]))
    flow.append(callout)

    # Stamp + disclaimer (SPEC 8)
    flow.append(Spacer(1, 16))
    flow.append(Paragraph(f"Изчислено по актове в сила към {date.today().isoformat()}.", small))
    flow.append(Paragraph(
        "Този доклад е информационна и аналитична подкрепа, а не правен или инвестиционен съвет.", small))

    doc.build(flow)
    return buf.getvalue()


def export_project_pdf(db: Session, project_id: int, project_name: str) -> bytes:
    """Raises NoComputedVersion if the project was never recalculated."""
    snapshot = latest_snapshot(db, project_id)
    return build_pdf(snapshot, project_name)
