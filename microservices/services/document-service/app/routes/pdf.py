"""PDF generation — Purchase Orders and generic documents."""
import logging
import re
import asyncio
from io import BytesIO
from html import escape, unescape
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, Body, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from shared.database.service import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


def _render_html_template(context: Dict[str, Any]) -> str:
    """Render a compact, print-ready purchase order."""
    items_rows = ""
    total = 0.0
    for i, item in enumerate(context.get("items") or [], 1):
        desc = _html(item.get("description", ""))
        try:
            qty = float(item.get("quantity", 1) or 0)
            rate = float(item.get("rate", 0) or 0)
        except (TypeError, ValueError):
            qty, rate = 0.0, 0.0
        amount = qty * rate
        total += amount
        quantity_text = f"{qty:g}"
        items_rows += (
            f"<tr><td class=\"row-number\">{i:02d}</td><td class=\"description\">{desc}</td>"
            f"<td class=\"numeric\">{quantity_text}</td>"
            f"<td class=\"numeric\">{rate:,.2f}</td><td class=\"numeric amount\">{amount:,.2f}</td></tr>"
        )
    if not context.get("items") and context.get("total_amount"):
        try:
            total = float(context.get("total_amount") or 0)
        except (TypeError, ValueError):
            total = 0.0

    po_number = _html(context.get("po_number") or "PO-XXXX")
    issue_date = _html(context.get("date", ""))
    vendor_name = _html(context.get("vendor_name", "")) or "—"
    client_name = _html(context.get("client_name", "")) or "—"
    client_email = _html(context.get("client_email", ""))
    billing_address = _html(context.get("client_billing_address", "")).replace("\n", "<br>")
    gstin = _html(context.get("client_gstin", ""))
    domain = _html(context.get("training_domain", "")) or "—"
    training_dates = _html(context.get("training_dates", "")) or "—"
    duration = _html(context.get("duration", "")) or "—"
    mode = _html(context.get("mode", "")) or "—"
    payment_terms = _html(context.get("payment_terms", "")) or "As agreed"
    notes = _html(context.get("notes", "")).replace("\n", "<br>")
    total_amount = f"{total:,.2f}"

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>Purchase Order {po_number}</title>
<style>
  @page {{ size: A4; margin: 17mm 16mm 18mm; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; color: #172033; font-family: Arial, Helvetica, sans-serif; font-size: 10pt; line-height: 1.45; }}
  .topline {{ height: 5px; background: #173b65; margin: -17mm -16mm 22px; }}
  .masthead {{ display: flex; align-items: center; justify-content: space-between; gap: 24px; padding-bottom: 17px; border-bottom: 1px solid #d8e0ea; }}
  .company {{ color: #173b65; font-size: 14pt; font-weight: 700; letter-spacing: .08em; }}
  .document-label {{ color: #64748b; font-size: 8pt; font-weight: 700; letter-spacing: .17em; text-align: right; }}
  h1 {{ margin: 4px 0 0; color: #173b65; font-size: 22pt; letter-spacing: .035em; text-align: right; }}
  .order-meta {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 20px 0 22px; }}
  .meta-card {{ border: 1px solid #dbe3ed; border-radius: 6px; padding: 11px 13px; }}
  .label {{ display: block; margin-bottom: 4px; color: #64748b; font-size: 7.5pt; font-weight: 700; letter-spacing: .11em; text-transform: uppercase; }}
  .meta-value {{ color: #172033; font-size: 11pt; font-weight: 700; }}
  .section-title {{ margin: 0 0 10px; color: #173b65; font-size: 9pt; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; }}
  .parties {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 19px; }}
  .party-card {{ min-height: 120px; border: 1px solid #dbe3ed; border-radius: 6px; padding: 13px 14px; break-inside: avoid; }}
  .party-name {{ margin: 0 0 5px; color: #172033; font-size: 12pt; font-weight: 700; }}
  .party-detail {{ margin: 2px 0; color: #475569; font-size: 9pt; overflow-wrap: anywhere; }}
  .training {{ margin-bottom: 20px; padding: 13px 14px; background: #f3f6fa; border-left: 3px solid #2b628f; break-inside: avoid; }}
  .training-grid {{ display: grid; grid-template-columns: 1.4fr 1fr 1fr 1fr; gap: 12px; }}
  .training-value {{ color: #172033; font-size: 9pt; font-weight: 600; overflow-wrap: anywhere; }}
  table {{ width: 100%; border-collapse: collapse; margin: 0 0 12px; }}
  thead {{ display: table-header-group; }}
  th {{ padding: 9px 8px; background: #173b65; color: #fff; font-size: 7.5pt; font-weight: 700; letter-spacing: .08em; text-align: left; text-transform: uppercase; }}
  th.numeric, td.numeric {{ text-align: right; white-space: nowrap; }}
  td {{ padding: 9px 8px; border-bottom: 1px solid #e2e8f0; vertical-align: top; }}
  tr {{ break-inside: avoid; }}
  .row-number {{ width: 34px; color: #64748b; font-size: 8pt; }}
  .description {{ width: 48%; }}
  .amount {{ color: #172033; font-weight: 700; }}
  .totals {{ display: flex; justify-content: flex-end; margin: 8px 0 20px; break-inside: avoid; }}
  .total-box {{ min-width: 230px; padding: 12px 14px; background: #f3f6fa; border: 1px solid #dbe3ed; border-radius: 6px; }}
  .total-label {{ color: #475569; font-size: 9pt; font-weight: 700; }}
  .total-value {{ float: right; color: #173b65; font-size: 13pt; font-weight: 700; }}
  .terms {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin-top: 3px; }}
  .terms-block {{ min-height: 48px; padding-top: 10px; border-top: 1px solid #dbe3ed; break-inside: avoid; }}
  .terms-text {{ margin: 3px 0 0; color: #475569; font-size: 9pt; }}
  .signature {{ margin-top: 32px; text-align: right; break-inside: avoid; }}
  .signature-line {{ display: inline-block; width: 210px; padding-top: 7px; border-top: 1px solid #94a3b8; color: #475569; font-size: 8pt; text-align: center; }}
  .footer {{ margin-top: 22px; padding-top: 8px; border-top: 1px solid #e2e8f0; color: #94a3b8; font-size: 7.5pt; text-align: center; }}
</style>
</head>
<body>
<div class="topline"></div>
<header class="masthead">
  <div><div class="company">CLAHAN TECHNOLOGIES</div></div>
  <div><div class="document-label">OFFICIAL DOCUMENT</div><h1>PURCHASE ORDER</h1></div>
</header>
<section class="order-meta">
  <div class="meta-card"><span class="label">Purchase order number</span><div class="meta-value">{po_number}</div></div>
  <div class="meta-card"><span class="label">Issue date</span><div class="meta-value">{issue_date or '—'}</div></div>
</section>
<section class="parties">
  <div class="party-card"><h2 class="section-title">Vendor / Trainer</h2><p class="party-name">{vendor_name}</p></div>
  <div class="party-card"><h2 class="section-title">Client / Bill to</h2><p class="party-name">{client_name}</p>
    {f'<p class="party-detail">{client_email}</p>' if client_email else ''}
    {f'<p class="party-detail">{billing_address}</p>' if billing_address else ''}
    {f'<p class="party-detail"><b>GSTIN:</b> {gstin}</p>' if gstin else ''}
  </div>
</section>
<section class="training">
  <h2 class="section-title">Order scope</h2>
  <div class="training-grid">
    <div><span class="label">Course / domain</span><div class="training-value">{domain}</div></div>
    <div><span class="label">Training dates</span><div class="training-value">{training_dates}</div></div>
    <div><span class="label">Duration</span><div class="training-value">{duration}</div></div>
    <div><span class="label">Delivery mode</span><div class="training-value">{mode}</div></div>
  </div>
</section>
<table>
  <thead><tr><th>#</th><th>Description</th><th class="numeric">Qty</th><th class="numeric">Rate (INR)</th><th class="numeric">Amount (INR)</th></tr></thead>
  <tbody>
  {items_rows}
  </tbody>
</table>
<div class="totals"><div class="total-box"><span class="total-label">Order total (INR)</span><span class="total-value">{total_amount}</span></div></div>
<section class="terms">
  <div class="terms-block"><span class="label">Payment terms</span><p class="terms-text">{payment_terms}</p></div>
  <div class="terms-block"><span class="label">Notes / delivery instructions</span><p class="terms-text">{notes or '—'}</p></div>
</section>
<div class="signature"><div class="signature-line">Authorized signatory</div></div>
<footer class="footer">Clahan Technologies · Purchase Order {po_number}</footer>
</body></html>"""


def _render_purchase_order_pdf_reportlab(context: Dict[str, Any]) -> bytes:
    """ReportLab fallback matching the print-ready HTML purchase order."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    navy = colors.HexColor("#173b65")
    ink = colors.HexColor("#172033")
    muted = colors.HexColor("#64748b")
    border = colors.HexColor("#dbe3ed")
    pale = colors.HexColor("#f3f6fa")
    buffer = BytesIO()
    po_number = str(context.get("po_number") or "PO-XXXX")
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
        topMargin=17 * mm, bottomMargin=19 * mm, title=f"Purchase Order {po_number}",
    )
    base = getSampleStyleSheet()
    company_style = ParagraphStyle("POCompany", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=14, leading=17, textColor=navy)
    document_style = ParagraphStyle("PODocument", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=18, leading=21, alignment=TA_RIGHT, textColor=navy)
    label_style = ParagraphStyle("POLabel", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=7.5, leading=9, textColor=muted, spaceAfter=3)
    heading_style = ParagraphStyle("POSection", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=navy, spaceAfter=5)
    body_style = ParagraphStyle("POBody", parent=base["Normal"], fontName="Helvetica", fontSize=9, leading=12, textColor=ink, wordWrap="CJK")
    strong_style = ParagraphStyle("POStrong", parent=body_style, fontName="Helvetica-Bold", fontSize=10, leading=13)
    right_style = ParagraphStyle("PORight", parent=body_style, alignment=TA_RIGHT)
    small_style = ParagraphStyle("POSmall", parent=body_style, fontSize=8, leading=10, textColor=muted)

    def para(value: Any, style=body_style) -> Paragraph:
        text = str(value or "").replace("—", "-").replace("–", "-").replace("·", "|").replace("₹", "INR")
        return Paragraph(_html(text).replace("\n", "<br/>") or "-", style)

    def label_value(label: str, value: Any, value_style=strong_style):
        return [Paragraph(_html(label.upper()), label_style), para(value, value_style)]

    story = []
    masthead = Table([[
        Paragraph("CLAHAN TECHNOLOGIES", company_style),
        Paragraph("PURCHASE ORDER", document_style),
    ]], colWidths=[89 * mm, 89 * mm])
    masthead.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEABOVE", (0, 0), (-1, 0), 5, navy),
        ("LINEBELOW", (0, 0), (-1, 0), 0.7, border),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    story.extend([masthead, Spacer(1, 5 * mm)])

    meta = Table([[
        label_value("Purchase order number", po_number),
        label_value("Issue date", context.get("date") or "-"),
    ]], colWidths=[89 * mm, 89 * mm])
    meta.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.7, border),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, border),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    story.extend([meta, Spacer(1, 6 * mm)])

    vendor = [Paragraph("VENDOR / TRAINER", heading_style), para(context.get("vendor_name") or "-", strong_style)]
    client = [Paragraph("CLIENT / BILL TO", heading_style), para(context.get("client_name") or "-", strong_style)]
    for value in (context.get("client_email"), context.get("client_billing_address")):
        if value:
            client.append(para(value, small_style))
    if context.get("client_gstin"):
        client.append(para(f"GSTIN: {context['client_gstin']}", small_style))
    parties = Table([[vendor, client]], colWidths=[89 * mm, 89 * mm])
    parties.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.7, border), ("INNERGRID", (0, 0), (-1, -1), 0.5, border),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.extend([parties, Spacer(1, 5 * mm), Paragraph("ORDER SCOPE", heading_style)])

    scope_values = [
        ("Course / domain", context.get("training_domain")),
        ("Training dates", context.get("training_dates")),
        ("Duration", context.get("duration")),
        ("Delivery mode", context.get("mode")),
    ]
    scope = Table([[
        label_value(label, value or "-", body_style) for label, value in scope_values
    ]], colWidths=[44.5 * mm] * 4)
    scope.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), pale), ("LINEBEFORE", (0, 0), (0, 0), 3, navy),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.extend([scope, Spacer(1, 6 * mm)])

    table_header_style = ParagraphStyle("POTableHeader", parent=label_style, textColor=colors.white)
    table_data = [[
        Paragraph("#", table_header_style), Paragraph("DESCRIPTION", table_header_style),
        Paragraph("QTY", ParagraphStyle("POHeadQty", parent=table_header_style, alignment=TA_RIGHT)),
        Paragraph("RATE (INR)", ParagraphStyle("POHeadRate", parent=table_header_style, alignment=TA_RIGHT)),
        Paragraph("AMOUNT (INR)", ParagraphStyle("POHeadAmount", parent=table_header_style, alignment=TA_RIGHT)),
    ]]
    total = 0.0
    for index, item in enumerate(context.get("items") or [], 1):
        try:
            quantity = float(item.get("quantity", 1) or 0)
            rate = float(item.get("rate", 0) or 0)
        except (TypeError, ValueError):
            quantity, rate = 0.0, 0.0
        amount = quantity * rate
        total += amount
        table_data.append([
            para(f"{index:02d}", small_style), para(item.get("description") or "-"),
            Paragraph(f"{quantity:g}", right_style), Paragraph(f"{rate:,.2f}", right_style),
            Paragraph(f"{amount:,.2f}", ParagraphStyle("POAmount", parent=right_style, fontName="Helvetica-Bold")),
        ])
    if not context.get("items"):
        try:
            total = float(context.get("total_amount") or 0)
        except (TypeError, ValueError):
            total = 0.0
    line_items = Table(table_data, colWidths=[11 * mm, 75 * mm, 20 * mm, 34 * mm, 38 * mm], repeatRows=1)
    line_items.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), navy), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, navy), ("LINEBELOW", (0, 1), (-1, -1), 0.45, border),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.extend([line_items, Spacer(1, 3 * mm)])
    total_box = Table([[
        Paragraph("ORDER TOTAL (INR)", ParagraphStyle("POTotalLabel", parent=body_style, fontName="Helvetica-Bold", textColor=navy)),
        Paragraph(f"{total:,.2f}", ParagraphStyle("POTotalValue", parent=body_style, fontName="Helvetica-Bold", fontSize=12, alignment=TA_RIGHT, textColor=navy)),
    ]], colWidths=[69 * mm, 37 * mm])
    total_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), pale), ("BOX", (0, 0), (-1, -1), 0.7, border),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    totals_row = Table([["", total_box]], colWidths=[72 * mm, 106 * mm])
    totals_row.setStyle(TableStyle([("ALIGN", (1, 0), (1, 0), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.extend([totals_row, Spacer(1, 6 * mm)])

    terms_data = [[
        [Paragraph("PAYMENT TERMS", label_style), para(context.get("payment_terms") or "As agreed", small_style)],
        [Paragraph("NOTES / DELIVERY INSTRUCTIONS", label_style), para(context.get("notes") or "-", small_style)],
    ]]
    terms = Table(terms_data, colWidths=[89 * mm, 89 * mm])
    terms.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, -1), 0.6, border), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([terms, Spacer(1, 15 * mm)])
    signature = Table([["", Paragraph("Authorized signatory", small_style)]], colWidths=[120 * mm, 58 * mm])
    signature.setStyle(TableStyle([
        ("LINEABOVE", (1, 0), (1, 0), 0.7, muted), ("ALIGN", (1, 0), (1, 0), "CENTER"),
        ("TOPPADDING", (1, 0), (1, 0), 5),
    ]))
    story.append(signature)

    def draw_footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(border)
        canvas.line(16 * mm, 13 * mm, A4[0] - 16 * mm, 13 * mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(muted)
        canvas.drawString(16 * mm, 9 * mm, f"Clahan Technologies  |  Purchase Order {po_number}")
        canvas.drawRightString(A4[0] - 16 * mm, 9 * mm, f"Page {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    return buffer.getvalue()


async def _html_to_pdf(html: str, purchase_order_context: Optional[Dict[str, Any]] = None) -> bytes:
    """Convert HTML to PDF bytes using weasyprint."""
    try:
        from weasyprint import HTML
        loop = asyncio.get_event_loop()
        pdf_bytes = await loop.run_in_executor(None, lambda: HTML(string=html).write_pdf())
        return pdf_bytes
    except Exception as exc:
        # If WeasyPrint fails (commonly due to missing native libs on Windows), fall back to ReportLab
        try:
            if purchase_order_context is not None:
                return _render_purchase_order_pdf_reportlab(purchase_order_context)

            from reportlab.lib.pagesizes import A4
            from reportlab.lib.units import mm
            from reportlab.pdfgen import canvas
            from io import BytesIO

            buffer = BytesIO()
            c = canvas.Canvas(buffer, pagesize=A4)
            width, height = A4

            text = _html_to_plain_text(html)
            lines = [line.strip() for line in text.splitlines() if line.strip()]

            margin_left = 16 * mm
            y = height - 20 * mm
            max_width = width - 32 * mm
            c.setFont("Helvetica", 10)
            for line in lines:
                # naive wrap based on character count approximation
                while line:
                    chars = int(max_width / 6.5)
                    part = line[:chars]
                    c.drawString(margin_left, y, part)
                    line = line[chars:]
                    y -= 12
                    if y < 20 * mm:
                        c.showPage()
                        c.setFont("Helvetica", 10)
                        y = height - 20 * mm

            c.save()
            buffer.seek(0)
            return buffer.read()
        except ImportError:
            raise HTTPException(503, "PDF generation requires weasyprint or reportlab. Install either package.")
        except Exception:
            # Re-raise the original weasyprint exception as a 500 for visibility
            raise HTTPException(500, f"PDF generation failed: {exc}")


def _money(value: Any) -> str:
    try:
        return f"Rs.{float(value or 0):,.2f}"
    except (TypeError, ValueError):
        return "Rs.0.00"


def _beulix_logo_html(css_class: str = "beulix-logo") -> str:
    return f"""
    <div class="{css_class}">
      <span class="logo-beuli">BEULI</span><span class="logo-x">X</span><span class="logo-solutions">SOLUTIONS</span>
      <span class="logo-private">PRIVATE LIMITED</span>
    </div>
    """


def _asset_data_uri(filename: str) -> str:
    path = Path(__file__).resolve().parents[1] / "assets" / filename
    if not path.exists():
        return ""
    import base64

    return f"data:image/png;base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _render_invoice_pdf_reportlab(context: Dict[str, Any]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = BytesIO()
    asset_dir = Path(__file__).resolve().parents[1] / "assets"
    logo_path = asset_dir / "beulix_logo.png"
    signature_path = asset_dir / "murali_signature.png"
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Invoice {context.get('invoice_number') or ''}",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "InvoiceTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=25,
        textColor=colors.HexColor("#0f172a"),
        leading=29,
        spaceAfter=6,
    )
    label_style = ParagraphStyle(
        "InvoiceLabel",
        parent=styles["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        textColor=colors.HexColor("#0f172a"),
        leading=10,
    )
    body_style = ParagraphStyle(
        "InvoiceBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9,
        leading=11,
        spaceAfter=2,
    )
    right_style = ParagraphStyle(
        "InvoiceRight",
        parent=body_style,
        alignment=TA_RIGHT,
        fontSize=8,
        leading=9,
    )
    small_style = ParagraphStyle(
        "InvoiceSmall",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#334155"),
    )
    table_header_style = ParagraphStyle(
        "InvoiceTableHeader",
        parent=small_style,
        fontName="Helvetica-Bold",
        textColor=colors.white,
    )

    company_name_full = context.get("company_name_full") or "BEULIX SOLUTIONS PRIVATE LIMITED"
    company_name_short = context.get("company_name_short") or "BEULIX"
    company_address = context.get("company_address") or ""
    company_email = context.get("company_email") or ""
    company_contact = context.get("company_contact") or ""
    company_pan = context.get("company_pan") or ""
    company_gst = context.get("company_gst") or context.get("gst_number") or ""
    client_address = context.get("client_address") or context.get("client_billing_address") or ""
    client_name = context.get("client_name") or ""
    client_gst = context.get("client_gst") or context.get("client_gstin") or ""
    po_number = context.get("po_number") or context.get("client_po_number") or ""
    place_of_supply = context.get("place_of_supply") or ""
    bank_account_no = context.get("bank_account_no") or ""
    bank_ifsc = context.get("bank_ifsc") or ""
    signatory_name = context.get("signatory_name") or "Authorized Signatory"
    terms_and_conditions = context.get("terms_and_conditions") or context.get("payment_terms") or ""

    items = context.get("items") or []
    table_items = []
    subtotal = 0.0
    if items:
        for index, item in enumerate(items, start=1):
            quantity = float(item.get("quantity") or 0)
            rate = float(item.get("rate") or 0)
            amount = item.get("amount")
            amount = float(amount) if amount is not None else quantity * rate
            subtotal += amount
            table_items.append([
                str(index),
                str(item.get("description", "")),
                str(item.get("hsn_sac", "")),
                f"{quantity:g}",
                f"{rate:,.2f}",
                f"{amount:,.2f}",
            ])
    else:
        subtotal = float(context.get("total_amount") or 0)
        table_items.append([
            "1",
            " | ".join(part for part in [
                context.get("training_domain") or "",
                context.get("training_dates") or "",
                f"Duration: {context.get('duration')}" if context.get("duration") else "",
                context.get("mode") or "",
            ] if part) or "Training Services",
            "",
            str(context.get("duration") or 1),
            f"{float(context.get('day_rate') or subtotal):,.2f}",
            f"{subtotal:,.2f}",
        ])

    gst_rate = float(context.get("gst_rate") or 0)
    gst_amount = subtotal * gst_rate / 100
    total_amount = subtotal + gst_amount
    balance_due = float(context.get("balance_due") if context.get("balance_due") is not None else total_amount)
    amount_words = _number_to_words(int(round(total_amount))) + " Rupees Only"

    from reportlab.pdfgen import canvas
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    blue = colors.HexColor("#1f4e84")
    dark = colors.HexColor("#111827")
    grid = colors.HexColor("#b7b7b7")
    light_blue = colors.HexColor("#c9e6f5")
    left = 15 * mm
    right = width - 15 * mm
    y = height - 15 * mm

    def draw_logo(x, y_top, scale=1.0, alpha=1.0):
        if logo_path.exists():
            c.saveState()
            try:
                c.setFillAlpha(alpha)
                c.setStrokeAlpha(alpha)
            except AttributeError:
                pass
            logo_width = 230 * scale
            logo_height = 45 * scale
            c.drawImage(
                str(logo_path),
                x,
                y_top - logo_height,
                width=logo_width,
                height=logo_height,
                mask="auto",
                preserveAspectRatio=True,
                anchor="sw",
            )
            c.restoreState()
            return
        c.saveState()
        try:
            c.setFillAlpha(alpha)
            c.setStrokeAlpha(alpha)
        except AttributeError:
            pass
        c.setFont("Helvetica-Bold", 24 * scale)
        c.setFillColor(colors.HexColor("#2d3393"))
        c.drawString(x, y_top - 20 * scale, "BEULI")
        c.setFont("Helvetica-Bold", 50 * scale)
        c.setFillColor(colors.HexColor("#19aee4"))
        c.drawString(x + 73 * scale, y_top - 32 * scale, "X")
        c.setFont("Helvetica-Bold", 24 * scale)
        c.setFillColor(colors.HexColor("#2d3393"))
        c.drawString(x + 120 * scale, y_top - 20 * scale, "SOLUTIONS")
        c.setFont("Helvetica-Bold", 11 * scale)
        c.setFillColor(colors.HexColor("#333333"))
        c.drawString(x + 124 * scale, y_top - 36 * scale, "P R I V A T E   L I M I T E D")
        c.restoreState()

    def draw_wrapped_text(text, x, y_start, max_width, line_height=10):
        words = str(text or "").split()
        line = ""
        y_pos = y_start
        for word in words:
            candidate = f"{line} {word}".strip()
            if line and c.stringWidth(candidate, "Helvetica-Bold", 8.5) > max_width:
                c.drawString(x, y_pos, line)
                y_pos -= line_height
                line = word
            else:
                line = candidate
        if line:
            c.drawString(x, y_pos, line)
            y_pos -= line_height
        return y_pos

    draw_logo(left, y, 0.62)
    c.setFillColor(blue)
    c.setFont("Helvetica-Bold", 23)
    c.drawRightString(right, y - 9, "TAX INVOICE")
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(right, y - 26, f"# {context.get('invoice_number') or ''}")

    y -= 44
    c.setStrokeColor(blue)
    c.setLineWidth(1.8)
    c.line(left, y, right, y)
    y -= 13
    c.setFillColor(dark)
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(left, y, company_name_full)
    y -= 14
    c.setFont("Helvetica", 9)
    for line in [
        company_address,
        f"Email: {company_email} | Contact: {company_contact}",
        f"PAN: {company_pan} | GST: {company_gst}",
    ]:
        if line.strip(" |"):
            c.drawString(left, y, line)
            y -= 10

    y -= 8
    c.setStrokeColor(colors.HexColor("#c7c7c7"))
    c.setLineWidth(0.8)
    c.line(left, y, right, y)
    y -= 18

    c.setFillColor(blue)
    c.setFont("Helvetica", 9)
    c.drawString(left, y, "Bill To:")
    c.setFillColor(dark)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(left, y - 13, client_name)
    c.setFont("Helvetica", 9)
    meta_x = width * 0.57
    bill_lines = [
        f"Full Address: {client_address}",
        f"PONO: {po_number}",
        f"PAN: {context.get('client_pan') or ''}",
        f"GST: {client_gst}",
        f"Place of Supply: {place_of_supply}",
    ]
    line_y = y - 25
    bill_max_width = meta_x - left - 18
    for line in bill_lines:
        line_y = draw_wrapped_text(line, left, line_y, bill_max_width)

    c.setFont("Helvetica", 9)
    c.drawString(meta_x, y, "Invoice Date:")
    c.drawString(meta_x, y - 36, "Due Date:")
    c.setFont("Helvetica-Bold", 8.5)
    c.drawRightString(right, y, str(context.get("invoice_date") or ""))
    c.drawRightString(right, y - 36, str(context.get("due_date") or ""))

    table_top = min(y - 84, line_y - 18)
    row_h = 20
    empty_h = 23
    total_h = 23
    col_widths = [13 * mm, 72 * mm, 27 * mm, 20 * mm, 29 * mm, 31 * mm]
    xs = [left]
    for col_width in col_widths:
        xs.append(xs[-1] + col_width)
    table_right = xs[-1]
    headers = ["S.No", "Item & Description", "HSN/SAC", "Qty", "Rate", "Amount"]

    c.setFillColor(blue)
    c.rect(left, table_top - row_h, table_right - left, row_h, fill=1, stroke=0)
    c.setStrokeColor(grid)
    c.setLineWidth(0.6)
    rows_count = max(1, len(table_items))
    table_bottom = table_top - row_h - (rows_count * row_h) - (2 * empty_h) - (4 * total_h)
    for x in xs:
        c.line(x, table_top, x, table_bottom)
    c.line(left, table_top, table_right, table_top)
    current_y = table_top - row_h
    c.line(left, current_y, table_right, current_y)

    c.setFillColor(colors.white)
    c.setFont("Helvetica", 9)
    for index, header in enumerate(headers):
        c.drawString(xs[index] + 3, table_top - 14, header)

    c.setFillColor(dark)
    c.setFont("Helvetica", 8.5)
    for row in table_items:
        next_y = current_y - row_h
        c.drawCentredString((xs[0] + xs[1]) / 2, current_y - 14, row[0])
        c.drawString(xs[1] + 4, current_y - 14, row[1][:44])
        c.drawCentredString((xs[2] + xs[3]) / 2, current_y - 14, row[2])
        c.drawCentredString((xs[3] + xs[4]) / 2, current_y - 14, row[3])
        c.drawRightString(xs[5] - 4, current_y - 14, row[4])
        c.drawRightString(xs[6] - 4, current_y - 14, row[5])
        c.line(left, next_y, table_right, next_y)
        current_y = next_y

    draw_logo(left + 33 * mm, current_y + 3, 1.38, alpha=0.035)
    for _ in range(2):
        current_y -= empty_h
        c.line(left, current_y, table_right, current_y)

    totals = [
        ("Sub Total", f"{subtotal:,.2f}", False),
        (f"CGST + SGST (Intra-State) ({gst_rate:.1f}%)", f"{gst_amount:,.2f}", False),
        ("Total", f"Rs.{total_amount:,.2f}", True),
        ("Balance Due", f"Rs.{balance_due:,.2f}", True),
    ]
    c.setFont("Helvetica-Bold", 9)
    for label, value, is_blue in totals:
        next_y = current_y - total_h
        c.line(left, next_y, table_right, next_y)
        c.setFillColor(blue if is_blue else dark)
        c.drawRightString(xs[5] - 4, current_y - 16, label)
        c.drawRightString(xs[6] - 4, current_y - 16, value)
        current_y = next_y

    y = current_y - 17
    c.setFillColor(blue)
    c.setFont("Helvetica", 9)
    c.drawString(left, y, f"AMOUNT IN WORDS: {amount_words}")
    y -= 22
    c.setFillColor(dark)
    c.setFont("Helvetica", 9)
    c.drawString(left, y, "Bank Details")
    c.setFont("Helvetica-Bold", 9)
    for line in [company_name_full, f"A/C No: {bank_account_no}", f"IFSC: {bank_ifsc}"]:
        y -= 10
        c.drawString(left, y, line)
    y -= 20
    c.setFont("Helvetica-Bold", 9)
    c.drawString(left, y, "Terms & Conditions")
    c.setFont("Helvetica-Bold", 9)
    c.drawString(left, y - 12, terms_and_conditions or "-")
    signature_display = signatory_name or "Murali Mohan"
    if signature_path.exists():
        c.drawImage(
            str(signature_path),
            right - 112,
            y - 31,
            width=96,
            height=28,
            mask="auto",
            preserveAspectRatio=True,
            anchor="c",
        )
    else:
        c.setFont("Times-Italic", 20)
        c.drawRightString(right, y - 27, signature_display)
    c.setFont("Helvetica-Bold", 8)
    c.drawRightString(right, y - 42, "Authorized Signature")
    c.save()
    buffer.seek(0)
    return buffer.read()

    items = context.get("items") or []
    rows = [[
        Paragraph("S.No", table_header_style),
        Paragraph("Item &amp; Description", table_header_style),
        Paragraph("HSN/SAC", table_header_style),
        Paragraph("Qty", table_header_style),
        Paragraph("Rate", table_header_style),
        Paragraph("Amount", table_header_style),
    ]]
    subtotal = 0.0
    if items:
        for index, item in enumerate(items, start=1):
            quantity = float(item.get("quantity") or 0)
            rate = float(item.get("rate") or 0)
            amount = item.get("amount")
            amount = float(amount) if amount is not None else quantity * rate
            subtotal += amount
            rows.append([
                Paragraph(str(index), body_style),
                Paragraph(_html(item.get("description", "")), body_style),
                Paragraph(_html(item.get("hsn_sac", "")), body_style),
                Paragraph(f"<nobr>{_html(quantity)}</nobr>", right_style),
                Paragraph(f"<nobr>{_money(rate)}</nobr>", right_style),
                Paragraph(f"<nobr>{_money(amount)}</nobr>", right_style),
            ])
    else:
        subtotal = float(context.get("total_amount") or 0)
        rows.append([
            Paragraph("1", body_style),
            Paragraph(
                _html(" | ".join(part for part in [
                    context.get("training_domain") or "",
                    context.get("training_dates") or "",
                    f"Duration: {context.get('duration')}" if context.get("duration") else "",
                    context.get("mode") or "",
                ] if part) or "Training Services"),
                body_style,
            ),
            Paragraph("", body_style),
            Paragraph(f"<nobr>{_html(context.get('duration') or 1)}</nobr>", right_style),
            Paragraph(f"<nobr>{_money(context.get('day_rate') or subtotal)}</nobr>", right_style),
            Paragraph(f"<nobr>{_money(subtotal)}</nobr>", right_style),
        ])

    gst_rate = float(context.get("gst_rate") or 0)
    gst_amount = subtotal * gst_rate / 100
    total_amount = subtotal + gst_amount
    balance_due = float(context.get("balance_due") if context.get("balance_due") is not None else total_amount)
    amount_words = _number_to_words(int(round(total_amount))) + " Rupees Only"

    item_table = Table(
        rows,
        colWidths=[12 * mm, 60 * mm, 17 * mm, 15 * mm, 24 * mm, 30 * mm],
        repeatRows=1,
    )
    item_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("LEADING", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
    ]))

    summary_rows = [
        ["Sub Total", _money(subtotal)],
        [f"CGST + SGST (Intra-State) ({gst_rate}%)", _money(gst_amount)],
        ["Total", _money(total_amount)],
        ["Balance Due", _money(balance_due)],
    ]
    summary_table = Table(summary_rows, colWidths=[55 * mm, 37 * mm], hAlign="RIGHT")
    summary_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#334155")),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, 2), (-1, 2), 1.2, colors.HexColor("#0f172a")),
        ("LINEABOVE", (0, 3), (-1, 3), 1.2, colors.HexColor("#0f172a")),
        ("FONTNAME", (0, 2), (-1, 3), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 2), (-1, 3), colors.HexColor("#0f172a")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))

    header_left = [
        Paragraph(company_name_full, title_style),
        Paragraph(company_address or company_name_short, body_style),
        Paragraph(f"Email: {company_email} | Contact: {company_contact}", body_style),
        Paragraph(f"PAN: {company_pan} | GST: {company_gst}", body_style),
    ]
    header_right = [
        Paragraph("TAX INVOICE", ParagraphStyle("InvoiceHeadRight", parent=title_style, alignment=TA_RIGHT)),
        Paragraph(f"# {_html(context.get('invoice_number'))}", ParagraphStyle("InvoiceNumberRight", parent=body_style, alignment=TA_RIGHT, fontName="Helvetica-Bold")),
        Paragraph(f"Invoice Date: {_html(context.get('invoice_date'))}", ParagraphStyle("InvoiceDateRight", parent=small_style, alignment=TA_RIGHT)),
        Paragraph(f"Due Date: {_html(context.get('due_date'))}", ParagraphStyle("DueDateRight", parent=small_style, alignment=TA_RIGHT)),
    ]
    top_table = Table([[header_left, header_right]], colWidths=[103 * mm, 63 * mm])
    top_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#cbd5e1")),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
    ]))

    bill_table = Table([
        [
            Paragraph("<b>Bill To</b>", label_style),
            Paragraph("<b>Reference</b>", label_style),
        ],
        [
            Paragraph(_html(client_name) or "-", body_style),
            Paragraph(_html(po_number) or "-", body_style),
        ],
        [
            Paragraph(_html(client_address) or "-", body_style),
            Paragraph(_html(client_gst) or "-", body_style),
        ],
        [
            Paragraph(f"Place of Supply: {_html(place_of_supply) or '-'}", body_style),
            Paragraph(f"Invoice #: {_html(context.get('invoice_number'))}", body_style),
        ],
    ], colWidths=[102 * mm, 64 * mm])
    bill_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#cbd5e1")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
        ("SPAN", (0, 1), (0, 2)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))

    def draw_watermark(canvas, doc_obj):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#0f172a"), alpha=0.09)
        canvas.translate(A4[0] / 2, A4[1] / 2)
        canvas.rotate(32)
        canvas.setFont("Helvetica-Bold", 38)
        canvas.drawCentredString(0, 0, company_name_full)
        canvas.restoreState()

    story = [
        top_table,
        Spacer(1, 8),
        bill_table,
        Spacer(1, 12),
        item_table,
        Spacer(1, 8),
        summary_table,
        Spacer(1, 10),
        Paragraph(f"AMOUNT IN WORDS: {amount_words}", ParagraphStyle("Words", parent=small_style, textColor=colors.HexColor("#1e3a8a"), fontName="Helvetica-Bold")),
        Spacer(1, 8),
        Paragraph("<b>Bank Details</b>", label_style),
        Paragraph(f"{_html(company_name_full)}<br/>A/C No: {_html(bank_account_no) or '-'}<br/>IFSC: {_html(bank_ifsc) or '-'}", body_style),
        Spacer(1, 6),
        Paragraph("<b>Terms &amp; Conditions</b>", label_style),
        Paragraph(_html(terms_and_conditions) or "-", body_style),
        Spacer(1, 12),
        Paragraph(f"<para alignment='right'><b>{_html(signatory_name)}</b><br/>Authorized Signature</para>", body_style),
    ]
    doc.build(story, onFirstPage=draw_watermark, onLaterPages=draw_watermark)
    buffer.seek(0)
    return buffer.read()


def _html_to_plain_text(html: str) -> str:
    text = re.sub(r"(?is)<!--.*?-->", "", html)
    text = re.sub(r"(?is)<(script|style|head|svg|noscript)\b[^>]*>.*?</\1>", "", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(td|th)>", "  ", text)
    text = re.sub(r"(?i)</(p|div|section|article|header|footer|tr|table|h[1-6]|li)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def _number_to_words(number: int) -> str:
    """Convert an integer number to English words for invoice totals."""
    if number == 0:
        return "Zero"

    units = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"]
    teens = ["Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
    scales = [(10000000, "Crore"), (100000, "Lakh"), (1000, "Thousand"), (100, "Hundred")]

    def _under_thousand(n: int) -> str:
        words = []
        if n >= 100:
            words.append(units[n // 100])
            words.append("Hundred")
            n %= 100
        if n >= 20:
            words.append(tens[n // 10])
            n %= 10
        elif n >= 10:
            words.append(teens[n - 10])
            n = 0
        if n > 0:
            words.append(units[n])
        return " ".join(words)

    parts = []
    for scale_value, scale_name in scales:
        if number >= scale_value:
            scale_count = number // scale_value
            parts.append(_under_thousand(scale_count))
            parts.append(scale_name)
            number %= scale_value
    if number > 0:
        parts.append(_under_thousand(number))
    return " ".join(part for part in parts if part)


def _html(value: Any) -> str:
    if value is None:
        return ""
    return escape(str(value), quote=True)


class PORequest(BaseModel):
    po_number: str = "PO-0001"
    date: str = ""
    vendor_name: str = ""
    client_name: str = ""
    client_email: str = ""
    client_billing_address: str = ""
    client_gstin: str = ""
    training_domain: str = ""
    training_dates: str = ""
    duration: str = ""
    mode: str = ""
    payment_terms: str = ""
    total_amount: float = 0.0
    items: list = []
    notes: Optional[str] = ""


@router.post("/purchase-order")
async def generate_purchase_order(
    payload: PORequest,
    format: str = "pdf",
):
    """Generate a Purchase Order as PDF or HTML."""
    context = payload.model_dump()
    html = _render_html_template(context)

    if format == "html":
        return Response(content=html, media_type="text/html")

    pdf_bytes = await _html_to_pdf(html, purchase_order_context=context)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={payload.po_number}.pdf"},
    )


class InvoiceRequest(BaseModel):
    invoice_number: str = "INV-0001"
    invoice_date: str = ""
    due_date: str = ""
    gst_number: str = ""
    vendor_name: str = ""
    company_name_short: str = ""
    company_name_full: str = ""
    company_address: str = ""
    company_email: str = ""
    company_contact: str = ""
    company_logo_url: Optional[str] = ""
    company_pan: str = ""
    company_gst: str = ""
    client_name: str = ""
    client_billing_address: str = ""
    client_address: str = ""
    client_po_number: str = ""
    client_po_date: str = ""
    client_gst: str = ""
    client_gstin: str = ""
    client_pan: str = ""
    training_domain: str = ""
    training_dates: str = ""
    duration: str = ""
    mode: str = ""
    day_rate: float = 0.0
    total_amount: float = 0.0
    gst_rate: float = 18.0
    place_of_supply: str = ""
    bank_account_no: str = ""
    bank_ifsc: str = ""
    payment_terms: Optional[str] = ""
    terms_and_conditions: Optional[str] = ""
    signatory_name: str = ""
    balance_due: Optional[float] = None
    notes: Optional[str] = ""
    items: list = []


@router.post("/invoice")
async def generate_invoice(
    payload: InvoiceRequest,
    format: str = "pdf",
):
    context = payload.model_dump()
    items_rows = ""
    subtotal = 0.0
    for i, item in enumerate(context.get("items") or [], 1):
        qty = item.get("quantity", 1)
        rate = item.get("rate", 0.0)
        amount = item.get("amount") if item.get("amount") is not None else qty * rate
        subtotal += amount
        items_rows += (
            f"<tr>"
            f"<td>{i}</td>"
            f"<td>{_html(item.get('description', ''))}</td>"
            f"<td>{_html(item.get('hsn_sac', ''))}</td>"
            f"<td class='num'>{_html(qty)}</td>"
            f"<td class='num'>{rate:,.2f}</td>"
            f"<td class='num'>{amount:,.2f}</td>"
            f"</tr>"
        )
    if not items_rows:
        subtotal = float(context.get("total_amount") or 0.0)
        description_parts = [
            context.get("training_domain"),
            context.get("training_dates"),
            f"Duration: {context.get('duration')}" if context.get("duration") else "",
            context.get("mode"),
        ]
        item_description = " | ".join(str(part) for part in description_parts if part) or "Training Services"
        quantity = context.get("duration") or 1
        rate = context.get("day_rate") or subtotal
        items_rows = (
            "<tr>"
            "<td>1</td>"
            f"<td>{_html(item_description)}</td>"
            "<td></td>"
            f"<td class='num'>{_html(quantity)}</td>"
            f"<td class='num'>{float(rate or 0):,.2f}</td>"
            f"<td class='num'>{subtotal:,.2f}</td>"
            "</tr>"
        )

    gst_rate = context.get("gst_rate", 18.0) or 0.0
    gst_amount = subtotal * gst_rate / 100
    total_amount = subtotal + gst_amount
    balance_due = context.get("balance_due")
    if balance_due is None:
        balance_due = total_amount

    amount_words = _number_to_words(int(round(total_amount))) + " Rupees Only"
    company_name_short = context.get("company_name_short") or "BEULIX"
    company_name_full = context.get("company_name_full") or "BEULIX SOLUTIONS PRIVATE LIMITED"
    company_address = context.get("company_address") or ""
    company_email = context.get("company_email") or ""
    company_contact = context.get("company_contact") or ""
    company_logo_url = context.get("company_logo_url") or ""
    company_pan = context.get("company_pan") or ""
    company_gst = context.get("company_gst") or context.get("gst_number") or ""
    embedded_logo_url = _asset_data_uri("beulix_logo.png")
    embedded_signature_url = _asset_data_uri("murali_signature.png")
    effective_logo_url = company_logo_url or embedded_logo_url
    company_logo_html = (
        f'<img src="{_html(effective_logo_url)}" class="company-logo-image" alt="Company logo" />'
        if effective_logo_url
        else _beulix_logo_html("beulix-logo beulix-logo-top")
    )
    watermark_logo_html = (
        f'<img src="{_html(effective_logo_url)}" class="invoice-watermark-image" alt="Watermark logo" />'
        if effective_logo_url
        else _beulix_logo_html("beulix-logo beulix-logo-watermark")
    )
    client_address = context.get("client_address") or context.get("client_billing_address") or ""
    po_number = context.get("po_number") or context.get("client_po_number") or ""
    place_of_supply = context.get("place_of_supply") or ""
    bank_account_no = context.get("bank_account_no") or ""
    bank_ifsc = context.get("bank_ifsc") or ""
    terms_and_conditions = context.get("terms_and_conditions") or context.get("payment_terms") or ""
    signatory_name = context.get("signatory_name") or "Authorized Signatory"
    client_gst = context.get("client_gst") or context.get("client_gstin") or ""
    signature_html = (
        f'<img src="{_html(embedded_signature_url)}" class="signature-image" alt="Authorized signature" />'
        if embedded_signature_url
        else f'<div class="signature-line">{_html(signatory_name)}</div>'
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Invoice {context.get('invoice_number')}</title>
<style>
  * {{ box-sizing: border-box; }}
  @page {{
    size: A4;
    margin: 11mm 12mm;
  }}
  body {{
    font-family: Arial, Helvetica, sans-serif;
    color: #000;
    margin: 0;
    padding: 0;
    font-size: 12.8px;
    font-weight: 500;
    background: #ffffff;
  }}
  .invoice-box {{
    width: 100%;
    min-height: 271mm;
    margin: 0 auto;
    position: relative;
    padding: 0;
  }}
  .invoice-watermark-image {{
    max-width: 430px;
    max-height: 120px;
    opacity: 0.07;
    object-fit: contain;
  }}
  .invoice-box > * {{ position: relative; z-index: 1; }}
  .header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    padding-bottom: 12px;
    border-bottom: 2px solid #0f172a;
  }}
  .company-logo {{
    display: flex;
    align-items: center;
    gap: 14px;
    font-weight: 900;
    color: #0f172a;
    line-height: 1;
  }}
  .company-logo-image {{
    width: 172px;
    height: auto;
    object-fit: contain;
    display: block;
  }}
  .beulix-logo {{
    position: relative;
    display: inline-block;
    line-height: 1;
    text-transform: uppercase;
    white-space: nowrap;
  }}
  .beulix-logo .logo-beuli {{
    color: #2c3191;
    font-size: 24px;
    font-weight: 900;
  }}
  .beulix-logo .logo-x {{
    color: #18a8e0;
    font-size: 54px;
    font-weight: 900;
    margin: 0 -8px;
    position: relative;
    top: 10px;
  }}
  .beulix-logo .logo-solutions {{
    color: #2c3191;
    font-size: 24px;
    font-weight: 900;
  }}
  .beulix-logo .logo-private {{
    display: block;
    margin-left: 112px;
    font-size: 11px;
    font-weight: 900;
    letter-spacing: 1.4px;
    color: #333;
  }}
  .beulix-logo-watermark {{
    transform: scale(1.3);
    opacity: 0.06;
  }}
  .invoice-title {{
    text-align: right;
    padding-top: 2px;
  }}
  .invoice-title h1 {{
    margin: 0;
    font-size: 26px;
    color: #1f4e84;
    letter-spacing: 0;
    line-height: 1;
  }}
  .invoice-title .invoice-no {{
    color: #1f4e84;
    font-weight: 900;
    margin-top: 8px;
  }}
  .company-info {{
    margin-top: 13px;
  }}
  .company-info h2 {{
    font-size: 15px;
    font-weight: 900;
    margin: 0 0 6px 0;
  }}
  .company-info p {{
    margin: 1px 0;
    color: #000;
    font-weight: 500;
  }}
  .bill-section {{
    display: flex;
    justify-content: space-between;
    gap: 18px;
    margin-top: 18px;
  }}
  .bill-to {{
    width: 54%;
  }}
  .bill-to .label {{
    color: #1f4e84;
    font-weight: 700;
    margin-bottom: 6px;
  }}
  .bill-to p {{ margin: 1px 0; color: #000; font-weight: 500; }}
  .bill-to strong {{ color: #000; font-size: 15px; font-weight: 900; }}
  .dates {{
    width: 38%;
    padding-top: 18px;
  }}
  .dates .row {{
    display: flex;
    justify-content: space-between;
    gap: 18px;
    padding: 2px 0;
  }}
  .dates .label {{ color: #000; font-weight: 900; }}
  table.items {{
    width: 100%;
    border-collapse: collapse;
    margin-top: 18px;
    font-size: 12.8px;
    position: relative;
  }}
  table.items thead th {{
    background: #1f4e84;
    color: #fff;
    padding: 12px 9px;
    text-align: left;
    font-weight: 900;
  }}
  table.items thead th.num,
  table.items tbody td.num {{
    text-align: right;
  }}
  table.items tbody td {{
    padding: 11px 8px;
    border: 1px solid #bfbfbf;
    font-weight: 700;
    color: #000;
  }}
  table.items tbody tr.empty td {{
    height: 34px;
  }}
  table.items tbody tr.watermark-row td {{
    height: 36px;
    padding: 0;
    text-align: center;
    vertical-align: middle;
  }}
  .table-watermark {{
    display: flex;
    align-items: center;
    justify-content: center;
    height: 36px;
    opacity: 0.07;
  }}
  .table-watermark .invoice-watermark-image {{
    max-width: 440px;
    max-height: 80px;
    opacity: 1;
  }}
  .table-watermark .beulix-logo-watermark {{
    transform: scale(1.45);
  }}
  .totals {{
    margin-top: 0;
    display: flex;
    justify-content: flex-end;
  }}
  .totals table {{
    width: 36%;
    border-collapse: collapse;
    background: #fff;
  }}
  .totals td {{
    padding: 9px 8px;
    text-align: right;
    font-weight: 700;
    border: 1px solid #bfbfbf;
  }}
  .totals tr.grand-total td {{
    font-weight: 900;
    color: #1f4e84;
  }}
  .totals tr.balance-due td {{
    font-weight: 900;
    color: #1f4e84;
  }}
  .amount-words {{
    margin-top: 16px;
    color: #1f4e84;
    font-size: 12px;
    font-weight: 900;
  }}
  .footer {{
    display: flex;
    justify-content: space-between;
    gap: 16px;
    margin-top: 18px;
    padding-top: 12px;
  }}
  .footer .col {{
    flex: 1;
  }}
  .footer h4 {{
    margin: 0 0 6px 0;
    color: #000;
    font-size: 14px;
    font-weight: 700;
  }}
  .footer p {{ margin: 1px 0; color: #000; font-weight: 500; }}
  .signature-block {{
    text-align: right;
    max-width: 220px;
    flex: 0 0 220px;
  }}
  .signature-line {{
    font-family: "Brush Script MT", cursive;
    font-size: 25px;
    color: #000;
    margin-bottom: 4px;
  }}
  .signature-image {{
    width: 96px;
    height: auto;
    margin-bottom: 5px;
  }}
  .signature-rule {{
    border-top: 1px solid #000;
    margin-top: 4px;
    padding-top: 4px;
    font-size: 11px;
    color: #333;
    text-align: center;
  }}
</style>
</head>
<body>
  <div class="invoice-box">
    <div class="header">
      <div class="company-logo">
        {company_logo_html}
      </div>
      <div class="invoice-title">
        <h1>TAX INVOICE</h1>
        <div class="invoice-no"># {_html(context.get('invoice_number'))}</div>
      </div>
    </div>
    <div class="company-info">
      <h2>{_html(company_name_full)}</h2>
      <p>{_html(company_address)}</p>
      <p>Email: {_html(company_email)} | Contact: {_html(company_contact)}</p>
      <p>PAN: {_html(company_pan)} | GST: {_html(company_gst)}</p>
    </div>
    <div class="bill-section">
      <div class="bill-to">
        <div class="label">Bill To:</div>
        <p><strong>{_html(context.get('client_name'))}</strong></p>
        <p>Full Address: {_html(client_address)}</p>
        <p>PONO: {_html(po_number)}</p>
        <p>PAN: {_html(context.get('client_pan'))}</p>
        <p>GST: {_html(client_gst)}</p>
        <p>Place of Supply: {_html(place_of_supply)}</p>
      </div>
      <div class="dates">
        <div class="row"><span class="label">Invoice Date:</span><span>{_html(context.get('invoice_date'))}</span></div>
        <div class="row"><span class="label">Due Date:</span><span>{_html(context.get('due_date'))}</span></div>
      </div>
    </div>
    <table class="items">
      <thead>
        <tr>
          <th>S.No</th>
          <th>Item &amp; Description</th>
          <th>HSN/SAC</th>
          <th class="num">Qty</th>
          <th class="num">Rate</th>
          <th class="num">Amount</th>
        </tr>
      </thead>
      <tbody>
        {items_rows}
        <tr class="watermark-row"><td colspan="6"><div class="table-watermark">{watermark_logo_html}</div></td></tr>
        <tr class="empty"><td colspan="6"></td></tr>
      </tbody>
    </table>
    <div class="totals">
      <table>
        <tr>
          <td colspan="5">Sub Total</td>
          <td>{subtotal:,.2f}</td>
        </tr>
        <tr>
          <td colspan="5">CGST + SGST (Intra-State) ({gst_rate}%)</td>
          <td>{gst_amount:,.2f}</td>
        </tr>
        <tr class="grand-total">
          <td colspan="5">Total</td>
          <td>Rs.{total_amount:,.2f}</td>
        </tr>
        <tr class="balance-due">
          <td colspan="5">Balance Due</td>
          <td>Rs.{balance_due:,.2f}</td>
        </tr>
      </table>
    </div>
    <div class="amount-words">AMOUNT IN WORDS: {amount_words}</div>
    <div class="footer">
      <div class="col">
        <h4>Bank Details:</h4>
        <p>{_html(company_name_full)}</p>
        <p>A/C No: {_html(bank_account_no)}</p>
        <p>IFSC: {_html(bank_ifsc)}</p>
      </div>
      <div class="col">
        <h4>Terms &amp; Conditions:</h4>
        <p>{_html(terms_and_conditions)}</p>
      </div>
      <div class="signature-block">
        {signature_html}
        <div class="signature-rule">Authorized Signature</div>
      </div>
    </div>
  </div>
</body>
</html>"""

    if format == "html":
        return Response(content=html, media_type="text/html")

    try:
        from weasyprint import HTML
        loop = asyncio.get_event_loop()
        pdf_bytes = await loop.run_in_executor(None, lambda: HTML(string=html).write_pdf())
    except Exception:
        pdf_bytes = _render_invoice_pdf_reportlab(context)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={payload.invoice_number}.pdf"},
    )


@router.post("/html-to-pdf")
async def html_to_pdf_endpoint(
    html_content: Optional[str] = Body(None, media_type="text/plain"),
    html_content_query: Optional[str] = Query(None, alias="html_content"),
    filename: Optional[str] = Query("document.pdf"),
):
    """Convert raw HTML to PDF."""
    html_input = html_content or html_content_query
    if not html_input:
        raise HTTPException(422, "Field required: html_content")
    pdf_bytes = await _html_to_pdf(html_input)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
