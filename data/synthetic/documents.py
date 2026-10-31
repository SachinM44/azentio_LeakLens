"""Renders the synthetic documents: an itemised hospital bill and a one-page discharge summary per claim
(reportlab), plus a rasteriser that turns a bill into rotated 150-dpi JPEG pages to look like a scan.
Output is deterministic: reportlab runs in invariant mode (fixed dates, no random ids).
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Sequence

import pymupdf
from PIL import Image
from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

rl_config.invariant = 1

SECTION_ORDER = ["room", "icu", "professional fees", "surgery", "services", "lab", "radiology", "pharma", "medical",
                 "other", "taxes"]
SECTION_TITLES = {"room": "Room and boarding", "icu": "Intensive care", "professional fees": "Professional fees",
                  "surgery": "Surgery / procedures", "services": "Hospital services", "lab": "Laboratory",
                  "radiology": "Radiology and diagnostics", "pharma": "Pharmacy", "medical": "Medical consumables",
                  "other": "Other charges", "taxes": "Taxes"}
CURRENCY_LABEL = {"INR": "Rs.", "AED": "AED"}


class NumberedCanvas(canvas.Canvas):
    """Draws 'Page N of M' on every page once the total is known."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states: List[dict] = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.setFont("Helvetica", 8)
            self.drawRightString(A4[0] - 15 * mm, 10 * mm, f"Page {self._pageNumber} of {total}")
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)


def fmt(x: float) -> str:
    return f"{x:,.2f}"


def pretty_date(iso: str) -> str:
    if not iso:
        return "-"
    return date.fromisoformat(iso).strftime("%d-%b-%Y")


def _styles() -> Dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontSize=15, spaceAfter=2 * mm),
        "h": ParagraphStyle("h", parent=base["Heading3"], fontSize=10.5, spaceBefore=3 * mm, spaceAfter=1 * mm),
        "body": ParagraphStyle("b", parent=base["Normal"], fontSize=9, leading=12),
        "small": ParagraphStyle("s", parent=base["Normal"], fontSize=8, leading=10, textColor=colors.HexColor("#444444")),
        "cell": ParagraphStyle("c", parent=base["Normal"], fontSize=8, leading=10),
    }


def _letterhead(provider: Dict[str, object], subtitle: str):
    def draw(c: canvas.Canvas, doc) -> None:
        c.saveState()
        c.setFillColor(colors.HexColor("#1F4E79"))
        c.rect(0, A4[1] - 22 * mm, A4[0], 22 * mm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 15)
        c.drawString(15 * mm, A4[1] - 11 * mm, str(provider["provider_name"]))
        c.setFont("Helvetica", 8.5)
        c.drawString(15 * mm, A4[1] - 16.5 * mm, f"{provider['address']}  |  Tel {provider['phone']}  |  "
                                                 f"Facility licence {provider['licence_no']}")
        c.drawRightString(A4[0] - 15 * mm, A4[1] - 11 * mm, subtitle)
        c.setFillColor(colors.HexColor("#444444"))
        c.setFont("Helvetica", 7.5)
        c.drawString(15 * mm, 10 * mm, "Computer-generated document. Synthetic data for a software demonstration; "
                                       "no real patient, hospital or insurer.")
        c.restoreState()
    return draw


def _patient_block(facts: Dict[str, str], claim: Dict[str, object], member: Dict[str, str], insurer: str,
                   doctor: str, extra_rows: Sequence[Sequence[str]], styles) -> Table:
    rows = [
        ["Patient name", facts["claimant_name"], "Member ID", member["claimant_id"]],
        ["Policy number", facts["policy_number"], "Insurer", insurer],
        ["Date of birth / Sex", f"{pretty_date(member['date_of_birth'])} / {member['gender']}", "Claim ref.", str(claim["claim_id"])],
        ["Admission", pretty_date(facts["admission_date"]), "Discharge", pretty_date(facts["discharge_date"])],
        ["Diagnosis", str(claim.get("diagnosis") or ""), "Treating doctor", doctor],
    ] + [list(r) for r in extra_rows]
    data = [[Paragraph(f"<b>{r[0]}</b>", styles["cell"]), Paragraph(str(r[1]), styles["cell"]),
             Paragraph(f"<b>{r[2]}</b>", styles["cell"]), Paragraph(str(r[3]), styles["cell"])] for r in rows]
    t = Table(data, colWidths=[30 * mm, 65 * mm, 30 * mm, 55 * mm])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#BBBBBB")),
                           ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF3F8")),
                           ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#EEF3F8")),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


def render_bill_pdf(path: str, *, provider: Dict[str, object], insurer: str, claim: Dict[str, object],
                    member: Dict[str, str], lines: Sequence[Dict[str, object]], facts: Dict[str, str], doctor: str,
                    currency: str) -> int:
    """Itemised final bill: letterhead, patient block, sectioned line table with subtotals, gross / discount / net."""
    styles = _styles()
    cur = CURRENCY_LABEL.get(currency, currency)
    story = [Spacer(1, 4 * mm), Paragraph("ITEMISED FINAL HOSPITAL BILL", styles["title"])]
    bill_date = facts["discharge_date"] or facts["admission_date"]
    story.append(_patient_block(facts, claim, member, insurer, doctor,
                                [["Bill number", facts["invoice_no"], "Bill date", pretty_date(bill_date)],
                                 ["Room category", str(claim.get("room_category") or "-"), "Currency", currency]], styles))
    story.append(Spacer(1, 4 * mm))

    header = ["S.No", "Date", "Code", "Description", "Qty", f"Rate ({cur})", f"Amount ({cur})"]
    data: List[List[object]] = [header]
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#BBBBBB")), ("ALIGN", (4, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    gross = 0.0
    discount = 0.0
    for section in SECTION_ORDER:
        rows = [l for l in lines if l["category"] == section and float(l["amount"]) >= 0]
        if not rows:
            continue
        data.append([SECTION_TITLES[section], "", "", "", "", "", ""])
        r = len(data) - 1
        style_cmds += [("SPAN", (0, r), (-1, r)), ("BACKGROUND", (0, r), (-1, r), colors.HexColor("#E8EEF5")),
                       ("FONTNAME", (0, r), (-1, r), "Helvetica-Bold")]
        subtotal = 0.0
        for l in rows:
            qty = float(l["quantity"])
            data.append([str(l["serial_no"]), pretty_date(l["service_date"].isoformat()), str(l["code"]),
                         Paragraph(str(l["description"]), styles["cell"]), f"{qty:g}", fmt(float(l["unit_price"])),
                         fmt(float(l["amount"]))])
            subtotal += float(l["amount"])
        data.append(["", "", "", f"Subtotal - {SECTION_TITLES[section]}", "", "", fmt(subtotal)])
        r = len(data) - 1
        style_cmds += [("SPAN", (0, r), (3, r)), ("ALIGN", (0, r), (3, r), "RIGHT"),
                       ("FONTNAME", (0, r), (-1, r), "Helvetica-Oblique")]
        gross += subtotal
    for l in lines:
        if float(l["amount"]) < 0:
            discount += -float(l["amount"])
    net = gross - discount
    table = Table(data, colWidths=[11 * mm, 20 * mm, 25 * mm, 71 * mm, 11 * mm, 20 * mm, 22 * mm], repeatRows=1)
    table.setStyle(TableStyle(style_cmds))
    story.append(table)
    story.append(Spacer(1, 3 * mm))

    totals = [["Gross total", fmt(gross)], ["Discount", fmt(discount)], ["NET PAYABLE", fmt(net)]]
    tt = Table(totals, colWidths=[130 * mm, 50 * mm], hAlign="RIGHT")
    tt.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "RIGHT"), ("FONTSIZE", (0, 0), (-1, -1), 9),
                            ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
                            ("LINEABOVE", (0, 2), (-1, 2), 0.8, colors.black),
                            ("BACKGROUND", (0, 2), (-1, 2), colors.HexColor("#E8EEF5"))]))
    story.append(tt)
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph(f"Net payable as printed: {cur} {fmt(net)}. Payment received from {insurer} under "
                           f"policy {facts['policy_number']} will be adjusted against this bill.", styles["small"]))
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph("For the hospital: ______________________ (Billing officer)", styles["body"]))

    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=28 * mm,
                            bottomMargin=18 * mm, title=f"Itemised bill {facts['invoice_no']}", author=str(provider["provider_name"]))
    on_page = _letterhead(provider, "Itemised final bill")
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page, canvasmaker=NumberedCanvas)
    return len(pymupdf.open(path))


def render_discharge_pdf(path: str, *, provider: Dict[str, object], claim: Dict[str, object], member: Dict[str, str],
                         lines: Sequence[Dict[str, object]], facts: Dict[str, str], doctor: str,
                         insurer: str = "") -> None:
    """One-page discharge summary: diagnosis, procedure, dates, course, condition, advice, follow-up."""
    styles = _styles()
    procedures = [str(l["description"]) for l in lines if l["category"] == "surgery"]
    drugs = [str(l["description"]) for l in lines if l["category"] == "pharma"][:4]
    nights = max(1, (date.fromisoformat(facts["discharge_date"]) - date.fromisoformat(facts["admission_date"])).days) \
        if facts.get("admission_date") and facts.get("discharge_date") else 1
    follow_up = (date.fromisoformat(facts["discharge_date"]) + timedelta(days=7)) if facts.get("discharge_date") else None
    story = [Spacer(1, 4 * mm), Paragraph("DISCHARGE SUMMARY", styles["title"]),
             _patient_block(facts, claim, member, insurer, doctor, [["Ward / room", str(claim.get("room_category") or "-"),
                                                                     "Length of stay", f"{nights} night(s)"]], styles),
             Paragraph("Diagnosis", styles["h"]),
             Paragraph(f"{claim.get('diagnosis')} (ICD-10 {claim.get('diagnosis_code') or '-'})", styles["body"]),
             Paragraph("Procedure", styles["h"]),
             Paragraph("; ".join(procedures) if procedures else "Conservative medical management; no operative procedure.",
                       styles["body"]),
             Paragraph("Course in hospital", styles["h"]),
             Paragraph(f"The patient was admitted on {pretty_date(facts['admission_date'])} with the above diagnosis. "
                       f"Investigations were carried out and treatment started on the day of admission. "
                       f"{'The procedure was performed under anaesthesia without complication. ' if procedures else ''}"
                       f"The patient improved steadily, tolerated oral intake and was mobilised. Vitals were stable "
                       f"throughout the stay of {nights} night(s).", styles["body"]),
             Paragraph("Condition at discharge", styles["h"]),
             Paragraph("Stable, afebrile, ambulant. Wound (if any) healthy. Discharged in satisfactory condition.", styles["body"]),
             Paragraph("Medication and advice", styles["h"]),
             Paragraph("<br/>".join(f"- {d}" for d in drugs) + "<br/>- Rest and a light diet; report at once if fever, "
                       "pain or bleeding occurs.", styles["body"]),
             Paragraph("Follow-up", styles["h"]),
             Paragraph(f"Review in the out-patient clinic on {follow_up.strftime('%d-%b-%Y') if follow_up else '-'} "
                       f"(one week after discharge) with the reports.", styles["body"]),
             Spacer(1, 12 * mm),
             Paragraph(f"{doctor}<br/>Consultant, {provider['provider_name']}<br/>Registration no. "
                       f"{str(provider['licence_no']).replace('HOSP', 'MED').replace('FL', 'MD')}", styles["body"])]
    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=28 * mm,
                            bottomMargin=18 * mm, title=f"Discharge summary {claim['claim_id']}",
                            author=str(provider["provider_name"]))
    on_page = _letterhead(provider, "Discharge summary")
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page, canvasmaker=NumberedCanvas)


def rasterise_pdf(pdf_path: str, out_dir: str, stem: str, *, dpi: int = 150, rotation_deg: float = 1.5) -> List[str]:
    """Each page to a JPEG at the given dpi, rotated slightly and tinted, like a flatbed scan."""
    out: List[str] = []
    with pymupdf.open(pdf_path) as doc:
        for n, page in enumerate(doc, start=1):
            pix = page.get_pixmap(dpi=dpi)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            img = img.rotate(rotation_deg, resample=Image.BICUBIC, expand=False, fillcolor=(250, 250, 250))
            tint = Image.new("RGB", img.size, (246, 243, 236))
            img = Image.blend(img, tint, 0.08)
            target = Path(out_dir) / f"{stem}_p{n}.jpg"
            img.save(str(target), "JPEG", quality=82, dpi=(dpi, dpi))
            out.append(str(target))
    return out
