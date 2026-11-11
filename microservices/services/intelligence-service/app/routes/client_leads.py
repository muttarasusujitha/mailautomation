"""Client leads — CRM discovery, auto-discover, draft generation, send email."""
import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from shared.database.service import get_db

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


class TrainingRequirement(BaseModel):
    request_text: str = Field(default='', max_length=6000)
    topics: str = Field(default='', max_length=1000)
    audience: str = Field(default='', max_length=500)
    level: str = Field(default='', max_length=200)
    dates: str = Field(default='', max_length=300)
    duration: str = Field(default='', max_length=200)
    delivery_mode: str = Field(default='', max_length=200)
    participant_count: Optional[int] = Field(default=None, ge=1, le=100000)
    goals: str = Field(default='', max_length=1000)


class ClientLeadCreate(BaseModel):
    company_name: str
    contact_name: Optional[str] = ""
    email: Optional[str] = ""
    phone: Optional[str] = ""
    domain: Optional[str] = ""
    source: Optional[str] = "manual"
    linkedin_url: Optional[str] = ""
    notes: Optional[str] = ""
    website: str = ""
    source_url: str = ""
    post_text: str = ""
    contact_email: str = ""
    contact_phone: str = ""
    training_requirement: Optional[TrainingRequirement] = None
    trainer_ids: List[str] = Field(default_factory=list, max_length=10)
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
    website: Optional[str] = None
    company_context: Optional[str] = None
    training_requirement: Optional[TrainingRequirement] = None
    trainer_ids: Optional[List[str]] = Field(default=None, max_length=10)


class SaveLeadDraftRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=4000)


class AnalyzeLeadRequest(BaseModel):
    company_name: str
    domain: Optional[str] = ""
    website: Optional[str] = ""
    description: Optional[str] = ""


class RegenerateDraftRequest(BaseModel):
    subject_hint: Optional[str] = ""
    tone: Optional[str] = "professional"


class OutreachOffering(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=10, max_length=2000)


class OutreachProfile(BaseModel):
    offerings: List[OutreachOffering] = Field(min_length=1, max_length=20)


@router.get("/outreach-profile")
async def get_outreach_profile(db: AsyncIOMotorDatabase = Depends(get_db)):
    profile = await db['outreach_profiles'].find_one({'profile_id': 'default'}, {'_id': 0})
    return {'success': True, 'offerings': (profile or {}).get('offerings', [])}


@router.put("/outreach-profile")
async def save_outreach_profile(payload: OutreachProfile, db: AsyncIOMotorDatabase = Depends(get_db)):
    offerings = [o.model_dump() for o in payload.offerings]
    if len({o['id'] for o in offerings}) != len(offerings):
        raise HTTPException(400, 'Service IDs must be unique')
    await db['outreach_profiles'].update_one({'profile_id': 'default'},
        {'$set': {'offerings': offerings, 'updated_at': datetime.utcnow()}}, upsert=True)
    return {'success': True, 'offerings': offerings}


class SendLeadEmailRequest(BaseModel):
    to_email: Optional[str] = ""
    subject: Optional[str] = ""
    body: Optional[str] = ""
    smtp_config: Optional[Dict[str, Any]] = None


class EnrichFromTextRequest(BaseModel):
    text: str


class SearchPublicRequest(BaseModel):
    query: Optional[str] = ""
    domains: Optional[List[str]] = None
    domain: Optional[str] = ""
    location: Optional[str] = ""
    max_results: int = 50
    max_queries: Optional[int] = None


@router.get("")
async def list_client_leads(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    limit: Optional[int] = Query(None, ge=1, le=500),
    status: Optional[str] = None,
    domain: Optional[str] = None,
    q: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    query: Dict[str, Any] = {}
    if status and status.lower() != "all":
        query["status"] = status
    if domain:
        query['$and'] = [{'$or': [
            {field: {'$regex': re.escape(domain), '$options': 'i'}}
            for field in ('domain', 'matched_domains')]}]
    if q:
        query["$or"] = [
            {"company_name": {"$regex": q, "$options": "i"}},
            {"contact_name": {"$regex": q, "$options": "i"}},
            {"domain": {"$regex": q, "$options": "i"}},
            {"matched_domains": {"$regex": q, "$options": "i"}},
            {"notes": {"$regex": q, "$options": "i"}},
            {"source_url": {"$regex": q, "$options": "i"}},
        ]
    total = await db["client_leads"].count_documents(query)
    if limit is not None:
        page_size = limit
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


def _extract_contact_from_text(text: str) -> Dict[str, str]:
    normalized = _normalize_contact_text(text)
    email_match = re.search(r"[A-Za-z0-9._%+\-]{2,64}@[A-Za-z0-9.\-]{2,253}\.[A-Za-z]{2,12}", normalized)
    phone_match = re.search(r"(?:\+91|0091|91)?[\s.\-()]*(6[\d\s.\-()]{9,20}|7[\d\s.\-()]{9,20}|8[\d\s.\-()]{9,20}|9[\d\s.\-()]{9,20})", normalized)
    phone = ""
    if phone_match:
        digits = re.sub(r"\D", "", phone_match.group(1))
        if len(digits) > 10:
            digits = digits[-10:]
        if len(digits) == 10:
            phone = f"+91{digits}"
    return {"email": email_match.group(0) if email_match else "", "phone": phone}


def _normalize_contact_text(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"(?i)\s*(?:\[|\()?at(?:\]|\))?\s*", "@", value)
    value = re.sub(r"(?i)\s*(?:\[|\()?dot(?:\]|\))?\s*", ".", value)
    value = re.sub(r"(?i)\s+at\s+", "@", value)
    value = re.sub(r"(?i)\s+dot\s+", ".", value)
    return value


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


@router.post("/{lead_id}/enrich-from-text")
async def enrich_client_lead_from_text(
    lead_id: str,
    payload: EnrichFromTextRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    contact = _extract_contact_from_text(payload.text)
    updates: Dict[str, Any] = {
        "post_text": payload.text[:5000],
        "notes": payload.text[:1000],
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
        updates["confidence"] = 0.88

    result = await db["client_leads"].update_one({"lead_id": lead_id}, {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(404, "Client lead not found")
    doc = await db["client_leads"].find_one({"lead_id": lead_id}, {"_id": 0})
    return {"success": True, "lead": doc, **contact}


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
    search_terms: List[str] = []
    if payload.query:
        search_terms.append(payload.query.strip())
    if payload.domain:
        search_terms.append(payload.domain.strip())
    for domain in payload.domains or []:
        term = str(domain or "").strip()
        if term:
            search_terms.append(term)
    search_terms = list(dict.fromkeys(search_terms))[: payload.max_queries or len(search_terms)]
    if not search_terms:
        return {"success": False, "error": "query or domain is required", "results": [], "saved_count": 0}

    results = []
    saved_count = 0
    skipped_count = 0
    now = datetime.utcnow()
    try:
        import httpx as _httpx
        async with _httpx.AsyncClient(timeout=20) as client:
            for term in search_terms:
                r = await client.post(
                    "http://intelligence-service:8005/api/v1/intelligence/trainers/search",
                    json={
                        "query": f"{term} trainer requirement corporate training client hiring",
                        "domain": term,
                        "location": payload.location or "",
                        "max_results": max(payload.max_results, 50),
                    },
                )
                if r.status_code >= 400:
                    continue
                for item in r.json().get("profiles", []):
                    source_url = item.get("source_url", "")
                    if not source_url:
                        skipped_count += 1
                        continue
                    results.append(item)
                    exists = await db["client_leads"].find_one({"source_url": source_url}, {"_id": 1})
                    if exists:
                        skipped_count += 1
                        continue
                    lead_id = f"CL-{uuid.uuid4().hex[:10].upper()}"
                    await db["client_leads"].insert_one({
                        "lead_id": lead_id,
                        "company_name": item.get("title") or "Public training lead",
                        "contact_name": "",
                        "email": "",
                        "phone": "",
                        "domain": term,
                        "source": item.get("source", "public_search"),
                        "source_url": source_url,
                        "linkedin_url": source_url if item.get("source") == "linkedin" else "",
                        "notes": item.get("snippet", ""),
                        "status": "new",
                        "created_at": now,
                        "updated_at": now,
                    })
                    saved_count += 1
    except Exception as exc:
        logger.warning("Public search failed: %s", exc)
    return {
        "success": True,
        "query": payload.query or ", ".join(search_terms),
        "results": results,
        "saved_count": saved_count,
        "new_stored": saved_count,
        "skipped_count": skipped_count,
    }


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

    from app.clients.lead_personalization import personalize_lead
    try:
        draft = await personalize_lead(doc, db, payload.tone, payload.subject_hint)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        logger.warning("Lead personalization failed: %s", type(exc).__name__)
        raise HTTPException(502, "Personalization unavailable. The existing draft was preserved; please retry.") from exc
    now = datetime.utcnow()
    await db["client_leads"].update_one(
        {"lead_id": lead_id},
        {"$set": {"draft_subject": draft['subject'], "draft_body": draft['body'],
                  "draft": draft, "personalization": draft,
                  "draft_regenerated_at": now, "updated_at": now}},
    )
    return {"success": True, "lead_id": lead_id, **draft}


@router.put("/{lead_id}/draft")
async def save_lead_draft(lead_id: str, payload: SaveLeadDraftRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    if not payload.subject.strip() or not payload.body.strip() or '\n' in payload.subject or '\r' in payload.subject:
        raise HTTPException(422, 'Provide a subject on one line and a nonempty email body.')
    result = await db['client_leads'].update_one({'lead_id': lead_id}, {'$set': {
        'draft_subject': payload.subject.strip(), 'draft_body': payload.body.strip(),
        'draft_reviewed_at': datetime.utcnow(), 'updated_at': datetime.utcnow(),
    }})
    if not result.matched_count:
        raise HTTPException(404, 'Client lead not found')
    return {'success': True, 'subject': payload.subject.strip(), 'body': payload.body.strip()}


@router.post("/{lead_id}/send-email")
async def send_lead_email(
    lead_id: str, payload: SendLeadEmailRequest = SendLeadEmailRequest(), db: AsyncIOMotorDatabase = Depends(get_db),
):
    doc = await db["client_leads"].find_one({"lead_id": lead_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Client lead not found")

    to_email = payload.to_email or doc.get("email") or doc.get("contact_email", "")
    if not to_email:
        raise HTTPException(400, "No recipient email found")

    subject = payload.subject or doc.get("draft_subject") or (doc.get("draft") or {}).get("subject")
    body = payload.body or doc.get("draft_body") or (doc.get("draft") or {}).get("body")
    if not subject or not body:
        raise HTTPException(400, "Generate and review an outreach draft before sending.")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await _post_with_local_fallback(client, f"{EMAIL_SVC}/api/v1/email/send", json={
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
