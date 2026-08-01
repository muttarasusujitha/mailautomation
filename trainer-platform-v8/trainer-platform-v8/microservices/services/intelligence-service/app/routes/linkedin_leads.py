"""Direct LinkedIn/Naukri lead search using public web signals."""
import asyncio
import html
import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

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
    max_queries: Optional[int] = None
    save: bool = True
    mode: str = "trainer"
    source: Optional[str] = "linkedin"


def _slug_from_url(url: str) -> str:
    linkedin = re.search(r"linkedin\.com/in/([a-zA-Z0-9\-_%]+)", url or "", re.IGNORECASE)
    if linkedin:
        return linkedin.group(1)
    return re.sub(r"[^a-zA-Z0-9]+", "-", (url or "").split("/", 3)[-1]).strip("-")[:80]


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
        if not re.search(
            r"\b(corporate trainer required|trainer required|training requirement|need trainer|trainer needed|looking for trainer|looking for corporate trainer|require trainer|freelance trainer required)\b",
            combined_text,
        ):
            return None
    if mode == "trainer" and source == "linkedin" and not re.search(r"linkedin\.com/in/", url, re.IGNORECASE):
        return None
    title = item.get("title") or item.get("name") or ""
    snippet = item.get("content") or item.get("snippet") or item.get("description") or ""
    combined_text = f"{title} {snippet}".lower()
    if mode == "trainer":
        if re.search(r"\b(actively seeking|job seeker|looking for job|open to work|full-time role)\b", combined_text):
            return None
        terms = _domain_terms(domain)
        has_sparse_profile_text = source == "linkedin" and re.search(r"linkedin\.com/in/", url, re.IGNORECASE) and len(combined_text.strip()) < 80
        if terms and combined_text.strip() and not has_sparse_profile_text and not any(term in combined_text for term in terms):
            return None
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


async def _plain_brave_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    settings = get_settings()
    api_key = settings.BRAVE_SEARCH_API_KEY.strip()
    if not api_key:
        return []

    requested = max(1, min(max_results, 100))
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    }
    items: List[Dict[str, Any]] = []
    seen_urls: set = set()
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=headers) as client:
        for offset in range(0, min(10, (requested + 19) // 20)):
            resp = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={
                    "q": query,
                    "count": min(20, requested),
                    "offset": offset,
                    "search_lang": "en",
                    "safesearch": "moderate",
                    "result_filter": "web",
                },
            )
            resp.raise_for_status()
            for result in (resp.json().get("web") or {}).get("results", []):
                url = result.get("url") or ""
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    items.append({
                        "url": url,
                        "title": result.get("title") or "",
                        "content": result.get("description") or "",
                    })
            if len(items) >= requested:
                break
    return items[:requested]


def _clean_public_result_url(raw_url: str) -> str:
    url = html.unescape(str(raw_url or "")).strip()
    if not url:
        return ""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    for key in ("uddg", "url", "u", "q"):
        if qs.get(key):
            url = unquote(qs[key][0])
            break
    url = url.replace("&amp;", "&").strip()
    return url.rstrip(").,;")


def _is_profile_url(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    return (
        parsed.scheme in {"http", "https"}
        and (
            ("linkedin.com" in host and path.startswith("/in/"))
            or ("naukri.com" in host)
        )
    )


def _public_result_items(page_html: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    seen_urls: set = set()
    generic_links = re.findall(r'(?is)<a[^>]+href=["\']([^"\']*(?:linkedin\.com/in|naukri\.com)[^"\']*)["\'][^>]*>(.*?)</a>', page_html or "")
    for href, title_html in generic_links:
        title = re.sub(r"(?is)<[^>]+>", " ", title_html)
        title = re.sub(r"\s+", " ", html.unescape(title)).strip()
        url = _clean_public_result_url(href)
        if _is_profile_url(url) and url not in seen_urls:
            seen_urls.add(url)
            items.append({"url": url, "title": title or url.rsplit("/", 1)[-1].replace("-", " "), "content": ""})
    if items:
        return items

    blocks = re.findall(r'(?is)<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page_html or "")
    for href, title_html in blocks:
        title = re.sub(r"(?is)<[^>]+>", " ", title_html)
        title = re.sub(r"\s+", " ", html.unescape(title)).strip()
        url = _clean_public_result_url(href)
        if _is_profile_url(url) and url not in seen_urls:
            seen_urls.add(url)
            items.append({"url": url, "title": title, "content": ""})
    if items:
        return items

    for match in re.finditer(r'https?://(?:www\.)?(?:linkedin\.com/in|naukri\.com)/[^"\'<>\s]+', page_html or "", re.IGNORECASE):
        url = _clean_public_result_url(match.group(0))
        if _is_profile_url(url) and url not in seen_urls:
            seen_urls.add(url)
            items.append({"url": url, "title": url.rsplit("/", 1)[-1].replace("-", " "), "content": ""})
    return items


async def _plain_public_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    """Search public web without a paid provider and return generic result dicts."""
    requested = max(1, min(max_results, 100))
    encoded = quote_plus(query)
    urls = []
    for start in range(0, requested + 20, 30):
        urls.append(f"https://html.duckduckgo.com/html/?q={encoded}&s={start}")
        urls.append(f"https://duckduckgo.com/html/?q={encoded}&s={start}")
    for start in range(0, requested + 20, 10):
        urls.append(f"https://www.google.com/search?q={encoded}&num=10&start={start}")
    for first in range(1, requested + 20, 10):
        urls.append(f"https://www.bing.com/search?q={encoded}&count=10&first={first}")
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; TrainerSyncPublicSearch/1.0)",
        "Accept": "text/html,application/xhtml+xml",
    }
    async with httpx.AsyncClient(timeout=12, follow_redirects=True, headers=headers) as client:
        last_error = ""
        items: List[Dict[str, Any]] = []
        seen_urls: set = set()

        async def fetch_items(url: str) -> List[Dict[str, Any]]:
            try:
                resp = await client.get(url)
                if resp.status_code >= 400:
                    logger.info("Public web search page failed for %s: %s %s", query, resp.status_code, resp.text[:120])
                    return []
                return _public_result_items(resp.text)
            except Exception as exc:
                last_error = str(exc)
                return []

        for batch in await asyncio.gather(*[fetch_items(url) for url in urls]):
            for item in batch:
                source_url = item.get("url") or item.get("source_url")
                if source_url and source_url not in seen_urls:
                    seen_urls.add(source_url)
                    items.append(item)
            if len(items) >= requested:
                return items[:requested]
        if last_error:
            logger.warning("Public web search failed for %s: %s", query, last_error)
    return items[:requested]


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


def _fallback_search_lead(domain: str, mode: str, location: str = "") -> Dict[str, Any]:
    topic = domain.strip() or "trainer"
    if mode == "client":
        query = f"{topic} corporate training requirement trainer required {location}".strip()
        return {
            "lead_id": f"CL-{uuid.uuid4().hex[:10].upper()}",
            "company_name": f"{topic} public search lead",
            "contact_name": "",
            "domain": topic,
            "source": "public_search_agent",
            "source_url": f"https://www.google.com/search?q={quote_plus(query)}",
            "linkedin_url": f"https://www.linkedin.com/search/results/content/?keywords={quote_plus(query)}",
            "post_text": f"Public search task for: {query}",
            "notes": "Exact public post URL was not exposed by the search provider. Review or enrich this search lead.",
            "status": "new",
            "confidence": 0.35,
        }
    query = f"{topic} corporate trainer instructor consultant {location}".strip()
    return {
        "lead_id": f"TPL-{uuid.uuid4().hex[:10].upper()}",
        "name": f"{topic} public trainer search",
        "trainer_name": f"{topic} public trainer search",
        "headline": f"Public search task for {topic} trainers",
        "domain": topic,
        "source": "public_search_agent",
        "source_url": f"https://www.google.com/search?q={quote_plus(query + ' site:linkedin.com/in')}",
        "linkedin_url": f"https://www.linkedin.com/search/results/people/?keywords={quote_plus(query)}",
        "external_slug": f"public-search-{re.sub(r'[^a-z0-9]+', '-', topic.lower()).strip('-')[:40]}",
        "snippet": f"Public search task for: {query}",
        "profile_text": f"Review Google/LinkedIn public search for {topic} trainers.",
        "status": "new",
        "verification_tier": "public_search_task",
        "confidence": 0.35,
    }


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
    skipped: List[Dict[str, Any]] = []
    seen_urls: set = set()

    mode = "client" if payload.mode == "client" else "trainer"

    target_results = max(1, min(payload.max_results, 100))
    query_budget = payload.max_queries or (1 if mode == "client" else 12)

    for domain in domains:
        raw_results: List[Dict[str, Any]] = []
        for query in _search_queries(domain, mode, payload.location or "")[:query_budget]:
            if len(all_results) >= target_results:
                break
            try:
                batch: List[Dict[str, Any]] = []
                try:
                    batch = await _plain_brave_search(query, target_results)
                    if not batch:
                        batch = await _plain_tavily_search(query, min(20, target_results))
                except Exception as exc:
                    logger.info("Provider search unavailable for %s; using built-in public search: %s", domain, exc)
                if not batch:
                    batch = await _plain_public_search(query, target_results)
                raw_results.extend(batch)
            except Exception as exc:
                logger.warning("Direct public LinkedIn search failed for %s: %s", domain, exc)
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
                    skipped_count += 1
                    skipped.append({"reason": "already_saved", "source_url": lead["source_url"], "source": lead.get("source", "")})
                    continue
                await db["client_leads"].insert_one({**lead, "created_at": now, "updated_at": now})
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
                    skipped_count += 1
                    skipped.append({"reason": "already_saved", "source_url": lead["source_url"], "source": lead.get("source", "")})
                    continue
                await db["trainer_profile_leads"].insert_one({**lead, "created_at": now, "updated_at": now})
            saved_count += 1

        if payload.save and not any((result.get("domain") or "").lower() == domain.lower() for result in all_results):
            fallback = _fallback_search_lead(domain, mode, payload.location or "")
            if mode == "client":
                exists = await db["client_leads"].find_one({"source_url": fallback["source_url"]}, {"_id": 1})
                if not exists:
                    await db["client_leads"].insert_one({**fallback, "created_at": now, "updated_at": now})
                    all_results.append(fallback)
                    saved_count += 1
            else:
                exists = await db["trainer_profile_leads"].find_one({"source_url": fallback["source_url"]}, {"_id": 1})
                if not exists:
                    await db["trainer_profile_leads"].insert_one({**fallback, "created_at": now, "updated_at": now})
                    all_results.append(fallback)
                    saved_count += 1

    return {
        "success": True,
        "saved_count": saved_count,
        "skipped_count": skipped_count,
        "skipped": skipped[:20],
        "found": len(all_results),
        "results": all_results,
    }
