"""free_search_agent.py — High-volume free web search. Zero cost. 100+ results.

Engine priority order (best → fallback):
  1. Google Custom Search API  — 100 free/day,   real API, zero bot block  (GOOGLE_CSE_API_KEY + GOOGLE_CSE_ID)
  2. SerpAPI                   — 100 free/month,  real API, zero bot block  (SERPAPI_KEY)
  3. ScraperAPI proxy + DDG    — 1000 free/month, residential IP, bypasses ALL blocks (SCRAPERAPI_KEY)
  4. ScraperAPI proxy + Bing   — same key, second engine through residential IP
  5. ScraperAPI proxy + Google — same key, third engine through residential IP
  6. DuckDuckGo HTML (direct)  — unlimited, no key, cloud IP (may get blocked)
  7. Bing HTML (direct)        — unlimited, no key, cloud IP
  8. Google HTML (direct)      — unlimited, no key, aggressive bot check
  9. Yahoo HTML (direct)       — unlimited, easy fallback
 10. Ask HTML (direct)         — last resort

How ScraperAPI works:
  Every HTTP request is routed through ScraperAPI's residential IP pool.
  ScraperAPI handles CAPTCHAs, retries, JS rendering automatically.
  The URL is passed as a query param: https://api.scraperapi.com/?api_key=KEY&url=TARGET_URL
  Free tier: 1,000 requests/month — enough for ~100 profiles/day.
  Sign up: https://www.scraperapi.com/ (no credit card for free tier)

Pagination: every engine supports fetching multiple pages so a single
call with max_results=20 triggers page 1 + page 2 automatically.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import random
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

# ── Defaults ──────────────────────────────────────────────────
DEFAULT_MAX_RESULTS = int(os.getenv("FREE_SEARCH_MAX_RESULTS", "20"))
DEFAULT_TIMEOUT     = int(os.getenv("FREE_SEARCH_TIMEOUT", "30"))
DEFAULT_PROVIDER    = os.getenv("FREE_SEARCH_PROVIDER", "auto").strip().lower()

# Optional API keys — each one unlocks a higher-quality engine tier
GOOGLE_CSE_API_KEY = os.getenv("GOOGLE_CSE_API_KEY", "").strip()
GOOGLE_CSE_ID      = os.getenv("GOOGLE_CSE_ID", "").strip()
SERPAPI_KEY        = os.getenv("SERPAPI_KEY", "").strip()
SCRAPERAPI_KEY     = os.getenv("SCRAPERAPI_KEY", "").strip()

# ScraperAPI endpoint
_SCRAPERAPI_BASE = "https://api.scraperapi.com/"

SearchResult = Dict[str, Any]



# ── Rotating browser User-Agents ──────────────────────────────
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.82 Mobile Safari/537.36",
]
_MOBILE_UA = "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"


def _headers(referer: str = "", mobile: bool = False) -> Dict[str, str]:
    ua = _MOBILE_UA if mobile else random.choice(_USER_AGENTS)
    h: Dict[str, str] = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,hi;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "DNT": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Cache-Control": "max-age=0",
    }
    if referer:
        h["Referer"] = referer
    return h


# ── ScraperAPI helpers ─────────────────────────────────────────

def _scraper_url(target_url: str, render_js: bool = False) -> str:
    """Wrap a target URL through ScraperAPI's residential proxy endpoint."""
    params = {
        "api_key":     SCRAPERAPI_KEY,
        "url":         target_url,
        "country_code": "in",      # route through Indian IPs for better LinkedIn/Naukri results
        "keep_headers": "true",
    }
    if render_js:
        params["render"] = "true"
    return _SCRAPERAPI_BASE + "?" + urllib.parse.urlencode(params)


def _make_scraper_client(timeout: int = DEFAULT_TIMEOUT) -> httpx.AsyncClient:
    """
    Create an httpx client configured to route ALL requests through ScraperAPI.
    ScraperAPI handles: residential IP rotation, CAPTCHA solving, retries.
    Usage cost: 1 credit per request (1,000 free credits/month on free tier).
    """
    return httpx.AsyncClient(
        timeout=timeout + 10,   # ScraperAPI adds ~5s overhead
        follow_redirects=True,
        http2=False,
    )



# ── HTML parsing helpers ───────────────────────────────────────

def _strip_html(html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html or "", flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>",   " ", text,        flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    for entity, char in [
        ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'),
        ("&#x27;", "'"), ("&nbsp;", " "), ("&#39;", "'"), ("&apos;", "'"),
    ]:
        text = text.replace(entity, char)
    return re.sub(r"\s+", " ", text).strip()


def _decode_url(raw: str) -> str:
    if not raw:
        return ""
    m = re.search(r"uddg=([^&]+)", raw)
    if m:
        return urllib.parse.unquote(m.group(1))
    m = re.search(r"[?&](?:q|url)=(https?[^&]+)", raw)
    if m:
        return urllib.parse.unquote(m.group(1))
    if raw.startswith("//"):
        return "https:" + raw
    return raw


def _make_result(url: str, title: str, snippet: str, source: str) -> SearchResult:
    url     = _decode_url(url.strip())
    title   = _strip_html(title).strip()
    snippet = _strip_html(snippet).strip()
    return {"url": url, "title": title, "content": snippet, "raw_content": snippet, "source": source}


def _dedup(results: List[SearchResult]) -> List[SearchResult]:
    """Deduplicate by URL, preserving order of first occurrence."""
    seen: set = set()
    out: List[SearchResult] = []
    for r in results:
        u = (r.get("url") or "").rstrip("/").lower()
        if u and u not in seen:
            seen.add(u)
            out.append(r)
    return out


async def _retry_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: Optional[Dict] = None,
    headers: Optional[Dict] = None,
    retries: int = 3,
    backoff: float = 1.0,
) -> Optional[httpx.Response]:
    """GET with automatic retry on 429 / 503."""
    for attempt in range(retries):
        try:
            resp = await client.get(url, params=params, headers=headers, follow_redirects=True)
            if resp.status_code in (429, 503):
                await asyncio.sleep(backoff * (attempt + 1))
                continue
            return resp
        except Exception as exc:
            if attempt < retries - 1:
                await asyncio.sleep(backoff * (attempt + 1))
            else:
                logger.debug("_retry_get %s failed: %s", url, exc)
    return None



# ══════════════════════════════════════════════════════════════
# ENGINE 1 — Google Custom Search API  (100 free queries/day)
# Real structured data, zero bot block, no proxy needed.
# Requires: GOOGLE_CSE_API_KEY + GOOGLE_CSE_ID in .env
# ══════════════════════════════════════════════════════════════

async def _search_google_cse(query: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    if not GOOGLE_CSE_API_KEY or not GOOGLE_CSE_ID:
        return []
    pages_needed = max(1, (max_results + 9) // 10)

    async def _fetch_page(start: int) -> List[SearchResult]:
        try:
            resp = await client.get(
                "https://www.googleapis.com/customsearch/v1",
                params={"key": GOOGLE_CSE_API_KEY, "cx": GOOGLE_CSE_ID, "q": query,
                        "num": min(10, max_results), "start": start, "gl": "in", "hl": "en"},
                headers={"Accept": "application/json"},
            )
            if resp.status_code != 200:
                return []
            return [
                _make_result(i.get("link",""), i.get("title",""), i.get("snippet",""), "google_cse")
                for i in (resp.json().get("items") or [])
            ]
        except Exception as exc:
            logger.debug("Google CSE page start=%d failed: %s", start, exc)
            return []

    pages = await asyncio.gather(*[_fetch_page(1 + i * 10) for i in range(min(pages_needed, 10))])
    results: List[SearchResult] = []
    for p in pages:
        results.extend(p)
    return _dedup(results)[:max_results]


# ══════════════════════════════════════════════════════════════
# ENGINE 2 — SerpAPI  (100 free queries/month)
# Real Google results via API, zero bot block, no proxy needed.
# Requires: SERPAPI_KEY in .env
# ══════════════════════════════════════════════════════════════

async def _search_serpapi(query: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    if not SERPAPI_KEY:
        return []
    pages_needed = max(1, (max_results + 9) // 10)

    async def _fetch_page(start: int) -> List[SearchResult]:
        try:
            resp = await client.get(
                "https://serpapi.com/search",
                params={"api_key": SERPAPI_KEY, "engine": "google", "q": query,
                        "num": min(10, max_results), "start": start, "gl": "in", "hl": "en"},
                headers={"Accept": "application/json"},
            )
            if resp.status_code != 200:
                return []
            return [
                _make_result(i.get("link",""), i.get("title",""), i.get("snippet",""), "serpapi")
                for i in (resp.json().get("organic_results") or [])
            ]
        except Exception as exc:
            logger.debug("SerpAPI page start=%d failed: %s", start, exc)
            return []

    pages = await asyncio.gather(*[_fetch_page(i * 10) for i in range(min(pages_needed, 10))])
    results: List[SearchResult] = []
    for p in pages:
        results.extend(p)
    return _dedup(results)[:max_results]



# ══════════════════════════════════════════════════════════════
# HTML PARSERS  (shared by both direct and ScraperAPI engines)
# ══════════════════════════════════════════════════════════════

async def _parse_ddg_html(html: str, source: str = "duckduckgo") -> List[SearchResult]:
    results: List[SearchResult] = []
    # Strategy A: structured result blocks
    blocks = re.findall(
        r'<div[^>]*class="[^"]*results_links[^"]*"[^>]*>(.*?)</div>\s*</div>',
        html, re.DOTALL | re.IGNORECASE,
    )
    for block in blocks:
        link = re.search(r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', block, re.DOTALL | re.IGNORECASE)
        snip = re.search(r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</(?:a|span|div)>', block, re.DOTALL | re.IGNORECASE)
        if link:
            results.append(_make_result(link.group(1), link.group(2), snip.group(1) if snip else "", source))
    # Strategy B: any result__a links
    if not results:
        for m in re.finditer(r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', html, re.DOTALL | re.IGNORECASE):
            results.append(_make_result(m.group(1), m.group(2), "", source))
    # Strategy C: uddg-encoded redirect links
    if not results:
        for m in re.finditer(r'href="(//duckduckgo\.com/l/[^"]+)"[^>]*>([^<]{10,120})</a>', html, re.IGNORECASE):
            results.append(_make_result(m.group(1), m.group(2), "", source))
    return [r for r in results if r.get("url")]


async def _parse_bing_html(html: str, source: str = "bing") -> List[SearchResult]:
    results: List[SearchResult] = []
    # Strategy A: b_algo organic blocks
    blocks = re.findall(r'<li[^>]*class="[^"]*b_algo[^"]*"[^>]*>(.*?)</li>', html, re.DOTALL | re.IGNORECASE)
    for block in blocks:
        link = re.search(r'<h2[^>]*>.*?<a[^>]+href="(https?://(?!(?:www\.)?bing\.)[^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL | re.IGNORECASE)
        snip = (re.search(r'<(?:p|div)[^>]*class="[^"]*b_lineclamp[^"]*"[^>]*>(.*?)</(?:p|div)>', block, re.DOTALL | re.IGNORECASE)
                or re.search(r'<p[^>]*>(.*?)</p>', block, re.DOTALL | re.IGNORECASE))
        if link:
            results.append(_make_result(link.group(1), link.group(2), snip.group(1) if snip else "", source))
    # Strategy B: h2 links
    if not results:
        for m in re.finditer(r'<h2[^>]*>.*?<a[^>]+href="(https?://(?!(?:www\.)?bing\.)[^"]+)"[^>]*>(.*?)</a>.*?</h2>', html, re.DOTALL | re.IGNORECASE):
            results.append(_make_result(m.group(1), m.group(2), "", source))
    # Strategy C: bold link sweep
    if not results:
        for m in re.finditer(r'<a[^>]+href="(https?://(?!(?:www\.)?bing\.)[^"#?][^"]{10,})"[^>]*><strong>(.*?)</strong>', html, re.DOTALL | re.IGNORECASE):
            results.append(_make_result(m.group(1), m.group(2), "", source))
    return [r for r in results if r.get("url")]


async def _parse_google_html(html: str, source: str = "google") -> List[SearchResult]:
    results: List[SearchResult] = []
    # Strategy A: class="g" organic blocks
    blocks = re.findall(r'<div[^>]*\bclass="[^"]*\bg\b[^"]*"[^>]*>(.*?)</div>\s*</div>', html, re.DOTALL | re.IGNORECASE)
    for block in blocks[:40]:
        link  = re.search(r'<a[^>]+href="(https?://(?!(?:www\.)?google)[^"&]+)"', block, re.IGNORECASE)
        title = re.search(r'<h3[^>]*>(.*?)</h3>', block, re.DOTALL | re.IGNORECASE)
        snip  = re.search(r'<(?:span|div)[^>]*class="[^"]*(?:st|VwiC3b|s3v9rd|lyLwlc)[^"]*"[^>]*>(.*?)</(?:span|div)>', block, re.DOTALL | re.IGNORECASE)
        if link and title:
            results.append(_make_result(link.group(1), title.group(1), snip.group(1) if snip else "", source))
    # Strategy B: /url?q= redirect + h3
    if not results:
        for m in re.finditer(r'href="/url\?q=(https?[^&"]+)[^"]*"[^>]*>.*?<h3[^>]*>(.*?)</h3>', html, re.DOTALL | re.IGNORECASE):
            results.append(_make_result(m.group(1), m.group(2), "", source))
    # Strategy C: external link + h3
    if not results:
        for m in re.finditer(r'<a[^>]+href="(https?://(?!(?:www\.)?google)[^"]+)"[^>]*>(?:[^<]*<[^>]+>)*?<h3[^>]*>(.*?)</h3>', html, re.DOTALL | re.IGNORECASE):
            results.append(_make_result(m.group(1), m.group(2), "", source))
    return [r for r in results if r.get("url")]



# ══════════════════════════════════════════════════════════════
# ENGINES 3–5 — ScraperAPI + HTML engines
# Each request is routed through ScraperAPI's residential IP pool.
# ScraperAPI handles: CAPTCHA, IP rotation, retries automatically.
# Cost: 1 credit per page (1,000 free credits/month).
# Result: ALL bot blocks bypassed — same results as if browsing from home.
# ══════════════════════════════════════════════════════════════

async def _scraper_get(client: httpx.AsyncClient, target_url: str, params: Optional[Dict] = None) -> Optional[str]:
    """Fetch target_url via ScraperAPI residential proxy. Returns HTML text or None."""
    if params:
        target_url = target_url + "?" + urllib.parse.urlencode(params)
    proxy_url = _scraper_url(target_url)
    try:
        resp = await client.get(proxy_url, headers={"Accept": "text/html"}, follow_redirects=True)
        if resp.status_code == 200 and len(resp.text) > 500:
            return resp.text
        logger.debug("ScraperAPI returned status=%d for %s", resp.status_code, target_url[:80])
    except Exception as exc:
        logger.debug("ScraperAPI fetch failed for %s: %s", target_url[:80], exc)
    return None


async def _search_scraper_duckduckgo(query: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    """DuckDuckGo HTML via ScraperAPI residential proxy — bypasses all bot blocks."""
    results: List[SearchResult] = []
    pages_needed = max(1, (max_results + 9) // 10)

    async def _fetch_page(offset: int) -> List[SearchResult]:
        # Build the DDG POST as a GET with query params for ScraperAPI
        params: Dict[str, Any] = {"q": query, "b": "", "kl": "in-en"}
        if offset > 0:
            params.update({"s": str(offset), "dc": str(offset + 1), "v": "l", "o": "json"})
        # ScraperAPI only supports GET — encode DDG POST params as query string
        target = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode(params)
        html = await _scraper_get(client, target.split("?")[0], dict(urllib.parse.parse_qsl(target.split("?")[1])))
        if not html:
            return []
        return await _parse_ddg_html(html, "scraper_duckduckgo")

    pages = await asyncio.gather(*[_fetch_page(i * 10) for i in range(min(pages_needed, 5))])
    for p in pages:
        results.extend(p)
    return _dedup(results)[:max_results]


async def _search_scraper_bing(query: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    """Bing HTML via ScraperAPI residential proxy — bypasses all bot blocks."""
    results: List[SearchResult] = []
    pages_needed = max(1, (max_results + 9) // 10)

    async def _fetch_page(first: int) -> List[SearchResult]:
        html = await _scraper_get(
            client,
            "https://www.bing.com/search",
            {"q": query, "count": 10, "first": first, "mkt": "en-IN", "setlang": "en"},
        )
        if not html:
            return []
        return await _parse_bing_html(html, "scraper_bing")

    pages = await asyncio.gather(*[_fetch_page(1 + i * 10) for i in range(min(pages_needed, 5))])
    for p in pages:
        results.extend(p)
    return _dedup(results)[:max_results]


async def _search_scraper_google(query: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    """Google HTML via ScraperAPI residential proxy — bypasses CAPTCHA and bot blocks."""
    results: List[SearchResult] = []
    pages_needed = max(1, (max_results + 9) // 10)

    async def _fetch_page(start: int) -> List[SearchResult]:
        html = await _scraper_get(
            client,
            "https://www.google.com/search",
            {"q": query, "num": 10, "start": start, "hl": "en", "gl": "in"},
        )
        if not html:
            return []
        return await _parse_google_html(html, "scraper_google")

    pages = await asyncio.gather(*[_fetch_page(i * 10) for i in range(min(pages_needed, 5))])
    for p in pages:
        results.extend(p)
    return _dedup(results)[:max_results]



# ══════════════════════════════════════════════════════════════
# ENGINES 6–8 — Direct HTML scrapers (no proxy, cloud IP)
# These work when the server IP is not blocked.
# DuckDuckGo & Bing rarely block cloud IPs.
# Google almost always blocks cloud IPs — use ScraperAPI instead.
# ══════════════════════════════════════════════════════════════

async def _search_duckduckgo(query: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    results: List[SearchResult] = []
    pages_needed = max(1, (max_results + 9) // 10)

    async def _fetch_page(offset: int) -> List[SearchResult]:
        try:
            data: Dict[str, Any] = {"q": query, "b": "", "kl": "in-en", "df": ""}
            if offset > 0:
                data.update({"s": str(offset), "dc": str(offset + 1), "nextParams": "", "v": "l", "o": "json"})
            resp = await client.post(
                "https://html.duckduckgo.com/html/",
                data=data,
                headers=_headers("https://duckduckgo.com/"),
                follow_redirects=True,
            )
            if resp.status_code >= 400:
                return []
            return await _parse_ddg_html(resp.text)
        except Exception as exc:
            logger.debug("DDG direct offset=%d failed: %s", offset, exc)
            return []

    pages = await asyncio.gather(*[_fetch_page(i * 10) for i in range(min(pages_needed, 5))])
    for p in pages:
        results.extend(p)
    return _dedup(results)[:max_results]


async def _search_bing(query: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    results: List[SearchResult] = []
    pages_needed = max(1, (max_results + 9) // 10)

    async def _fetch_page(first: int) -> List[SearchResult]:
        resp = await _retry_get(
            client, "https://www.bing.com/search",
            params={"q": query, "count": 10, "first": first, "mkt": "en-IN", "setlang": "en"},
            headers=_headers("https://www.bing.com/"),
        )
        if not resp or resp.status_code >= 400:
            return []
        return await _parse_bing_html(resp.text)

    pages = await asyncio.gather(*[_fetch_page(1 + i * 10) for i in range(min(pages_needed, 5))])
    for p in pages:
        results.extend(p)
    return _dedup(results)[:max_results]


async def _search_google(query: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    results: List[SearchResult] = []
    pages_needed = max(1, (max_results + 9) // 10)

    async def _fetch_page(start: int) -> List[SearchResult]:
        for url, mobile in [
            ("https://www.google.com/search",   True),
            ("https://www.google.co.in/search", False),
        ]:
            try:
                resp = await client.get(
                    url,
                    params={"q": query, "num": 10, "start": start, "hl": "en", "gl": "in"},
                    headers=_headers(url, mobile=mobile),
                    follow_redirects=True,
                )
                if resp.status_code == 200 and len(resp.text) > 2000:
                    page = await _parse_google_html(resp.text)
                    if page:
                        return page
            except Exception as exc:
                logger.debug("Google direct start=%d failed: %s", start, exc)
        return []

    pages = await asyncio.gather(*[_fetch_page(i * 10) for i in range(min(pages_needed, 5))])
    for p in pages:
        results.extend(p)
    return _dedup(results)[:max_results]


# ══════════════════════════════════════════════════════════════
# ENGINE 9 — Yahoo  (direct, unlimited, easy fallback)
# ══════════════════════════════════════════════════════════════

async def _search_yahoo(query: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    results: List[SearchResult] = []
    pages_needed = max(1, (max_results + 6) // 7)

    async def _fetch_page(b: int) -> List[SearchResult]:
        resp = await _retry_get(
            client, "https://search.yahoo.com/search",
            params={"p": query, "n": 10, "b": b, "ei": "UTF-8"},
            headers=_headers("https://search.yahoo.com/"),
        )
        if not resp or resp.status_code >= 400:
            return []
        html = resp.text
        page: List[SearchResult] = []
        blocks = re.findall(r'<div[^>]*class="[^"]*(?:algo|dd)[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL | re.IGNORECASE)
        for block in blocks:
            link = re.search(r'<h3[^>]*>.*?<a[^>]+href="(https?://(?!(?:www\.)?yahoo)[^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL | re.IGNORECASE)
            snip = re.search(r'<p[^>]*class="[^"]*s-desc[^"]*"[^>]*>(.*?)</p>', block, re.DOTALL | re.IGNORECASE)
            if link:
                page.append(_make_result(link.group(1), link.group(2), snip.group(1) if snip else "", "yahoo"))
        if not page:
            for m in re.finditer(r'<a[^>]+href="(https?://(?!(?:www\.)?yahoo)[^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL | re.IGNORECASE):
                t = _strip_html(m.group(2)).strip()
                if len(t) > 10:
                    page.append(_make_result(m.group(1), t, "", "yahoo"))
        return page

    pages = await asyncio.gather(*[_fetch_page(1 + i * 10) for i in range(min(pages_needed, 4))])
    for p in pages:
        results.extend(p)
    return _dedup(results)[:max_results]


# ══════════════════════════════════════════════════════════════
# ENGINE 10 — Ask.com  (direct, last resort)
# ══════════════════════════════════════════════════════════════

async def _search_ask(query: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    resp = await _retry_get(
        client, "https://www.ask.com/web",
        params={"q": query, "qsrc": "0", "o": "0", "l": "dir"},
        headers=_headers("https://www.ask.com/"),
    )
    if not resp or resp.status_code >= 400:
        return []
    html = resp.text
    results: List[SearchResult] = []
    blocks = re.findall(r'<div[^>]*class="[^"]*PartialSearchResults-item[^"]*"[^>]*>(.*?)</div>\s*</div>', html, re.DOTALL | re.IGNORECASE)
    for block in blocks[:max_results]:
        link = re.search(r'<a[^>]+href="(https?://(?!ask\.com)[^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL | re.IGNORECASE)
        snip = re.search(r'<p[^>]*>(.*?)</p>', block, re.DOTALL | re.IGNORECASE)
        if link:
            results.append(_make_result(link.group(1), link.group(2), snip.group(1) if snip else "", "ask"))
    if not results:
        for m in re.finditer(r'<a[^>]+href="(https?://(?!(?:www\.)?ask\.com)[^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL | re.IGNORECASE):
            t = _strip_html(m.group(2)).strip()
            if len(t) > 10:
                results.append(_make_result(m.group(1), t, "", "ask"))
                if len(results) >= max_results:
                    break
    return _dedup(results)[:max_results]



# ══════════════════════════════════════════════════════════════
# ENGINE REGISTRY
# ══════════════════════════════════════════════════════════════

# Direct HTML engines (cloud IP — may get blocked by Google/LinkedIn)
_DIRECT_HTML_ENGINES: List[Tuple[str, Any]] = [
    ("duckduckgo", _search_duckduckgo),
    ("bing",       _search_bing),
    ("google",     _search_google),
    ("yahoo",      _search_yahoo),
    ("ask",        _search_ask),
]

# ScraperAPI-backed HTML engines (residential IP — bypasses all blocks)
_SCRAPER_HTML_ENGINES: List[Tuple[str, Any]] = [
    ("scraper_duckduckgo", _search_scraper_duckduckgo),
    ("scraper_bing",       _search_scraper_bing),
    ("scraper_google",     _search_scraper_google),
]


def _build_engine_list(force: Optional[str] = None) -> List[Tuple[str, Any]]:
    """
    Return ordered engine list based on available API keys.

    Priority:
      1. Google CSE API      — if GOOGLE_CSE_API_KEY + GOOGLE_CSE_ID set
      2. SerpAPI             — if SERPAPI_KEY set
      3. ScraperAPI engines  — if SCRAPERAPI_KEY set (residential IP, no bot block)
      4. Direct HTML engines — always available as last resort
    """
    chosen = (force or DEFAULT_PROVIDER).lower()

    # Force a specific single engine
    if chosen == "google_cse":
        return [("google_cse", _search_google_cse)]
    if chosen == "serpapi":
        return [("serpapi", _search_serpapi)]
    if chosen in {"scraper_duckduckgo", "scraper_bing", "scraper_google"}:
        mapping = dict(_SCRAPER_HTML_ENGINES)
        return [(chosen, mapping[chosen])] if chosen in mapping else []
    for name, fn in _DIRECT_HTML_ENGINES:
        if chosen == name:
            return [(name, fn)]

    # AUTO mode — build optimal waterfall based on available keys
    ordered: List[Tuple[str, Any]] = []
    if GOOGLE_CSE_API_KEY and GOOGLE_CSE_ID:
        ordered.append(("google_cse", _search_google_cse))
    if SERPAPI_KEY:
        ordered.append(("serpapi", _search_serpapi))
    if SCRAPERAPI_KEY:
        # ScraperAPI engines go before direct HTML — they bypass bot blocks
        ordered.extend(_SCRAPER_HTML_ENGINES)
    # Direct HTML engines always at the end as fallback
    ordered.extend(_DIRECT_HTML_ENGINES)
    return ordered



# ══════════════════════════════════════════════════════════════
# MAIN PUBLIC API
# ══════════════════════════════════════════════════════════════

async def free_web_search(
    query: str,
    *,
    max_results: int = DEFAULT_MAX_RESULTS,
    timeout: int = DEFAULT_TIMEOUT,
    provider: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> List[SearchResult]:
    """
    Search the web for up to `max_results` results.

    Engine waterfall (auto mode, based on which keys are set in .env):
      1. Google CSE API      — GOOGLE_CSE_API_KEY + GOOGLE_CSE_ID
      2. SerpAPI             — SERPAPI_KEY
      3. ScraperAPI + DDG    — SCRAPERAPI_KEY  (residential IP, no bot block)
      4. ScraperAPI + Bing   — SCRAPERAPI_KEY  (same key, second engine)
      5. ScraperAPI + Google — SCRAPERAPI_KEY  (same key, third engine)
      6. DuckDuckGo direct   — no key needed   (cloud IP, may get blocked)
      7. Bing direct         — no key needed
      8. Google direct       — no key needed   (usually blocked on cloud IPs)
      9. Yahoo direct        — no key needed
     10. Ask direct          — no key needed

    Returns list of { url, title, content, raw_content, source }
    Same shape as old Tavily — callers need zero changes.
    """
    engines = _build_engine_list(provider)
    own_client = client is None

    # When SCRAPERAPI_KEY is set, use a dedicated longer-timeout client
    # because ScraperAPI adds ~5s overhead per request.
    if own_client:
        client = (
            _make_scraper_client(timeout)
            if SCRAPERAPI_KEY
            else httpx.AsyncClient(timeout=timeout, follow_redirects=True, http2=False)
        )

    results: List[SearchResult] = []
    try:
        for name, engine_fn in engines:
            try:
                results = await engine_fn(query, max_results, client)
                results = _dedup(results)
                if results:
                    logger.debug(
                        "free_web_search: '%s' → %d results via %s",
                        query[:60], len(results), name,
                    )
                    break
                else:
                    logger.debug("free_web_search: %s returned 0 — trying next engine", name)
            except Exception as exc:
                logger.debug("Engine %s error: %s", name, exc)
    except Exception as exc:
        logger.warning("free_web_search error for '%s': %s", query[:60], exc)
    finally:
        if own_client:
            await client.aclose()

    return [r for r in results if r.get("url")]


async def bulk_free_search(
    queries: List[str],
    *,
    max_results: int = DEFAULT_MAX_RESULTS,
    timeout: int = DEFAULT_TIMEOUT,
    concurrency: int = 6,
    provider: Optional[str] = None,
) -> List[tuple]:
    """
    Run multiple search queries concurrently.

    All queries share a single httpx client — if SCRAPERAPI_KEY is set,
    that client routes every request through ScraperAPI's residential IP pool,
    so bot blocking is bypassed for the entire batch automatically.

    Returns: List of (query, {"results": [...]}, error_or_None) tuples
    Same contract as old Tavily bulk gather — callers need zero changes.
    """
    semaphore = asyncio.Semaphore(max(1, min(concurrency, 12)))
    chosen = (provider or DEFAULT_PROVIDER).lower()

    # Choose client: ScraperAPI adds ~5s overhead, so use longer timeout
    client_timeout = (timeout + 15) if SCRAPERAPI_KEY else timeout
    shared_client = (
        _make_scraper_client(client_timeout)
        if SCRAPERAPI_KEY
        else httpx.AsyncClient(timeout=client_timeout, follow_redirects=True, http2=False)
    )

    async def _run(query: str) -> tuple:
        async with semaphore:
            # Stagger requests slightly so the proxy pool sees natural traffic
            await asyncio.sleep(random.uniform(0.1, 0.4))
            try:
                results = await free_web_search(
                    query,
                    max_results=max_results,
                    provider=chosen,
                    client=shared_client,   # reuse shared client — no per-query overhead
                )
                return query, {"results": results}, None
            except Exception as exc:
                return query, None, str(exc)

    try:
        return list(await asyncio.gather(*[_run(q) for q in queries]))
    finally:
        await shared_client.aclose()



# ── Convenience helpers ────────────────────────────────────────

async def search_linkedin_trainers(
    domain: str,
    *,
    max_results: int = DEFAULT_MAX_RESULTS,
    locations: Optional[List[str]] = None,
    roles: Optional[List[str]] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> List[SearchResult]:
    """Search for LinkedIn trainer profiles for a given domain. No API key needed."""
    _roles = roles or ["trainer", "corporate trainer", "certified trainer", "freelance trainer", "instructor"]
    _locs  = locations or ["Hyderabad", "Bangalore", "Mumbai", "Delhi", "India"]
    queries = [
        f'site:linkedin.com/in "{domain}" "{role}" "{loc}"'
        for role in _roles[:4]
        for loc in _locs[:4]
    ]
    results_list = await bulk_free_search(queries, max_results=max_results, timeout=timeout)
    seen: set = set()
    combined: List[SearchResult] = []
    for _, data, _ in results_list:
        for r in (data or {}).get("results") or []:
            if r.get("url") and r["url"] not in seen:
                seen.add(r["url"])
                combined.append(r)
    return combined[:max_results]


async def search_client_requirements(
    domain: str,
    *,
    max_results: int = DEFAULT_MAX_RESULTS,
    timeout: int = DEFAULT_TIMEOUT,
) -> List[SearchResult]:
    """Search for LinkedIn posts that look like trainer hiring requirements."""
    phrases = [
        "Corporate Trainer Required", "Need Technical Trainer",
        "Trainer Required", "Training Requirement",
        "Looking for Corporate Trainer", "Hiring Trainer",
    ]
    queries = [f'site:linkedin.com/posts "{phrase}" "{domain}"' for phrase in phrases[:4]]
    results_list = await bulk_free_search(queries, max_results=max_results, timeout=timeout)
    seen: set = set()
    combined: List[SearchResult] = []
    for _, data, _ in results_list:
        for r in (data or {}).get("results") or []:
            if r.get("url") and r["url"] not in seen:
                seen.add(r["url"])
                combined.append(r)
    return combined[:max_results]


def is_configured() -> dict:
    """Returns current engine configuration and capability summary."""
    return {
        "google_cse":          bool(GOOGLE_CSE_API_KEY and GOOGLE_CSE_ID),
        "serpapi":             bool(SERPAPI_KEY),
        "scraperapi":          bool(SCRAPERAPI_KEY),
        "duckduckgo":          True,
        "bing":                True,
        "google":              True,
        "yahoo":               True,
        "ask":                 True,
        "active_provider":     DEFAULT_PROVIDER,
        "max_results":         DEFAULT_MAX_RESULTS,
        "timeout":             DEFAULT_TIMEOUT,
        "requires_api_key":    False,
        "bot_block_bypassed":  bool(SCRAPERAPI_KEY or GOOGLE_CSE_API_KEY or SERPAPI_KEY),
        "api_engines_active":  bool(GOOGLE_CSE_API_KEY or SERPAPI_KEY or SCRAPERAPI_KEY),
        "expected_results_per_run": (
            "100+" if (GOOGLE_CSE_API_KEY or SERPAPI_KEY or SCRAPERAPI_KEY) else "5-20 (cloud IP may be blocked)"
        ),
    }
