"""Trainer profile leads — LinkedIn and public enrichment pipeline."""
import logging
import re
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
LOCAL_SERVICE_FALLBACKS = {
    "https://email-service:8002": "http://email-service:8002",
    "http://127.0.0.1:8002": "http://email-service:8002",
}


async def _post_with_local_fallback(
    client: httpx.AsyncClient,
    url: str,
    **kwargs: Any,
) -> httpx.Response:
    try:
        return await client.post(url, **kwargs)
    except httpx.RequestError:
        for service_base, local_base in LOCAL_SERVICE_FALLBACKS.items():
            if url.startswith(service_base):
                fallback_url = local_base + url[len(service_base):]
                return await client.post(fallback_url, **kwargs)
        raise


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
    requirement_id: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class EnrichRequest(BaseModel):
    lead_ids: Optional[List[str]] = None


class EnrichFromTextRequest(BaseModel):
    text: str


class BackfillTrainerContactsRequest(BaseModel):
    limit: int = 50
    recheck: bool = False


class SearchPublicRequest(BaseModel):
    domain: Optional[str] = ""
    requirement_id: Optional[str] = ""
    domains: Optional[List[str]] = None
    query: Optional[str] = ""
    queries: Optional[List[Dict[str, Any]]] = None
    source: Optional[str] = "linkedin"
    location: Optional[str] = ""
    max_results: int = 10
    max_queries: Optional[int] = None


class SendOutreachRequest(BaseModel):
    lead_ids: List[str]
    subject: Optional[str] = ""
    body: Optional[str] = ""
    smtp_config: Optional[Dict[str, Any]] = None


class VerifyInternalRequest(BaseModel):
    verified: bool = True
    notes: Optional[str] = ""


def _normalize_contact_text(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"(?i)\s*(?:\[|\()?at(?:\]|\))?\s*", "@", value)
    value = re.sub(r"(?i)\s*(?:\[|\()?dot(?:\]|\))?\s*", ".", value)
    value = re.sub(r"(?i)\s+at\s+", "@", value)
    value = re.sub(r"(?i)\s+dot\s+", ".", value)
    return value


def _extract_contact_from_text(text: str) -> Dict[str, str]:
    normalized = _normalize_contact_text(text)
    email = ""
    for email_match in re.finditer(r"[A-Za-z0-9._%+\-]{2,64}@[A-Za-z0-9.\-]{2,253}\.[A-Za-z]{2,12}", normalized):
        candidate = email_match.group(0)
        local, domain = candidate.lower().split("@", 1)
        context = normalized[max(0, email_match.start() - 50): email_match.end() + 50].lower()
        if local in {"st", "static", "noreply", "no-reply"} or domain in {"licdn.com", "linkedin.com", "lnkd.in"}:
            continue
        if not re.search(r"\b(email|e-mail|mail|contact|reach|write|dm|inbox)\b|mailto:", context):
            continue
        email = candidate
        break
    phone = ""
    for phone_match in re.finditer(r"(?:\+91|0091|91)?[\s.\-()]*(6[\d\s.\-()]{9,20}|7[\d\s.\-()]{9,20}|8[\d\s.\-()]{9,20}|9[\d\s.\-()]{9,20})", normalized):
        context = normalized[max(0, phone_match.start() - 40): phone_match.end() + 40].lower()
        if not re.search(r"\b(phone|mobile|mob|call|contact|whatsapp|wa|reach)\b", context):
            continue
        digits = re.sub(r"\D", "", phone_match.group(1))
        if len(digits) > 10:
            digits = digits[-10:]
        if len(digits) == 10 and digits[0] in "6789":
            phone = f"+91{digits}"
            break
    return {"email": email, "phone": phone}


def _trainer_saved_text(lead: Dict[str, Any]) -> str:
    return "\n".join(
        str(lead.get(key) or "")
        for key in (
            "profile_text",
            "post_text",
            "snippet",
            "notes",
            "title",
            "headline",
            "name",
            "trainer_name",
            "domain",
        )
    )


@router.get("")
async def list_trainer_leads(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    limit: Optional[int] = Query(None, ge=1, le=500),
    status: Optional[str] = None,
    domain: Optional[str] = None,
    requirement_id: Optional[str] = None,
    q: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    query: Dict[str, Any] = {}
    if status and status.lower() != "all":
        query["status"] = status
    if domain:
        query["domain"] = {"$regex": domain, "$options": "i"}
    if requirement_id:
        query["requirement_id"] = requirement_id
    if q:
        query["$or"] = [
            {"name": {"$regex": q, "$options": "i"}},
            {"trainer_name": {"$regex": q, "$options": "i"}},
            {"headline": {"$regex": q, "$options": "i"}},
            {"domain": {"$regex": q, "$options": "i"}},
            {"snippet": {"$regex": q, "$options": "i"}},
        ]
    total = await db["trainer_profile_leads"].count_documents(query)
    if limit is not None:
        page_size = limit
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


@router.post("/{lead_id}/enrich-from-text")
async def enrich_trainer_lead_from_text(
    lead_id: str,
    payload: EnrichFromTextRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    contact = _extract_contact_from_text(payload.text)
    updates: Dict[str, Any] = {
        "profile_text": payload.text[:5000],
        "snippet": payload.text[:1000],
        "updated_at": datetime.utcnow(),
    }
    if contact["email"]:
        updates["email"] = contact["email"]
        updates["contact_email"] = contact["email"]
    if contact["phone"]:
        updates["phone"] = contact["phone"]
        updates["contact_phone"] = contact["phone"]
    if contact["email"] or contact["phone"]:
        updates["verification_tier"] = "contact_in_post"
        updates["confidence"] = 0.9

    result = await db["trainer_profile_leads"].update_one({"lead_id": lead_id}, {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(404, "Trainer profile lead not found")
    doc = await db["trainer_profile_leads"].find_one({"lead_id": lead_id}, {"_id": 0})
    return {"success": True, "lead": doc, **contact}


@router.post("/batch/backfill-contacts")
async def backfill_trainer_contacts(
    payload: BackfillTrainerContactsRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    now = datetime.utcnow()
    query: Dict[str, Any] = {}
    if not payload.recheck:
        query["$or"] = [
            {"email": {"$in": ["", None]}},
            {"phone": {"$in": ["", None]}},
            {"contact_email": {"$in": ["", None]}},
            {"contact_phone": {"$in": ["", None]}},
        ]
    if not payload.recheck:
        query["contact_backfill_checked_at"] = {"$exists": False}

    leads = await db["trainer_profile_leads"].find(query, {"_id": 0}).sort("created_at", -1).limit(max(1, min(payload.limit, 100))).to_list(length=None)
    checked = 0
    updated_count = 0
    no_contact_count = 0
    for lead in leads:
        checked += 1
        contact = _extract_contact_from_text(_trainer_saved_text(lead))
        updates: Dict[str, Any] = {
            "contact_backfill_checked_at": now,
            "updated_at": now,
        }
        if contact["email"]:
            updates["email"] = contact["email"]
            updates["contact_email"] = contact["email"]
        if contact["phone"]:
            updates["phone"] = contact["phone"]
            updates["contact_phone"] = contact["phone"]
        if contact["email"] or contact["phone"]:
            updates["verification_tier"] = "contact_in_saved_post_text"
            updates["confidence"] = max(float(lead.get("confidence") or 0), 0.88)
            updated_count += 1
        else:
            updates["contact_backfill_note"] = "No email or phone found in available trainer text"
            no_contact_count += 1

        update_doc: Dict[str, Any] = {"$set": updates}
        if payload.recheck:
            unset_fields: Dict[str, str] = {}
            if not contact["email"]:
                unset_fields["email"] = ""
                unset_fields["contact_email"] = ""
            if not contact["phone"]:
                unset_fields["phone"] = ""
                unset_fields["contact_phone"] = ""
            if unset_fields:
                update_doc["$unset"] = unset_fields

        await db["trainer_profile_leads"].update_one({"lead_id": lead["lead_id"]}, update_doc)

    return {
        "success": True,
        "checked": checked,
        "updated_count": updated_count,
        "no_contact_count": no_contact_count,
    }


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
    search_items: List[Dict[str, str]] = []
    for item in payload.queries or []:
        query_text = str(item.get("query") or item.get("text") or item.get("title") or "").strip()
        domain_text = str(item.get("domain") or payload.domain or "").strip()
        if query_text or domain_text:
            search_items.append({"query": query_text or domain_text, "domain": domain_text or query_text})

    if not search_items:
        domains = payload.domains or ([payload.domain] if payload.domain else [])
        for domain in domains:
            domain_text = str(domain or "").strip()
            if domain_text:
                search_items.append({"query": domain_text, "domain": domain_text})

    if payload.query:
        search_items.insert(0, {"query": payload.query.strip(), "domain": payload.domain or payload.query.strip()})

    max_queries = payload.max_queries or len(search_items)
    search_items = search_items[:max_queries]
    if not search_items:
        return {
            "success": False,
            "error": "query or domain is required",
            "found": 0,
            "new_stored": 0,
            "saved_count": 0,
            "skipped_count": 0,
            "skipped": [],
        }

    profiles = []
    search_error = ""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            for item in search_items:
                r = await client.post(
                    "http://intelligence-service:8005/api/v1/intelligence/trainers/search",
                    json={
                        "query": item["query"],
                        "domain": item["domain"],
                        "location": payload.location or "",
                        "max_results": max(payload.max_results, 50),
                        "save_leads": False,
                    },
                )
                if r.status_code < 400:
                    for profile in r.json().get("profiles", []):
                        profile["_searched_domain"] = item["domain"]
                        profiles.append(profile)
                else:
                    search_error = r.text[:300]
    except Exception as exc:
        search_error = str(exc)
        logger.warning("Public search failed: %s", exc)

    now = datetime.utcnow()
    new_count = 0
    skipped: List[Dict[str, Any]] = []
    seen_urls: set = set()
    for p in profiles:
        slug = p.get("slug", "")
        source_url = p.get("source_url", "")
        source = p.get("source", "linkedin")
        if not slug and not source_url:
            skipped.append({"reason": "missing_identifier", "title": p.get("title", ""), "source": source})
            continue
        if source_url in seen_urls:
            skipped.append({"reason": "duplicate_in_search", "source_url": source_url, "source": source})
            continue
        seen_urls.add(source_url)

        dedupe_terms: List[Dict[str, str]] = []
        if source_url:
            dedupe_terms.append({"source_url": source_url})
            if source == "linkedin":
                dedupe_terms.append({"linkedin_url": source_url})
        if slug:
            dedupe_terms.append({"external_slug": slug})
            if source == "linkedin":
                dedupe_terms.append({"linkedin_slug": slug})

        exists = await db["trainer_profile_leads"].find_one(
            {"$or": dedupe_terms},
            {"_id": 1},
        )
        if exists:
            skipped.append({"reason": "already_saved", "source_url": source_url, "slug": slug, "source": source})
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
            "domain": p.get("_searched_domain") or payload.domain or p.get("domain", ""),
            "requirement_id": payload.requirement_id or "",
            "source": source,
            "status": "found", "verification_tier": "unverified",
            "created_at": now, "updated_at": now,
        })
        new_count += 1
    return {
        "success": True,
        "found": len(profiles),
        "new_stored": new_count,
        "saved_count": new_count,
        "skipped_count": len(skipped),
        "skipped": skipped[:20],
        "search_error": search_error,
    }


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
                    "http://intelligence-service:8005/api/v1/intelligence/contacts/find",
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
            r = await _post_with_local_fallback(
                client,
                f"{EMAIL_SVC}/api/v1/email/send",
                json={"to": to_email, "subject": subject, "body": body},
            )
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
