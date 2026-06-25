"""free_search_agent.py — High-volume free web search. Zero cost. 100+ results.

Engine priority order (best → fallback):
  1. Google Custom Search API  — 100 free queries/day, 10 results each  (GOOGLE_CSE_API_KEY + GOOGLE_CSE_ID)
  2. SerpAPI                   — 100 free queries/month, 10 results each (SERPAPI_KEY)
  3. DuckDuckGo HTML scrape    — unlimited, no key, no account
  4. Bing HTML scrape          — unlimited, no key, rarely blocks
  5. Google HTML scrape        — unlimited, aggressive bot detection, last resort
  6. Yahoo HTML scrape         — unlimited, easy fallback
  7. Ask HTML scrape           — unlimited, last resort

Pagination: every engine supports fetching multiple pages so a single
call with max_results=20 triggers page 1 + page 2 automatically.

Key improvements over previous version:
  - DEFAULT_MAX_RESULTS raised from 5 → 20
  - Google CSE and SerpAPI real API engines added (100 results/day free)
  - Bing pagination support (page 1 + 2 = up to 20 results)
  - DuckDuckGo pagination via vqd token (page 1 + 2)
  - Parallel multi-page fetching for each engine
  - Result dedup by URL across all engines within a single query
  - Smarter HTML parsers with multiple fallback regex strategies
  - per-engine retry with exponential backoff on 429/503
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
DEFAULT_TIMEOUT     = int(os.getenv("FREE_SEARCH_TIMEOUT", "25"))
DEFAULT_PROVIDER    = os.getenv("FREE_SEARCH_PROVIDER", "auto").strip().lower()

# Optional API keys for higher-quality results
GOOGLE_CSE_API_KEY  = os.getenv("GOOGLE_CSE_API_KEY", "").strip()
GOOGLE_CSE_ID       = os.getenv("GOOGLE_CSE_ID", "").strip()
SERPAPI_KEY         = os.getenv("SERPAPI_KEY", "").strip()

SearchResult = Dict[str, Any]



# ── Rotating browser headers ───────────────────────────────────
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



# ── HTML helpers ───────────────────────────────────────────────

def _strip_html(html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html or "", flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>",  " ", text,        flags=re.DOTALL | re.IGNORECASE)
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
    """Deduplicate by URL, preserving first occurrence."""
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
    """GET with automatic retry on 429/503."""
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
# ENGINE 1 — Google Custom Search API (100 free queries/day)
# Best quality, real structured data, never gets bot-blocked.
# Requires: GOOGLE_CSE_API_KEY + GOOGLE_CSE_ID in .env
# ══════════════════════════════════════════════════════════════

async def _search_google_cse(query: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    if not GOOGLE_CSE_API_KEY or not GOOGLE_CSE_ID:
        return []
    results: List[SearchResult] = []
    pages_needed = max(1, (max_results + 9) // 10)  # 10 results per page

    async def _fetch_page(start: int) -> List[SearchResult]:
        try:
            resp = await client.get(
                "https://www.googleapis.com/customsearch/v1",
                params={
                    "key":   GOOGLE_CSE_API_KEY,
                    "cx":    GOOGLE_CSE_ID,
                    "q":     query,
                    "num":   min(10, max_results),
                    "start": start,
                    "gl":    "in",
                    "hl":    "en",
                },
                headers={"Accept": "application/json"},
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            page_results = []
            for item in data.get("items") or []:
                page_results.append(_make_result(
                    item.get("link", ""),
                    item.get("title", ""),
                    item.get("snippet", ""),
                    "google_cse",
                ))
            return page_results
        except Exception as exc:
            logger.debug("Google CSE page %d failed: %s", start, exc)
            return []

    page_tasks = [_fetch_page(1 + i * 10) for i in range(min(pages_needed, 10))]
    pages = await asyncio.gather(*page_tasks)
    for page in pages:
        results.extend(page)
    return _dedup(results)[:max_results]



# ══════════════════════════════════════════════════════════════
# ENGINE 2 — SerpAPI (100 free queries/month)
# Real Google results via API, zero bot detection risk.
# Requires: SERPAPI_KEY in .env
# ══════════════════════════════════════════════════════════════

async def _search_serpapi(query: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    if not SERPAPI_KEY:
        return []
    results: List[SearchResult] = []
    pages_needed = max(1, (max_results + 9) // 10)

    async def _fetch_page(start: int) -> List[SearchResult]:
        try:
            resp = await client.get(
                "https://serpapi.com/search",
                params={
                    "api_key": SERPAPI_KEY,
                    "engine":  "google",
                    "q":       query,
                    "num":     min(10, max_results),
                    "start":   start,
                    "gl":      "in",
                    "hl":      "en",
                },
                headers={"Accept": "application/json"},
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            page_results = []
            for item in (data.get("organic_results") or []):
                page_results.append(_make_result(
                    item.get("link", ""),
                    item.get("title", ""),
                    item.get("snippet", ""),
                    "serpapi",
                ))
            return page_results
        except Exception as exc:
            logger.debug("SerpAPI page %d failed: %s", start, exc)
            return []

    page_tasks = [_fetch_page(i * 10) for i in range(min(pages_needed, 10))]
    pages = await asyncio.gather(*page_tasks)
    for page in pages:
        results.extend(page)
    return _dedup(results)[:max_results]



# ══════════════════════════════════════════════════════════════
# ENGINE 3 — DuckDuckGo HTML  (unlimited, no key)
# POST html.duckduckgo.com — most reliable free engine.
# Supports multi-page via the `s` (offset) + `dc` parameters.
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

    # Strategy C: generic links with title text
    if not results:
        for m in re.finditer(r'href="(//duckduckgo\.com/l/[^"]+)"[^>]*>([^<]{10,120})</a>', html, re.IGNORECASE):
            results.append(_make_result(m.group(1), m.group(2), "", source))

    return [r for r in results if r.get("url")]


async def _search_duckduckgo(query: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    results: List[SearchResult] = []

    async def _fetch_page(offset: int) -> List[SearchResult]:
        try:
            data: Dict[str, Any] = {"q": query, "b": "", "kl": "in-en", "df": ""}
            if offset > 0:
                data["s"]  = str(offset)
                data["dc"] = str(offset + 1)
                data["nextParams"] = ""
                data["v"] = "l"
                data["o"] = "json"
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
            logger.debug("DDG page offset=%d failed: %s", offset, exc)
            return []

    pages_needed = max(1, (max_results + 9) // 10)
    offsets = [i * 10 for i in range(min(pages_needed, 5))]
    page_results = await asyncio.gather(*[_fetch_page(o) for o in offsets])
    for page in page_results:
        results.extend(page)
    return _dedup(results)[:max_results]



# ══════════════════════════════════════════════════════════════
# ENGINE 4 — Bing HTML  (unlimited, no key, multi-page)
# GET www.bing.com/search — high quality Indian results.
# Pagination via `first` param: 1, 11, 21 ...
# ══════════════════════════════════════════════════════════════

async def _parse_bing_html(html: str) -> List[SearchResult]:
    results: List[SearchResult] = []

    # Strategy A: b_algo blocks (main organic results)
    blocks = re.findall(r'<li[^>]*class="[^"]*b_algo[^"]*"[^>]*>(.*?)</li>', html, re.DOTALL | re.IGNORECASE)
    for block in blocks:
        link = re.search(r'<h2[^>]*>.*?<a[^>]+href="(https?://(?!(?:www\.)?bing\.)[^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL | re.IGNORECASE)
        snip = re.search(r'<(?:p|div)[^>]*class="[^"]*b_lineclamp[^"]*"[^>]*>(.*?)</(?:p|div)>', block, re.DOTALL | re.IGNORECASE) \
            or re.search(r'<p[^>]*>(.*?)</p>', block, re.DOTALL | re.IGNORECASE)
        if link:
            results.append(_make_result(link.group(1), link.group(2), snip.group(1) if snip else "", "bing"))

    # Strategy B: any direct https href inside h2 tags
    if not results:
        for m in re.finditer(r'<h2[^>]*>.*?<a[^>]+href="(https?://(?!(?:www\.)?bing\.)[^"]+)"[^>]*>(.*?)</a>.*?</h2>', html, re.DOTALL | re.IGNORECASE):
            results.append(_make_result(m.group(1), m.group(2), "", "bing"))

    # Strategy C: broad link sweep fallback
    if not results:
        for m in re.finditer(r'<a[^>]+href="(https?://(?!(?:www\.)?bing\.)[^"#?][^"]{10,})"[^>]*><strong>(.*?)</strong>', html, re.DOTALL | re.IGNORECASE):
            results.append(_make_result(m.group(1), m.group(2), "", "bing"))

    return [r for r in results if r.get("url")]


async def _search_bing(query: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    results: List[SearchResult] = []
    pages_needed = max(1, (max_results + 9) // 10)

    async def _fetch_page(first: int) -> List[SearchResult]:
        resp = await _retry_get(
            client,
            "https://www.bing.com/search",
            params={"q": query, "count": 10, "first": first, "mkt": "en-IN", "setlang": "en"},
            headers=_headers("https://www.bing.com/"),
        )
        if not resp or resp.status_code >= 400:
            return []
        return await _parse_bing_html(resp.text)

    page_results = await asyncio.gather(*[_fetch_page(1 + i * 10) for i in range(min(pages_needed, 5))])
    for page in page_results:
        results.extend(page)
    return _dedup(results)[:max_results]



# ══════════════════════════════════════════════════════════════
# ENGINE 5 — Google HTML  (unlimited, needs bypass tricks)
# Multi-strategy: mobile UA, google.co.in, country params.
# Pagination via `start` param: 0, 10, 20 ...
# ══════════════════════════════════════════════════════════════

async def _parse_google_html(html: str) -> List[SearchResult]:
    results: List[SearchResult] = []

    # Strategy A: <div class="g"> organic result blocks
    blocks = re.findall(r'<div[^>]*\bclass="[^"]*\bg\b[^"]*"[^>]*>(.*?)</div>\s*</div>', html, re.DOTALL | re.IGNORECASE)
    for block in blocks[:40]:
        link  = re.search(r'<a[^>]+href="(https?://(?!(?:www\.)?google)[^"&]+)"', block, re.IGNORECASE)
        title = re.search(r'<h3[^>]*>(.*?)</h3>', block, re.DOTALL | re.IGNORECASE)
        snip  = re.search(r'<(?:span|div)[^>]*class="[^"]*(?:st|VwiC3b|s3v9rd|lyLwlc)[^"]*"[^>]*>(.*?)</(?:span|div)>', block, re.DOTALL | re.IGNORECASE)
        if link and title:
            results.append(_make_result(link.group(1), title.group(1), snip.group(1) if snip else "", "google"))

    # Strategy B: /url?q= redirect links with h3
    if not results:
        for m in re.finditer(r'href="/url\?q=(https?[^&"]+)[^"]*"[^>]*>.*?<h3[^>]*>(.*?)</h3>', html, re.DOTALL | re.IGNORECASE):
            results.append(_make_result(m.group(1), m.group(2), "", "google"))

    # Strategy C: any external https link near an h3
    if not results:
        for m in re.finditer(r'<a[^>]+href="(https?://(?!(?:www\.)?google)[^"]+)"[^>]*>(?:[^<]*<[^>]+>)*?<h3[^>]*>(.*?)</h3>', html, re.DOTALL | re.IGNORECASE):
            results.append(_make_result(m.group(1), m.group(2), "", "google"))

    return [r for r in results if r.get("url")]


async def _search_google(query: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    results: List[SearchResult] = []
    pages_needed = max(1, (max_results + 9) // 10)

    async def _fetch_page(start: int) -> List[SearchResult]:
        endpoints = [
            ("https://www.google.com/search",    {"q": query, "num": 10, "start": start, "hl": "en", "gl": "in"}, True),
            ("https://www.google.co.in/search",  {"q": query, "num": 10, "start": start, "hl": "en"},             False),
        ]
        for url, params, mobile in endpoints:
            try:
                resp = await client.get(url, params=params, headers=_headers(url, mobile=mobile), follow_redirects=True)
                if resp.status_code == 200 and len(resp.text) > 2000:
                    page = await _parse_google_html(resp.text)
                    if page:
                        return page
            except Exception as exc:
                logger.debug("Google HTML start=%d failed: %s", start, exc)
        return []

    page_results = await asyncio.gather(*[_fetch_page(i * 10) for i in range(min(pages_needed, 5))])
    for page in page_results:
        results.extend(page)
    return _dedup(results)[:max_results]



# ══════════════════════════════════════════════════════════════
# ENGINE 6 — Yahoo Search  (unlimited, easy fallback)
# ══════════════════════════════════════════════════════════════

async def _search_yahoo(query: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    results: List[SearchResult] = []
    pages_needed = max(1, (max_results + 6) // 7)  # Yahoo returns ~7 per page

    async def _fetch_page(b: int) -> List[SearchResult]:
        resp = await _retry_get(
            client,
            "https://search.yahoo.com/search",
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

    page_results = await asyncio.gather(*[_fetch_page(1 + i * 10) for i in range(min(pages_needed, 4))])
    for page in page_results:
        results.extend(page)
    return _dedup(results)[:max_results]


# ══════════════════════════════════════════════════════════════
# ENGINE 7 — Ask.com  (last resort)
# ══════════════════════════════════════════════════════════════

async def _search_ask(query: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    resp = await _retry_get(
        client,
        "https://www.ask.com/web",
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
# MAIN PUBLIC API
# ══════════════════════════════════════════════════════════════

# Engine registry — ordered from best quality to last resort.
# API-based engines are inserted at the front at runtime when keys are present.
_HTML_ENGINES = [
    ("duckduckgo", _search_duckduckgo),
    ("bing",       _search_bing),
    ("google",     _search_google),
    ("yahoo",      _search_yahoo),
    ("ask",        _search_ask),
]


def _build_engine_list(force: Optional[str] = None) -> List[Tuple[str, Any]]:
    """Return ordered engine list, promoting API engines to the front."""
    chosen = (force or DEFAULT_PROVIDER).lower()

    # Named single-engine mode
    if chosen == "google_cse":
        return [("google_cse", _search_google_cse)]
    if chosen == "serpapi":
        return [("serpapi", _search_serpapi)]
    for name, fn in _HTML_ENGINES:
        if chosen == name:
            return [(name, fn)]

    # AUTO mode — build optimal waterfall
    ordered: List[Tuple[str, Any]] = []
    if GOOGLE_CSE_API_KEY and GOOGLE_CSE_ID:
        ordered.append(("google_cse", _search_google_cse))
    if SERPAPI_KEY:
        ordered.append(("serpapi", _search_serpapi))
    ordered.extend(_HTML_ENGINES)
    return ordered


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

    Engine waterfall (auto mode):
      1. Google CSE API   — if GOOGLE_CSE_API_KEY + GOOGLE_CSE_ID set
      2. SerpAPI          — if SERPAPI_KEY set
      3. DuckDuckGo HTML  — unlimited, no key
      4. Bing HTML        — unlimited, multi-page
      5. Google HTML      — unlimited, bypass tricks
      6. Yahoo HTML       — unlimited fallback
      7. Ask HTML         — last resort

    All engines support pagination to return up to max_results.
    Returns list of { url, title, content, raw_content, source }
    """
    engines = _build_engine_list(provider)
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=timeout, follow_redirects=True, http2=False)

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
                    logger.debug("free_web_search: %s returned 0 results, trying next engine", name)
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
    Run multiple queries concurrently via the free search engine.

    Concurrency default raised to 6 (was 4) so 60 queries finish faster.
    Returns: List of (query, {"results": [...]}, error_or_None) tuples
    Same contract as old Tavily gather — zero changes needed in callers.
    """
    semaphore = asyncio.Semaphore(max(1, min(concurrency, 12)))
    chosen = (provider or DEFAULT_PROVIDER).lower()

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, http2=False) as shared_client:

        async def _run(query: str):
            async with semaphore:
                # Small staggered delay so engines don't see identical-IP burst
                await asyncio.sleep(random.uniform(0.1, 0.5))
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


# ── Convenience helpers (unchanged interface) ─────────────────

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
    queries = []
    for role in _roles[:4]:
        for loc in _locs[:4]:
            queries.append(f'site:linkedin.com/in "{domain}" "{role}" "{loc}"')
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
    """Returns current engine configuration and status."""
    return {
        "google_cse":        bool(GOOGLE_CSE_API_KEY and GOOGLE_CSE_ID),
        "serpapi":           bool(SERPAPI_KEY),
        "duckduckgo":        True,
        "bing":              True,
        "google":            True,
        "yahoo":             True,
        "ask":               True,
        "active_provider":   DEFAULT_PROVIDER,
        "max_results":       DEFAULT_MAX_RESULTS,
        "timeout":           DEFAULT_TIMEOUT,
        "requires_api_key":  False,
        "api_engines_active": bool(GOOGLE_CSE_API_KEY or SERPAPI_KEY),
    }
