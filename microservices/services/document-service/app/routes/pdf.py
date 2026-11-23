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
    from app.commercial_documents import render_html
    return render_html(context, "po")


def _render_purchase_order_pdf_reportlab(context: Dict[str, Any]) -> bytes:
    from app.commercial_documents import render_pdf
    return render_pdf(context, "po")


async def _html_to_pdf(html: str, purchase_order_context: Optional[Dict[str, Any]] = None) -> bytes:
    """Render commercial records consistently; convert generic HTML separately."""
    if purchase_order_context is not None:
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(_render_purchase_order_pdf_reportlab, purchase_order_context)
    try:
        from weasyprint import HTML
        loop = asyncio.get_event_loop()
        pdf_bytes = await loop.run_in_executor(None, lambda: HTML(string=html).write_pdf())
        return pdf_bytes
    except Exception as exc:
        # If WeasyPrint fails (commonly due to missing native libs on Windows), fall back to ReportLab.
        # Apart from purchase orders, the fallback is plain text without the designed layout, so record why.
        logger.warning("WeasyPrint could not render the PDF; using the ReportLab fallback", exc_info=True)
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
    from app.commercial_documents import render_pdf
    return render_pdf(context, "invoice")


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
    vendor_address: str = ""
    vendor_email: str = ""
    vendor_contact: str = ""
    vendor_pan: str = ""
    vendor_gst: str = ""
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
    gst_rate: float = 0.0
    company_name: str = ""
    company_address: str = ""
    items: list = []
    notes: Optional[str] = ""


@router.post("/purchase-order")
async def generate_purchase_order(
    payload: PORequest,
    format: str = "pdf",
):
    """Generate a Purchase Order as PDF or HTML."""
    context = payload.model_dump()
    from app.commercial_documents import prepare
    try:
        context = prepare(context)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
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
    tax_type: str = ""
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
    from app.commercial_documents import prepare, render_html, render_pdf
    try:
        context = prepare(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if format == "html":
        return Response(content=render_html(context, "invoice"), media_type="text/html")
    from starlette.concurrency import run_in_threadpool
    content = await run_in_threadpool(render_pdf, context, "invoice")
    return Response(content=content, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={payload.invoice_number}.pdf"})


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
