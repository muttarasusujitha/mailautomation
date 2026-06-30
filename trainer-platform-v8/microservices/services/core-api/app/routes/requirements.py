from fastapi import APIRouter, HTTPException, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId
from datetime import datetime
from typing import Optional

from app.database import get_db
from shared.models.schemas import Requirement, RequirementCreate, RequirementUpdate, PaginatedResponse

router = APIRouter()


def _doc(doc: dict) -> Requirement:
    doc["_id"] = str(doc["_id"])
    return Requirement(**doc)


@router.get("", response_model=PaginatedResponse)
async def list_requirements(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    customer_id: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    query: dict = {}
    if customer_id:
        query["customer_id"] = customer_id
    if status:
        query["status"] = status
    total = await db.requirements.count_documents(query)
    skip = (page - 1) * page_size
    cursor = db.requirements.find(query).skip(skip).limit(page_size).sort("created_at", -1)
    items = [_doc(d) async for d in cursor]
    return PaginatedResponse(
        items=items, total=total, page=page, page_size=page_size,
        pages=max(1, (total + page_size - 1) // page_size),
    )


@router.post("", response_model=Requirement, status_code=201)
async def create_requirement(
    payload: RequirementCreate,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    now = datetime.utcnow()
    doc = payload.model_dump()
    doc.update({"created_at": now, "updated_at": now})
    result = await db.requirements.insert_one(doc)
    created = await db.requirements.find_one({"_id": result.inserted_id})
    return _doc(created)


@router.get("/{req_id}", response_model=Requirement)
async def get_requirement(
    req_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    doc = await db.requirements.find_one({"_id": ObjectId(req_id)})
    if not doc:
        raise HTTPException(404, "Requirement not found")
    return _doc(doc)


@router.patch("/{req_id}", response_model=Requirement)
async def update_requirement(
    req_id: str,
    payload: RequirementUpdate,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not data:
        raise HTTPException(400, "No fields to update")
    data["updated_at"] = datetime.utcnow()
    result = await db.requirements.update_one({"_id": ObjectId(req_id)}, {"$set": data})
    if result.matched_count == 0:
        raise HTTPException(404, "Requirement not found")
    return _doc(await db.requirements.find_one({"_id": ObjectId(req_id)}))


@router.delete("/{req_id}", status_code=204)
async def delete_requirement(
    req_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    result = await db.requirements.delete_one({"_id": ObjectId(req_id)})
    if result.deleted_count == 0:
        raise HTTPException(404, "Requirement not found")



# ─── Client PO + budget routes ────────────────────────────────────────────────

from pydantic import BaseModel as _BaseModel
import httpx as _httpx


class ClientPORequest(_BaseModel):
    client_email: str = ""
    subject: str = ""
    notes: str = ""


class BudgetIncreaseRequest(_BaseModel):
    current_budget: float = 0.0
    requested_budget: float = 0.0
    reason: str = ""
    client_email: str = ""


class InvoiceFromPORequest(_BaseModel):
    gst_number: str = ""
    invoice_date: str = ""
    additional_notes: str = ""


@router.post("/{req_id}/request-client-po")
async def request_client_po(
    req_id: str,
    payload: ClientPORequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Send a Purchase Order request email to the client for a requirement."""
    doc = await db.requirements.find_one({"requirement_id": req_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Requirement not found")

    client_email = payload.client_email or doc.get("client_email", "")
    if not client_email:
        raise HTTPException(400, "client_email is required")

    subject = payload.subject or f"Purchase Order Request — {req_id}"
    body = (
        f"Dear {doc.get('client_name') or doc.get('client_company') or 'Client'},\n\n"
        f"Please find attached the Purchase Order for training requirement {req_id}.\n"
        f"{payload.notes or ''}\n\nKindly acknowledge at your earliest convenience.\n\n"
        "Regards,\nTrainerSync Team"
    )

    try:
        async with _httpx.AsyncClient(timeout=30) as client:
            await client.post(
                "http://email-service:8002/api/v1/email/send",
                json={"to": client_email, "subject": subject, "body": body,
                      "requirement_id": req_id, "mail_type": "client_po_request"},
            )
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc

    now = datetime.utcnow()
    await db.requirements.update_one(
        {"requirement_id": req_id},
        {"$set": {"client_po_requested": True, "client_po_requested_at": now, "updated_at": now}},
    )
    return {"success": True, "requirement_id": req_id, "sent_to": client_email}


@router.post("/{req_id}/request-client-budget-increase")
async def request_client_budget_increase(
    req_id: str,
    payload: BudgetIncreaseRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Email the client requesting a budget increase for a requirement."""
    doc = await db.requirements.find_one({"requirement_id": req_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Requirement not found")

    client_email = payload.client_email or doc.get("client_email", "")
    if not client_email:
        raise HTTPException(400, "client_email is required")

    subject = f"Budget Increase Request — {req_id}"
    body = (
        f"Dear {doc.get('client_name') or doc.get('client_company') or 'Client'},\n\n"
        f"We are writing regarding training requirement {req_id}.\n\n"
        f"The current approved budget is ₹{payload.current_budget:,.0f}. "
        f"Based on trainer profiles and market rates, we would like to request an "
        f"increase to ₹{payload.requested_budget:,.0f}.\n\n"
        f"Reason: {payload.reason or 'Market rate adjustment required.'}\n\n"
        "Please confirm your approval at your earliest convenience.\n\n"
        "Regards,\nTrainerSync Team"
    )

    try:
        async with _httpx.AsyncClient(timeout=30) as client:
            await client.post(
                "http://email-service:8002/api/v1/email/send",
                json={"to": client_email, "subject": subject, "body": body,
                      "requirement_id": req_id, "mail_type": "budget_increase_request"},
            )
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc

    now = datetime.utcnow()
    await db.requirements.update_one(
        {"requirement_id": req_id},
        {"$set": {
            "budget_increase_requested": True,
            "budget_increase_amount": payload.requested_budget,
            "budget_increase_requested_at": now,
            "updated_at": now,
        }},
    )
    return {"success": True, "requirement_id": req_id, "sent_to": client_email,
            "requested_budget": payload.requested_budget}


@router.post("/{req_id}/client-po/generate-invoice")
async def generate_invoice_from_requirement_po(
    req_id: str,
    payload: InvoiceFromPORequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Generate an invoice from the PO linked to a requirement via trainer-service."""
    doc = await db.requirements.find_one({"requirement_id": req_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Requirement not found")

    # Find linked PO
    po = await db["purchase_orders"].find_one({"requirement_id": req_id}, {"_id": 0})
    if not po:
        raise HTTPException(404, "No purchase order found for this requirement")

    po_id = po.get("po_id", "")
    try:
        async with _httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"http://trainer-service:8004/api/v1/purchase-orders/{po_id}/generate-invoice",
                json={
                    "gst_number": payload.gst_number,
                    "invoice_date": payload.invoice_date,
                    "additional_notes": payload.additional_notes,
                },
            )
        if r.status_code < 400:
            return r.json()
        raise HTTPException(502, f"Trainer service error: {r.text[:200]}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
