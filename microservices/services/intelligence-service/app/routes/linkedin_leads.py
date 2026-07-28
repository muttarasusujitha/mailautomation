"""Direct LinkedIn/Naukri lead search using the Tavily API key from env."""
import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.config import get_settings
from app.database import get_db

router = APIRouter()
logger = logging.getLogger(__name__)
EMAIL_SVC = "http://email-service:8002"
LOCAL_SERVICE_FALLBACKS = {
    "https://email-service:8002": "http://email-service:8002",
    "http://127.0.0.1:8002": "http://email-service:8002",
}
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]{2,64}@[A-Za-z0-9.\-]{2,253}\.[A-Za-z]{2,12}")
PHONE_RE = re.compile(r"(?:\+91|0091|91)?[\s.\-()]*(6[\d\s.\-()]{9,20}|7[\d\s.\-()]{9,20}|8[\d\s.\-()]{9,20}|9[\d\s.\-()]{9,20})")
BAD_EMAIL_LOCALS = {"noreply", "no-reply", "donotreply", "support", "admin", "info", "sales", "hr", "careers", "jobs"}


class LinkedInLeadSearchRequest(BaseModel):
    query: Optional[str] = ""
    domain: Optional[str] = ""
    domains: Optional[List[str]] = None
    location: Optional[str] = ""
    max_results: int = 10
    max_queries: Optional[int] = None
    save: bool = True
    mode: str = "trainer"
    source: Optional[str] = "linkedin"


class BackfillClientContactsRequest(BaseModel):
    limit: int = 50
    auto_send: bool = True
    recheck: bool = False
    external_lookup: bool = False


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


def _slug_from_url(url: str) -> str:
    linkedin = re.search(r"linkedin\.com/in/([a-zA-Z0-9\-_%]+)", url or "", re.IGNORECASE)
    if linkedin:
        return linkedin.group(1)
    return re.sub(r"[^a-zA-Z0-9]+", "-", (url or "").split("/", 3)[-1]).strip("-")[:80]


def _contact_name_from_linkedin_post(url: str) -> str:
    match = re.search(r"linkedin\.com/posts/([^_/]+)", url or "", re.IGNORECASE)
    if not match:
        return ""
    parts = [part for part in match.group(1).split("-") if part and not part.isdigit()]
    cleaned: List[str] = []
    for part in parts:
        if re.fullmatch(r"[a-f0-9]{6,}", part, re.IGNORECASE):
            break
        cleaned.append(part)
    if not cleaned:
        return ""
    return " ".join(word.capitalize() for word in cleaned[:4])


def _domain_terms(domain: str) -> List[str]:
    words = re.findall(r"[a-zA-Z0-9+#.]+", domain.lower())
    generic = {
        "trainer",
        "training",
        "corporate",
        "freelance",
        "technical",
        "online",
        "instructor",
        "consultant",
        "developer",
        "india",
        "indian",
    }
    terms = [word for word in words if len(word) > 1 and word not in generic]
    if "full" in terms and "stack" in terms:
        terms.append("full stack")
    return terms


def _extract_emails(text: str) -> List[str]:
    normalized = _normalize_contact_text(text)
    found = EMAIL_RE.findall(normalized)
    seen: set = set()
    emails: List[str] = []
    for email in found:
        key = email.lower()
        local = key.split("@", 1)[0]
        if local in BAD_EMAIL_LOCALS or key in seen:
            continue
        seen.add(key)
        emails.append(email)
    return emails


def _extract_phones(text: str) -> List[str]:
    phones: List[str] = []
    seen: set = set()
    normalized = _normalize_contact_text(text)
    for match in PHONE_RE.finditer(normalized):
        digits = re.sub(r"\D", "", match.group(1))
        if len(digits) > 10:
            digits = digits[-10:]
        if len(digits) == 10 and digits[0] in "6789":
            phone = f"+91{digits}"
            if phone not in seen:
                seen.add(phone)
                phones.append(phone)
    return phones


def _normalize_contact_text(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"(?i)\s*(?:\[|\()?at(?:\]|\))?\s*", "@", value)
    value = re.sub(r"(?i)\s*(?:\[|\()?dot(?:\]|\))?\s*", ".", value)
    value = re.sub(r"(?i)\s+at\s+", "@", value)
    value = re.sub(r"(?i)\s+dot\s+", ".", value)
    return value


def _best_email(text: str) -> str:
    emails = _extract_emails(text)
    personal_domains = {"gmail.com", "yahoo.com", "yahoo.co.in", "outlook.com", "hotmail.com", "rediffmail.com"}
    personal = [email for email in emails if email.split("@")[-1].lower() in personal_domains]
    return personal[0] if personal else (emails[0] if emails else "")


def _looks_like_resume_trainer_post(text: str) -> bool:
    return bool(
        re.search(r"\b(resume|cv|trainer profile|profile attached|sharing profile|contact me|email|phone)\b", text)
        and re.search(r"\b(trainer|instructor|training|corporate training|facilitator|coach)\b", text)
    )


def _looks_like_client_requirement_post(text: str) -> bool:
    return bool(
        re.search(r"\b(need|looking for|required|requirement|required|hiring|seeking)\b", text)
        and re.search(r"\b(trainer|instructor|corporate training|training vendor|facilitator)\b", text)
    )


def _result_text(item: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key in (
        "title",
        "name",
        "content",
        "raw_content",
        "snippet",
        "description",
        "answer",
        "summary",
    ):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return "\n".join(parts)


def _contact_update_fields(lead: Dict[str, Any]) -> Dict[str, Any]:
    updates: Dict[str, Any] = {}
    for key in ("email", "phone", "contact_email", "contact_phone", "contact_name", "post_text", "notes", "verification_tier", "confidence"):
        value = lead.get(key)
        if value:
            updates[key] = value
    return updates


def _client_mail(lead: Dict[str, Any]) -> Dict[str, str]:
    domain = lead.get("domain") or "your training"
    company = lead.get("company_name") or "your team"
    contact = lead.get("contact_name") or "Client"
    return {
        "subject": f"Trainer Support for {domain} Requirement",
        "body": (
            f"Dear {contact},\n\n"
            f"I saw your LinkedIn post about a {domain} trainer requirement for {company}.\n\n"
            "We are a training consultancy and can provide experienced corporate trainers for your requirement. "
            "Please share the training dates, duration, delivery mode, participant count, and commercials so we can send suitable trainer profiles.\n\n"
            "Regards,\nRecruitment Team\nClahan Technologies"
        ),
    }


async def _auto_send_client_mail(lead: Dict[str, Any], db: AsyncIOMotorDatabase, now: datetime) -> bool:
    email = lead.get("email") or lead.get("contact_email") or ""
    if not email:
        return False
    existing = await db["client_leads"].find_one(
        {"source_url": lead.get("source_url", "")},
        {"_id": 0, "status": 1, "last_emailed_at": 1, "auto_mail1_sent_at": 1},
    )
    if existing and (existing.get("last_emailed_at") or existing.get("auto_mail1_sent_at") or existing.get("status") == "contacted"):
        return False

    mail = _client_mail(lead)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await _post_with_local_fallback(
                client,
                f"{EMAIL_SVC}/api/v1/email/send",
                json={"to": email, "subject": mail["subject"], "body": mail["body"]},
            )
        success = resp.status_code < 400
    except Exception as exc:
        logger.warning("Auto Mail 1 failed for client lead %s: %s", lead.get("source_url"), exc)
        success = False

    await db["client_leads"].update_one(
        {"source_url": lead.get("source_url", "")},
        {"$set": {
            "status": "contacted" if success else "email_failed",
            "auto_mail1_sent_at": now if success else None,
            "last_emailed_at": now if success else None,
            "auto_mail1_error": "" if success else "Email delivery failed",
            "updated_at": now,
        }},
    )
    return success


def _normalize_result(item: Dict[str, Any], domain: str, mode: str) -> Optional[Dict[str, Any]]:
    url = item.get("url") or item.get("source_url") or item.get("link") or ""
    if not re.search(r"(linkedin\.com|naukri\.com)", url, re.IGNORECASE):
        return None

    source = "linkedin" if "linkedin.com" in url.lower() else "naukri"
    if mode == "client":
        if source != "linkedin":
            return None
        if not re.search(r"linkedin\.com/(posts|feed/update|pulse)/", url, re.IGNORECASE):
            return None
        if re.search(r"linkedin\.com/(jobs|in)/", url, re.IGNORECASE):
            return None
        combined_text = _result_text(item).lower()
        if not _looks_like_client_requirement_post(combined_text):
            return None
    title = item.get("title") or item.get("name") or ""
    raw_text = _result_text(item)
    snippet = raw_text or title
    combined_text = raw_text.lower()
    email = _best_email(raw_text)
    phone = (_extract_phones(raw_text) or [""])[0]
    if mode == "trainer":
        if re.search(r"\b(actively seeking|job seeker|looking for job|open to work|full-time role)\b", combined_text):
            return None
        is_profile = bool(re.search(r"linkedin\.com/in/", url, re.IGNORECASE))
        is_post = bool(re.search(r"linkedin\.com/(posts|feed/update|pulse)/", url, re.IGNORECASE))
        is_resume_post = is_post and _looks_like_resume_trainer_post(combined_text)
        if source == "linkedin" and not (is_profile or is_resume_post):
            return None
        if source == "linkedin" and not re.search(r"\b(trainer|instructor|corporate training|training consultant|facilitator|coach)\b", combined_text):
            return None
        terms = _domain_terms(domain)
        if terms and not any(term in combined_text for term in terms):
            return None
    slug = _slug_from_url(url)
    if mode == "client":
        contact_name = _contact_name_from_linkedin_post(url)
        return {
            "lead_id": f"CL-{uuid.uuid4().hex[:10].upper()}",
            "company_name": title,
            "contact_name": contact_name,
            "email": email,
            "phone": phone,
            "contact_email": email,
            "contact_phone": phone,
            "domain": domain,
            "source": source,
            "source_url": url,
            "linkedin_url": url if source == "linkedin" else "",
            "post_text": snippet[:5000],
            "notes": snippet[:1000],
            "status": "new",
            "lead_type": "client_requirement_post",
            "verification_tier": "contact_in_post" if email or phone else "linkedin_signal",
            "confidence": 0.88 if email or phone else 0.75,
        }

    return {
        "lead_id": f"TPL-{uuid.uuid4().hex[:10].upper()}",
        "name": title,
        "trainer_name": title,
        "headline": title,
        "email": email,
        "phone": phone,
        "contact_email": email,
        "contact_phone": phone,
        "domain": domain,
        "source": source,
        "source_url": url,
        "linkedin_url": url if source == "linkedin" else "",
        "linkedin_slug": slug if source == "linkedin" else "",
        "external_slug": slug,
        "snippet": snippet[:500],
        "profile_text": snippet[:5000],
        "status": "new",
        "lead_type": "resume_trainer_post" if re.search(r"linkedin\.com/(posts|feed/update|pulse)/", url, re.IGNORECASE) else "trainer_profile",
        "verification_tier": "contact_in_post" if email or phone else "linkedin_signal",
        "confidence": 0.9 if email or phone else 0.75,
    }


async def _plain_tavily_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    settings = get_settings()
    if not settings.TAVILY_API_KEY:
        raise RuntimeError("TAVILY_API_KEY is not configured")

    include_domains = ["linkedin.com", "naukri.com"]
    payload = {
        "query": query,
        "max_results": max(1, min(max_results, 20)),
        "search_depth": settings.TAVILY_SEARCH_DEPTH,
        "include_domains": include_domains,
    }
    headers = {
        "Authorization": f"Bearer {settings.TAVILY_API_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        primary_url = f"{settings.TAVILY_API_URL.rstrip('/')}/search"
        try:
            resp = await client.post(primary_url, json=payload, headers=headers)
        except httpx.HTTPError:
            resp = await client.post("https://api.tavily.com/search", json=payload, headers=headers)
        if resp.status_code == 404 and "api.tavily.dev" in settings.TAVILY_API_URL:
            resp = await client.post("https://api.tavily.com/search", json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    return data.get("results") or []


async def _find_existing_post_contact(lead: Dict[str, Any], external_lookup: bool = False) -> Dict[str, Any]:
    source_url = lead.get("source_url") or lead.get("linkedin_url") or ""
    saved_text = "\n".join(
        str(lead.get(key) or "")
        for key in ("post_text", "notes", "title", "description", "company_name", "domain")
    )
    email = _best_email(saved_text)
    phone = (_extract_phones(saved_text) or [""])[0]
    if email or phone:
        updates: Dict[str, Any] = {
            "verification_tier": "contact_in_saved_post_text",
            "confidence": max(float(lead.get("confidence") or 0), 0.88),
        }
        if email:
            updates["email"] = email
            updates["contact_email"] = email
        if phone:
            updates["phone"] = phone
            updates["contact_phone"] = phone
        return updates

    if not external_lookup:
        return {}

    search_terms = [
        source_url,
        " ".join(part for part in [
            lead.get("company_name") or "",
            lead.get("domain") or "",
            "email phone contact",
            "site:linkedin.com/posts OR site:linkedin.com/feed/update",
        ] if part),
    ]
    for query in [term for term in search_terms if term.strip()]:
        try:
            results = await _plain_tavily_search(query, 5)
        except Exception as exc:
            logger.warning("Backfill search failed for %s: %s", source_url or lead.get("lead_id"), exc)
            continue
        for item in results:
            if not isinstance(item, dict):
                continue
            item_url = item.get("url") or item.get("source_url") or item.get("link") or ""
            if source_url and item_url and item_url != source_url:
                if _slug_from_url(item_url) != _slug_from_url(source_url):
                    continue
            raw_text = _result_text(item)
            email = _best_email(raw_text)
            phone = (_extract_phones(raw_text) or [""])[0]
            if email or phone:
                updates: Dict[str, Any] = {
                    "post_text": raw_text[:5000],
                    "notes": raw_text[:1000],
                    "verification_tier": "contact_in_post",
                    "confidence": 0.88,
                }
                if email:
                    updates["email"] = email
                    updates["contact_email"] = email
                if phone:
                    updates["phone"] = phone
                    updates["contact_phone"] = phone
                return updates
    return {}


def _search_queries(domain: str, mode: str, location: str = "") -> List[str]:
    location_text = f" {location}" if location else ""
    if mode == "client":
        topic = domain.strip() or "trainer"
        return [
            (
                f'"{topic}" ("corporate trainer required" OR "trainer required" OR "training requirement"){location_text} '
                "site:linkedin.com/posts OR site:linkedin.com/feed/update "
                "-jobs -job -hiring -opening -vacancy -careers -jobseeker -resume"
            ),
            (
                f'"{topic}" ("looking for freelance trainer" OR "need trainer" OR "trainer needed"){location_text} '
                "site:linkedin.com/posts OR site:linkedin.com/feed/update "
                "-jobs -job -hiring -opening -vacancy -careers -jobseeker -resume"
            ),
            (
                f'"{topic}" ("looking for corporate trainer" OR "require trainer" OR "training vendor"){location_text} '
                "site:linkedin.com/posts OR site:linkedin.com/feed/update "
                "-jobs -job -hiring -opening -vacancy -careers -jobseeker -resume"
            ),
        ]

    base = f"{domain}{location_text}"
    return [
        f'"{base}" ("resume trainer" OR "trainer resume" OR "trainer profile") ("email" OR "phone" OR "contact") site:linkedin.com/posts -jobs -job -hiring -opening -vacancy -careers',
        f'"{base}" ("resume trainer" OR "trainer resume" OR "trainer profile") ("email" OR "phone" OR "contact") site:linkedin.com/feed/update -jobs -job -hiring -opening -vacancy -careers',
        f'"{base}" "corporate trainer" site:linkedin.com/in -jobs -job -hiring -opening -vacancy -careers',
        f'"{base}" "freelance trainer" site:linkedin.com/in -jobs -job -hiring -opening -vacancy -careers',
        f'"{base}" "technical trainer" site:linkedin.com/in -jobs -job -hiring -opening -vacancy -careers',
        f'"{base}" trainer instructor consultant site:linkedin.com/in -jobs -job -hiring -opening -vacancy -careers',
        f'"{base}" "online trainer" site:linkedin.com/in -jobs -job -hiring -opening -vacancy -careers',
        f'"{base}" "training consultant" site:linkedin.com/in -jobs -job -hiring -opening -vacancy -careers',
        f'"{base}" "corporate training" "India" site:linkedin.com/in -jobs -job -hiring -opening -vacancy -careers',
        f'"{base}" "trainer" "Bangalore" OR "Hyderabad" OR "Pune" site:linkedin.com/in -jobs -job -hiring -opening -vacancy -careers',
        f'"{base}" trainer instructor corporate training site:naukri.com -jobs -job -hiring -opening -vacancy -careers',
    ]


@router.post("/search")
async def search_linkedin_leads(
    payload: LinkedInLeadSearchRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    domains = [item.strip() for item in (payload.domains or []) if item and item.strip()]
    single = (payload.query or payload.domain or "").strip()
    if single and not domains:
        domains = [single]
    if not domains:
        return {"success": False, "error": "query, domain, or domains is required", "saved_count": 0, "results": []}

    now = datetime.utcnow()
    saved_count = 0
    auto_sent_count = 0
    skipped_count = 0
    all_results: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    seen_urls: set = set()

    mode = "client" if payload.mode == "client" else "trainer"

    target_results = max(1, min(payload.max_results, 100))
    query_budget = payload.max_queries or (1 if mode == "client" else 8)

    for domain in domains:
        raw_results: List[Dict[str, Any]] = []
        for query in _search_queries(domain, mode, payload.location or "")[:query_budget]:
            if len(all_results) >= target_results:
                break
            try:
                raw_results.extend(await _plain_tavily_search(query, min(20, target_results)))
            except Exception as exc:
                logger.warning("Direct Tavily LinkedIn search failed for %s: %s", domain, exc)
                return {
                    "success": False,
                    "error": str(exc),
                    "saved_count": saved_count,
                    "skipped_count": skipped_count,
                    "skipped": skipped[:20],
                    "results": all_results,
                }

        for item in raw_results:
            if len(all_results) >= target_results:
                break
            if not isinstance(item, dict):
                continue
            lead = _normalize_result(item, domain, mode)
            if not lead:
                skipped_count += 1
                skipped.append({"reason": "unsupported_result", "url": item.get("url") or item.get("link") or ""})
                continue
            source_url = lead.get("source_url", "")
            if source_url in seen_urls:
                skipped_count += 1
                skipped.append({"reason": "duplicate_in_search", "source_url": source_url, "source": lead.get("source", "")})
                continue
            seen_urls.add(source_url)
            all_results.append(lead)
            if not payload.save:
                continue
            if mode == "client":
                exists = await db["client_leads"].find_one({"source_url": lead["source_url"]}, {"_id": 1})
                if exists:
                    updates = _contact_update_fields(lead)
                    if updates:
                        updates["updated_at"] = now
                        await db["client_leads"].update_one({"source_url": lead["source_url"]}, {"$set": updates})
                    if lead.get("email") or lead.get("contact_email"):
                        if await _auto_send_client_mail(lead, db, now):
                            auto_sent_count += 1
                    skipped_count += 1
                    skipped.append({"reason": "already_saved_updated", "source_url": lead["source_url"], "source": lead.get("source", "")})
                    continue
                await db["client_leads"].insert_one({**lead, "created_at": now, "updated_at": now})
                if lead.get("email") or lead.get("contact_email"):
                    if await _auto_send_client_mail(lead, db, now):
                        auto_sent_count += 1
            else:
                dedupe_terms: List[Dict[str, str]] = []
                if lead.get("source_url"):
                    dedupe_terms.append({"source_url": lead["source_url"]})
                    if lead.get("source") == "linkedin":
                        dedupe_terms.append({"linkedin_url": lead["source_url"]})
                if lead.get("external_slug"):
                    dedupe_terms.append({"external_slug": lead["external_slug"]})
                if lead.get("linkedin_slug"):
                    dedupe_terms.append({"linkedin_slug": lead["linkedin_slug"]})

                exists = await db["trainer_profile_leads"].find_one(
                    {"$or": dedupe_terms},
                    {"_id": 1},
                )
                if exists:
                    updates = _contact_update_fields(lead)
                    if updates:
                        updates["updated_at"] = now
                        await db["trainer_profile_leads"].update_one(
                            {"$or": dedupe_terms},
                            {"$set": updates},
                        )
                    skipped_count += 1
                    skipped.append({"reason": "already_saved_updated", "source_url": lead["source_url"], "source": lead.get("source", "")})
                    continue
                await db["trainer_profile_leads"].insert_one({**lead, "created_at": now, "updated_at": now})
            saved_count += 1

    return {
        "success": True,
        "saved_count": saved_count,
        "auto_sent_count": auto_sent_count,
        "skipped_count": skipped_count,
        "skipped": skipped[:20],
        "found": len(all_results),
        "results": all_results,
    }


@router.post("/backfill-client-contacts")
async def backfill_client_contacts(
    payload: BackfillClientContactsRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    now = datetime.utcnow()
    query = {
        "source": "linkedin",
        "$or": [
            {"email": {"$in": ["", None]}},
            {"phone": {"$in": ["", None]}},
            {"contact_email": {"$in": ["", None]}},
            {"contact_phone": {"$in": ["", None]}},
        ],
    }
    if not payload.recheck:
        query["contact_backfill_checked_at"] = {"$exists": False}
    leads = await db["client_leads"].find(query, {"_id": 0}).sort("created_at", -1).limit(max(1, min(payload.limit, 100))).to_list(length=None)
    updated_count = 0
    auto_sent_count = 0
    checked = 0
    no_contact_count = 0
    for lead in leads:
        checked += 1
        updates = await _find_existing_post_contact(lead, payload.external_lookup)
        contact_name = _contact_name_from_linkedin_post(lead.get("source_url") or lead.get("linkedin_url") or "")
        if contact_name and not lead.get("contact_name"):
            updates["contact_name"] = contact_name
        updates["contact_backfill_checked_at"] = now
        if not (updates.get("email") or updates.get("phone") or updates.get("contact_email") or updates.get("contact_phone")):
            updates["contact_backfill_note"] = "No email or phone found in available post text/search result"
            no_contact_count += 1
        updates["updated_at"] = now
        await db["client_leads"].update_one({"lead_id": lead["lead_id"]}, {"$set": updates})
        if updates.get("email") or updates.get("phone") or updates.get("contact_email") or updates.get("contact_phone") or updates.get("contact_name"):
            updated_count += 1
        merged = {**lead, **updates}
        if payload.auto_send and (merged.get("email") or merged.get("contact_email")):
            if await _auto_send_client_mail(merged, db, now):
                auto_sent_count += 1

    return {
        "success": True,
        "checked": checked,
        "updated_count": updated_count,
        "auto_sent_count": auto_sent_count,
        "no_contact_count": no_contact_count,
    }
