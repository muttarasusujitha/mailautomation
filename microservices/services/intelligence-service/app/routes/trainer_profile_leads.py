"""Trainer profile leads — LinkedIn and public enrichment pipeline."""
import logging
import hashlib
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from app.clients.lead_identity import lead_key, save_trainer_lead, trainer_lead_key
from app.clients.lead_queries import NO_DOMAIN, TRAINER_KINDS, lead_counts, trainer_query
from app.clients.search_runs import (
    failure_summary,
    merge_sources,
    outcome_status,
    record_search_run,
    search_succeeded,
)
from shared.database.service import get_db

router = APIRouter()
logger = logging.getLogger(__name__)
EMAIL_SVC = "http://email-service:8002"
EMAIL_ADDRESS_RE = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
# Pages that track a sent mail as "contacted" ask for that status; the Pipeline keeps "outreach_sent".
SENT_STATUSES = ("outreach_sent", "contacted")
# A send moves only these statuses on. Later stages and decisions (converted, rejected) are kept.
NOT_CONTACTED_STATUSES = ("", "new", "found", "reviewed", "outreach_failed")
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
    max_results: int = 50
    max_queries: Optional[int] = None
    # An ID from the page, saved with the run report (GET /linkedin-leads/search-runs?search_ref=...).
    search_ref: Optional[str] = ""


class ResdexImportRequest(BaseModel):
    candidates: List[Dict[str, Any]] = Field(min_length=1, max_length=500)


class SendOutreachRequest(BaseModel):
    # Required by the bulk endpoint only; one lead's send-email takes the lead from the URL.
    lead_ids: List[str] = Field(default_factory=list)
    # An address typed on the page for a lead without a saved email.
    to_email: Optional[str] = ""
    subject: Optional[str] = ""
    body: Optional[str] = ""
    # Status after a successful send: "outreach_sent" (default) or "contacted".
    sent_status: Optional[str] = ""
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
    source: Optional[str] = None,
    q: Optional[str] = None,
    statuses: Optional[str] = None,
    kind: Optional[str] = None,
    has_contact: bool = False,
    topic: Optional[str] = None,
    requirement_scope: Optional[str] = None,
    domain_exact: Optional[str] = None,
    include_counts: bool = False,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Saved trainer leads, newest first.

    statuses: comma list of statuses to include. kind: linkedin_profile, linkedin, shortlist or
    naukri_profile, the filters of the LinkedIn Search, Pipeline, Shortlist and Naukri pages.
    topic: text that the domain or profile text must contain. requirement_scope: leads of that
    requirement or of none. domain_exact: one saved domain, or __none__ for leads without one.
    include_counts adds counts.by_status, counts.by_domain and the contact counts.
    """
    if kind and kind not in TRAINER_KINDS:
        raise HTTPException(400, f"kind must be one of: {', '.join(TRAINER_KINDS)}")
    filters = dict(status=status, statuses=statuses, domain=domain, domain_value=domain_exact,
                   requirement_id=requirement_id, requirement_scope=requirement_scope, source=source, q=q,
                   kind=kind, has_contact=has_contact, topic=topic)
    query = trainer_query(**filters)
    table = db["trainer_profile_leads"]
    total = await table.count_documents(query)
    if limit is not None:
        page_size = limit
    skip = (page - 1) * page_size
    # _id breaks ties: one search saves many leads with the same created_at, and pages must not overlap.
    cursor = table.find(query, {"_id": 0}).sort([("created_at", -1), ("_id", -1)]).skip(skip).limit(page_size)
    items = [d async for d in cursor]
    result = {"success": True, "total": total, "page": page, "page_size": page_size,
              "pages": max(1, (total + page_size - 1) // page_size), "leads": items}
    if include_counts:
        result["counts"] = await lead_counts(
            table, trainer_query(**filters, skip_status=True), trainer_query(**filters, skip_domain=True), query)
    return result


@router.post("")
async def create_trainer_lead(payload: TrainerLeadCreate, db: AsyncIOMotorDatabase = Depends(get_db)):
    now = datetime.utcnow()
    lead_id = f"TPL-{uuid.uuid4().hex[:10].upper()}"
    doc = {**payload.model_dump(), "lead_id": lead_id, "status": "found",
           "verification_tier": "unverified", "created_at": now, "updated_at": now}
    key = lead_key(doc)
    if key:
        doc["profile_key"] = key
    try:
        await db["trainer_profile_leads"].insert_one(doc)
    except DuplicateKeyError as exc:
        saved = await db["trainer_profile_leads"].find_one({"profile_key": key}, {"_id": 0, "lead_id": 1})
        raise HTTPException(409, f"This profile is already saved as {(saved or {}).get('lead_id', 'another lead')}") from exc
    doc.pop("_id", None)
    return {"success": True, "lead_id": lead_id, "lead": doc}


@router.post("/import-resdex")
async def import_resdex_candidates(payload: ResdexImportRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Import rows the recruiter exported from their authorized Naukri Resdex account."""
    table = db["trainer_profile_leads"]
    now = datetime.utcnow()
    imported = duplicates = skipped = 0
    for row in payload.candidates:
        name = str(row.get("name") or "").strip()[:200]
        if not name:
            skipped += 1
            continue
        email = str(row.get("email") or "").strip()[:254]
        if email and not EMAIL_ADDRESS_RE.fullmatch(email):
            email = ""
        phone = str(row.get("phone") or "").strip()[:40]
        headline = str(row.get("headline") or "").strip()[:300]
        company = str(row.get("company") or "").strip()[:200]
        location = str(row.get("location") or "").strip()[:200]
        experience = str(row.get("experience") or "").strip()[:100]
        domain = str(row.get("skills") or row.get("domain") or "").strip()[:500]
        summary = str(row.get("summary") or "").strip()[:5000]
        profile_url = str(row.get("profile_url") or "").strip()[:1000]
        try:
            parsed = urlsplit(profile_url)
            host = (parsed.hostname or "").lower()
            if parsed.scheme not in ("http", "https") or not (host == "naukri.com" or host.endswith(".naukri.com")):
                profile_url = ""
        except ValueError:
            profile_url = ""
        identity = ("url:" + trainer_lead_key(profile_url)) if profile_url else (
            "email:" + email.lower() if email else "row:" + "|".join(
                part.lower() for part in (name, phone, headline, company)
            )
        )
        import_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        if await table.find_one({"import_key": import_key}, {"_id": 1}):
            duplicates += 1
            continue
        doc = {
            "lead_id": f"TPL-{uuid.uuid4().hex[:10].upper()}", "name": name,
            "trainer_name": name, "headline": headline, "company": company,
            "location": location, "experience": experience, "domain": domain,
            "email": email, "contact_email": email, "phone": phone, "contact_phone": phone,
            "source_url": profile_url, "snippet": summary or headline,
            "profile_text": summary or headline, "source": "naukri", "import_method": "resdex_export",
            "import_key": import_key, "status": "found", "verification_tier": "unverified",
            "created_at": now, "updated_at": now,
        }
        if profile_url:
            key = lead_key(doc)
            if key:
                doc["profile_key"] = key
        try:
            await table.insert_one(doc)
            imported += 1
        except DuplicateKeyError:
            duplicates += 1
    return {"success": True, "received": len(payload.candidates), "imported": imported,
            "duplicates": duplicates, "skipped": skipped}


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


# Declared before "/{lead_id}": routes match in order, and "/{lead_id}" would take "by-domain" as an ID.
@router.delete("/by-domain")
async def delete_trainer_leads_by_domain(
    domain: str = Query(...),
    status: Optional[str] = None,
    statuses: Optional[str] = None,
    kind: Optional[str] = None,
    source: Optional[str] = None,
    q: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Delete the leads of one saved domain (__none__: no domain), within the same filters as the list.

    Passing the page's kind, status and q deletes exactly the leads its domain chip counted.
    """
    domain = (domain or "").strip()
    if not domain:
        raise HTTPException(400, f"domain is required; use {NO_DOMAIN} for leads without a domain")
    if kind and kind not in TRAINER_KINDS:
        raise HTTPException(400, f"kind must be one of: {', '.join(TRAINER_KINDS)}")
    query = trainer_query(status=status, statuses=statuses, kind=kind, source=source, q=q, domain_value=domain)
    result = await db["trainer_profile_leads"].delete_many(query)
    return {"success": True, "domain": domain, "deleted_count": result.deleted_count}


@router.delete("/{lead_id}")
async def delete_trainer_lead(lead_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    result = await db["trainer_profile_leads"].delete_one({"lead_id": lead_id})
    if result.deleted_count == 0:
        raise HTTPException(404, "Trainer profile lead not found")
    return {"success": True, "deleted": lead_id}


_TRAINER_SEARCH_TIMEOUT = 30


def _search_items(payload: SearchPublicRequest) -> List[Dict[str, str]]:
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

    # The Pipeline sends the same text as query and domain. Search it once.
    unique: List[Dict[str, str]] = []
    seen = set()
    for item in search_items:
        key = (item["query"].lower(), item["domain"].lower())
        if key not in seen:
            seen.add(key)
            unique.append(item)
    max_queries = payload.max_queries or len(unique)
    return unique[:max_queries]


def _item_outcome(item: Dict[str, str], target: int, matched: int, sources: List[Dict[str, Any]],
                  status: str = "", reason: str = "") -> Dict[str, Any]:
    return {"domain": item["domain"], "query": item["query"], "target": target, "matched": matched,
            "target_met": bool(target) and matched >= target,
            "status": status or outcome_status(matched, target, sources),
            "limit_reason": reason, "sources": sources}


def _service_error(exc: Exception) -> Dict[str, Any]:
    if isinstance(exc, httpx.TimeoutException):
        reason = f"The trainer search service did not answer within {_TRAINER_SEARCH_TIMEOUT} seconds."
    else:
        reason = f"Could not reach the trainer search service: {str(exc) or type(exc).__name__}"[:300]
    return {"source": "trainer_search", "label": "Trainer search service", "status": "error",
            "found": 0, "qualified": 0, "reason": reason}


@router.post("/search-public")
async def search_public_trainer_leads(payload: SearchPublicRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Search the requested public source for matching profile links and store leads.

    The response lists each source's outcome (sources, and per domain in domain_outcomes),
    and the run is saved to lead_search_runs.
    """
    started_at = datetime.utcnow()
    search_items = _search_items(payload)
    if not search_items:
        return {
            "success": False,
            "error": "query or domain is required",
            "found": 0,
            "new_stored": 0,
            "saved_count": 0,
            "skipped_count": 0,
            "skipped": [],
            "sources": [],
        }

    profiles = []
    search_error = ""
    outcomes: List[Dict[str, Any]] = []
    requested_source = (payload.source or "linkedin").strip().lower()
    source_domain = {"naukri": "naukri.com", "linkedin": "linkedin.com"}.get(requested_source)
    if not source_domain:
        raise HTTPException(400, "source must be linkedin or naukri")
    result_limit = min(max(int(payload.max_results or 10), 10), 30) if requested_source == "naukri" else max(int(payload.max_results or 50), 50)
    logger.info(
        "Trainer lead search started: source=%s provider=%s queries=%s limit=%s",
        requested_source,
        "public_naukri_index" if requested_source == "naukri" else "public_search",
        len(search_items),
        result_limit,
    )
    try:
        if requested_source == "naukri":
            from app.clients.naukri_public_search import search_public_naukri_profiles
            remainder = result_limit
            for index, item in enumerate(search_items):
                if remainder <= 0:
                    outcomes.append(_item_outcome(item, 0, 0, [], "not_needed",
                                                  "Not searched: the requested number of profiles was already found."))
                    continue
                queries_left = len(search_items) - index
                requested = min(max(1, (remainder + queries_left - 1) // queries_left), remainder)
                item_report: Dict[str, Any] = {}
                found = await search_public_naukri_profiles(item["domain"], payload.location or "", requested,
                                                            report=item_report)
                for profile in found:
                    profile["source"] = "naukri"
                    profile["_searched_domain"] = item["domain"]
                    profiles.append(profile)
                outcomes.append(_item_outcome(item, requested, len(found), item_report.get("sources") or []))
                remainder = result_limit - len(profiles)
        else:
            async with httpx.AsyncClient(timeout=_TRAINER_SEARCH_TIMEOUT) as client:
                for index, item in enumerate(search_items):
                    try:
                        r = await client.post(
                            "http://intelligence-service:8005/api/v1/intelligence/trainers/search",
                            json={
                                "query": item["query"],
                                "domain": item["domain"],
                                "location": payload.location or "",
                                "max_results": result_limit,
                                "save_leads": False,
                                "include_domains": [source_domain],
                            },
                        )
                    except httpx.HTTPError as exc:
                        failure = _service_error(exc)
                        search_error = failure["reason"]
                        outcomes.append(_item_outcome(item, result_limit, 0, [failure]))
                        # The next request would wait just as long, so the rest are reported as not searched.
                        outcomes.extend(_item_outcome(rest, 0, 0, [], "not_run",
                                                      "Not searched: the trainer search service stopped answering.")
                                        for rest in search_items[index + 1:])
                        logger.warning("Trainer search request failed: %s", failure["reason"])
                        break
                    if r.status_code < 400:
                        search_result = r.json()
                        if search_result.get("search_error"):
                            search_error = str(search_result["search_error"])
                        matched = 0
                        for profile in search_result.get("profiles", []):
                            host = (urlsplit(str(profile.get("source_url") or "")).hostname or "").lower()
                            if not (host == source_domain or host.endswith("." + source_domain)):
                                continue
                            profile["source"] = requested_source
                            profile["_searched_domain"] = item["domain"]
                            profiles.append(profile)
                            matched += 1
                        outcomes.append(_item_outcome(item, result_limit, matched, search_result.get("sources") or []))
                    else:
                        search_error = r.text[:300]
                        outcomes.append(_item_outcome(item, result_limit, 0, [{
                            "source": "trainer_search", "label": "Trainer search service", "status": "error",
                            "found": 0, "qualified": 0, "reason": f"HTTP {r.status_code}: {r.text[:200]}"}]))
    except Exception as exc:
        search_error = str(exc) or type(exc).__name__
        logger.warning("Public search failed: %s", exc)

    now = datetime.utcnow()
    new_count = 0
    skipped: List[Dict[str, Any]] = []
    seen_keys: set = set()
    sources = merge_sources(outcome.get("sources") for outcome in outcomes)
    if requested_source == "naukri":
        # The requested range applies to the whole batch, not independently to
        # each query/domain in the batch.
        profiles = profiles[:result_limit]
    if not profiles and not search_error:
        search_error = failure_summary(sources)
    if requested_source == "naukri" and not profiles and not search_error:
        search_error = (
            "No publicly indexed Naukri job-seeker profiles were found for these skills and location. "
            "Try broader terms. Private resumes require recruiter Resdex access."
        )
    for p in profiles:
        slug = p.get("slug", "")
        source_url = p.get("source_url", "")
        source = p.get("source", requested_source)
        if source != requested_source:
            skipped.append({"reason": "wrong_source", "source_url": source_url, "source": source})
            continue
        if not slug and not source_url:
            skipped.append({"reason": "missing_identifier", "title": p.get("title", ""), "source": source})
            continue
        identity = trainer_lead_key(source_url) or source_url or slug
        if identity in seen_keys:
            skipped.append({"reason": "duplicate_in_search", "source_url": source_url, "source": source})
            continue
        seen_keys.add(identity)

        saved = await save_trainer_lead(db, {
            "lead_id": f"TPL-{uuid.uuid4().hex[:10].upper()}",
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
        }, now)
        if not saved["created"]:
            skipped.append({"reason": "already_saved", "source_url": source_url, "slug": slug, "source": source,
                            "lead_id": saved["lead_id"]})
            continue
        new_count += 1
    logger.info(
        "Trainer lead search finished: source=%s provider=%s found=%s saved=%s error=%s",
        requested_source,
        "public_naukri_index" if requested_source == "naukri" else "public_search",
        len(profiles),
        new_count,
        bool(search_error),
    )
    result = {
        "success": search_succeeded(len(profiles), sources),
        "found": len(profiles),
        "new_stored": new_count,
        "saved_count": new_count,
        "skipped_count": len(skipped),
        "skipped": skipped[:20],
        "search_error": search_error,
        "sources": sources,
        "domain_outcomes": outcomes,
    }
    result["run_id"] = await record_search_run(db, "naukri_search" if requested_source == "naukri" else "trainer_search_public", {
        "source": requested_source,
        "domains": [item["domain"] for item in search_items],
        "queries": [item["query"] for item in search_items],
        "location": payload.location or "",
        "max_results": payload.max_results,
        "requirement_id": payload.requirement_id or "",
    }, result, started_at, payload.search_ref)
    return result


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
    failed = 0
    error = ""
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
            else:
                failed += 1
                error = error or f"The contact lookup returned HTTP {r.status_code}."
        except Exception as exc:
            failed += 1
            error = error or f"The contact lookup failed: {str(exc) or type(exc).__name__}"[:300]
            logger.warning("Enrich failed for %s: %s", lead.get("lead_id"), exc)
    # A lookup that answered without an email is not a failure; every lookup failing is.
    return {"success": not leads or failed < len(leads), "checked": len(leads), "enriched": enriched,
            "failed": failed, "error": error}


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
    typed_email = (payload.to_email or "").strip()
    if typed_email and not EMAIL_ADDRESS_RE.fullmatch(typed_email):
        raise HTTPException(400, "Enter a valid email address")
    saved_email = str(doc.get("email") or doc.get("contact_email") or "").strip()
    to_email = typed_email or saved_email
    if not to_email:
        raise HTTPException(400, "No email found for this lead")
    sent_status = payload.sent_status if payload.sent_status in SENT_STATUSES else "outreach_sent"
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
    if not success:
        # The status stays as it was: no page lists a failed status, so the lead would disappear.
        await db["trainer_profile_leads"].update_one(
            {"lead_id": lead_id},
            {"$set": {"last_email_error": f"Email delivery failed (HTTP {r.status_code})",
                      "last_email_failed_at": now, "updated_at": now}},
        )
        raise HTTPException(502, "Email delivery failed")
    updates: Dict[str, Any] = {"last_emailed_at": now, "updated_at": now, "last_email_error": ""}
    status = str(doc.get("status") or "")
    if status in NOT_CONTACTED_STATUSES:
        updates["status"] = status = sent_status
    if typed_email and not saved_email:
        updates["email"] = typed_email
        updates["contact_email"] = typed_email
    await db["trainer_profile_leads"].update_one({"lead_id": lead_id}, {"$set": updates})
    return {"success": True, "lead_id": lead_id, "sent_to": to_email, "status": status}


@router.post("/send-public-email-outreach")
async def send_public_email_outreach(payload: SendOutreachRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Send outreach emails to a list of leads in bulk. Each lead is sent to its own saved email.

    Leads that were contacted already, or converted or rejected, are skipped, so sending the
    same list again (for example after a gateway timeout) does not email anyone twice.
    """
    if not payload.lead_ids:
        raise HTTPException(400, "lead_ids is required")
    sent_status = payload.sent_status if payload.sent_status in SENT_STATUSES else "outreach_sent"
    sent = failed = skipped = 0
    errors: List[Dict[str, str]] = []
    for lead_id in dict.fromkeys(payload.lead_ids):
        saved = await db["trainer_profile_leads"].find_one({"lead_id": lead_id}, {"_id": 0, "status": 1})
        if saved is not None:
            previous = saved.get("status")
            if str(previous or "") not in NOT_CONTACTED_STATUSES:
                skipped += 1
                continue
            # Claim the lead before mailing it: the update matches only while the status is unchanged,
            # so a second request for the same lead (another tab, a retry) skips it instead of mailing again.
            claim = await db["trainer_profile_leads"].update_one(
                {"lead_id": lead_id, "status": previous},
                {"$set": {"status": sent_status, "outreach_claimed_at": datetime.utcnow()}},
            )
            if not claim.matched_count:
                skipped += 1
                continue
        try:
            req = SendOutreachRequest(lead_ids=[lead_id], subject=payload.subject, body=payload.body,
                                      sent_status=payload.sent_status)
            await send_lead_outreach(lead_id, req, db)
            sent += 1
        except Exception as exc:
            if saved is not None:
                # Not sent: give the lead its status back, so it can be sent later.
                await db["trainer_profile_leads"].update_one(
                    {"lead_id": lead_id, "status": sent_status}, {"$set": {"status": previous or "new"}})
            if not isinstance(exc, HTTPException):
                logger.exception("Outreach to %s failed", lead_id)
            failed += 1
            errors.append({"lead_id": lead_id, "error": str(getattr(exc, "detail", None) or exc or type(exc).__name__)})
    return {"success": True, "sent": sent, "failed": failed, "skipped": skipped, "errors": errors[:20]}
