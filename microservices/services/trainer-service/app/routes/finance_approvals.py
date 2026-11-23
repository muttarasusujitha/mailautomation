"""Separate finance approval queue for client PO and invoice requests."""
import base64
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
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
    if payload.total_amount <= 0:
        raise HTTPException(400, "Approved PO amount must be greater than zero")
    # Atomically claim the approval before creating documents or sending mail.
    # A duplicate click can therefore never create two invoices.
    claimed = await db["finance_approvals"].update_one(
        {"finance_id": finance_id, "status": "pending_human_approval"},
        {"$set": {"status": "processing_invoice", "updated_at": datetime.utcnow()}},
    )
    if not claimed.modified_count:
        raise HTTPException(404, "Pending finance approval not found")
    approval = await db["finance_approvals"].find_one({"finance_id": finance_id}, {"_id": 0}) or {}
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
            pdf = await client.post(f"{doc_url}/api/v1/documents/pdf/invoice", json=jsonable_encoder({key: value for key, value in invoice.items() if key != "_id"}))
            pdf.raise_for_status()
            if not pdf.content:
                raise ValueError("Invoice PDF is empty")
            finance_name = str(payload.client_name or "").strip()
            finance_greeting = f"Hello {finance_name}," if finance_name and finance_name.lower() not in {"client", "team"} else "Hello,"
            finance_body = (
                f"{finance_greeting}\n\n"
                f"Please find the invoice attached against PO {payload.po_number}.\n\n"
                "Thanks and Regards,\nMurali Mohan M\nClahan Technologies"
            )
            mail = await client.post(f"{email_url}/api/v1/email/send", json={"to": payload.client_email, "subject": f"Invoice {invoice_id} - Clahan Technologies", "body": finance_body, "mail_type": "finance_invoice", "idempotency_key": f"finance-invoice:{finance_id}", "attachments": [{"filename": f"{invoice_id}.pdf", "content_base64": base64.b64encode(pdf.content).decode(), "subtype": "pdf"}]})
            mail.raise_for_status()
            if mail.json().get("success") is not True:
                raise HTTPException(502, "Invoice email delivery is not confirmed")
    except Exception as exc:
        await db["finance_approvals"].update_one({"finance_id": finance_id}, {"$set": {"status": "approved_invoice_send_failed", "error": str(exc), "updated_at": datetime.utcnow()}})
        raise HTTPException(502, f"Invoice created but email failed: {exc}")
    await db["invoices"].update_one({"invoice_id": invoice_id}, {"$set": {"status": "sent", "sent_to": payload.client_email, "sent_at": datetime.utcnow()}})
    await db["finance_approvals"].update_one({"finance_id": finance_id}, {"$set": {"status": "invoice_sent", "po_id": po_id, "invoice_id": invoice_id, "reviewed_at": datetime.utcnow(), "updated_at": datetime.utcnow()}})
    await _confirm_batch_after_invoice(db, approval, po_id, invoice_id)
    return {"success": True, "finance_id": finance_id, "po_id": po_id, "invoice_id": invoice_id, "status": "invoice_sent"}


def _db_collection(db, name: str):
    getter = getattr(db, "get", None)
    if callable(getter):
        found = getter(name)
        if found is not None:
            return found
        if isinstance(db, dict):
            return None
    try:
        return db[name]
    except Exception:
        return None


async def _confirm_batch_after_invoice(db, approval: Dict[str, Any], po_id: str, invoice_id: str) -> None:
    """PO approval that creates and emails the invoice also closes the batch."""
    approval = approval or {}
    requirement_id = str(approval.get("requirement_id") or "").strip()
    requirements = _db_collection(db, "requirements")
    if not requirement_id and requirements is not None:
        client_email = str(approval.get("client_email") or "").strip()
        if client_email:
            try:
                requirement = await requirements.find_one(
                    {"client_email": client_email},
                    {"_id": 0, "requirement_id": 1},
                )
            except TypeError:
                requirement = await requirements.find_one({"client_email": client_email})
            requirement_id = str((requirement or {}).get("requirement_id") or "").strip()
    if not requirement_id or requirements is None:
        return
    now = datetime.utcnow()
    await requirements.update_one(
        {"requirement_id": requirement_id},
        {"$set": {
            "batch_confirmed": True,
            "status": "batch_confirmed",
            "training_status": "confirmed",
            "pipeline_status": "completed",
            "client_po_status": "invoice_sent",
            "invoice_status": "sent",
            "po_id": po_id,
            "invoice_id": invoice_id,
            "batch_confirmed_at": now,
            "updated_at": now,
        }},
    )
    shortlists = _db_collection(db, "shortlists")
    if shortlists is None:
        return
    stage_update = {
        "pipeline_summary.status": "completed",
        "pipeline_summary.current_stage": "batch_confirmed",
        "pipeline_summary.batch_confirmed": True,
        "pipeline_summary.matching_status": "completed",
        "updated_at": now,
    }
    trainer_id = str(approval.get("trainer_id") or "").strip()
    if trainer_id:
        await shortlists.update_one(
            {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
            {"$set": {**stage_update, "top_trainers.$.pipeline_status": "training_confirmed", "top_trainers.$.batch_confirmed": True}},
        )
        return
    try:
        shortlist = await shortlists.find_one({"requirement_id": requirement_id}, {"_id": 0, "top_trainers": 1})
    except TypeError:
        shortlist = await shortlists.find_one({"requirement_id": requirement_id})
    trainers = list((shortlist or {}).get("top_trainers") or [])
    for trainer in trainers:
        stage = str(trainer.get("pipeline_status") or "").lower()
        if stage in {"rejected", "declined", "stopped_selected"}:
            continue
        trainer["pipeline_status"] = "training_confirmed"
        trainer["batch_confirmed"] = True
    await shortlists.update_one(
        {"requirement_id": requirement_id},
        {"$set": {**stage_update, "top_trainers": trainers} if trainers else stage_update},
    )
