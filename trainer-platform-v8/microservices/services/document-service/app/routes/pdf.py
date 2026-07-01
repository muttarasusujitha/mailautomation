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
