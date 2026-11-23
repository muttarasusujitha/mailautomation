"""Separate finance approval queue for client PO and invoice requests."""
import base64
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
from shared.database.service import get_db
from shared.document_amounts import offline_expense_items
from shared.commercial_policy import commercial_breakdown

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


@router.get("/travel-bookings")
async def list_travel_bookings(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Operations view for all travel tasks, including bookings no longer awaiting approval."""
    tasks = await db["travel_booking_tasks"].find({}, {"_id": 0}).sort("updated_at", -1).to_list(300)
    results = []
    for task in tasks:
        requirement = {}
        if not task.get("client_name") or not task.get("client_email"):
            requirement = await db["requirements"].find_one(
                {"requirement_id": task.get("requirement_id")}, {"_id": 0, "client_name": 1, "client_company": 1, "client_email": 1},
            ) or {}
        results.append({
            **task,
            "client_name": task.get("client_name") or requirement.get("client_name") or requirement.get("client_company") or "Client not recorded",
            "client_email": task.get("client_email") or requirement.get("client_email") or "",
            "live_supplier_search": False,
            "live_supplier_search_note": "Connect a travel supplier API to show live availability and prices in TrainerSync.",
        })
    return {"bookings": results, "count": len(results)}


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
    existing_invoice = await db["invoices"].find_one(
        {"source_finance_id": finance_id, "invoice_kind": {"$ne": "lab"}}, {"_id": 0, "invoice_id": 1, "po_id": 1},
    ) or {}
    po_id = existing_invoice.get("po_id") or f"PO-{uuid.uuid4().hex[:10].upper()}"
    invoice_id = existing_invoice.get("invoice_id") or f"INV-{uuid.uuid4().hex[:10].upper()}"
    requirement = await db["requirements"].find_one({"requirement_id": approval.get("requirement_id")}, {"_id": 0}) or {}
    commercials = commercial_breakdown(requirement)
    if commercials["needs_lab_price"] or commercials["invalid"]:
        await db["finance_approvals"].update_one(
            {"finance_id": finance_id},
            {"$set": {"status": "pending_human_approval", "commercial_split_required": True, "updated_at": datetime.utcnow()}},
        )
        raise HTTPException(409, "The training and lab commercial split must be completed before sending the training invoice")
    training_amount = float(commercials["training_client_amount"] or payload.total_amount)
    training_description = "Training services" if commercials["lab_client_amount"] else payload.description
    invoice_items = [{"description": training_description, "quantity": 1, "rate": training_amount, "amount": training_amount}]
    invoice_items.extend(offline_expense_items(requirement))
    invoice_subtotal = round(sum(float(row["amount"]) for row in invoice_items), 2)
    gst_amount = round(invoice_subtotal * payload.gst_rate / 100, 2)
    grand_total = round(invoice_subtotal + gst_amount, 2)
    po_items = invoice_items[:1]
    lab_invoice = None
    if commercials["lab_client_amount"]:
        existing_lab_invoice = await db["invoices"].find_one(
            {"invoice_kind": "lab", "lab_requirement_id": approval.get("requirement_id")}, {"_id": 0, "invoice_id": 1},
        ) or {}
        lab_invoice_id = existing_lab_invoice.get("invoice_id") or f"LINV-{uuid.uuid4().hex[:10].upper()}"
        course = requirement.get("technology_needed") or requirement.get("technology") or requirement.get("domain") or "Training"
        lab_amount = float(commercials["lab_client_amount"])
        lab_items = [{"description": f"{course} lab services", "quantity": 1, "rate": lab_amount, "amount": lab_amount}]
        lab_gst_amount = round(lab_amount * payload.gst_rate / 100, 2)
        lab_grand_total = round(lab_amount + lab_gst_amount, 2)
        lab_invoice = {
            "requirement_id": approval.get("requirement_id"), "invoice_id": lab_invoice_id,
            "invoice_number": lab_invoice_id, "invoice_kind": "lab", "lab_requirement_id": approval.get("requirement_id"),
            "po_id": po_id, "client_name": payload.client_name, "client_email": payload.client_email,
            "client_billing_address": payload.billing_address, "client_address": payload.billing_address,
            "client_po_number": payload.po_number, "client_po_date": payload.po_date, "client_gstin": payload.gstin,
            "training_domain": course, "total_amount": lab_amount, "gst_rate": payload.gst_rate,
            "payment_terms": payload.payment_terms, "items": lab_items,
            "invoice_date": now.strftime("%d-%m-%Y"), "issue_date": now.strftime("%d-%m-%Y"), "due_date": payload.due_date,
            "commercials": {"subtotal": lab_amount, "gst_rate": payload.gst_rate, "gst_amount": lab_gst_amount, "grand_total": lab_grand_total},
            "balance_due": lab_grand_total, "status": "draft", "source_finance_id": finance_id, "updated_at": now,
        }
        po_items = [*po_items, {"description": "Lab services", "quantity": 1, "rate": lab_amount, "amount": lab_amount}]
    po = {"po_id": po_id, "po_number": payload.po_number, "client_po_number": payload.po_number, "client_po_date": payload.po_date, "client_name": payload.client_name, "client_email": payload.client_email, "client_billing_address": payload.billing_address, "client_gstin": payload.gstin, "total_amount": round(training_amount + float(commercials["lab_client_amount"]), 2), "gst_rate": payload.gst_rate, "payment_terms": payload.payment_terms, "items": po_items, "requirement_id": approval.get("requirement_id"), "status": "approved", "source_finance_id": finance_id, "updated_at": now}
    invoice = {"requirement_id": approval.get("requirement_id"), "invoice_id": invoice_id, "invoice_number": invoice_id, "po_id": po_id, "client_name": payload.client_name, "client_email": payload.client_email, "client_billing_address": payload.billing_address, "client_address": payload.billing_address, "client_po_number": payload.po_number, "client_po_date": payload.po_date, "client_gstin": payload.gstin, "total_amount": invoice_subtotal, "gst_rate": payload.gst_rate, "payment_terms": payload.payment_terms, "items": invoice_items, "invoice_date": now.strftime("%d-%m-%Y"), "issue_date": now.strftime("%d-%m-%Y"), "due_date": payload.due_date, "commercials": {"subtotal": invoice_subtotal, "gst_rate": payload.gst_rate, "gst_amount": gst_amount, "grand_total": grand_total}, "balance_due": grand_total, "status": "draft", "source_finance_id": finance_id, "updated_at": now}
    await db["purchase_orders"].update_one(
        {"source_finance_id": finance_id}, {"$set": po, "$setOnInsert": {"created_at": now}}, upsert=True,
    )
    await db["invoices"].update_one(
        {"source_finance_id": finance_id, "invoice_kind": {"$ne": "lab"}}, {"$set": invoice, "$setOnInsert": {"created_at": now}}, upsert=True,
    )
    if lab_invoice:
        await db["invoices"].update_one(
            {"invoice_id": lab_invoice["invoice_id"]}, {"$set": lab_invoice, "$setOnInsert": {"created_at": now}}, upsert=True,
        )
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
            subject = f"Invoices {invoice_id} and {lab_invoice['invoice_id']} - Beulix Solutions Private Limited" if lab_invoice else f"Invoice {invoice_id} - Beulix Solutions Private Limited"
            mail = await client.post(f"{email_url}/api/v1/email/send", json={"to": payload.client_email, "subject": subject, "body": finance_body, "mail_type": "finance_invoice", "idempotency_key": f"finance-invoice:{finance_id}", "attachments": attachments})
            mail.raise_for_status()
            if mail.json().get("success") is not True:
                raise HTTPException(502, "Invoice email delivery is not confirmed")
    except Exception as exc:
        await db["finance_approvals"].update_one({"finance_id": finance_id}, {"$set": {"status": "approved_invoice_send_failed", "error": str(exc), "updated_at": datetime.utcnow()}})
        raise HTTPException(502, f"Invoice created but email failed: {exc}")
    await db["invoices"].update_one({"invoice_id": invoice_id}, {"$set": {"status": "sent", "sent_to": payload.client_email, "sent_at": datetime.utcnow()}})
    if lab_invoice:
        await db["invoices"].update_one({"invoice_id": lab_invoice["invoice_id"]}, {"$set": {"status": "sent", "sent_to": payload.client_email, "sent_at": datetime.utcnow()}})
    await db["finance_approvals"].update_one({"finance_id": finance_id}, {"$set": {"status": "invoice_sent", "po_id": po_id, "invoice_id": invoice_id, "lab_invoice_id": lab_invoice.get("invoice_id", "") if lab_invoice else "", "reviewed_at": datetime.utcnow(), "updated_at": datetime.utcnow()}})
    await _confirm_batch_after_invoice(db, approval, po_id, invoice_id)
    return {"success": True, "finance_id": finance_id, "po_id": po_id, "invoice_id": invoice_id, "lab_invoice_id": lab_invoice.get("invoice_id", "") if lab_invoice else "", "status": "invoice_sent"}


def _db_collection(db, name: str):
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
