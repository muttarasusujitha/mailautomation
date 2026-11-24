"""Separate finance approval queue for client PO and invoice requests."""
import base64
import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from fastapi.encoders import jsonable_encoder
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.config import get_settings
from app.travel_supplier import (
    TravelSupplierConfigurationError,
    TravelSupplierError,
    search_amadeus_flights,
)
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
    coordination_tasks = await db["offline_coordination_tasks"].find(
        {"status": "pending_completion"}, {"_id": 0},
    ).sort("created_at", -1).to_list(100)
    for task in coordination_tasks:
        rows.append({**task, "finance_id": task.get("task_id"), "request_type": "offline_coordination", "status": "pending_human_approval"})
    travel_booking_tasks = await db["travel_booking_tasks"].find(
        {"status": {"$in": ["awaiting_finance_approval", "ready_to_book", "booked_pending_cost_review"]}}, {"_id": 0},
    ).sort("created_at", -1).to_list(100)
    for task in travel_booking_tasks:
        rows.append({
            **task,
            "finance_id": task.get("booking_task_id"),
            "request_type": "travel_booking",
            "status": "pending_human_approval" if task.get("status") == "awaiting_finance_approval" else task.get("status"),
        })
    return {"approvals": rows, "pending": sum(1 for row in rows if row.get("status") == "pending_human_approval")}


@router.get("/approvals/{finance_id}/source-document")
async def get_approval_source_document(finance_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    approval = await db["finance_approvals"].find_one(
        {"finance_id": finance_id}, {"_id": 0, "source_email_id": 1, "attachment_names": 1},
    )
    if not approval:
        raise HTTPException(404, "Finance approval not found")
    source = await db["client_emails"].find_one(
        {"email_id": approval.get("source_email_id")}, {"_id": 0, "attachments": 1},
    ) or {}
    for attachment in source.get("attachments") or []:
        filename = str(attachment.get("filename") or "purchase-order.pdf")
        encoded = attachment.get("content_base64") or ""
        if filename.lower().endswith(".pdf") and encoded:
            try:
                content = base64.b64decode(encoded, validate=True)
            except Exception:
                continue
            safe_filename = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._") or "purchase-order.pdf"
            return Response(
                content=content,
                media_type="application/pdf",
                headers={"Content-Disposition": f'inline; filename="{safe_filename}"'},
            )
    raise HTTPException(404, "No captured PDF is available on the source email")


@router.post("/approvals/{finance_id}/reject")
async def reject_finance_approval(finance_id: str, payload: FinanceRejectRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    result = await db["finance_approvals"].update_one(
        {"finance_id": finance_id, "status": "pending_human_approval"},
        {"$set": {"status": "rejected", "rejection_reason": payload.reason, "reviewed_at": datetime.utcnow(), "updated_at": datetime.utcnow()}},
    )
    if not result.modified_count:
        raise HTTPException(404, "Pending finance approval not found")
    return {"success": True, "finance_id": finance_id, "status": "rejected"}


@router.post("/approvals/{finance_id}/approve-trainer-po")
async def approve_and_send_trainer_po(finance_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    approval = await db["finance_approvals"].find_one({"finance_id": finance_id, "request_type": "trainer_po", "status": "pending_human_approval"}, {"_id": 0})
    if not approval:
        raise HTTPException(404, "Pending trainer PO approval not found")
    requirement = await db["requirements"].find_one(
        {"requirement_id": approval.get("requirement_id")}, {"_id": 0},
    ) or {}
    commercials = commercial_breakdown(requirement)
    if commercials["needs_lab_price"] or commercials["invalid"]:
        raise HTTPException(409, "The training and lab commercial split must be completed before sending the trainer PO")
    # Recalculate at send time so a lab workbook received after trainer
    # selection cannot leave the trainer PO based on the combined budget.
    trainer_amount = commercials["trainer_amount"]
    if trainer_amount <= 0:
        raise HTTPException(400, "Training commercial amount is required before sending the trainer PO")
    claimed = await db["finance_approvals"].update_one(
        {"finance_id": finance_id, "request_type": "trainer_po", "status": "pending_human_approval"},
        {"$set": {"status": "sending_trainer_po", "updated_at": datetime.utcnow()}},
    )
    if not claimed.modified_count:
        raise HTTPException(409, "Trainer PO is already being processed")
    po_id = f"TPO-{uuid.uuid5(uuid.NAMESPACE_URL, finance_id).hex[:10].upper()}"
    now = datetime.utcnow()
    po = {
        "po_kind": "trainer", "po_id": po_id, "po_number": approval.get("po_number") or po_id,
        "requirement_id": approval.get("requirement_id"), "trainer_id": approval.get("trainer_id"),
        "vendor_name": approval.get("trainer_name"), "vendor_email": approval.get("trainer_email"),
        "client_name": approval.get("client_name"), "client_email": approval.get("client_email"),
        "training_domain": approval.get("training_domain"), "training_dates": approval.get("training_dates"),
        "company_name": "BEULIX SOLUTIONS PRIVATE LIMITED",
        "total_amount": trainer_amount, "gst_rate": 0,
        "commercial_breakdown": commercials,
        "items": [{"description": f"Training services for {approval.get('requirement_id')}", "quantity": 1, "rate": trainer_amount, "amount": trainer_amount}],
        "status": "draft", "created_at": now, "updated_at": now,
    }
    await db["purchase_orders"].update_one({"po_id": po_id}, {"$set": po}, upsert=True)
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            pdf = await client.post(f"{settings.DOCUMENT_SERVICE_URL.rstrip('/')}/api/v1/documents/pdf/purchase-order", json=jsonable_encoder(po))
            pdf.raise_for_status()
            if not pdf.content:
                raise ValueError("Trainer PO PDF is empty")
            sent = await client.post(f"{settings.EMAIL_SERVICE_URL.rstrip('/')}/api/v1/email/send", json={
                "to": approval.get("trainer_email"), "subject": f"Purchase Order {po['po_number']} - Beulix Solutions Private Limited",
                "body": f"Hello {approval.get('trainer_name') or 'Trainer'},\n\nPlease find the approved purchase order attached.\n\nRegards,\nBeulix Solutions Private Limited",
                "mail_type": "trainer_purchase_order", "idempotency_key": f"trainer-po:{finance_id}",
                "attachments": [{"filename": f"{po_id}.pdf", "content_base64": base64.b64encode(pdf.content).decode(), "subtype": "pdf"}],
            })
            sent.raise_for_status()
            if sent.json().get("success") is not True:
                raise ValueError("Trainer PO email delivery is not confirmed")
    except Exception as exc:
        await db["finance_approvals"].update_one({"finance_id": finance_id}, {"$set": {"status": "trainer_po_send_failed", "error": str(exc), "updated_at": datetime.utcnow()}})
        raise HTTPException(502, f"Trainer PO created but could not be sent: {exc}")
    await db["purchase_orders"].update_one({"po_id": po_id}, {"$set": {"status": "sent", "sent_to": approval.get("trainer_email"), "sent_at": datetime.utcnow()}})
    await db["finance_approvals"].update_one({"finance_id": finance_id}, {"$set": {"status": "trainer_po_sent", "po_id": po_id, "total_amount": trainer_amount, "commercial_breakdown": commercials, "reviewed_at": datetime.utcnow(), "updated_at": datetime.utcnow()}})
    await db["requirements"].update_one({"requirement_id": approval.get("requirement_id")}, {"$set": {"trainer_po_approval_status": "sent", "trainer_po_id": po_id, "updated_at": datetime.utcnow()}})
    await db["offline_coordination_tasks"].update_one(
        {"requirement_id": approval.get("requirement_id"), "trainer_id": approval.get("trainer_id")},
        {"$set": {"status": "pending_completion", "trainer_po_id": po_id, "trainer_po_sent_at": datetime.utcnow(), "updated_at": datetime.utcnow()}},
    )
    task = await db["offline_coordination_tasks"].find_one(
        {"requirement_id": approval.get("requirement_id"), "trainer_id": approval.get("trainer_id")}, {"_id": 0},
    ) or {}
    if task.get("whatsapp_group_requested"):
        try:
            async with httpx.AsyncClient(timeout=35) as client:
                group = await client.post(
                    f"{settings.NOTIFICATION_SERVICE_URL.rstrip('/')}/api/v1/notifications/whatsapp/groups/offline/{approval.get('requirement_id')}"
                )
            group.raise_for_status()
            group_result = group.json()
            await db["offline_coordination_tasks"].update_one(
                {"requirement_id": approval.get("requirement_id"), "trainer_id": approval.get("trainer_id")},
                {"$set": {"whatsapp_group_creation_result": group_result, "updated_at": datetime.utcnow()}},
            )
        except Exception as exc:
            await db["offline_coordination_tasks"].update_one(
                {"requirement_id": approval.get("requirement_id"), "trainer_id": approval.get("trainer_id")},
                {"$set": {"whatsapp_group_status": "staff_action_required", "whatsapp_group_error": str(exc)[:500], "updated_at": datetime.utcnow()}},
            )
    if task:
        await dispatch_offline_bookings(approval["requirement_id"], db)
    return {"success": True, "status": "trainer_po_sent", "po_id": po_id, "sent_to": approval.get("trainer_email")}


@router.post("/offline-coordination/{requirement_id}/booking-request")
async def dispatch_offline_bookings(requirement_id: str, db=Depends(get_db)):
    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
    trainer_id = requirement.get("selected_trainer_id")
    task_key = {"requirement_id": requirement_id, "trainer_id": trainer_id}
    task = await db["offline_coordination_tasks"].find_one(task_key, {"_id": 0}) or {}
    if not task or requirement.get("trainer_po_approval_status") != "sent":
        return {"status": "awaiting_trainer_po"}
    logistics = requirement.get("offline_logistics") or {}
    owners = logistics.get("owners") or {}
    answers = logistics.get("answers") or {}
    categories = [key for key in ("travel", "accommodation", "food") if owners.get(key) == "clahan"]
    if not categories:
        return {"status": "no_clahan_bookings"}
    admin = await db["admin_settings"].find_one({"settings_id": "default"}, {"offlineOperations": 1}) or {}
    agent_email = str((admin.get("offlineOperations") or {}).get("travelAgentEmail") or "").strip()
    update = {"logistics_owners": owners, "updated_at": datetime.utcnow()}
    sent_items = set(task.get("booking_requested_items") or [])
    if task.get("booking_request_status") == "sent" and "booking_requested_items" not in task:
        sent_items.update(k for k,v in (task.get("logistics_owners") or {}).items() if v == "clahan")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            for category in categories:
                if category in sent_items:
                    continue
                if not agent_email:
                    raise ValueError("Set the travel agent email in Offline Operations")
                body = (
                    f"Please arrange {category} for {task.get('trainer_name') or 'the selected trainer'}.\n"
                    f"Trainer contact: {task.get('trainer_email') or 'Please confirm'}\n"
                    f"Training: {requirement.get('technology_needed') or requirement_id}\n"
                    f"Dates: {requirement.get('training_dates') or requirement.get('timeline_start') or 'Please confirm'}\n"
                    f"Venue: {logistics.get('venue') or requirement.get('location') or 'Please confirm'}\n"
                    f"Client instructions: {answers.get(category) or 'Please confirm details'}\n"
                    f"Approved limit: {(logistics.get('limits') or {}).get(category) or 'Refer to client instructions'}\n\n"
                    "Confirm missing traveler details, dates and limits before purchase. Please share the itinerary "
                    "and tickets with the trainer, and return the booking reference, actual expense and receipts to Clahan."
                )
                response = await client.post(f"{settings.EMAIL_SERVICE_URL.rstrip('/')}/api/v1/email/send", json={
                    "to": agent_email, "subject": f"Offline {category} booking request - {requirement_id}",
                    "body": body, "mail_type": "offline_booking_request", "requirement_id": requirement_id,
                    "trainer_id": trainer_id, "idempotency_key": f"offline-booking:{requirement_id}:{trainer_id}:{category}",
                })
                response.raise_for_status()
                if response.json().get("success") is not True:
                    raise ValueError("Travel agent email delivery is not confirmed")
                await db["offline_coordination_tasks"].update_one(task_key, {"$addToSet": {"booking_requested_items": category}})
        update.update(booking_request_status="sent", travel_agent_email=agent_email, booking_request_error="")
    except (ValueError, httpx.HTTPError) as exc:
        update.update(booking_request_status="failed", booking_request_error=str(exc)[:500])
    await db["offline_coordination_tasks"].update_one(task_key, {"$set": update})
    return {"status": update["booking_request_status"], "error": update.get("booking_request_error", "")}


@router.post("/approvals/{finance_id}/approve-send")
async def approve_and_send_invoice(finance_id: str, payload: FinanceApproveRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    if payload.total_amount <= 0:
        raise HTTPException(400, "Approved PO amount must be greater than zero")
    # Atomically claim the approval before creating documents or sending mail.
    # A duplicate click can therefore never create two invoices.
    claimed = await db["finance_approvals"].update_one(
        {"finance_id": finance_id, "request_type": {"$ne": "trainer_po"}, "status": "pending_human_approval"},
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
            # Generate distinct documents in one approved finance action. A lab
            # commercial is never added to the trainer PO or training invoice.
            attachments = []
            for document in [invoice, *([lab_invoice] if lab_invoice else [])]:
                invoice_document = {**document, "created_at": now}
                pdf = await client.post(f"{doc_url}/api/v1/documents/pdf/invoice", json=jsonable_encoder({key: value for key, value in invoice_document.items() if key != "_id"}))
                pdf.raise_for_status()
                if not pdf.content:
                    raise ValueError("Invoice PDF is empty")
                attachments.append({"filename": f"{document['invoice_id']}.pdf", "content_base64": base64.b64encode(pdf.content).decode(), "subtype": "pdf"})
            finance_name = str(payload.client_name or "").strip()
            finance_greeting = f"Hello {finance_name}," if finance_name and finance_name.lower() not in {"client", "team"} else "Hello,"
            invoice_label = "invoices" if lab_invoice else "invoice"
            finance_body = (
                f"{finance_greeting}\n\n"
                f"Please find the {invoice_label} attached against PO {payload.po_number}.\n\n"
                "Thanks and Regards,\nMurali Mohan M\nBeulix Solutions Private Limited"
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
