"""Invoice routes - download PDF and send by email."""
import logging
from datetime import datetime
from typing import Optional

import httpx
import base64
from fastapi import APIRouter, Depends, HTTPException, Response
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.config import get_settings
from app.database import get_db

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()

DOC_SVC = settings.DOCUMENT_SERVICE_URL.rstrip("/")
EMAIL_SVC = settings.EMAIL_SERVICE_URL.rstrip("/")


class InvoiceSendRequest(BaseModel):
    to_email: Optional[str] = ""
    subject: Optional[str] = ""
    body: Optional[str] = ""


@router.get("/{invoice_id}/download")
async def download_invoice(invoice_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    doc = await db["invoices"].find_one({"invoice_id": invoice_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Invoice not found")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{DOC_SVC}/api/v1/documents/pdf/invoice",
                json={
                    "invoice_number": doc.get("invoice_number", invoice_id),
                    "invoice_date": doc.get("invoice_date", ""),
                    "due_date": doc.get("due_date", ""),
                    "gst_number": doc.get("gst_number", ""),
                    "vendor_name": doc.get("vendor_name", ""),
                    "company_name_short": doc.get("company_name_short", ""),
                    "company_name_full": doc.get("company_name_full", ""),
                    "company_address": doc.get("company_address", ""),
                    "company_email": doc.get("company_email", ""),
                    "company_contact": doc.get("company_contact", ""),
                    "company_pan": doc.get("company_pan", ""),
                    "company_gst": doc.get("company_gst", ""),
                    "client_name": doc.get("client_name", ""),
                    "client_billing_address": doc.get("client_billing_address", ""),
                    "client_address": doc.get("client_address", ""),
                    "client_po_number": doc.get("client_po_number", ""),
                    "client_po_date": doc.get("client_po_date", ""),
                    "client_gstin": doc.get("client_gstin", ""),
                    "client_gst": doc.get("client_gstin", ""),
                    "client_pan": doc.get("client_pan", ""),
                    "training_domain": doc.get("training_domain", ""),
                    "training_dates": doc.get("training_dates", ""),
                    "duration": doc.get("duration", ""),
                    "mode": doc.get("mode", ""),
                    "day_rate": doc.get("day_rate", 0.0),
                    "total_amount": doc.get("total_amount", 0.0),
                    "gst_rate": doc.get("gst_rate", 18.0),
                    "place_of_supply": doc.get("place_of_supply", ""),
                    "bank_account_no": doc.get("bank_account_no", ""),
                    "bank_ifsc": doc.get("bank_ifsc", ""),
                    "payment_terms": doc.get("payment_terms", ""),
                    "terms_and_conditions": doc.get("terms_and_conditions", ""),
                    "signatory_name": doc.get("signatory_name", ""),
                    "balance_due": doc.get("balance_due"),
                    "notes": doc.get("notes", ""),
                    "items": doc.get("items", []),
                },
            )
        if response.status_code >= 400:
            raise HTTPException(502, f"Document service error: {response.text[:200]}")
        return Response(
            content=response.content,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={invoice_id}.pdf"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc


@router.post("/{invoice_id}/send")
async def send_invoice(
    invoice_id: str,
    payload: InvoiceSendRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    doc = await db["invoices"].find_one({"invoice_id": invoice_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Invoice not found")

    req = await db["requirements"].find_one(
        {"requirement_id": doc.get("requirement_id")}, {"_id": 0}
    ) or {}
    to_email = payload.to_email or doc.get("client_email") or req.get("client_email") or ""
    if not to_email:
        raise HTTPException(400, "to_email is required")

    invoice_number = doc.get("invoice_number") or invoice_id
    subject = payload.subject or f"Invoice {invoice_number} - TrainerSync"
    body = payload.body or (
        f"Dear Client,\n\n"
        f"Please find your invoice {invoice_number} attached.\n\n"
        "Regards,\nTrainerSync Team"
    )

    try:
        # generate invoice PDF and attach to email
        attachment_payload = None
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{DOC_SVC}/api/v1/documents/pdf/invoice",
                    json={
                        "invoice_number": doc.get("invoice_number", invoice_id),
                        "invoice_date": doc.get("invoice_date", ""),
                        "due_date": doc.get("due_date", ""),
                        "gst_number": doc.get("gst_number", ""),
                        "vendor_name": doc.get("vendor_name", ""),
                        "company_name_short": doc.get("company_name_short", ""),
                        "company_name_full": doc.get("company_name_full", ""),
                        "company_address": doc.get("company_address", ""),
                        "company_email": doc.get("company_email", ""),
                        "company_contact": doc.get("company_contact", ""),
                        "company_pan": doc.get("company_pan", ""),
                        "company_gst": doc.get("company_gst", ""),
                        "client_name": doc.get("client_name", ""),
                        "client_billing_address": doc.get("client_billing_address", ""),
                        "client_address": doc.get("client_address", ""),
                        "client_po_number": doc.get("client_po_number", ""),
                        "client_po_date": doc.get("client_po_date", ""),
                        "client_gstin": doc.get("client_gstin", ""),
                        "client_gst": doc.get("client_gstin", ""),
                        "client_pan": doc.get("client_pan", ""),
                        "training_domain": doc.get("training_domain", ""),
                        "training_dates": doc.get("training_dates", ""),
                        "duration": doc.get("duration", ""),
                        "mode": doc.get("mode", ""),
                        "day_rate": doc.get("day_rate", 0.0),
                        "total_amount": doc.get("total_amount", 0.0),
                        "gst_rate": doc.get("gst_rate", 18.0),
                        "place_of_supply": doc.get("place_of_supply", ""),
                        "bank_account_no": doc.get("bank_account_no", ""),
                        "bank_ifsc": doc.get("bank_ifsc", ""),
                        "payment_terms": doc.get("payment_terms", ""),
                        "terms_and_conditions": doc.get("terms_and_conditions", ""),
                        "signatory_name": doc.get("signatory_name", ""),
                        "balance_due": doc.get("balance_due"),
                        "notes": doc.get("notes", ""),
                        "items": doc.get("items", []),
                    },
                )
            if response.status_code == 200 and response.content:
                attachment_payload = [{
                    "filename": f"{invoice_id}.pdf",
                    "content_base64": base64.b64encode(response.content).decode(),
                    "subtype": "pdf",
                }]
        except Exception:
            logger.exception("Failed to generate invoice PDF for attachment")

        async with httpx.AsyncClient(timeout=30) as client:
            email_json = {
                "to": to_email,
                "subject": subject,
                "body": body,
                "mail_type": "invoice",
                "requirement_id": doc.get("requirement_id"),
            }
            if attachment_payload:
                email_json["attachments"] = attachment_payload
            response = await client.post(f"{EMAIL_SVC}/api/v1/email/send", json=email_json)
        if response.status_code >= 400:
            raise HTTPException(502, f"Email service error: {response.text[:200]}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc

    now = datetime.utcnow()
    await db["invoices"].update_one(
        {"invoice_id": invoice_id},
        {"$set": {"status": "sent", "sent_to": to_email, "sent_at": now, "updated_at": now}},
    )
    if doc.get("requirement_id"):
        await db["requirements"].update_one(
            {"requirement_id": doc.get("requirement_id")},
            {"$set": {
                "invoice_status": "sent",
                "client_po_status": "invoice_sent",
                "updated_at": now,
            }},
        )
    invoice = await db["invoices"].find_one({"invoice_id": invoice_id}, {"_id": 0})
    return {"success": True, "invoice_id": invoice_id, "sent_to": to_email, "invoice": invoice}
