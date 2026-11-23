"""Invoice routes - download PDF and send by email."""
import logging
import uuid
from datetime import datetime
from typing import Optional

import httpx
import base64
from fastapi import APIRouter, Depends, HTTPException, Response
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from app.config import get_settings
from shared.database.service import get_db
from shared.generation_mode import application_ai_enabled
from shared.document_amounts import calculate_document

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()

DOC_SVC = settings.DOCUMENT_SERVICE_URL.rstrip("/")
EMAIL_SVC = settings.EMAIL_SERVICE_URL.rstrip("/")


class InvoiceSendRequest(BaseModel):
    to_email: Optional[str] = ""
    subject: Optional[str] = ""
    body: Optional[str] = ""


class LabInvoiceRequest(BaseModel):
    lab_amount: float = Field(gt=0)
    gst_rate: float = Field(default=18, ge=0, le=100)
    due_date: str = ""
    invoice_number: str = ""


async def _lab_invoice_source(requirement_id: str, db):
    request = await db["lab_cost_requests"].find_one(
        {"requirement_id": requirement_id}, {"_id": 0},
    ) or {}
    requirement = await db["requirements"].find_one(
        {"requirement_id": requirement_id}, {"_id": 0},
    ) or {}
    source = request or requirement
    if not source:
        raise HTTPException(404, "Lab-cost request not found")
    return source


@router.get("/lab/{requirement_id}")
async def get_lab_invoice(requirement_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    invoice = await db["invoices"].find_one(
        {"invoice_kind": "lab", "lab_requirement_id": requirement_id}, {"_id": 0},
    )
    return {"invoice": invoice}


@router.post("/lab/{requirement_id}")
async def generate_lab_invoice(
    requirement_id: str,
    payload: LabInvoiceRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    existing = await db["invoices"].find_one(
        {"invoice_kind": "lab", "lab_requirement_id": requirement_id}, {"_id": 0},
    )
    if existing:
        return {"success": True, "already_generated": True, "invoice": existing}
    source = await _lab_invoice_source(requirement_id, db)
    client_email = str(source.get("client_email") or "").strip()
    if not client_email:
        raise HTTPException(422, "Client email is required before creating the lab invoice")
    course = source.get("technology_needed") or source.get("technology") or source.get("domain") or "Training"
    totals = calculate_document(
        [{"description": f"{course} lab services", "quantity": 1, "rate": payload.lab_amount}],
        gst_rate=payload.gst_rate,
    )
    now = datetime.utcnow()
    invoice_id = f"LINV-{uuid.uuid4().hex[:10].upper()}"
    invoice = {
        "invoice_id": invoice_id,
        "invoice_number": payload.invoice_number or invoice_id,
        "invoice_kind": "lab",
        "lab_requirement_id": requirement_id,
        "requirement_id": requirement_id,
        "client_name": source.get("client_name") or source.get("client_company") or "",
        "client_email": client_email,
        "client_billing_address": source.get("client_billing_address") or source.get("client_address") or "",
        "client_address": source.get("client_billing_address") or source.get("client_address") or "",
        "client_gstin": source.get("client_gstin") or "",
        "training_domain": course,
        "duration": str(source.get("duration_days") or ""),
        "mode": source.get("mode") or "",
        "total_amount": totals["subtotal"],
        "gst_rate": totals["gst_rate"],
        "items": totals["items"],
        "invoice_date": now.strftime("%d-%m-%Y"),
        "issue_date": now.strftime("%d-%m-%Y"),
        "due_date": payload.due_date,
        "commercials": totals,
        "balance_due": totals["grand_total"],
        "status": "draft",
        "created_at": now,
        "updated_at": now,
    }
    await db["invoices"].insert_one(invoice)
    invoice.pop("_id", None)
    return {"success": True, "invoice": invoice}


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
                    "tax_type": doc.get("tax_type", ""),
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

    # A sent invoice is final. Returning the recorded delivery avoids a
    # second physical invoice email when a user refreshes or double-clicks.
    if str(doc.get("status") or "").lower() == "sent":
        return {
            "success": True,
            "already_sent": True,
            "invoice_id": invoice_id,
            "sent_to": doc.get("sent_to"),
            "invoice": doc,
        }

    invoice_number = doc.get("invoice_number") or invoice_id
    subject = payload.subject or f"Invoice {invoice_number} - Clahan Technologies"
    client_name = str(doc.get("client_name") or "").strip()
    greeting = f"Hello {client_name}," if client_name and client_name.lower() not in {"client", "team"} else "Hello,"
    body = payload.body or (
        f"{greeting}\n\n"
        f"Please find the invoice {invoice_number} attached.\n\n"
        "Thanks and Regards,\nMurali Mohan M\nClahan Technologies"
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
                    "tax_type": doc.get("tax_type", ""),
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

        if not attachment_payload:
            raise HTTPException(502, "Invoice PDF generation failed; no email was sent")

        async with httpx.AsyncClient(timeout=30) as client:
            email_json = {
                "to": to_email,
                "subject": subject,
                "body": body,
                "mail_type": "invoice",
                "requirement_id": doc.get("requirement_id"),
                # email-service stores this key uniquely, protecting the
                # invoice against concurrent send requests as well.
                "idempotency_key": f"invoice:{invoice_id}:{to_email.strip().lower()}",
                "ai_generate": await application_ai_enabled(db),
                "ai_context": {
                    "workflow": "invoice",
                    "requirement_id": doc.get("requirement_id") or "",
                    "invoice_number": invoice_number,
                    "client_name": doc.get("client_name") or "",
                    "commercial": doc.get("balance_due") or doc.get("total_amount") or "",
                    "requested_action": "review the attached invoice",
                },
            }
            if attachment_payload:
                email_json["attachments"] = attachment_payload
            response = await client.post(f"{EMAIL_SVC}/api/v1/email/send", json=email_json)
        if response.status_code >= 400:
            raise HTTPException(502, f"Email service error: {response.text[:200]}")
        if response.json().get("success") is not True:
            raise HTTPException(502, "Invoice email delivery is not confirmed; retry later")
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
