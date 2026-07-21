"""Trainer profile leads — LinkedIn and public enrichment pipeline."""
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
EMAIL_SVC = "https://email-service:8002"


class TrainerLeadCreate(BaseModel):
    name: str
    linkedin_url: Optional[str] = ""
    email: Optional[str] = ""
    phone: Optional[str] = ""
    domain: Optional[str] = ""
    source: Optional[str] = "linkedin"
    snippet: Optional[str] = ""
    metadata: Dict[str, Any] = {}


class TrainerLeadUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    domain: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class EnrichRequest(BaseModel):
    lead_ids: Optional[List[str]] = None


class SearchPublicRequest(BaseModel):
    domain: Optional[str] = ""
    query: Optional[str] = ""
    location: Optional[str] = ""
    max_results: int = 10


class SendOutreachRequest(BaseModel):
    lead_ids: List[str]
    subject: Optional[str] = ""
    body: Optional[str] = ""
    smtp_config: Optional[Dict[str, Any]] = None


class VerifyInternalRequest(BaseModel):
    verified: bool = True
    notes: Optional[str] = ""


@router.get("")
async def list_trainer_leads(
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
    total = await db["trainer_profile_leads"].count_documents(query)
    skip = (page - 1) * page_size
    cursor = db["trainer_profile_leads"].find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(page_size)
    items = [d async for d in cursor]
    return {"success": True, "total": total, "page": page, "page_size": page_size,
            "pages": max(1, (total + page_size - 1) // page_size), "leads": items}


@router.post("")
async def create_trainer_lead(payload: TrainerLeadCreate, db: AsyncIOMotorDatabase = Depends(get_db)):
    now = datetime.utcnow()
    lead_id = f"TPL-{uuid.uuid4().hex[:10].upper()}"
    doc = {**payload.model_dump(), "lead_id": lead_id, "status": "found",
           "verification_tier": "unverified", "created_at": now, "updated_at": now}
    await db["trainer_profile_leads"].insert_one(doc)
    doc.pop("_id", None)
    return {"success": True, "lead_id": lead_id, "lead": doc}


@router.patch("/{lead_id}")
async def update_trainer_lead(lead_id: str, payload: TrainerLeadUpdate, db: AsyncIOMotorDatabase = Depends(get_db)):
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not data:
        raise HTTPException(400, "No fields to update")
    data["updated_at"] = datetime.utcnow()
    result = await db["trainer_profile_leads"].update_one({"lead_id": lead_id}, {"$set": data})
    if result.matched_count == 0:
        raise HTTPException(404, "Trainer profile lead not found")
    doc = await db["trainer_profile_leads"].find_one({"lead_id": lead_id}, {"_id": 0})
    return {"success": True, "lead": doc}


@router.delete("/{lead_id}")
async def delete_trainer_lead(lead_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    result = await db["trainer_profile_leads"].delete_one({"lead_id": lead_id})
    if result.deleted_count == 0:
        raise HTTPException(404, "Trainer profile lead not found")
    return {"success": True, "deleted": lead_id}


@router.delete("/by-domain")
async def delete_trainer_leads_by_domain(domain: str = Query(...), db: AsyncIOMotorDatabase = Depends(get_db)):
    result = await db["trainer_profile_leads"].delete_many({"domain": {"$regex": f"^{domain}$", "$options": "i"}})
    return {"success": True, "domain": domain, "deleted_count": result.deleted_count}


@router.post("/search-public")
async def search_public_trainer_leads(payload: SearchPublicRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Search for trainers via public web and store as leads."""
    search_text = (payload.query or payload.domain or "").strip()
    if not search_text:
        return {"success": False, "error": "query or domain is required", "found": 0, "new_stored": 0}

    profiles = []
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            r = await client.post(
                "https://intelligence-service:8005/api/v1/intelligence/trainers/search",
                json={"query": search_text, "domain": payload.domain or search_text, "location": payload.location or "", "max_results": payload.max_results, "save_leads": False},
            )
            if r.status_code < 400:
                profiles = r.json().get("profiles", [])
    except Exception as exc:
        logger.warning("Public search failed: %s", exc)

    now = datetime.utcnow()
    new_count = 0
    for p in profiles:
        slug = p.get("slug", "")
        source_url = p.get("source_url", "")
        source = p.get("source", "linkedin")
        if not slug and not source_url:
            continue
        exists = await db["trainer_profile_leads"].find_one(
            {"$or": [{"source_url": source_url}, {"linkedin_slug": slug}]},
            {"_id": 1},
        )
        if exists:
            continue
        lead_id = f"TPL-{uuid.uuid4().hex[:10].upper()}"
        await db["trainer_profile_leads"].insert_one({
            "lead_id": lead_id,
            "name": p.get("title", ""),
            "linkedin_url": source_url if source == "linkedin" else "",
            "linkedin_slug": slug if source == "linkedin" else "",
            "source_url": source_url,
            "external_slug": slug,
            "snippet": p.get("snippet", ""),
            "domain": payload.domain or search_text,
            "source": source,
            "status": "found", "verification_tier": "unverified",
            "created_at": now, "updated_at": now,
        })
        new_count += 1
    return {"success": True, "found": len(profiles), "new_stored": new_count}


@router.post("/enrich-from-mails")
async def enrich_leads_from_mails(payload: EnrichRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Try to find emails for leads by scanning the email inbox."""
    query: Dict[str, Any] = {"email": {"$in": ["", None]}}
    if payload.lead_ids:
        query["lead_id"] = {"$in": payload.lead_ids}
    leads = await db["trainer_profile_leads"].find(query, {"_id": 0}).to_list(50)
    enriched = 0
    for lead in leads:
        name = lead.get("name", "")
        if not name:
            continue
        # Check inbound email logs for matching sender name
        match = await db["email_logs"].find_one(
            {"direction": "inbound", "sender": {"$regex": name, "$options": "i"}},
            {"_id": 0, "sender": 1},
        )
        if match:
            import re
            m = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", match.get("sender", ""))
            if m:
                await db["trainer_profile_leads"].update_one(
                    {"lead_id": lead["lead_id"]},
                    {"$set": {"email": m.group(0), "verification_tier": "email_found", "updated_at": datetime.utcnow()}},
                )
                enriched += 1
    return {"success": True, "checked": len(leads), "enriched": enriched}


@router.post("/enrich-public-emails")
async def enrich_public_emails(payload: EnrichRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Use contact-finder to discover emails for leads without one."""
    query: Dict[str, Any] = {"email": {"$in": ["", None]}}
    if payload.lead_ids:
        query["lead_id"] = {"$in": payload.lead_ids}
    leads = await db["trainer_profile_leads"].find(query, {"_id": 0}).to_list(20)
    enriched = 0
    for lead in leads:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    "https://intelligence-service:8005/api/v1/intelligence/contacts/find",
                    json={"name": lead.get("name", ""), "domain": lead.get("domain", ""),
                          "linkedin_url": lead.get("linkedin_url", "")},
                )
            if r.status_code < 400:
                result = r.json()
                if result.get("email"):
                    await db["trainer_profile_leads"].update_one(
                        {"lead_id": lead["lead_id"]},
                        {"$set": {"email": result["email"], "phone": result.get("phone", ""),
                                  "verification_tier": "public_found", "updated_at": datetime.utcnow()}},
                    )
                    enriched += 1
        except Exception as exc:
            logger.warning("Enrich failed for %s: %s", lead.get("lead_id"), exc)
    return {"success": True, "checked": len(leads), "enriched": enriched}


@router.post("/expand-from-profiles")
async def expand_from_profiles(payload: EnrichRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Merge leads that match an existing trainer in the trainers collection."""
    query: Dict[str, Any] = {"trainer_id": {"$exists": False}}
    if payload.lead_ids:
        query["lead_id"] = {"$in": payload.lead_ids}
    leads = await db["trainer_profile_leads"].find(query, {"_id": 0}).to_list(50)
    merged = 0
    for lead in leads:
        email = lead.get("email", "")
        if not email:
            continue
        trainer = await db["trainers"].find_one(
            {"email": {"$regex": f"^{email}$", "$options": "i"}}, {"_id": 0, "trainer_id": 1}
        )
        if trainer:
            await db["trainer_profile_leads"].update_one(
                {"lead_id": lead["lead_id"]},
                {"$set": {"trainer_id": trainer["trainer_id"], "status": "matched", "updated_at": datetime.utcnow()}},
            )
            merged += 1
    return {"success": True, "checked": len(leads), "merged": merged}


@router.post("/{lead_id}/verify-internal")
async def verify_internal(lead_id: str, payload: VerifyInternalRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    result = await db["trainer_profile_leads"].update_one(
        {"lead_id": lead_id},
        {"$set": {"internally_verified": payload.verified, "verification_notes": payload.notes,
                  "verification_tier": "internal_verified" if payload.verified else "unverified",
                  "updated_at": datetime.utcnow()}},
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Trainer profile lead not found")
    return {"success": True, "lead_id": lead_id, "verified": payload.verified}


@router.post("/{lead_id}/send-email")
async def send_lead_outreach(
    lead_id: str, payload: SendOutreachRequest, db: AsyncIOMotorDatabase = Depends(get_db),
):
    doc = await db["trainer_profile_leads"].find_one({"lead_id": lead_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Trainer profile lead not found")
    to_email = doc.get("email", "")
    if not to_email:
        raise HTTPException(400, "No email found for this lead")
    subject = payload.subject or f"Training Opportunity — {doc.get('domain', 'Your Domain')}"
    body = payload.body or (
        f"Dear {doc.get('name', 'Trainer')},\n\nWe have a training requirement matching your expertise.\n"
        "Please revert if interested.\n\nRegards,\nTrainerSync Team"
    )
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{EMAIL_SVC}/api/v1/email/send",
                                  json={"to": to_email, "subject": subject, "body": body})
        success = r.status_code < 400
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    now = datetime.utcnow()
    await db["trainer_profile_leads"].update_one(
        {"lead_id": lead_id},
        {"$set": {"status": "outreach_sent" if success else "outreach_failed",
                  "last_emailed_at": now, "updated_at": now}},
    )
    if not success:
        raise HTTPException(502, "Email delivery failed")
    return {"success": True, "lead_id": lead_id, "sent_to": to_email}


@router.post("/send-public-email-outreach")
async def send_public_email_outreach(payload: SendOutreachRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Send outreach emails to a list of leads in bulk."""
    sent = failed = 0
    for lead_id in payload.lead_ids:
        try:
            req = SendOutreachRequest(lead_ids=[lead_id], subject=payload.subject, body=payload.body)
            await send_lead_outreach(lead_id, req, db)
            sent += 1
        except HTTPException:
            failed += 1
    return {"success": True, "sent": sent, "failed": failed}
