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


class LinkedInLeadSearchRequest(BaseModel):
    query: Optional[str] = ""
    domain: Optional[str] = ""
    domains: Optional[List[str]] = None
    location: Optional[str] = ""
    max_results: int = 10
    save: bool = True
    mode: str = "trainer"
    source: Optional[str] = "linkedin"


def _slug_from_url(url: str) -> str:
    linkedin = re.search(r"linkedin\.com/in/([a-zA-Z0-9\-_%]+)", url or "", re.IGNORECASE)
    if linkedin:
        return linkedin.group(1)
    return re.sub(r"[^a-zA-Z0-9]+", "-", (url or "").split("/", 3)[-1]).strip("-")[:80]


def _normalize_result(item: Dict[str, Any], domain: str, mode: str) -> Optional[Dict[str, Any]]:
    url = item.get("url") or item.get("source_url") or item.get("link") or ""
    if not re.search(r"(linkedin\.com|naukri\.com)", url, re.IGNORECASE):
        return None

    source = "linkedin" if "linkedin.com" in url.lower() else "naukri"
    title = item.get("title") or item.get("name") or ""
    snippet = item.get("content") or item.get("snippet") or item.get("description") or ""
    slug = _slug_from_url(url)
    if mode == "client":
        return {
            "lead_id": f"CL-{uuid.uuid4().hex[:10].upper()}",
            "company_name": title,
            "contact_name": "",
            "domain": domain,
            "source": source,
            "source_url": url,
            "linkedin_url": url if source == "linkedin" else "",
            "post_text": snippet[:1000],
            "notes": snippet[:500],
            "status": "new",
            "confidence": 0.75,
        }

    return {
        "lead_id": f"TPL-{uuid.uuid4().hex[:10].upper()}",
        "name": title,
        "trainer_name": title,
        "headline": title,
        "domain": domain,
        "source": source,
        "source_url": url,
        "linkedin_url": url if source == "linkedin" else "",
        "linkedin_slug": slug if source == "linkedin" else "",
        "external_slug": slug,
        "snippet": snippet[:500],
        "profile_text": snippet[:1000],
        "status": "new",
        "verification_tier": "linkedin_signal",
        "confidence": 0.75,
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
    skipped_count = 0
    all_results: List[Dict[str, Any]] = []

    mode = "client" if payload.mode == "client" else "trainer"

    for domain in domains:
        if mode == "client":
            query = f'{domain} trainer required training requirement looking for trainer'
        else:
            query = f'{domain} trainer instructor corporate training'
        if payload.location:
            query += f" {payload.location}"
        query += " site:linkedin.com OR site:naukri.com"
        try:
            raw_results = await _plain_tavily_search(query, payload.max_results)
        except Exception as exc:
            logger.warning("Direct Tavily LinkedIn search failed for %s: %s", domain, exc)
            return {"success": False, "error": str(exc), "saved_count": saved_count, "results": all_results}

        for item in raw_results:
            if not isinstance(item, dict):
                continue
            lead = _normalize_result(item, domain, mode)
            if not lead:
                skipped_count += 1
                continue
            all_results.append(lead)
            if not payload.save:
                continue
            if mode == "client":
                exists = await db["client_leads"].find_one({"source_url": lead["source_url"]}, {"_id": 1})
                if exists:
                    skipped_count += 1
                    continue
                await db["client_leads"].insert_one({**lead, "created_at": now, "updated_at": now})
            else:
                exists = await db["trainer_profile_leads"].find_one(
                    {"$or": [{"source_url": lead["source_url"]}, {"linkedin_slug": lead["linkedin_slug"]}]},
                    {"_id": 1},
                )
                if exists:
                    skipped_count += 1
                    continue
                await db["trainer_profile_leads"].insert_one({**lead, "created_at": now, "updated_at": now})
            saved_count += 1

    return {
        "success": True,
        "saved_count": saved_count,
        "skipped_count": skipped_count,
        "found": len(all_results),
        "results": all_results,
    }
