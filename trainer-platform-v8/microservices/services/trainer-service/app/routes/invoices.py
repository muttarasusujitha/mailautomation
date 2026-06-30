"""Invoice routes — download PDF and send by email."""
import logging
import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel
from typing import Optional

from app.database import get_db

router = APIRouter()
logger = logging.getLogger(__name__)

DOC_SVC = "http://document-service:8006"
EMAIL_SVC = "http://email-service:8002"


class InvoiceSendRequest(BaseModel):
    to_email: str
    subject: Optional[str] = ""
    body: Optional[str] = ""


@router.get("/{invoice_id}/download")
async def download_invoice(invoice_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    doc = await db["invoices"].find_one({"invoice_id": invoice_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Invoice not found")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{DOC_SVC}/api/v1/documents/pdf/purchase-order", json={
                "po_number": invoice_id,
                "date": doc.get("invoice_date", ""),
                "vendor_name": doc.get("vendor_name", ""),
                "client_name": doc.get("client_name", ""),
                "training_domain": doc.get("training_domain", ""),
                "items": doc.get("items", []),
                "notes": doc.get("notes", ""),
            })
        return Response(content=r.content, media_type="application/pdf",
                        headers={"Content-Disposition": f"attachment; filename={invoice_id}.pdf"})
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc


@router.post("/{invoice_id}/send")
async def send_invoice(invoice_id: str, payload: InvoiceSendRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    doc = await db["invoices"].find_one({"invoice_id": invoice_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Invoice not found")

    subject = payload.subject or f"Invoice {invoice_id} — TrainerSync"
    body = payload.body or f"Dear Client,\n\nPlease find your invoice {invoice_id} attached.\n\nRegards,\nTrainerSync Team"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(f"{EMAIL_SVC}/api/v1/email/send", json={
                "to": payload.to_email, "subject": subject, "body": body})
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc

    from datetime import datetime
    await db["invoices"].update_one({"invoice_id": invoice_id},
        {"$set": {"status": "sent", "sent_to": payload.to_email, "sent_at": datetime.utcnow(), "updated_at": datetime.utcnow()}})
    return {"success": True, "invoice_id": invoice_id, "sent_to": payload.to_email}
