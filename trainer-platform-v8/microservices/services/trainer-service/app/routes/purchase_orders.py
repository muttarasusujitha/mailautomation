"""Purchase orders and invoices — generate, send, download, acknowledge."""
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.database import get_db
from app.config import get_settings

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()

DOC_SVC = "http://document-service:8006"
EMAIL_SVC = "http://email-service:8002"


class POGenerateRequest(BaseModel):
    requirement_id: str
    trainer_id: str
    vendor_name: Optional[str] = ""
    client_name: Optional[str] = ""
    training_domain: Optional[str] = ""
    duration: Optional[str] = ""
    items: List[Dict[str, Any]] = []
    notes: Optional[str] = ""


class POSendRequest(BaseModel):
    to_email: str
    subject: Optional[str] = ""
    body: Optional[str] = ""


class POAcknowledgeRequest(BaseModel):
    acknowledged_by: Optional[str] = ""
    notes: Optional[str] = ""


class InvoiceGenerateRequest(BaseModel):
    gst_number: Optional[str] = ""
    invoice_date: Optional[str] = ""
    additional_notes: Optional[str] = ""


class InvoiceSendRequest(BaseModel):
    to_email: str
    subject: Optional[str] = ""



@router.post("/generate")
async def generate_purchase_order(payload: POGenerateRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    po_id = f"PO-{uuid.uuid4().hex[:10].upper()}"
    now = datetime.utcnow()

    req = await db["requirements"].find_one({"requirement_id": payload.requirement_id}, {"_id": 0}) or {}
    trainer = await db["trainers"].find_one({"trainer_id": payload.trainer_id}, {"_id": 0}) or {}

    doc = {
        "po_id": po_id,
        "po_number": po_id,
        "requirement_id": payload.requirement_id,
        "trainer_id": payload.trainer_id,
        "vendor_name": payload.vendor_name or trainer.get("name", ""),
        "client_name": payload.client_name or req.get("client_name") or req.get("client_company", ""),
        "training_domain": payload.training_domain or req.get("technology_needed", ""),
        "duration": payload.duration or str(req.get("duration_days", "")),
        "items": payload.items,
        "notes": payload.notes,
        "status": "draft",
        "date": now.strftime("%d-%m-%Y"),
        "created_at": now,
        "updated_at": now,
    }
    await db["purchase_orders"].insert_one(doc)
    doc.pop("_id", None)
    return {"success": True, "po_id": po_id, "purchase_order": doc}


@router.get("/{po_id}/download")
async def download_po_pdf(po_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    doc = await db["purchase_orders"].find_one({"po_id": po_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Purchase order not found")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{DOC_SVC}/api/v1/documents/pdf/purchase-order", json={
                "po_number": doc.get("po_number", po_id),
                "date": doc.get("date", ""),
                "vendor_name": doc.get("vendor_name", ""),
                "client_name": doc.get("client_name", ""),
                "training_domain": doc.get("training_domain", ""),
                "duration": doc.get("duration", ""),
                "items": doc.get("items", []),
                "notes": doc.get("notes", ""),
            })
        return Response(content=r.content, media_type="application/pdf",
                        headers={"Content-Disposition": f"attachment; filename={po_id}.pdf"})
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc


@router.post("/{po_id}/send")
async def send_po(po_id: str, payload: POSendRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    doc = await db["purchase_orders"].find_one({"po_id": po_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Purchase order not found")

    subject = payload.subject or f"Purchase Order {po_id} — TrainerSync"
    body = payload.body or f"Dear Trainer,\n\nPlease find attached Purchase Order {po_id}.\n\nRegards,\nTrainerSync Team"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(f"{EMAIL_SVC}/api/v1/email/send", json={
                "to": payload.to_email, "subject": subject, "body": body})
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc

    now = datetime.utcnow()
    await db["purchase_orders"].update_one({"po_id": po_id}, {"$set": {
        "status": "sent", "sent_to": payload.to_email, "sent_at": now, "updated_at": now}})
    return {"success": True, "po_id": po_id, "sent_to": payload.to_email}


@router.post("/{po_id}/acknowledge")
async def acknowledge_po(po_id: str, payload: POAcknowledgeRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    result = await db["purchase_orders"].update_one({"po_id": po_id}, {"$set": {
        "status": "acknowledged", "acknowledged_by": payload.acknowledged_by,
        "acknowledgement_notes": payload.notes, "acknowledged_at": datetime.utcnow(), "updated_at": datetime.utcnow()}})
    if result.matched_count == 0:
        raise HTTPException(404, "Purchase order not found")
    return {"success": True, "po_id": po_id, "status": "acknowledged"}


@router.post("/{po_id}/generate-invoice")
async def generate_invoice_from_po(po_id: str, payload: InvoiceGenerateRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    po = await db["purchase_orders"].find_one({"po_id": po_id}, {"_id": 0})
    if not po:
        raise HTTPException(404, "Purchase order not found")

    inv_id = f"INV-{uuid.uuid4().hex[:10].upper()}"
    now = datetime.utcnow()
    invoice = {
        "invoice_id": inv_id, "po_id": po_id,
        "requirement_id": po.get("requirement_id"),
        "trainer_id": po.get("trainer_id"),
        "vendor_name": po.get("vendor_name"), "client_name": po.get("client_name"),
        "training_domain": po.get("training_domain"),
        "items": po.get("items", []),
        "gst_number": payload.gst_number,
        "invoice_date": payload.invoice_date or now.strftime("%d-%m-%Y"),
        "notes": payload.additional_notes,
        "status": "draft", "created_at": now, "updated_at": now,
    }
    await db["invoices"].insert_one(invoice)
    invoice.pop("_id", None)
    return {"success": True, "invoice_id": inv_id, "invoice": invoice}
