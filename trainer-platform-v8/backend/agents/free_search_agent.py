"""free_search_agent.py — Zero-cost web search engine for TrainerSync.

Replaces the paid Tavily API with a cascading set of completely free providers.

Provider waterfall (tried in order until one succeeds):
  1. DuckDuckGo HTML scrape — no API key, no account, no rate-limit
  2. Google Custom Search JSON API (free tier) — 100 queries/day, needs
     GOOGLE_CSE_ID + GOOGLE_CSE_API_KEY (one-time 5-min setup)
  3. Bing Web Search (unofficial HTML scrape) — fallback, no key needed
  4. SerpAPI free tier — 100 searches/month, needs SERPAPI_KEY

Each provider returns results in a uniform shape:
    {
        "url":         str,
        "title":       str,
        "content":     str,   # snippet / description
        "raw_content": str,   # longer body text when available
        "source":      str,   # which provider returned this
    }

Usage
-----
    from agents.free_search_agent import free_web_search, search_linkedin_trainers

    results = await free_web_search('site:linkedin.com/in "Python trainer" India')
    # returns List[dict] — same shape as Tavily results

Env vars (all optional — agent falls back gracefully if unset)
--------------------------------------------------------------
    FREE_SEARCH_PROVIDER   = auto | duckduckgo | google | bing | serpapi
                             (default: auto — tries providers in order)
    GOOGLE_CSE_ID          = your Google Custom Search Engine ID
    GOOGLE_CSE_API_KEY     = your Google CSE API key (free 100/day)
    SERPAPI_KEY            = your SerpAPI key (free 100/month)
    FREE_SEARCH_MAX_RESULTS = max results per query (default: 5)
    FREE_SEARCH_TIMEOUT    = HTTP timeout seconds (default: 20)
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import urllib.parse
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────
DUCKDUCKGO_URL = "https://html.duckduckgo.com/html/"
GOOGLE_CSE_URL = "https://www.googleapis.com/customsearch/v1"
BING_SEARCH_URL = "https://www.bing.com/search"
SERPAPI_URL = "https://serpapi.com/search.json"

DEFAULT_MAX_RESULTS = int(os.getenv("FREE_SEARCH_MAX_RESULTS", "5"))
DEFAULT_TIMEOUT = int(os.getenv("FREE_SEARCH_TIMEOUT", "20"))

# Browser-like headers to avoid bot detection on HTML scrapers
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Result shape identical to what Tavily returns so the caller needs zero changes
SearchResult = Dict[str, Any]


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _strip_html(html: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#x27;", "'", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_attr(tag_html: str, attr: str) -> str:
    """Pull the value of a named attribute out of a raw HTML tag string."""
    match = re.search(rf'{attr}=["\']([^"\']*)["\']', tag_html, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _clean_ddg_url(raw: str) -> str:
    """DuckDuckGo wraps real URLs in a redirect; unwrap them."""
    if not raw:
        return ""
    # DuckDuckGo redirect format: //duckduckgo.com/l/?uddg=<encoded_url>
    match = re.search(r"uddg=([^&]+)", raw)
    if match:
        return urllib.parse.unquote(match.group(1))
    if raw.startswith("//"):
        raw = "https:" + raw
    return raw


def _provider() -> str:
    return os.getenv("FREE_SEARCH_PROVIDER", "auto").strip().lower()


# ──────────────────────────────────────────────────────────────
# Provider 1 — DuckDuckGo HTML scrape (no key, unlimited)
# ──────────────────────────────────────────────────────────────

async def _search_duckduckgo(
    query: str,
    max_results: int,
    client: httpx.AsyncClient,
) -> List[SearchResult]:
    """Scrape DuckDuckGo HTML results. No API key required."""
    try:
        response = await client.post(
            DUCKDUCKGO_URL,
            data={"q": query, "b": "", "kl": "in-en"},
            headers=_HEADERS,
            follow_redirects=True,
        )
        if response.status_code >= 400:
            logger.debug("DuckDuckGo returned %s for query: %s", response.status_code, query[:80])
            return []
        html = response.text
    except Exception as exc:
        logger.debug("DuckDuckGo request failed: %s", exc)
        return []

    results: List[SearchResult] = []
    # Each result block: <div class="result results_links ..."> ... </div>
    blocks = re.findall(
        r'<div[^>]*class="[^"]*result[^"]*results_links[^"]*"[^>]*>(.*?)</div>\s*</div>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    for block in blocks[:max_results]:
        # Title + URL
        link_match = re.search(r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', block, re.DOTALL | re.IGNORECASE)
        if not link_match:
            continue
        raw_url = _clean_ddg_url(link_match.group(1))
        title = _strip_html(link_match.group(2))
        # Snippet
        snippet_match = re.search(r'<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', block, re.DOTALL | re.IGNORECASE)
        snippet = _strip_html(snippet_match.group(1)) if snippet_match else ""
        if not raw_url:
            continue
        results.append({
            "url": raw_url,
            "title": title,
            "content": snippet,
            "raw_content": snippet,
            "source": "duckduckgo",
        })
    return results


# ──────────────────────────────────────────────────────────────
# Provider 2 — Google Custom Search JSON API (100 free/day)
# ──────────────────────────────────────────────────────────────

async def _search_google_cse(
    query: str,
    max_results: int,
    client: httpx.AsyncClient,
) -> List[SearchResult]:
    """Use Google's Custom Search JSON API (free 100 queries/day).

    Setup (5 min, one time):
      1. Go to https://programmablesearchengine.google.com → New search engine
         → Search the entire web → get your CX (GOOGLE_CSE_ID)
      2. Go to https://console.cloud.google.com → APIs → Custom Search API → Enable
         → Credentials → Create API Key → copy it (GOOGLE_CSE_API_KEY)
      3. Add both to backend/.env
    """
    cse_id = os.getenv("GOOGLE_CSE_ID", "").strip()
    api_key = os.getenv("GOOGLE_CSE_API_KEY", "").strip()
    if not cse_id or not api_key:
        logger.debug("GOOGLE_CSE_ID or GOOGLE_CSE_API_KEY not set — skipping Google CSE")
        return []
    try:
        response = await client.get(
            GOOGLE_CSE_URL,
            params={
                "key": api_key,
                "cx": cse_id,
                "q": query,
                "num": min(max_results, 10),
            },
            headers={"Accept": "application/json"},
        )
        if response.status_code >= 400:
            logger.debug("Google CSE returned %s: %s", response.status_code, response.text[:200])
            return []
        data = response.json()
    except Exception as exc:
        logger.debug("Google CSE request failed: %s", exc)
        return []

    results: List[SearchResult] = []
    for item in (data.get("items") or [])[:max_results]:
        snippet = item.get("snippet") or ""
        pagemap = item.get("pagemap") or {}
        # Try to pull a longer body from the metatag description
        metatags = (pagemap.get("metatags") or [{}])[0]
        long_desc = metatags.get("og:description") or metatags.get("description") or snippet
        results.append({
            "url": item.get("link") or "",
            "title": item.get("title") or "",
            "content": snippet,
            "raw_content": long_desc,
            "source": "google_cse",
        })
    return results


# ──────────────────────────────────────────────────────────────
# Provider 3 — Bing HTML scrape (no key needed, fallback)
# ──────────────────────────────────────────────────────────────

async def _search_bing(
    query: str,
    max_results: int,
    client: httpx.AsyncClient,
) -> List[SearchResult]:
    """Scrape Bing search HTML. No API key required."""
    try:
        response = await client.get(
            BING_SEARCH_URL,
            params={"q": query, "count": max_results, "mkt": "en-IN"},
            headers=_HEADERS,
            follow_redirects=True,
        )
        if response.status_code >= 400:
            logger.debug("Bing returned %s for query: %s", response.status_code, query[:80])
            return []
        html = response.text
    except Exception as exc:
        logger.debug("Bing request failed: %s", exc)
        return []

    results: List[SearchResult] = []
    # Bing result blocks: <li class="b_algo"> ... </li>
    blocks = re.findall(r'<li[^>]*class="[^"]*b_algo[^"]*"[^>]*>(.*?)</li>', html, re.DOTALL | re.IGNORECASE)
    for block in blocks[:max_results]:
        # URL + title
        link_match = re.search(r'<h2[^>]*>.*?<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', block, re.DOTALL | re.IGNORECASE)
        if not link_match:
            continue
        url = link_match.group(1).strip()
        title = _strip_html(link_match.group(2))
        # Snippet
        snippet_match = re.search(r'<p[^>]*>(.*?)</p>', block, re.DOTALL | re.IGNORECASE)
        snippet = _strip_html(snippet_match.group(1)) if snippet_match else ""
        if not url or url.startswith("javascript:"):
            continue
        results.append({
            "url": url,
            "title": title,
            "content": snippet,
            "raw_content": snippet,
            "source": "bing",
        })
    return results


# ──────────────────────────────────────────────────────────────
# Provider 4 — SerpAPI free tier (100 searches/month)
# ──────────────────────────────────────────────────────────────

async def _search_serpapi(
    query: str,
    max_results: int,
    client: httpx.AsyncClient,
) -> List[SearchResult]:
    """Use SerpAPI JSON API. Free tier: 100 searches/month.

    Setup: Register at https://serpapi.com → copy your API key → add
    SERPAPI_KEY to backend/.env
    """
    api_key = os.getenv("SERPAPI_KEY", "").strip()
    if not api_key:
        logger.debug("SERPAPI_KEY not set — skipping SerpAPI")
        return []
    try:
        response = await client.get(
            SERPAPI_URL,
            params={
                "api_key": api_key,
                "q": query,
                "engine": "google",
                "num": min(max_results, 10),
                "gl": "in",
                "hl": "en",
            },
            headers={"Accept": "application/json"},
        )
        if response.status_code >= 400:
            logger.debug("SerpAPI returned %s: %s", response.status_code, response.text[:200])
            return []
        data = response.json()
    except Exception as exc:
        logger.debug("SerpAPI request failed: %s", exc)
        return []

    results: List[SearchResult] = []
    for item in (data.get("organic_results") or [])[:max_results]:
        snippet = item.get("snippet") or ""
        results.append({
            "url": item.get("link") or "",
            "title": item.get("title") or "",
            "content": snippet,
            "raw_content": snippet,
            "source": "serpapi",
        })
    return results


# ──────────────────────────────────────────────────────────────
# Public API — single entry point that replaces Tavily
# ──────────────────────────────────────────────────────────────

async def free_web_search(
    query: str,
    *,
    max_results: int = DEFAULT_MAX_RESULTS,
    timeout: int = DEFAULT_TIMEOUT,
    provider: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> List[SearchResult]:
    """Search the web for free and return results in Tavily-compatible shape.

    Args:
        query:       The search query string (same as you'd pass to Tavily).
        max_results: How many results to return (default 5).
        timeout:     HTTP timeout in seconds (default 20).
        provider:    Force a specific provider: duckduckgo | google | bing | serpapi | auto
                     Defaults to FREE_SEARCH_PROVIDER env var (fallback: auto).
        client:      Optional shared httpx.AsyncClient (created internally if omitted).

    Returns:
        List of result dicts:
          { url, title, content, raw_content, source }
        Empty list on complete failure (never raises).
    """
    chosen = (provider or _provider()).lower()
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=timeout, headers=_HEADERS, follow_redirects=True)

    results: List[SearchResult] = []
    try:
        if chosen == "duckduckgo":
            results = await _search_duckduckgo(query, max_results, client)

        elif chosen == "google":
            results = await _search_google_cse(query, max_results, client)

        elif chosen == "bing":
            results = await _search_bing(query, max_results, client)

        elif chosen == "serpapi":
            results = await _search_serpapi(query, max_results, client)

        else:
            # auto — waterfall: DDG → Google CSE → Bing → SerpAPI
            results = await _search_duckduckgo(query, max_results, client)
            if not results:
                results = await _search_google_cse(query, max_results, client)
            if not results:
                results = await _search_bing(query, max_results, client)
            if not results:
                results = await _search_serpapi(query, max_results, client)

    except Exception as exc:
        logger.warning("free_web_search unexpected error for query '%s': %s", query[:80], exc)
    finally:
        if own_client:
            await client.aclose()

    return [r for r in results if r.get("url")]


async def bulk_free_search(
    queries: List[str],
    *,
    max_results: int = DEFAULT_MAX_RESULTS,
    timeout: int = DEFAULT_TIMEOUT,
    concurrency: int = 4,
    provider: Optional[str] = None,
) -> List[tuple]:
    """Run multiple queries concurrently.

    Returns:
        List of (query, results, error) tuples — same contract as the old
        Tavily _run_public_trainer_query gather pattern in api.py.
    """
    semaphore = asyncio.Semaphore(max(1, min(concurrency, 10)))
    chosen = (provider or _provider()).lower()

    # Share one HTTP client across all queries for connection reuse
    async with httpx.AsyncClient(
        timeout=timeout,
        headers=_HEADERS,
        follow_redirects=True,
    ) as shared_client:

        async def _run(query: str):
            async with semaphore:
                try:
                    results = await free_web_search(
                        query,
                        max_results=max_results,
                        provider=chosen,
                        client=shared_client,
                    )
                    return query, {"results": results}, None
                except Exception as exc:
                    return query, None, str(exc)

        return list(await asyncio.gather(*[_run(q) for q in queries]))


# ──────────────────────────────────────────────────────────────
# Convenience helpers used by the route layer
# ──────────────────────────────────────────────────────────────

async def search_linkedin_trainers(
    domain: str,
    *,
    max_results: int = DEFAULT_MAX_RESULTS,
    locations: Optional[List[str]] = None,
    roles: Optional[List[str]] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> List[SearchResult]:
    """Search for LinkedIn trainer profiles for a given domain."""
    _roles = roles or ["trainer", "corporate trainer", "certified trainer", "instructor"]
    _locs = locations or ["India"]
    queries = []
    for role in _roles[:3]:
        for loc in _locs[:3]:
            queries.append(f'site:linkedin.com/in "{domain}" "{role}" "{loc}"')

    results = await bulk_free_search(queries, max_results=max_results, timeout=timeout)
    seen_urls: set = set()
    combined: List[SearchResult] = []
    for _, data, _ in results:
        for r in (data or {}).get("results") or []:
            if r.get("url") and r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                combined.append(r)
    return combined[:max_results]


async def search_client_requirements(
    domain: str,
    *,
    max_results: int = DEFAULT_MAX_RESULTS,
    timeout: int = DEFAULT_TIMEOUT,
) -> List[SearchResult]:
    """Search for LinkedIn company posts that look like trainer requirements."""
    phrases = [
        "Corporate Trainer Required",
        "Need Technical Trainer",
        "Trainer Required",
        "Training Requirement",
    ]
    queries = [f'site:linkedin.com/posts "{phrase}" "{domain}"' for phrase in phrases[:3]]
    results = await bulk_free_search(queries, max_results=max_results, timeout=timeout)
    seen_urls: set = set()
    combined: List[SearchResult] = []
    for _, data, _ in results:
        for r in (data or {}).get("results") or []:
            if r.get("url") and r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                combined.append(r)
    return combined[:max_results]


def is_configured() -> dict:
    """Return a dict describing which free search providers are available."""
    return {
        "duckduckgo": True,   # always available — no key needed
        "google_cse": bool(os.getenv("GOOGLE_CSE_ID") and os.getenv("GOOGLE_CSE_API_KEY")),
        "bing": True,          # always available — no key needed
        "serpapi": bool(os.getenv("SERPAPI_KEY")),
        "active_provider": _provider(),
        "max_results": DEFAULT_MAX_RESULTS,
        "timeout": DEFAULT_TIMEOUT,
    }
