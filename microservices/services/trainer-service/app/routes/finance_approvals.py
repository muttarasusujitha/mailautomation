"""Separate finance approval queue for client PO and invoice requests."""
import base64
import logging
import re
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
from shared.generation_mode import application_ai_enabled

router = APIRouter()
settings = get_settings()
logger = logging.getLogger(__name__)


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


def _clean(value: Any) -> str:
    return str(value or "").strip()


async def _mark_batch_confirmed_and_pipeline_complete(db, approval: Dict[str, Any]) -> None:
    """A received PO that produced an invoice closes the confirmed batch."""
    requirement_id = _clean(approval.get("requirement_id"))
    trainer_id = _clean(approval.get("trainer_id"))
    try:
        requirements = db["requirements"]
        shortlists = db["shortlists"]
    except Exception:
        logger.warning("Pipeline completion skipped; requirement collections are unavailable")
        return
    if not requirement_id:
        client_email = _clean(approval.get("client_email"))
        if client_email:
            requirement = await requirements.find_one(
                {"client_email": {"$regex": f"^{re.escape(client_email)}$", "$options": "i"}},
                {"_id": 0, "requirement_id": 1, "selected_trainer_id": 1},
            )
            if requirement:
                requirement_id = _clean(requirement.get("requirement_id"))
                trainer_id = trainer_id or _clean(requirement.get("selected_trainer_id"))
    if not requirement_id:
        return
    now = datetime.utcnow()
    await requirements.update_one(
        {"requirement_id": requirement_id},
        {"$set": {
            "batch_confirmed": True,
            "client_po_received": True,
            "invoice_sent": True,
            "status": "completed",
            "pipeline_status": "completed",
            "updated_at": now,
        }},
    )
    summary = {
        "pipeline_summary.status": "completed",
        "pipeline_summary.current_stage": "training_confirmed",
        "pipeline_summary.batch_confirmed": True,
        "updated_at": now,
    }
    if not trainer_id:
        shortlist = await shortlists.find_one(
            {"requirement_id": requirement_id},
            {"_id": 0, "selected_trainer_id": 1, "top_trainers": 1},
        ) or {}
        trainer_id = _clean(shortlist.get("selected_trainer_id"))
        if not trainer_id:
            for trainer in shortlist.get("top_trainers") or []:
                if trainer.get("selected") or _clean(trainer.get("selection_status")) == "selected":
                    trainer_id = _clean(trainer.get("trainer_id"))
                    break
    if trainer_id:
        await shortlists.update_one(
            {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
            {"$set": {
                **summary,
                "top_trainers.$.pipeline_status": "training_confirmed",
                "top_trainers.$.batch_confirmed": True,
                "top_trainers.$.client_po_received": True,
                "top_trainers.$.invoice_sent": True,
            }},
        )
    else:
        await shortlists.update_one({"requirement_id": requirement_id}, {"$set": summary})


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
    linked_requirement_id = _clean(approval.get("requirement_id"))
    linked_trainer_id = _clean(approval.get("trainer_id"))
    po = {"po_id": po_id, "po_number": payload.po_number, "client_po_number": payload.po_number, "client_po_date": payload.po_date, "client_name": payload.client_name, "client_email": payload.client_email, "client_billing_address": payload.billing_address, "client_gstin": payload.gstin, "total_amount": payload.total_amount, "gst_rate": payload.gst_rate, "payment_terms": payload.payment_terms, "items": [item], "status": "approved", "source_finance_id": finance_id, "requirement_id": linked_requirement_id, "trainer_id": linked_trainer_id, "created_at": now, "updated_at": now}
    invoice = {"invoice_id": invoice_id, "invoice_number": invoice_id, "po_id": po_id, "client_name": payload.client_name, "client_email": payload.client_email, "client_billing_address": payload.billing_address, "client_address": payload.billing_address, "client_po_number": payload.po_number, "client_po_date": payload.po_date, "client_gstin": payload.gstin, "total_amount": payload.total_amount, "gst_rate": payload.gst_rate, "payment_terms": payload.payment_terms, "items": [item], "invoice_date": now.strftime("%d-%m-%Y"), "issue_date": now.strftime("%d-%m-%Y"), "due_date": payload.due_date, "commercials": {"subtotal": payload.total_amount, "gst_rate": payload.gst_rate, "gst_amount": gst_amount, "grand_total": grand_total}, "balance_due": grand_total, "status": "draft", "source_finance_id": finance_id, "requirement_id": linked_requirement_id, "trainer_id": linked_trainer_id, "created_at": now, "updated_at": now}
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
            mail = await client.post(f"{email_url}/api/v1/email/send", json={
                "to": payload.client_email,
                "subject": f"Invoice {invoice_id} - Clahan Technologies",
                "body": finance_body,
                "mail_type": "finance_invoice",
                "idempotency_key": f"finance-invoice:{finance_id}",
                "attachments": [{"filename": f"{invoice_id}.pdf", "content_base64": base64.b64encode(pdf.content).decode(), "subtype": "pdf"}],
                "ai_generate": await application_ai_enabled(db),
                "ai_context": {
                    "workflow": "invoice",
                    "requirement_id": linked_requirement_id,
                    "invoice_number": invoice_id,
                    "client_name": payload.client_name,
                    "po_number": payload.po_number,
                    "commercial": grand_total,
                    "requested_action": "review the attached invoice",
                },
            })
            mail.raise_for_status()
            if mail.json().get("success") is not True:
                raise HTTPException(502, "Invoice email delivery is not confirmed")
    except Exception as exc:
        await db["finance_approvals"].update_one({"finance_id": finance_id}, {"$set": {"status": "approved_invoice_send_failed", "error": str(exc), "updated_at": datetime.utcnow()}})
        raise HTTPException(502, f"Invoice created but email failed: {exc}")
    await db["invoices"].update_one({"invoice_id": invoice_id}, {"$set": {"status": "sent", "sent_to": payload.client_email, "sent_at": datetime.utcnow()}})
    await db["finance_approvals"].update_one({"finance_id": finance_id}, {"$set": {"status": "invoice_sent", "po_id": po_id, "invoice_id": invoice_id, "reviewed_at": datetime.utcnow(), "updated_at": datetime.utcnow()}})
    await _mark_batch_confirmed_and_pipeline_complete(db, approval)
    return {"success": True, "finance_id": finance_id, "po_id": po_id, "invoice_id": invoice_id, "status": "invoice_sent", "batch_confirmed": True, "pipeline_status": "completed"}
