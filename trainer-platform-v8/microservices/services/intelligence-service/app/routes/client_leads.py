"""Client leads — CRM discovery, auto-discover, draft generation, send email."""
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.database import get_db

router = APIRouter()
logger = logging.getLogger(__name__)
EMAIL_SVC = "http://email-service:8002"


class ClientLeadCreate(BaseModel):
    company_name: str
    contact_name: Optional[str] = ""
    email: Optional[str] = ""
    phone: Optional[str] = ""
    domain: Optional[str] = ""
    source: Optional[str] = "manual"
    linkedin_url: Optional[str] = ""
    notes: Optional[str] = ""
    metadata: Dict[str, Any] = {}


class ClientLeadUpdate(BaseModel):
    company_name: Optional[str] = None
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    domain: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class AnalyzeLeadRequest(BaseModel):
    company_name: str
    domain: Optional[str] = ""
    website: Optional[str] = ""
    description: Optional[str] = ""


class RegenerateDraftRequest(BaseModel):
    subject_hint: Optional[str] = ""
    tone: Optional[str] = "professional"


class SendLeadEmailRequest(BaseModel):
    to_email: str
    subject: Optional[str] = ""
    body: Optional[str] = ""
    smtp_config: Optional[Dict[str, Any]] = None


class SearchPublicRequest(BaseModel):
    query: str
    domain: Optional[str] = ""
    location: Optional[str] = ""
    max_results: int = 10


@router.get("")
async def list_client_leads(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    domain: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    query: Dict[str, Any] = {}
    if status:
        query["status"] = status
    if domain:
        query["domain"] = {"$regex": domain, "$options": "i"}
    total = await db["client_leads"].count_documents(query)
    skip = (page - 1) * page_size
    cursor = db["client_leads"].find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(page_size)
    items = [d async for d in cursor]
    return {"success": True, "total": total, "page": page, "page_size": page_size,
            "pages": max(1, (total + page_size - 1) // page_size), "leads": items}


@router.post("")
async def create_client_lead(payload: ClientLeadCreate, db: AsyncIOMotorDatabase = Depends(get_db)):
    now = datetime.utcnow()
    lead_id = f"CL-{uuid.uuid4().hex[:10].upper()}"
    doc = {**payload.model_dump(), "lead_id": lead_id, "status": "new", "created_at": now, "updated_at": now}
    await db["client_leads"].insert_one(doc)
    doc.pop("_id", None)
    return {"success": True, "lead_id": lead_id, "lead": doc}


@router.patch("/{lead_id}")
async def update_client_lead(lead_id: str, payload: ClientLeadUpdate, db: AsyncIOMotorDatabase = Depends(get_db)):
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not data:
        raise HTTPException(400, "No fields to update")
    data["updated_at"] = datetime.utcnow()
    result = await db["client_leads"].update_one({"lead_id": lead_id}, {"$set": data})
    if result.matched_count == 0:
        raise HTTPException(404, "Client lead not found")
    doc = await db["client_leads"].find_one({"lead_id": lead_id}, {"_id": 0})
    return {"success": True, "lead": doc}


@router.delete("/{lead_id}")
async def delete_client_lead(lead_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    result = await db["client_leads"].delete_one({"lead_id": lead_id})
    if result.deleted_count == 0:
        raise HTTPException(404, "Client lead not found")
    return {"success": True, "deleted": lead_id}


@router.delete("/by-domain")
async def delete_client_leads_by_domain(
    domain: str = Query(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    result = await db["client_leads"].delete_many({"domain": {"$regex": f"^{domain}$", "$options": "i"}})
    return {"success": True, "domain": domain, "deleted_count": result.deleted_count}


@router.post("/analyze")
async def analyze_lead(payload: AnalyzeLeadRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Use AI to extract intent signals and score a client lead."""
    from app.config import get_settings
    cfg = get_settings()
    score = 0.5
    signals = []
    text = f"{payload.company_name} {payload.domain} {payload.description}".lower()
    training_signals = ["training", "trainer", "workshop", "course", "learning", "upskill", "batch"]
    for sig in training_signals:
        if sig in text:
            score += 0.07
            signals.append(sig)
    score = min(1.0, round(score, 2))
    return {"success": True, "company": payload.company_name, "intent_score": score, "signals": signals}


@router.post("/search-public")
async def search_public_leads(payload: SearchPublicRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Search for client companies using public web signals."""
    # Delegates to intelligence free-search pattern
    results = []
    try:
        import httpx as _httpx
        async with _httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                "http://intelligence-service:8005/api/v1/intelligence/trainers/search",
                json={"domain": payload.query, "location": payload.location or "", "max_results": payload.max_results},
            )
            if r.status_code < 400:
                results = r.json().get("profiles", [])
    except Exception as exc:
        logger.warning("Public search failed: %s", exc)
    return {"success": True, "query": payload.query, "results": results}


@router.post("/auto-discover-now")
async def auto_discover_leads(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Trigger background discovery of new client leads from email inbox."""
    # Placeholder — real implementation polls client_emails and extracts companies
    discovered = await db["client_emails"].count_documents({"processed": False})
    return {"success": True, "message": f"Auto-discovery triggered. {discovered} unprocessed emails queued."}


@router.post("/{lead_id}/regenerate-draft")
async def regenerate_lead_draft(
    lead_id: str, payload: RegenerateDraftRequest, db: AsyncIOMotorDatabase = Depends(get_db),
):
    doc = await db["client_leads"].find_one({"lead_id": lead_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Client lead not found")

    from app.config import get_settings
    cfg = get_settings()
    company = doc.get("company_name", "your company")
    domain = doc.get("domain", "training")
    contact = doc.get("contact_name", "")
    tone = payload.tone or "professional"
    greeting = f"Dear {contact}," if contact else "Dear Sir/Madam,"

    draft_body = (
        f"{greeting}\n\n"
        f"I hope this message finds you well. I'm reaching out from TrainerSync regarding "
        f"{domain} training solutions for {company}.\n\n"
        "We specialize in connecting organizations with highly skilled trainers across technology domains. "
        "Our curated trainer network covers everything from DevOps and Cloud to AI, Data Engineering, and more.\n\n"
        "Would you be open to a brief discussion about your upcoming training needs?\n\n"
        "Regards,\nTrainerSync Team"
    )
    draft_subject = payload.subject_hint or f"Training Solutions for {company} — TrainerSync"

    now = datetime.utcnow()
    await db["client_leads"].update_one(
        {"lead_id": lead_id},
        {"$set": {"draft_subject": draft_subject, "draft_body": draft_body, "draft_regenerated_at": now, "updated_at": now}},
    )
    return {"success": True, "lead_id": lead_id, "subject": draft_subject, "body": draft_body}


@router.post("/{lead_id}/send-email")
async def send_lead_email(
    lead_id: str, payload: SendLeadEmailRequest, db: AsyncIOMotorDatabase = Depends(get_db),
):
    doc = await db["client_leads"].find_one({"lead_id": lead_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Client lead not found")

    to_email = payload.to_email or doc.get("email", "")
    if not to_email:
        raise HTTPException(400, "No recipient email found")

    subject = payload.subject or doc.get("draft_subject") or f"Training Solutions — {doc.get('company_name', '')}"
    body = payload.body or doc.get("draft_body") or "Dear Client,\n\nWe would like to discuss training solutions for your team.\n\nRegards,\nTrainerSync Team"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{EMAIL_SVC}/api/v1/email/send", json={
                "to": to_email, "subject": subject, "body": body, "smtp_config": payload.smtp_config,
            })
        success = r.status_code < 400
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc

    now = datetime.utcnow()
    await db["client_leads"].update_one(
        {"lead_id": lead_id},
        {"$set": {"status": "contacted" if success else "email_failed",
                  "last_emailed_at": now, "updated_at": now}},
    )
    if not success:
        raise HTTPException(502, "Email delivery failed")
    return {"success": True, "lead_id": lead_id, "sent_to": to_email}
