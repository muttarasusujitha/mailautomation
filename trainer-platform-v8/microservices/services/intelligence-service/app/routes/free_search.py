"""Free trainer search using web scraping (Google + Bing + LinkedIn signals)."""
import asyncio
import logging
import random
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.database import get_db

router = APIRouter()
logger = logging.getLogger(__name__)

_UA = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/123.0 Safari/537.36",
]


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()


def _extract_linkedin_profiles(html: str) -> List[Dict[str, Any]]:
    profiles = []
    seen: set = set()
    # Find LinkedIn profile URLs in search results
    for m in re.finditer(
        r"https://(?:www\.)?linkedin\.com/in/([a-zA-Z0-9\-_%]+)/?",
        html, re.IGNORECASE
    ):
        slug = m.group(1)
        url = f"https://linkedin.com/in/{slug}"
        if url in seen:
            continue
        seen.add(url)
        # Try to grab a name from surrounding text (best-effort)
        start = max(0, m.start() - 200)
        end = min(len(html), m.end() + 200)
        snippet = _strip_html(html[start:end])
        profiles.append({
            "source_url": url,
            "slug": slug,
            "snippet": snippet[:300],
            "lead_id": f"LI-{uuid.uuid4().hex[:8].upper()}",
        })
    return profiles[:10]


async def _google_trainer_search(domain: str, location: str, client: httpx.AsyncClient) -> List[Dict[str, Any]]:
    query = f'site:linkedin.com/in "{domain}" trainer India'
    if location:
        query += f" {location}"
    try:
        resp = await client.get(
            "https://www.google.com/search",
            params={"q": query, "num": 10, "hl": "en"},
            headers={"User-Agent": random.choice(_UA), "Accept": "text/html"},
            follow_redirects=True,
        )
        if resp.status_code == 200:
            return _extract_linkedin_profiles(resp.text)
    except Exception as exc:
        logger.debug("Google trainer search failed: %s", exc)
    return []


async def _bing_trainer_search(domain: str, location: str, client: httpx.AsyncClient) -> List[Dict[str, Any]]:
    query = f'site:linkedin.com/in "{domain}" trainer'
    if location:
        query += f" {location}"
    try:
        resp = await client.get(
            "https://www.bing.com/search",
            params={"q": query, "count": 10},
            headers={"User-Agent": random.choice(_UA), "Accept": "text/html"},
            follow_redirects=True,
        )
        if resp.status_code == 200:
            return _extract_linkedin_profiles(resp.text)
    except Exception as exc:
        logger.debug("Bing trainer search failed: %s", exc)
    return []


class FreeSearchRequest(BaseModel):
    domain: str
    location: Optional[str] = ""
    max_results: int = 10
    save_leads: bool = False


@router.post("/search")
async def free_search_trainers(
    payload: FreeSearchRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Search for trainers via public Google/Bing LinkedIn signals."""
    all_profiles: List[Dict[str, Any]] = []
    seen_slugs: set = set()

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        results = await asyncio.gather(
            _google_trainer_search(payload.domain, payload.location or "", client),
            _bing_trainer_search(payload.domain, payload.location or "", client),
        )

    for batch in results:
        for p in batch:
            if p["slug"] not in seen_slugs:
                seen_slugs.add(p["slug"])
                all_profiles.append(p)

    profiles = all_profiles[: payload.max_results]

    if payload.save_leads and profiles:
        now = datetime.utcnow()
        for p in profiles:
            await db.linkedin_leads.update_one(
                {"source_url": p["source_url"]},
                {"$setOnInsert": {
                    **p,
                    "searched_domain": payload.domain,
                    "status": "found",
                    "created_at": now,
                    "updated_at": now,
                }},
                upsert=True,
            )

    return {
        "domain": payload.domain,
        "location": payload.location,
        "found": len(profiles),
        "profiles": profiles,
    }
