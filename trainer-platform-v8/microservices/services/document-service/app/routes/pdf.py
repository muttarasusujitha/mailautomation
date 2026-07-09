"""PDF generation — Purchase Orders and generic documents."""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.database import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


def _render_html_template(context: Dict[str, Any]) -> str:
    """Build a basic Purchase Order HTML from context dict."""
    items_rows = ""
    total = 0.0
    for i, item in enumerate(context.get("items") or [], 1):
        desc = item.get("description", "")
        qty = item.get("quantity", 1)
        rate = item.get("rate", 0)
        amount = qty * rate
        total += amount
        items_rows += (
            f"<tr><td>{i}</td><td>{desc}</td><td>{qty}</td>"
            f"<td>{rate:,.2f}</td><td>{amount:,.2f}</td></tr>"
        )

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8">
<style>
  body {{ font-family: Arial, sans-serif; margin: 40px; color: #1e293b; }}
  h1 {{ color: #2563eb; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
  th {{ background: #2563eb; color: white; padding: 8px; text-align: left; }}
  td {{ padding: 8px; border-bottom: 1px solid #e2e8f0; }}
  .total {{ font-weight: bold; font-size: 1.1em; }}
  .header-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 30px; }}
  .label {{ color: #64748b; font-size: 0.85em; }}
</style>
</head>
<body>
<h1>PURCHASE ORDER</h1>
<div class="header-grid">
  <div>
    <p class="label">PO Number</p><p><b>{context.get('po_number', 'PO-XXXX')}</b></p>
    <p class="label">Date</p><p>{context.get('date', '')}</p>
  </div>
  <div>
    <p class="label">Vendor / Trainer</p><p><b>{context.get('vendor_name', '')}</b></p>
    <p class="label">Client</p><p>{context.get('client_name', '')}</p>
  </div>
</div>
<p><b>Training:</b> {context.get('training_domain', '')} | <b>Duration:</b> {context.get('duration', '')}</p>
<table>
  <tr><th>#</th><th>Description</th><th>Qty</th><th>Rate (INR)</th><th>Amount (INR)</th></tr>
  {items_rows}
  <tr class="total"><td colspan="4" style="text-align:right">Total</td><td>{total:,.2f}</td></tr>
</table>
<br><p>{context.get('notes', '')}</p>
</body></html>"""


async def _html_to_pdf(html: str) -> bytes:
    """Convert HTML to PDF bytes using weasyprint."""
    try:
        from weasyprint import HTML
        import asyncio
        loop = asyncio.get_event_loop()
        pdf_bytes = await loop.run_in_executor(None, lambda: HTML(string=html).write_pdf())
        return pdf_bytes
    except ImportError:
        raise HTTPException(503, "PDF generation requires weasyprint. Install it or use /html endpoint.")


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


class PORequest(BaseModel):
    po_number: str = "PO-0001"
    date: str = ""
    vendor_name: str = ""
    client_name: str = ""
    training_domain: str = ""
    duration: str = ""
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

    pdf_bytes = await _html_to_pdf(html)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={payload.po_number}.pdf"},
    )


class InvoiceRequest(BaseModel):
    invoice_number: str = "INV-0001"
    invoice_date: str = ""
    gst_number: str = ""
    vendor_name: str = ""
    client_name: str = ""
    client_billing_address: str = ""
    client_po_number: str = ""
    client_po_date: str = ""
    client_gstin: str = ""
    training_domain: str = ""
    training_dates: str = ""
    duration: str = ""
    mode: str = ""
    day_rate: float = 0.0
    total_amount: float = 0.0
    gst_rate: float = 18.0
    payment_terms: Optional[str] = ""
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
            f"<tr><td>{i}</td><td>{item.get('description', '')}</td>"
            f"<td>{item.get('hsn_sac', '')}</td><td>{qty}</td><td>{rate:,.2f}</td><td>{amount:,.2f}</td></tr>"
        )

    total = subtotal
    gst_rate = context.get("gst_rate", 18.0) or 0.0
    gst_amount = total * gst_rate / 100
    grand_total = total + gst_amount

    amount_words = _number_to_words(int(round(grand_total))) + " Rupees Only"
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset=\"UTF-8\">\n<style>
  body {{ font-family: Arial, sans-serif; margin: 40px; color: #1f2937; }}
  .header {{ display: flex; justify-content: space-between; align-items: flex-start; }}
  .brand {{ font-size: 18px; font-weight: bold; color: #0f172a; }}
  .tagline {{ color: #2563eb; font-size: 12px; margin-top: 4px; }}
  .invoice-title {{ font-size: 22px; font-weight: bold; color: #0f172a; }}
  .meta {{ text-align: right; }}
  .meta p {{ margin: 4px 0; }}
  .section {{ margin-top: 24px; }}
  .section h2 {{ font-size: 14px; letter-spacing: 0.08em; color: #475569; margin-bottom: 8px; }}
  .box {{ border: 1px solid #e2e8f0; padding: 16px; border-radius: 12px; background: #f8fafc; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 16px; }}
  th, td {{ padding: 10px 12px; border: 1px solid #e2e8f0; }}
  th {{ background: #2563eb; color: white; text-align: left; }}
  .right {{ text-align: right; }}
  .total-row td {{ font-weight: bold; }}
  .notes {{ margin-top: 18px; font-size: 12px; color: #475569; }}
</style>
</head>
<body>
<div class=\"header\">
  <div>
    <div class=\"brand\">BEULIX SOLUTIONS PRIVATE LIMITED</div>
    <div class=\"tagline\">TAX INVOICE</div>
  </div>
  <div class=\"meta\">
    <p><strong># {context.get('invoice_number')}</strong></p>
    <p>Invoice Date: {context.get('invoice_date')}</p>
    <p>GSTIN: {context.get('gst_number')}</p>
  </div>
</div>
<div class=\"section\">
  <div class=\"box\">
    <h2>Bill To</h2>
    <p><strong>{context.get('client_name')}</strong></p>
    <p>{context.get('client_billing_address')}</p>
    <p>GSTIN: {context.get('client_gstin')}</p>
    <p>PO No: {context.get('client_po_number')}</p>
    <p>PO Date: {context.get('client_po_date')}</p>
  </div>
</div>
<div class=\"section\">
  <table>
    <tr><th>S.No</th><th>Item & Description</th><th>HSN/SAC</th><th>Qty</th><th>Rate</th><th>Amount</th></tr>
    {items_rows}
    <tr class=\"total-row\"><td colspan=\"5\" class=\"right\">Sub Total</td><td>{subtotal:,.2f}</td></tr>
    <tr class=\"total-row\"><td colspan=\"5\" class=\"right\">CGST @ {gst_rate/2:.2f}%</td><td>{gst_amount/2:,.2f}</td></tr>
    <tr class=\"total-row\"><td colspan=\"5\" class=\"right\">SGST @ {gst_rate/2:.2f}%</td><td>{gst_amount/2:,.2f}</td></tr>
    <tr class=\"total-row\"><td colspan=\"5\" class=\"right\">Total</td><td>{grand_total:,.2f}</td></tr>
  </table>
</div>
<div class=\"notes\">
  <p><strong>Amount in words:</strong> {amount_words}</p>
  <p>{context.get('payment_terms')}</p>
  <p>{context.get('notes')}</p>
</div>
</body>
</html>"""

    if format == "html":
        return Response(content=html, media_type="text/html")

    pdf_bytes = await _html_to_pdf(html)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={payload.invoice_number}.pdf"},
    )


@router.post("/html-to-pdf")
async def html_to_pdf_endpoint(
    html_content: str,
    filename: Optional[str] = "document.pdf",
):
    """Convert raw HTML to PDF."""
    pdf_bytes = await _html_to_pdf(html_content)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
