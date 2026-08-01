"""People Search & Contact Intelligence orchestration.

Phase 1 focuses on provider planning, public search, normalization,
deduplication, ranking, and optional persistence. It deliberately avoids
direct scraping of restricted profile sites.
"""
import asyncio
import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from app.config import get_settings
from app.database import get_db

router = APIRouter()
logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]{2,64}@[A-Za-z0-9.\-]{2,253}\.[A-Za-z]{2,12}")
PHONE_RE = re.compile(r"(?:\+91|0091|91)?[\s.\-()]*([6-9]\d{2}[\s.\-]*\d{3}[\s.\-]*\d{4})")

PROVIDER_DOMAINS = {
    "internal_db": [],
    "linkedin": ["linkedin.com"],
    "naukri": ["naukri.com"],
    "github": ["github.com"],
    "portfolio": [],
    "company": [],
    "web": [],
}


class PeopleSearchRequest(BaseModel):
    query: str = Field(..., min_length=2)
    role: Optional[str] = ""
    technology: Optional[str] = ""
    location: Optional[str] = ""
    company: Optional[str] = ""
    max_results: int = 10
    providers: Optional[List[str]] = None
    save: bool = False
    enrich_contacts: bool = True


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _domain_from_url(url: str) -> str:
    match = re.search(r"https?://(?:www\.)?([^/]+)/?", url or "", flags=re.IGNORECASE)
    return (match.group(1).lower() if match else "").replace("www.", "")


def _source_from_url(url: str) -> str:
    domain = _domain_from_url(url)
    if "linkedin.com" in domain:
        return "linkedin"
    if "naukri.com" in domain:
        return "naukri"
    if "github.com" in domain:
        return "github"
    if domain:
        return "web"
    return "unknown"


def _emails(text: str) -> List[str]:
    seen = set()
    out = []
    for email in EMAIL_RE.findall(text or ""):
        key = email.lower()
        if key not in seen:
            seen.add(key)
            out.append(email)
    return out


def _phones(text: str) -> List[str]:
    seen = set()
    out = []
    for match in PHONE_RE.finditer(text or ""):
        digits = re.sub(r"\D", "", match.group(1))
        if len(digits) == 10 and digits[0] in "6789":
            phone = f"+91{digits}"
            if phone not in seen:
                seen.add(phone)
                out.append(phone)
    return out


def _planned_providers(payload: PeopleSearchRequest) -> List[str]:
    if payload.providers:
        requested = [p.lower().strip() for p in payload.providers if p.strip()]
        providers = [p for p in requested if p in PROVIDER_DOMAINS] or ["internal_db"]
        if "internal_db" not in providers:
            providers.insert(0, "internal_db")
        return providers

    query = " ".join([payload.query, payload.role or "", payload.technology or "", payload.company or ""]).lower()
    providers = ["internal_db", "web", "linkedin"]
    if any(word in query for word in ["trainer", "developer", "engineer", "consultant", "instructor"]):
        providers.extend(["github", "naukri"])
    if payload.company:
        providers.append("company")
    if any(word in query for word in ["github", "code", "repository", "open source"]):
        providers.append("github")
    return list(dict.fromkeys(providers))


def _search_terms(payload: PeopleSearchRequest) -> List[str]:
    terms = []
    for value in [payload.query, payload.role, payload.technology, payload.location, payload.company]:
        for part in re.split(r"[,/|]+|\s{2,}", value or ""):
            part = _clean(part)
            if len(part) >= 2 and part.lower() not in {"find", "trainer", "trainers", "profile", "contact"}:
                terms.append(part)
    return list(dict.fromkeys(terms))


def _provider_query(payload: PeopleSearchRequest, provider: str) -> str:
    parts = [
        payload.query,
        payload.role or "",
        payload.technology or "",
        payload.company or "",
        payload.location or "",
    ]
    base = " ".join(part for part in parts if part).strip()
    if provider == "linkedin":
        return f'{base} site:linkedin.com/in'
    if provider == "naukri":
        return f'{base} site:naukri.com trainer profile'
    if provider == "github":
        return f'{base} site:github.com'
    if provider == "company":
        return f'{base} company profile contact trainer'
    return f'{base} trainer profile contact email phone portfolio'


async def _tavily_search(query: str, provider: str, limit: int) -> Dict[str, Any]:
    settings = get_settings()
    if not settings.TAVILY_API_KEY:
        return {"provider": provider, "success": False, "error": "TAVILY_API_KEY is not configured", "results": []}

    payload: Dict[str, Any] = {
        "query": query,
        "max_results": max(1, min(limit, 20)),
        "search_depth": settings.TAVILY_SEARCH_DEPTH,
    }
    domains = PROVIDER_DOMAINS.get(provider) or []
    if domains:
        payload["include_domains"] = domains

    headers = {"Authorization": f"Bearer {settings.TAVILY_API_KEY}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            resp = await client.post(f"{settings.TAVILY_API_URL.rstrip('/')}/search", json=payload, headers=headers)
            if resp.status_code == 404 and "api.tavily.dev" in settings.TAVILY_API_URL:
                resp = await client.post("https://api.tavily.com/search", json=payload, headers=headers)
            resp.raise_for_status()
            return {"provider": provider, "success": True, "error": "", "results": resp.json().get("results", []) or []}
    except Exception as exc:
        logger.warning("People search provider %s failed: %s", provider, exc)
        return {"provider": provider, "success": False, "error": str(exc), "results": []}


async def _internal_search(db: AsyncIOMotorDatabase, payload: PeopleSearchRequest, limit: int) -> Dict[str, Any]:
    terms = _search_terms(payload)
    clauses = []
    for term in terms:
        regex = {"$regex": re.escape(term), "$options": "i"}
        clauses.extend([
            {"name": regex},
            {"trainer_name": regex},
            {"title": regex},
            {"headline": regex},
            {"domain": regex},
            {"technologies": regex},
            {"skills": regex},
            {"resume": regex},
            {"snippet": regex},
            {"profile_text": regex},
            {"location": regex},
            {"company": regex},
        ])
    query = {"$or": clauses} if clauses else {}
    projection = {"_id": 0}
    per_collection = max(5, min(limit, 50))
    trainers = await db.trainers.find(query, projection).limit(per_collection).to_list(per_collection)
    leads = await db.trainer_profile_leads.find(query, projection).limit(per_collection).to_list(per_collection)
    return {
        "provider": "internal_db",
        "success": True,
        "error": "",
        "results": [{"_collection": "trainers", **doc} for doc in trainers]
        + [{"_collection": "trainer_profile_leads", **doc} for doc in leads],
    }


def _name_guess(title: str, url: str) -> str:
    title = re.sub(r"\s*[-|]\s*(LinkedIn|GitHub|Naukri|Profile).*$", "", title or "", flags=re.IGNORECASE).strip()
    if title:
        return title[:120]
    slug = re.sub(r"[-_]+", " ", (url or "").rstrip("/").split("/")[-1]).strip()
    return slug.title()[:120]


def _normalize_result(item: Dict[str, Any], provider: str) -> Dict[str, Any]:
    if provider == "internal_db":
        source_url = _clean(item.get("source_url") or item.get("linkedin_url") or item.get("linkedin") or item.get("github") or "")
        source = _source_from_url(source_url) if source_url else _clean(item.get("source") or item.get("_collection") or "internal_db")
        skills = item.get("skills") or []
        if isinstance(skills, str):
            skills = [part.strip() for part in re.split(r"[,/|]+", skills) if part.strip()]
        name = _clean(item.get("trainer_name") or item.get("name") or item.get("headline"))
        title = _clean(item.get("title") or item.get("headline") or item.get("designation") or item.get("domain"))
        snippet = _clean(item.get("profile_text") or item.get("snippet") or item.get("resume") or title)
        email = _clean(item.get("email") or item.get("email_id"))
        phone = _clean(item.get("phone") or item.get("mobile") or item.get("contact"))
        return {
            "lead_id": _clean(item.get("lead_id") or item.get("trainer_id") or f"PS-{uuid.uuid4().hex[:10].upper()}"),
            "name": name or _name_guess(title, source_url),
            "designation": title,
            "company": _clean(item.get("company")),
            "location": _clean(item.get("location") or item.get("city")),
            "skills": skills,
            "experience": _clean(item.get("experience") or item.get("experience_years") or item.get("years_experience")),
            "profiles": {source: source_url} if source_url else {},
            "contacts": {"email": email, "phone": phone},
            "source": source,
            "source_url": source_url,
            "snippet": snippet[:500],
            "confidence": int(float(item.get("confidence") or 0) * 100) if isinstance(item.get("confidence"), float) else int(item.get("match_score") or 0),
            "raw_sources": [{"provider": provider, "collection": item.get("_collection"), "id": item.get("lead_id") or item.get("trainer_id")}],
        }

    url = _clean(item.get("url") or item.get("source_url") or item.get("link"))
    title = _clean(item.get("title") or item.get("name"))
    snippet = _clean(item.get("content") or item.get("snippet") or item.get("description"))
    text = f"{title} {snippet}"
    emails = _emails(text)
    phones = _phones(text)
    source = _source_from_url(url) if url else provider
    return {
        "lead_id": f"PS-{uuid.uuid4().hex[:10].upper()}",
        "name": _name_guess(title, url),
        "designation": title,
        "company": "",
        "location": "",
        "skills": [],
        "experience": "",
        "profiles": {source: url} if url else {},
        "contacts": {"email": emails[0] if emails else "", "phone": phones[0] if phones else ""},
        "source": source,
        "source_url": url,
        "snippet": snippet[:500],
        "confidence": 0,
        "raw_sources": [{"provider": provider, "url": url, "title": title}],
    }


def _dedupe_key(profile: Dict[str, Any]) -> str:
    url = profile.get("source_url") or ""
    if url:
        return re.sub(r"/+$", "", url.lower())
    return "|".join([
        _clean(profile.get("name")).lower(),
        _clean(profile.get("designation")).lower(),
        _clean(profile.get("snippet")).lower()[:80],
    ])


def _merge_profiles(profiles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for profile in profiles:
        key = _dedupe_key(profile)
        if not key:
            continue
        current = merged.get(key)
        if not current:
            merged[key] = profile
            continue
        current["profiles"].update(profile.get("profiles") or {})
        current["raw_sources"].extend(profile.get("raw_sources") or [])
        if not current["contacts"].get("email"):
            current["contacts"]["email"] = (profile.get("contacts") or {}).get("email", "")
        if not current["contacts"].get("phone"):
            current["contacts"]["phone"] = (profile.get("contacts") or {}).get("phone", "")
        if len(profile.get("snippet") or "") > len(current.get("snippet") or ""):
            current["snippet"] = profile.get("snippet")
    return list(merged.values())


def _score_profile(profile: Dict[str, Any], payload: PeopleSearchRequest) -> int:
    structured = " ".join([
        profile.get("name") or "",
        profile.get("designation") or "",
        profile.get("company") or "",
        profile.get("location") or "",
        " ".join(profile.get("skills") or []),
    ]).lower()
    broad = " ".join([
        structured,
        profile.get("snippet") or "",
        " ".join((profile.get("profiles") or {}).values()),
    ]).lower()
    score = 30

    tech = _clean(payload.technology).lower()
    if tech:
        if tech in structured:
            score += 28
        elif tech in broad:
            score += 8

    role = _clean(payload.role).lower()
    if role:
        if role in structured:
            score += 16
        elif role in broad:
            score += 6

    location = _clean(payload.location).lower()
    if location:
        if location in structured:
            score += 12
        elif location in broad:
            score += 5

    company = _clean(payload.company).lower()
    if company:
        if company in structured:
            score += 10
        elif company in broad:
            score += 4

    source = profile.get("source")
    if source == "linkedin":
        score += 12
    elif source == "github":
        score += 8
    elif source == "naukri":
        score += 8
    if (profile.get("contacts") or {}).get("email"):
        score += 10
    if (profile.get("contacts") or {}).get("phone"):
        score += 8
    if profile.get("source_url"):
        score += 5
    if tech and tech not in structured and profile.get("source") in {"linkedin", "naukri", "web"}:
        score -= 18
    return min(score, 99)


async def _save_people_search(db: AsyncIOMotorDatabase, payload: PeopleSearchRequest, profiles: List[Dict[str, Any]], plan: Dict[str, Any]) -> str:
    search_id = f"PSEARCH-{uuid.uuid4().hex[:10].upper()}"
    now = datetime.utcnow()
    await db.people_search_runs.insert_one({
        "search_id": search_id,
        "query": payload.model_dump(),
        "plan": plan,
        "result_count": len(profiles),
        "created_at": now,
        "updated_at": now,
    })
    if profiles:
        for profile in profiles:
            await db.people_search_leads.update_one(
                {"source_url": profile.get("source_url")},
                {"$set": {**profile, "search_id": search_id, "updated_at": now}, "$setOnInsert": {"created_at": now}},
                upsert=True,
            )
    return search_id


@router.post("/people-search")
async def people_search(payload: PeopleSearchRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    requested = max(1, min(int(payload.max_results or 10), 50))
    providers = _planned_providers(payload)
    settings = get_settings()
    external_enabled = bool(settings.TAVILY_API_KEY)
    if not external_enabled:
        providers = [provider for provider in providers if provider == "internal_db"]
    per_provider = max(5, min(requested, 20))
    plan = {
        "providers": providers,
        "queries": {provider: _provider_query(payload, provider) for provider in providers},
        "phase": "phase_1_search_dedupe_rank",
        "contact_enrichment": "inline_public_snippet" if payload.enrich_contacts else "disabled",
        "external_search": "enabled" if external_enabled else "disabled_missing_tavily_key",
    }

    tasks = []
    for provider, query in plan["queries"].items():
        if provider == "internal_db":
            tasks.append(_internal_search(db, payload, requested))
        else:
            tasks.append(_tavily_search(query, provider, per_provider))
    provider_results = await asyncio.gather(*tasks)

    normalized: List[Dict[str, Any]] = []
    provider_status = []
    for result in provider_results:
        provider = result["provider"]
        provider_status.append({
            "provider": provider,
            "success": result["success"],
            "error": result["error"],
            "count": len(result["results"]),
        })
        for item in result["results"]:
            if isinstance(item, dict):
                normalized.append(_normalize_result(item, provider))

    profiles = _merge_profiles(normalized)
    for profile in profiles:
        profile["confidence"] = _score_profile(profile, payload)
    profiles.sort(key=lambda item: item.get("confidence", 0), reverse=True)
    profiles = profiles[:requested]

    search_id = ""
    if payload.save:
        search_id = await _save_people_search(db, payload, profiles, plan)

    return {
        "success": True,
        "search_id": search_id,
        "query": payload.query,
        "plan": plan,
        "provider_status": provider_status,
        "found": len(profiles),
        "profiles": profiles,
        "next_phases": [
            "crawler_parser",
            "profile_extractor",
            "contact_discovery",
            "embeddings_reranker",
            "background_refresh_monitoring",
        ],
    }
