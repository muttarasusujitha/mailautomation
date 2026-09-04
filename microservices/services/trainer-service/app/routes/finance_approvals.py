"""Separate finance approval queue for client PO and invoice requests."""
import base64
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.config import get_settings
from shared.database.service import get_db

router = APIRouter()
settings = get_settings()


class FinanceApproveRequest(BaseModel):
    client_name: str
    client_email: str
    po_number: str
    po_date: str = ""
    total_amount: float
    gst_rate: float = 18.0
    billing_address: str = ""
    gstin: str = ""
    payment_terms: str = ""
    description: str = "Professional services"
    due_date: str = ""


class FinanceRejectRequest(BaseModel):
    reason: str


@router.get("/approvals")
async def list_finance_approvals(db: AsyncIOMotorDatabase = Depends(get_db)):
    rows = await db["finance_approvals"].find({}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"approvals": rows, "pending": sum(1 for row in rows if row.get("status") == "pending_human_approval")}


@router.post("/approvals/{finance_id}/reject")
async def reject_finance_approval(finance_id: str, payload: FinanceRejectRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    result = await db["finance_approvals"].update_one(
        {"finance_id": finance_id, "status": "pending_human_approval"},
        {"$set": {"status": "rejected", "rejection_reason": payload.reason, "reviewed_at": datetime.utcnow(), "updated_at": datetime.utcnow()}},
    )
    if not result.modified_count:
        raise HTTPException(404, "Pending finance approval not found")
    return {"success": True, "finance_id": finance_id, "status": "rejected"}


@router.post("/approvals/{finance_id}/approve-send")
async def approve_and_send_invoice(finance_id: str, payload: FinanceApproveRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    # Atomically claim the approval before creating documents or sending mail.
    # A duplicate click can therefore never create two invoices.
    claimed = await db["finance_approvals"].update_one(
        {"finance_id": finance_id, "status": "pending_human_approval"},
        {"$set": {"status": "processing_invoice", "updated_at": datetime.utcnow()}},
    )
    if not claimed.modified_count:
        raise HTTPException(404, "Pending finance approval not found")
    approval = await db["finance_approvals"].find_one({"finance_id": finance_id}, {"_id": 0}) or {}
    if payload.total_amount <= 0:
        raise HTTPException(400, "Approved PO amount must be greater than zero")
    now = datetime.utcnow()
    po_id, invoice_id = f"PO-{uuid.uuid4().hex[:10].upper()}", f"INV-{uuid.uuid4().hex[:10].upper()}"
    item = {"description": payload.description, "quantity": 1, "rate": payload.total_amount, "amount": payload.total_amount}
    gst_amount = round(payload.total_amount * payload.gst_rate / 100, 2)
    grand_total = round(payload.total_amount + gst_amount, 2)
    po = {"po_id": po_id, "po_number": payload.po_number, "client_po_number": payload.po_number, "client_po_date": payload.po_date, "client_name": payload.client_name, "client_email": payload.client_email, "client_billing_address": payload.billing_address, "client_gstin": payload.gstin, "total_amount": payload.total_amount, "gst_rate": payload.gst_rate, "payment_terms": payload.payment_terms, "items": [item], "status": "approved", "source_finance_id": finance_id, "created_at": now, "updated_at": now}
    invoice = {"invoice_id": invoice_id, "invoice_number": invoice_id, "po_id": po_id, "client_name": payload.client_name, "client_email": payload.client_email, "client_billing_address": payload.billing_address, "client_address": payload.billing_address, "client_po_number": payload.po_number, "client_po_date": payload.po_date, "client_gstin": payload.gstin, "total_amount": payload.total_amount, "gst_rate": payload.gst_rate, "payment_terms": payload.payment_terms, "items": [item], "invoice_date": now.strftime("%d-%m-%Y"), "issue_date": now.strftime("%d-%m-%Y"), "due_date": payload.due_date, "commercials": {"subtotal": payload.total_amount, "gst_rate": payload.gst_rate, "gst_amount": gst_amount, "grand_total": grand_total}, "balance_due": grand_total, "status": "draft", "source_finance_id": finance_id, "created_at": now, "updated_at": now}
    await db["purchase_orders"].insert_one(po)
    await db["invoices"].insert_one(invoice)
    doc_url, email_url = settings.DOCUMENT_SERVICE_URL.rstrip("/"), settings.EMAIL_SERVICE_URL.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            pdf = await client.post(f"{doc_url}/api/v1/documents/pdf/invoice", json=invoice)
            pdf.raise_for_status()
            mail = await client.post(f"{email_url}/api/v1/email/send", json={"to": payload.client_email, "subject": f"Invoice {invoice_id} - Clahan Technologies", "body": f"Dear {payload.client_name},\n\nPlease find the invoice attached against PO {payload.po_number}.\n\nRegards,\nClahan Technologies", "mail_type": "finance_invoice", "idempotency_key": f"finance-invoice:{finance_id}", "attachments": [{"filename": f"{invoice_id}.pdf", "content_base64": base64.b64encode(pdf.content).decode(), "subtype": "pdf"}]})
            mail.raise_for_status()
    except Exception as exc:
        await db["finance_approvals"].update_one({"finance_id": finance_id}, {"$set": {"status": "approved_invoice_send_failed", "error": str(exc), "updated_at": datetime.utcnow()}})
        raise HTTPException(502, f"Invoice created but email failed: {exc}")
    await db["invoices"].update_one({"invoice_id": invoice_id}, {"$set": {"status": "sent", "sent_to": payload.client_email, "sent_at": datetime.utcnow()}})
    await db["finance_approvals"].update_one({"finance_id": finance_id}, {"$set": {"status": "invoice_sent", "po_id": po_id, "invoice_id": invoice_id, "reviewed_at": datetime.utcnow(), "updated_at": datetime.utcnow()}})
    return {"success": True, "finance_id": finance_id, "po_id": po_id, "invoice_id": invoice_id, "status": "invoice_sent"}
