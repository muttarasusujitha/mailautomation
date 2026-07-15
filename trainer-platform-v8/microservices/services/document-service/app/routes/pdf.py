"""PDF generation — Purchase Orders and generic documents."""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, Body, Query
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
    due_date: str = ""
    gst_number: str = ""
    vendor_name: str = ""
    company_name_short: str = ""
    company_name_full: str = ""
    company_address: str = ""
    company_email: str = ""
    company_contact: str = ""
    company_pan: str = ""
    company_gst: str = ""
    client_name: str = ""
    client_billing_address: str = ""
    client_address: str = ""
    client_po_number: str = ""
    client_po_date: str = ""
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
            f"<td>{item.get('description', '')}</td>"
            f"<td>{item.get('hsn_sac', '')}</td>"
            f"<td class='num'>{qty}</td>"
            f"<td class='num'>{rate:,.2f}</td>"
            f"<td class='num'>{amount:,.2f}</td>"
            f"</tr>"
        )

    gst_rate = context.get("gst_rate", 18.0) or 0.0
    gst_amount = subtotal * gst_rate / 100
    total_amount = subtotal + gst_amount
    balance_due = context.get("balance_due")
    if balance_due is None:
        balance_due = total_amount

    amount_words = _number_to_words(int(round(total_amount))) + " Rupees Only"
    company_name_short = context.get("company_name_short") or context.get("vendor_name") or "Company"
    company_name_full = context.get("company_name_full") or company_name_short
    company_address = context.get("company_address") or ""
    company_email = context.get("company_email") or ""
    company_contact = context.get("company_contact") or ""
    company_pan = context.get("company_pan") or ""
    company_gst = context.get("company_gst") or context.get("gst_number") or ""
    client_address = context.get("client_address") or context.get("client_billing_address") or ""
    po_number = context.get("po_number") or context.get("client_po_number") or ""
    place_of_supply = context.get("place_of_supply") or ""
    bank_account_no = context.get("bank_account_no") or ""
    bank_ifsc = context.get("bank_ifsc") or ""
    terms_and_conditions = context.get("terms_and_conditions") or context.get("payment_terms") or ""
    signatory_name = context.get("signatory_name") or "Authorized Signatory"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Invoice {context.get('invoice_number')}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    font-family: Arial, Helvetica, sans-serif;
    color: #0f172a;
    margin: 0;
    padding: 40px;
    font-size: 13px;
    background: #f8fafc;
  }}
  .invoice-box {{
    max-width: 900px;
    margin: 0 auto;
    background: #ffffff;
    padding: 32px;
    border-radius: 16px;
    box-shadow: 0 8px 30px rgba(15, 23, 42, 0.08);
  }}
  .header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 24px;
  }}
  .company-logo {{
    font-size: 20px;
    font-weight: 800;
    color: #172554;
    letter-spacing: 0.4px;
  }}
  .company-logo .accent {{ color: #f59e0b; }}
  .invoice-title {{ text-align: right; min-width: 220px; }}
  .invoice-title .tax-label {{ color: #1e40af; font-size: 14px; font-weight: 700; letter-spacing: 1px; }}
  .invoice-title .invoice-no {{ font-size: 18px; font-weight: 800; margin-top: 8px; color: #172554; }}
  .invoice-title .invoice-meta {{ margin-top: 12px; color: #334155; font-size: 13px; line-height: 1.6; }}
  .company-info {{ margin-top: 24px; }}
  .company-info h2 {{ font-size: 16px; margin: 0 0 6px 0; color: #172554; }}
  .company-info p {{ margin: 2px 0; color: #334155; font-size: 12.8px; }}
  .bill-section {{ display: flex; justify-content: space-between; gap: 24px; margin-top: 32px; }}
  .bill-to {{ width: 58%; background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 12px; padding: 22px; }}
  .bill-to .label {{ color: #0f172a; font-weight: 700; margin-bottom: 10px; display: block; }}
  .bill-to p {{ margin: 6px 0; color: #334155; font-size: 13px; }}
  .bill-to p span.label {{ display: inline-block; width: 80px; color: #64748b; }}
  .dates {{ width: 38%; display: grid; gap: 10px; align-content: start; }}
  .dates .row {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px 16px; }}
  .dates .row .label {{ display: block; color: #334155; font-weight: 700; margin-bottom: 6px; }}
  .dates .row .value {{ color: #0f172a; }}
  table.items {{ width: 100%; border-collapse: collapse; margin-top: 32px; }}
  table.items thead th {{
    background: #1e3a8a;
    color: #fff;
    padding: 14px 12px;
    text-align: left;
    font-weight: 700;
    font-size: 13px;
  }}
  table.items tbody td {{ padding: 14px 12px; border-bottom: 1px solid #e2e8f0; color: #334155; font-size: 13px; }}
  table.items tbody td.num {{ text-align: right; }}
  table.items tbody tr:last-child td {{ border-bottom: none; }}
  .totals {{ margin-top: 24px; }}
  .totals table {{ width: 100%; border-collapse: collapse; }}
  .totals td {{ padding: 10px 12px; text-align: right; font-size: 13px; color: #334155; }}
  .totals tr.grand-total td {{
    font-weight: 700;
    color: #0f172a;
    border-top: 2px solid #1e3a8a;
    font-size: 15px;
  }}
  .totals tr.balance-due td {{ font-weight: 700; color: #0f172a; }}
  .amount-words {{ margin-top: 20px; color: #1e3a8a; font-size: 12.5px; }}
  .footer {{ display: flex; justify-content: space-between; gap: 18px; margin-top: 32px; padding-top: 24px; border-top: 1px solid #e2e8f0; }}
  .footer .col {{ width: 32%; }}
  .footer h4 {{ margin: 0 0 8px 0; color: #1e3a8a; font-size: 13px; }}
  .footer p {{ margin: 4px 0; color: #334155; font-size: 12.8px; }}
  .signature-block {{ text-align: right; width: 32%; }}
  .signature-line {{ font-family: "Brush Script MT", cursive; font-size: 22px; color: #0f172a; margin-bottom: 4px; }}
  .signature-rule {{ border-top: 1px solid #334155; margin-top: 4px; padding-top: 4px; font-size: 11px; color: #334155; text-align: center; }}
</style>
</head>
<body>
  <div class="invoice-box">
    <div class="header">
      <div class="company-logo">
        {company_name_short} <span class="accent">SOLUTIONS</span>
      </div>
      <div class="invoice-title">
        <div class="tax-label">TAX INVOICE</div>
        <div class="invoice-no"># {context.get('invoice_number')}</div>
        <div class="invoice-meta">
          <div>Invoice Date: {context.get('invoice_date')}</div>
          <div>Due Date: {context.get('due_date')}</div>
          <div>GSTIN: {company_gst}</div>
        </div>
      </div>
    </div>
    <div class="company-info">
      <h2>{company_name_full}</h2>
      <p>{company_address}</p>
      <p>Email: {company_email} | Contact: {company_contact}</p>
      <p>PAN: {company_pan} | GST: {company_gst}</p>
    </div>
    <div class="bill-section">
      <div class="bill-to">
        <div class="label">Bill To</div>
        <p><strong>{context.get('client_name')}</strong></p>
        <p><span class="label">Full Address:</span> {client_address}</p>
        <p><span class="label">PONO:</span> {po_number}</p>
        <p><span class="label">PAN:</span> {context.get('client_pan')}</p>
        <p><span class="label">GST:</span> {context.get('client_gst')}</p>
        <p><span class="label">Place of Supply:</span> {place_of_supply}</p>
      </div>
      <div class="dates">
        <div class="row"><span class="label">Invoice Date</span><span class="value">{context.get('invoice_date')}</span></div>
        <div class="row"><span class="label">Due Date</span><span class="value">{context.get('due_date')}</span></div>
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
          <td>Rs:{total_amount:,.2f}</td>
        </tr>
        <tr class="balance-due">
          <td colspan="5">Balance Due</td>
          <td>Rs:{balance_due:,.2f}</td>
        </tr>
      </table>
    </div>
    <div class="amount-words">AMOUNT IN WORDS: {amount_words}</div>
    <div class="footer">
      <div class="col">
        <h4>Bank Details:</h4>
        <p>{company_name_full}</p>
        <p>A/C No: {bank_account_no}</p>
        <p>IFSC: {bank_ifsc}</p>
      </div>
      <div class="col">
        <h4>Terms &amp; Conditions:</h4>
        <p>{terms_and_conditions}</p>
      </div>
      <div class="signature-block">
        <div class="signature-line">{signatory_name}</div>
        <div class="signature-rule">Authorized Signature</div>
      </div>
    </div>
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
