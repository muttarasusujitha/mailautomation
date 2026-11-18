"""Trainer search using Tavily LinkedIn/Naukri signals."""
import asyncio
import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.clients.search_accuracy import is_current_year_result, matches_requested_skill
from app.config import get_settings
from shared.database.service import get_db

router = APIRouter()
logger = logging.getLogger(__name__)

def _profile_from_url(url: str, snippet: str = "", title: str = "") -> Optional[Dict[str, Any]]:
    linkedin = re.search(r"https?://(?:www\.)?linkedin\.com/in/([a-zA-Z0-9\-_%]+)/?", url or "", re.IGNORECASE)
    if linkedin:
        slug = linkedin.group(1)
        return {
            "source_url": f"https://linkedin.com/in/{slug}",
            "slug": slug,
            "source": "linkedin",
            "title": title,
            "snippet": snippet[:300],
            "lead_id": f"LI-{uuid.uuid4().hex[:8].upper()}",
        }

    naukri = re.search(r"https?://(?:www\.)?naukri\.com/[^\"'\s<>]+", url or "", re.IGNORECASE)
    if naukri:
        clean_url = naukri.group(0).rstrip(").,;")
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", clean_url.split("naukri.com/", 1)[-1]).strip("-")[:80]
        return {
            "source_url": clean_url,
            "slug": slug or uuid.uuid4().hex[:12],
            "source": "naukri",
            "title": title,
            "snippet": snippet[:300],
            "lead_id": f"NK-{uuid.uuid4().hex[:8].upper()}",
        }

    return None


def _normalize_tavily_profiles(results: Any) -> List[Dict[str, Any]]:
    profiles: List[Dict[str, Any]] = []
    seen: set = set()
    if not isinstance(results, list):
        return profiles
    for item in results:
        if not isinstance(item, dict):
            continue
        url = item.get("url") or item.get("source_url") or item.get("link") or ""
        title = item.get("title") or item.get("name") or ""
        snippet = item.get("content") or item.get("snippet") or item.get("description") or ""
        profile = _profile_from_url(url, snippet=snippet, title=title)
        if profile and profile["source_url"] not in seen:
            seen.add(profile["source_url"])
            # The engine's own URL, so each engine can be credited with the profiles that were kept.
            profile["result_url"] = url
            profiles.append(profile)
    return profiles


def _search_sources(reports: List[Dict[str, Any]], profiles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Per-source status for one trainer search: Tavily, or the key-free engines used without a key."""
    from app.clients.public_search import engine_sources, merge_engine_reports

    calls = [report["tavily"] for report in reports if report.get("tavily")]
    if any(call.get("configured") for call in calls):
        found = sum(int(call.get("rows") or 0) for call in calls)
        errors = [call for call in calls if call.get("error")]
        if found:
            status = "ok" if profiles else "filtered"
            reason = "" if profiles else f"Tavily returned {found} link(s), but none passed the skill and date checks."
        elif errors and len(errors) == len(calls):
            limited = any(call.get("http_status") == 429 for call in errors)
            status = "blocked" if limited else "error"
            reason = f"Tavily failed on all {len(calls)} searches: {errors[0]['error']}"
        else:
            status = "no_results"
            reason = "Tavily returned no LinkedIn or Naukri profiles for these searches."
        if errors and status in ("ok", "filtered", "no_results"):
            reason = (reason + " " if reason else "") + f"{len(errors)} of {len(calls)} Tavily searches failed: {errors[0]['error']}"
        return [{"source": "tavily", "label": "Tavily", "status": status, "found": found,
                 "qualified": len(profiles), "reason": reason}]
    engines = merge_engine_reports(report.get("engines") for report in reports)
    kept = [profile["result_url"] for profile in profiles if profile.get("result_url")]
    return [
        {"source": "tavily", "label": "Tavily", "status": "not_configured", "found": 0, "qualified": 0,
         "reason": "TAVILY_API_KEY is not set, so the key-free engines were used instead."},
        *engine_sources(engines, kept),
    ]


async def _tavily_trainer_search(search_text: str, location: str, max_results: int, query_suffix: str = "", include_domains: Optional[List[str]] = None, report: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    current_year = datetime.utcnow().year
    domains = include_domains or ["linkedin.com", "naukri.com"]
    naukri_only = domains == ["naukri.com"]
    # Naukri CVs are rarely indexed with a current year or corporate-training
    # wording. Keep the Naukri query broad; retain the more selective LinkedIn query.
    query = f'"{search_text}"' if naukri_only else f'"{search_text}" {current_year} trainer instructor corporate training'
    if query_suffix:
        query += f" {query_suffix}"
    if location:
        query += f" {location}"
    query += " " + " OR ".join(f"site:{domain}" for domain in domains)

    report = report if report is not None else {}
    settings = get_settings()
    if not settings.TAVILY_API_KEY:
        from app.clients.public_search import search_public_many
        engines: Dict[str, Any] = {}
        batch = await search_public_many([query], max_results, allowed_domains=domains, report=engines)
        rows, attempts = batch
        logger.info("Public trainer search fallback: domains=%s attempts=%s results=%s", domains, attempts, len(rows))
        report["tavily"] = {"configured": False}
        report["engines"] = engines
        return _normalize_tavily_profiles(rows)

    payload = {
        "query": query,
        "max_results": max_results,
        "search_depth": settings.TAVILY_SEARCH_DEPTH,
        "include_domains": domains,
        "time_range": "year",
    }
    headers = {
        "Authorization": f"Bearer {settings.TAVILY_API_KEY}",
        "Content-Type": "application/json",
    }
    call: Dict[str, Any] = {"configured": True, "rows": 0, "error": "", "http_status": None}
    report["tavily"] = call
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            resp = await client.post(f"{settings.TAVILY_API_URL.rstrip('/')}/search", json=payload, headers=headers)
            if resp.status_code == 404 and "api.tavily.dev" in settings.TAVILY_API_URL:
                resp = await client.post("https://api.tavily.com/search", json=payload, headers=headers)
            resp.raise_for_status()
            profiles = _normalize_tavily_profiles(resp.json().get("results", []))
            call["rows"] = len(profiles)
            return profiles
    except Exception as exc:
        logger.warning("Tavily trainer search failed: %s", exc)
        response = getattr(exc, "response", None)
        call["http_status"] = getattr(response, "status_code", None)
        if isinstance(exc, httpx.TimeoutException):
            call["error"] = "Tavily did not answer in time."
        elif call["http_status"]:
            call["error"] = f"Tavily returned HTTP {call['http_status']}."
        else:
            call["error"] = (str(exc) or type(exc).__name__)[:200]
    return []


class FreeSearchRequest(BaseModel):
    domain: Optional[str] = ""
    query: Optional[str] = ""
    location: Optional[str] = ""
    max_results: int = 50
    save_leads: bool = False
    include_domains: Optional[List[str]] = None


@router.post("/search")
async def free_search_trainers(
    payload: FreeSearchRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Search for trainers via plain Tavily API."""
    search_text = (payload.query or payload.domain or "").strip()
    match_text = (payload.domain or payload.query or "").strip()
    if not search_text:
        return {
            "success": False,
            "error": "query or domain is required for trainer search",
            "domain": payload.domain,
            "query": payload.query,
            "location": payload.location,
            "found": 0,
            "profiles": [],
        }

    all_profiles: List[Dict[str, Any]] = []
    seen_slugs: set = set()

    naukri_only = payload.include_domains == ["naukri.com"]
    requested = min(max(int(payload.max_results or (10 if naukri_only else 50)), 10), 30) if naukri_only else max(1, min(int(payload.max_results or 50), 50))
    allowed_domains = [str(item).strip().lower() for item in (payload.include_domains or ["linkedin.com", "naukri.com"]) if str(item).strip()]
    if not allowed_domains or any(item not in {"linkedin.com", "naukri.com"} for item in allowed_domains):
        return {"success": False, "error": "include_domains must contain linkedin.com and/or naukri.com", "found": 0, "profiles": []}
    per_query = min(max(requested, 20), 50)
    naukri_only = allowed_domains == ["naukri.com"]
    query_suffixes = [
        "",
        '"corporate trainer"',
        '"freelance trainer"',
        '"technical trainer"',
        '"online trainer"',
        '"training consultant"',
    ]
    if naukri_only:
        query_suffixes = ["", '"trainer"', '"instructor"']
    reports: List[Dict[str, Any]] = [{} for _ in query_suffixes]
    results = await asyncio.gather(*[
        _tavily_trainer_search(search_text, payload.location or "", per_query, suffix, allowed_domains, report=report)
        for suffix, report in zip(query_suffixes, reports)
    ])

    for batch in results:
        for p in batch:
            dedupe_key = p.get("source_url") or p.get("slug")
            if (
                dedupe_key
                and dedupe_key not in seen_slugs
                and matches_requested_skill(p, match_text)
                and (naukri_only or is_current_year_result(p))
                and any((p.get("source_url", "").lower().split("/", 3)[2] == domain or p.get("source_url", "").lower().split("/", 3)[2].endswith("." + domain)) for domain in allowed_domains)
            ):
                seen_slugs.add(dedupe_key)
                all_profiles.append(p)

    profiles = all_profiles[:requested]
    sources = _search_sources(reports, profiles)
    for batch in results:
        for p in batch:
            p.pop("result_url", None)

    search_error = ""
    if naukri_only and not profiles:
        search_error = "Public Naukri search returned no profiles."

    if payload.save_leads and profiles:
        now = datetime.utcnow()
        for p in profiles:
            await db.linkedin_leads.update_one(
                {"source_url": p["source_url"]},
                {"$setOnInsert": {
                    **p,
                    "searched_domain": search_text,
                    "status": "found",
                    "created_at": now,
                    "updated_at": now,
                }},
                upsert=True,
            )

    from app.clients.search_runs import search_succeeded
    return {
        "success": search_succeeded(len(profiles), sources),
        "domain": payload.domain or search_text,
        "query": payload.query or search_text,
        "location": payload.location,
        "found": len(profiles),
        "profiles": profiles,
        "search_error": search_error,
        "sources": sources,
    }
