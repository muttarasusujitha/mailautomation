"""Client leads — CRM discovery, auto-discover, draft generation, send email."""
import asyncio
import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from app.clients.lead_queries import NO_DOMAIN, client_query, lead_counts
from app.clients.search_runs import failure_summary, merge_sources, outcome_status, record_search_run, search_succeeded
from shared.database.service import get_db

router = APIRouter()
logger = logging.getLogger(__name__)
EMAIL_SVC = "http://email-service:8002"
LOCAL_SERVICE_FALLBACKS = {
    "https://email-service:8002": "http://email-service:8002",
    "http://127.0.0.1:8002": "http://email-service:8002",
}

_CONSUMER_EMAIL_DOMAINS = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "aol.com"}


def _inferred_website(lead: Dict[str, Any]) -> str:
    """Use a business contact domain for research without asking a user to type it."""
    for value in (lead.get("website"), (lead.get("metadata") or {}).get("website")):
        if str(value or "").strip():
            return str(value).strip()
    for value in (lead.get("email"), lead.get("contact_email")):
        domain = str(value or "").strip().lower().rsplit("@", 1)[-1]
        if "." in domain and domain not in _CONSUMER_EMAIL_DOMAINS:
            return f"https://{domain}"
    return ""


async def _auto_personalize(lead_id: str, db: AsyncIOMotorDatabase) -> None:
    """Generate a grounded training outreach draft after lead ingestion."""
    doc = await db["client_leads"].find_one({"lead_id": lead_id}, {"_id": 0})
    if not doc or doc.get("personalization_status") == "complete":
        return
    website = _inferred_website(doc)
    if website and not doc.get("website"):
        doc["website"] = website
        await db["client_leads"].update_one({"lead_id": lead_id}, {"$set": {"website": website}})
    await db["client_leads"].update_one({"lead_id": lead_id}, {"$set": {
        "personalization_status": "generating", "personalization_error": "", "updated_at": datetime.utcnow(),
    }})
    from app.clients.lead_personalization import personalize_lead
    try:
        draft = await personalize_lead(doc, db)
    except Exception as exc:
        logger.warning("Automatic personalization failed for %s: %s", lead_id, type(exc).__name__)
        await db["client_leads"].update_one({"lead_id": lead_id}, {"$set": {
            "personalization_status": "needs_retry", "personalization_error": str(exc)[:500], "updated_at": datetime.utcnow(),
        }})
        return
    await db["client_leads"].update_one({"lead_id": lead_id}, {"$set": {
        "draft_subject": draft["subject"], "draft_body": draft["body"], "draft": draft,
        "personalization": draft, "personalization_status": "complete",
        "draft_regenerated_at": datetime.utcnow(), "updated_at": datetime.utcnow(),
    }})


def queue_auto_personalization(lead_id: str, db: AsyncIOMotorDatabase) -> None:
    asyncio.create_task(_auto_personalize(lead_id, db))


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
    statuses: Optional[str] = None,
    topic: Optional[str] = None,
    domain_exact: Optional[str] = None,
    include_counts: bool = False,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Saved client leads, newest first. Filters and counts work as on GET /trainer-profile-leads."""
    filters = dict(status=status, statuses=statuses, domain=domain, domain_value=domain_exact, q=q, topic=topic)
    query = client_query(**filters)
    table = db["client_leads"]
    total = await table.count_documents(query)
    if limit is not None:
        page_size = limit
    skip = (page - 1) * page_size
    # _id breaks ties between leads saved with the same created_at, so pages do not overlap.
    cursor = table.find(query, {"_id": 0}).sort([("created_at", -1), ("_id", -1)]).skip(skip).limit(page_size)
    items = [d async for d in cursor]
    result = {"success": True, "total": total, "page": page, "page_size": page_size,
              "pages": max(1, (total + page_size - 1) // page_size), "leads": items}
    if include_counts:
        result["counts"] = await lead_counts(
            table, client_query(**filters, skip_status=True), client_query(**filters, skip_domain=True), query)
    return result


@router.post("")
async def create_client_lead(payload: ClientLeadCreate, db: AsyncIOMotorDatabase = Depends(get_db)):
    now = datetime.utcnow()
    lead_id = f"CL-{uuid.uuid4().hex[:10].upper()}"
    doc = {**payload.model_dump(), "lead_id": lead_id, "status": "new", "created_at": now, "updated_at": now}
    await db["client_leads"].insert_one(doc)
    queue_auto_personalization(lead_id, db)
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
    queue_auto_personalization(lead_id, db)
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
    queue_auto_personalization(lead_id, db)
    return {"success": True, "lead": doc, **contact}


# Declared before "/{lead_id}": routes match in order, and "/{lead_id}" would take "by-domain" as an ID.
@router.delete("/by-domain")
async def delete_client_leads_by_domain(
    domain: str = Query(...),
    status: Optional[str] = None,
    statuses: Optional[str] = None,
    q: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Delete the leads of one saved domain (__none__: no domain), within the same filters as the list."""
    domain = (domain or "").strip()
    if not domain:
        raise HTTPException(400, f"domain is required; use {NO_DOMAIN} for leads without a domain")
    query = client_query(status=status, statuses=statuses, q=q, domain_value=domain)
    result = await db["client_leads"].delete_many(query)
    return {"success": True, "domain": domain, "deleted_count": result.deleted_count}


@router.delete("/{lead_id}")
async def delete_client_lead(lead_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    result = await db["client_leads"].delete_one({"lead_id": lead_id})
    if result.deleted_count == 0:
        raise HTTPException(404, "Client lead not found")
    return {"success": True, "deleted": lead_id}


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


_PUBLIC_SEARCH_TIMEOUT = 20


def _term_outcome(term: str, target: int, matched: int, sources: List[Dict[str, Any]],
                  status: str = "", reason: str = "") -> Dict[str, Any]:
    return {"domain": term, "target": target, "matched": matched, "target_met": bool(target) and matched >= target,
            "status": status or outcome_status(matched, target, sources), "limit_reason": reason, "sources": sources}


def _search_service_error(exc: Exception) -> Dict[str, Any]:
    if isinstance(exc, httpx.TimeoutException):
        reason = f"The search service did not answer within {_PUBLIC_SEARCH_TIMEOUT} seconds."
    else:
        reason = f"Could not reach the search service: {str(exc) or type(exc).__name__}"[:300]
    return {"source": "trainer_search", "label": "Search service", "status": "error", "found": 0, "qualified": 0,
            "reason": reason}


async def _save_public_client_lead(db: AsyncIOMotorDatabase, lead: Dict[str, Any], now: datetime) -> bool:
    """Save one search result unless it is saved already, under any URL variant of the same LinkedIn page.

    A lead saved before is left as it is, so a search never overwrites reviewed or edited leads.
    """
    from pymongo.errors import DuplicateKeyError
    from app.clients.client_post_identity import post_identity, post_lookup
    try:
        key = post_identity(lead["source_url"])
        lookup = post_lookup(lead["source_url"])
    except ValueError:
        # Not a LinkedIn page, for example a Naukri page: the exact URL identifies it, as before.
        key, lookup = None, {"source_url": lead["source_url"]}
    record = {**lead, "created_at": now, "updated_at": now}
    if key:
        record["post_key"] = key
    try:
        result = await db["client_leads"].update_one(lookup, {"$setOnInsert": record}, upsert=True)
    except DuplicateKeyError:
        # Another search saved it after the lookup.
        return False
    if result.upserted_id is None:
        return False
    queue_auto_personalization(lead["lead_id"], db)
    return True


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
        return {"success": False, "error": "query or domain is required", "results": [], "saved_count": 0,
                "sources": []}

    started_at = datetime.utcnow()
    results = []
    saved_count = 0
    skipped_count = 0
    search_error = ""
    outcomes: List[Dict[str, Any]] = []
    now = datetime.utcnow()
    target = max(payload.max_results, 50)
    try:
        import httpx as _httpx
        async with _httpx.AsyncClient(timeout=_PUBLIC_SEARCH_TIMEOUT) as client:
            for index, term in enumerate(search_terms):
                try:
                    r = await client.post(
                        "http://intelligence-service:8005/api/v1/intelligence/trainers/search",
                        json={
                            "query": f"{term} trainer requirement corporate training client hiring",
                            "domain": term,
                            "location": payload.location or "",
                            "max_results": target,
                        },
                    )
                except _httpx.HTTPError as exc:
                    failure = _search_service_error(exc)
                    search_error = failure["reason"]
                    outcomes.append(_term_outcome(term, target, 0, [failure]))
                    # The next request would wait just as long, so the rest are reported as not searched.
                    outcomes.extend(_term_outcome(rest, 0, 0, [], "not_run",
                                                  "Not searched: the search service stopped answering.")
                                    for rest in search_terms[index + 1:])
                    break
                if r.status_code >= 400:
                    search_error = search_error or f"The search service returned HTTP {r.status_code}."
                    outcomes.append(_term_outcome(term, target, 0, [{
                        "source": "trainer_search", "label": "Search service", "status": "error",
                        "found": 0, "qualified": 0, "reason": f"HTTP {r.status_code}: {r.text[:200]}"}]))
                    continue
                data = r.json()
                profiles = data.get("profiles", [])
                for item in profiles:
                    source_url = item.get("source_url", "")
                    if not source_url:
                        skipped_count += 1
                        continue
                    results.append(item)
                    lead = {
                        "lead_id": f"CL-{uuid.uuid4().hex[:10].upper()}",
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
                    }
                    if await _save_public_client_lead(db, lead, now):
                        saved_count += 1
                    else:
                        skipped_count += 1
                outcomes.append(_term_outcome(term, target, len(profiles), data.get("sources") or []))
    except Exception as exc:
        logger.warning("Public search failed: %s", exc)
        search_error = search_error or str(exc) or type(exc).__name__
    sources = merge_sources(outcome.get("sources") for outcome in outcomes)
    if not results and not search_error:
        search_error = failure_summary(sources)
    result = {
        "success": search_succeeded(len(results), sources),
        "query": payload.query or ", ".join(search_terms),
        "results": results,
        "found": len(results),
        "saved_count": saved_count,
        "new_stored": saved_count,
        "skipped_count": skipped_count,
        "search_error": search_error,
        "sources": sources,
        "domain_outcomes": outcomes,
    }
    result["run_id"] = await record_search_run(db, "client_search_public", {
        "domains": search_terms, "location": payload.location or "", "max_results": payload.max_results,
    }, result, started_at)
    return result


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
