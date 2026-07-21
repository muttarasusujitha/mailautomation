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

from app.config import get_settings
from app.database import get_db

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
            profiles.append(profile)
    return profiles


def _matches_requested_domain(profile: Dict[str, Any], search_text: str) -> bool:
    """Keep broad web search results anchored to the requested technology."""
    wanted = re.sub(r"[^a-z0-9+#. ]+", " ", (search_text or "").lower()).strip()
    if not wanted:
        return True
    haystack = " ".join([
        str(profile.get("title") or ""),
        str(profile.get("snippet") or ""),
        str(profile.get("slug") or ""),
        str(profile.get("source_url") or ""),
    ]).lower()
    tokens = [token for token in wanted.split() if len(token) > 1 and token not in {"trainer", "instructor", "training"}]
    if not tokens:
        return True
    return any(token in haystack for token in tokens)


def _is_current_year_result(profile: Dict[str, Any]) -> bool:
    """Reject results that explicitly advertise an older year in the title/snippet."""
    current_year = datetime.utcnow().year
    haystack = " ".join([
        str(profile.get("title") or ""),
        str(profile.get("snippet") or ""),
    ])
    years = [int(year) for year in re.findall(r"\b20\d{2}\b", haystack)]
    return not years or max(years) >= current_year


async def _tavily_trainer_search(search_text: str, location: str, max_results: int, query_suffix: str = "") -> List[Dict[str, Any]]:
    current_year = datetime.utcnow().year
    query = f'"{search_text}" {current_year} trainer instructor corporate training'
    if query_suffix:
        query += f" {query_suffix}"
    if location:
        query += f" {location}"
    query += " site:linkedin.com/in OR site:naukri.com"

    settings = get_settings()
    if not settings.TAVILY_API_KEY:
        logger.warning("TAVILY_API_KEY is not configured")
        return []

    payload = {
        "query": query,
        "max_results": max_results,
        "search_depth": settings.TAVILY_SEARCH_DEPTH,
        "include_domains": ["linkedin.com", "naukri.com"],
        "time_range": "year",
    }
    headers = {
        "Authorization": f"Bearer {settings.TAVILY_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            resp = await client.post(f"{settings.TAVILY_API_URL.rstrip('/')}/search", json=payload, headers=headers)
            if resp.status_code == 404 and "api.tavily.dev" in settings.TAVILY_API_URL:
                resp = await client.post("https://api.tavily.com/search", json=payload, headers=headers)
            resp.raise_for_status()
            return _normalize_tavily_profiles(resp.json().get("results", []))
    except Exception as exc:
        logger.warning("Tavily trainer search failed: %s", exc)
    return []


class FreeSearchRequest(BaseModel):
    domain: Optional[str] = ""
    query: Optional[str] = ""
    location: Optional[str] = ""
    max_results: int = 10
    save_leads: bool = False


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

    requested = max(1, min(int(payload.max_results or 10), 100))
    per_query = min(max(requested, 20), 50)
    query_suffixes = [
        "",
        '"corporate trainer"',
        '"freelance trainer"',
        '"technical trainer"',
        '"online trainer"',
        '"training consultant"',
    ]
    results = await asyncio.gather(*[
        _tavily_trainer_search(search_text, payload.location or "", per_query, suffix)
        for suffix in query_suffixes
    ])

    for batch in results:
        for p in batch:
            dedupe_key = p.get("source_url") or p.get("slug")
            if (
                dedupe_key
                and dedupe_key not in seen_slugs
                and _matches_requested_domain(p, match_text)
                and _is_current_year_result(p)
            ):
                seen_slugs.add(dedupe_key)
                all_profiles.append(p)

    profiles = all_profiles[:requested]

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

    return {
        "domain": payload.domain or search_text,
        "query": payload.query or search_text,
        "location": payload.location,
        "found": len(profiles),
        "profiles": profiles,
    }
