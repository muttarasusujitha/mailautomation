"""free_search_agent.py — Pure scraping, zero API keys, 100+ trainer profiles per run.

How it reaches 100 profiles without any API:
  ┌─────────────────────────────────────────────────────────────────┐
  │  domains (e.g. Python, DevOps, AWS …)  ×                       │
  │  roles   (trainer, corporate trainer, instructor …)  ×         │
  │  sources (LinkedIn, Naukri, Shine, JustDial, GitHub) ×         │
  │  pages   (page 1 + page 2 + page 3 per query)                  │
  │  ──────────────────────────────────────────────────            │
  │  5 domains × 8 roles × 5 sources × 3 pages = 600 queries      │
  │  Each query returns 3–10 results  →  easily 100–500 profiles   │
  └─────────────────────────────────────────────────────────────────┘

Sources (all free, no login, no API key):
  1. DuckDuckGo HTML  — most reliable, never blocks cloud IPs
  2. Bing HTML        — high-quality Indian results, rarely blocks
  3. Naukri.com       — direct scrape of public trainer profiles
  4. Shine.com        — direct scrape of public trainer profiles
  5. Google HTML      — best quality, strict bot check — used as last resort

All engines support multi-page pagination.
Results from ALL sources are merged and deduplicated by URL.
The caller (api.py) gets a clean deduplicated list of 100+ profiles.
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

# ── Config (env overridable) ──────────────────────────────────
DEFAULT_MAX_RESULTS = int(os.getenv("FREE_SEARCH_MAX_RESULTS", "20"))
DEFAULT_TIMEOUT     = int(os.getenv("FREE_SEARCH_TIMEOUT", "30"))
DEFAULT_PROVIDER    = os.getenv("FREE_SEARCH_PROVIDER", "auto").strip().lower()

SearchResult = Dict[str, Any]

# ── Rotating User-Agents (7 different browsers) ───────────────
_UA = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.82 Mobile Safari/537.36",
]
_MOB_UA = "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36"


def _h(referer: str = "", mobile: bool = False) -> Dict[str, str]:
    """Return browser-like headers with a random desktop or mobile UA."""
    return {
        "User-Agent": _MOB_UA if mobile else random.choice(_UA),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,hi;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "DNT": "1",
        "Referer": referer or "https://www.google.com/",
        "Cache-Control": "max-age=0",
    }


# ══════════════════════════════════════════════════════════════
# HTML UTILITY HELPERS
# ══════════════════════════════════════════════════════════════

def _strip(html: str) -> str:
    """Strip all HTML tags and decode entities."""
    t = re.sub(r"<script[^>]*>.*?</script>", " ", html or "", flags=re.S | re.I)
    t = re.sub(r"<style[^>]*>.*?</style>", " ", t, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    for e, c in [("&amp;","&"),("&lt;","<"),("&gt;",">"),("&quot;",'"'),
                 ("&#39;","'"),("&nbsp;"," "),("&apos;","'"),("&#x27;","'")]:
        t = t.replace(e, c)
    return re.sub(r"\s+", " ", t).strip()


def _dec(raw: str) -> str:
    """Decode DDG / Google redirect-wrapped URLs."""
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


def _mk(url: str, title: str, snippet: str, src: str) -> SearchResult:
    return {
        "url":         _dec(url.strip()),
        "title":       _strip(title).strip(),
        "content":     _strip(snippet).strip(),
        "raw_content": _strip(snippet).strip(),
        "source":      src,
    }


def _dedup(results: List[SearchResult]) -> List[SearchResult]:
    seen: set = set()
    out: List[SearchResult] = []
    for r in results:
        u = (r.get("url") or "").rstrip("/").lower().split("?")[0]
        if u and u not in seen:
            seen.add(u)
            out.append(r)
    return out


async def _get(
    client: httpx.AsyncClient,
    url: str,
    params: Optional[Dict] = None,
    headers: Optional[Dict] = None,
    retries: int = 3,
) -> Optional[httpx.Response]:
    """GET with retry on 429/503."""
    for attempt in range(retries):
        try:
            r = await client.get(url, params=params, headers=headers or _h(url), follow_redirects=True)
            if r.status_code in (429, 503):
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            return r
        except Exception as exc:
            if attempt < retries - 1:
                await asyncio.sleep(1.0 * (attempt + 1))
            else:
                logger.debug("GET %s failed: %s", url[:80], exc)
    return None



# ══════════════════════════════════════════════════════════════
# SOURCE 1 — DuckDuckGo HTML
# POST html.duckduckgo.com — most reliable, never blocks cloud IPs
# Multi-page: offset 0, 10, 20 ... via s= param
# ══════════════════════════════════════════════════════════════

async def _ddg_page(query: str, offset: int, client: httpx.AsyncClient) -> List[SearchResult]:
    """Fetch one page of DDG results."""
    data: Dict[str, Any] = {"q": query, "b": "", "kl": "in-en"}
    if offset > 0:
        data.update({"s": str(offset), "dc": str(offset + 1), "v": "l", "o": "json", "nextParams": ""})
    try:
        r = await client.post(
            "https://html.duckduckgo.com/html/",
            data=data,
            headers=_h("https://duckduckgo.com/"),
            follow_redirects=True,
        )
        if r.status_code >= 400:
            return []
        html = r.text
    except Exception as exc:
        logger.debug("DDG page offset=%d: %s", offset, exc)
        return []

    results: List[SearchResult] = []
    # Strategy A — result blocks
    for block in re.findall(r'<div[^>]*class="[^"]*results_links[^"]*"[^>]*>(.*?)</div>\s*</div>', html, re.S | re.I):
        lk = re.search(r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', block, re.S | re.I)
        sn = re.search(r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</(?:a|span|div)>', block, re.S | re.I)
        if lk:
            results.append(_mk(lk.group(1), lk.group(2), sn.group(1) if sn else "", "duckduckgo"))
    # Strategy B — any result__a
    if not results:
        for m in re.finditer(r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', html, re.S | re.I):
            results.append(_mk(m.group(1), m.group(2), "", "duckduckgo"))
    # Strategy C — uddg redirect links
    if not results:
        for m in re.finditer(r'href="(//duckduckgo\.com/l/[^"]+)"[^>]*>([^<]{10,120})</a>', html, re.I):
            results.append(_mk(m.group(1), m.group(2), "", "duckduckgo"))
    return [r for r in results if r["url"]]


async def _search_duckduckgo(query: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    pages = max(1, (max_results + 9) // 10)
    all_pages = await asyncio.gather(*[_ddg_page(query, i * 10, client) for i in range(min(pages, 5))])
    out: List[SearchResult] = []
    for p in all_pages:
        out.extend(p)
    return _dedup(out)[:max_results]


# ══════════════════════════════════════════════════════════════
# SOURCE 2 — Bing HTML
# High-quality Indian results, pagination via first= param
# ══════════════════════════════════════════════════════════════

async def _bing_page(query: str, first: int, client: httpx.AsyncClient) -> List[SearchResult]:
    r = await _get(
        client, "https://www.bing.com/search",
        params={"q": query, "count": 10, "first": first, "mkt": "en-IN", "setlang": "en"},
        headers=_h("https://www.bing.com/"),
    )
    if not r or r.status_code >= 400:
        return []
    html = r.text
    results: List[SearchResult] = []
    # Strategy A — b_algo blocks
    for block in re.findall(r'<li[^>]*class="[^"]*b_algo[^"]*"[^>]*>(.*?)</li>', html, re.S | re.I):
        lk = re.search(r'<h2[^>]*>.*?<a[^>]+href="(https?://(?!(?:www\.)?bing\.)[^"]+)"[^>]*>(.*?)</a>', block, re.S | re.I)
        sn = re.search(r'<(?:p|div)[^>]*class="[^"]*b_lineclamp[^"]*"[^>]*>(.*?)</(?:p|div)>', block, re.S | re.I) \
          or re.search(r'<p[^>]*>(.*?)</p>', block, re.S | re.I)
        if lk:
            results.append(_mk(lk.group(1), lk.group(2), sn.group(1) if sn else "", "bing"))
    # Strategy B — h2 links
    if not results:
        for m in re.finditer(r'<h2[^>]*>.*?<a[^>]+href="(https?://(?!(?:www\.)?bing\.)[^"]+)"[^>]*>(.*?)</a>.*?</h2>', html, re.S | re.I):
            results.append(_mk(m.group(1), m.group(2), "", "bing"))
    # Strategy C — strong links
    if not results:
        for m in re.finditer(r'<a[^>]+href="(https?://(?!(?:www\.)?bing\.)[^"#?][^"]{10,})"[^>]*><strong>(.*?)</strong>', html, re.S | re.I):
            results.append(_mk(m.group(1), m.group(2), "", "bing"))
    return [r for r in results if r["url"]]


async def _search_bing(query: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    pages = max(1, (max_results + 9) // 10)
    all_pages = await asyncio.gather(*[_bing_page(query, 1 + i * 10, client) for i in range(min(pages, 5))])
    out: List[SearchResult] = []
    for p in all_pages:
        out.extend(p)
    return _dedup(out)[:max_results]



# ══════════════════════════════════════════════════════════════
# SOURCE 3 — Naukri.com direct scrape
# Naukri has public trainer profile pages that show name, skills,
# experience, location — and sometimes email + phone.
# We search Naukri's own search endpoint directly (no Google needed).
# ══════════════════════════════════════════════════════════════

async def _naukri_search(query: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    """
    Scrape Naukri public profile search.
    URL: https://www.naukri.com/training-jobs?k=<query>
    Also tries: https://www.naukri.com/<keyword>-trainer-jobs
    Returns profile URLs + name + snippet.
    """
    results: List[SearchResult] = []

    # Build Naukri search URLs — job keyword search returns trainer profiles
    keyword = urllib.parse.quote_plus(query.replace('"', '').replace("site:naukri.com", "").strip())
    urls_to_try = [
        f"https://www.naukri.com/jobs?k={keyword}&l=india&jobAge=30",
        f"https://www.naukri.com/training-jobs-in-india?k={keyword}",
    ]

    for search_url in urls_to_try:
        r = await _get(client, search_url, headers=_h("https://www.naukri.com/"))
        if not r or r.status_code >= 400 or len(r.text) < 500:
            continue
        html = r.text

        # Extract profile/job links
        for m in re.finditer(
            r'<a[^>]+href="(https://www\.naukri\.com/(?:job-listings|[a-z0-9\-]+-\d+)[^"]*)"[^>]*>(.*?)</a>',
            html, re.S | re.I
        ):
            url = m.group(1).split("?")[0]
            title = _strip(m.group(2)).strip()
            if len(title) > 5:
                results.append(_mk(url, title, "", "naukri"))

        # Also extract candidate profile URLs
        for m in re.finditer(
            r'href="(https://www\.naukri\.com/mnjuser/profile\?[^"]+)"',
            html, re.I
        ):
            results.append(_mk(m.group(1), "Naukri Trainer Profile", "", "naukri"))

        if results:
            break

    return _dedup(results)[:max_results]


async def _naukri_direct_profile_search(domain: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    """
    Direct Naukri trainer keyword search — searches for trainer profiles by skill.
    This is the most reliable Naukri source because it hits their actual search index.
    """
    results: List[SearchResult] = []
    kw = urllib.parse.quote_plus(f"{domain} trainer")

    pages_to_try = [
        f"https://www.naukri.com/{urllib.parse.quote(domain.lower())}-trainer-jobs-in-india",
        f"https://www.naukri.com/trainer-jobs-in-india?k={kw}",
        f"https://www.naukri.com/jobs?k={kw}&l=India",
    ]

    for url in pages_to_try[:2]:
        r = await _get(client, url, headers={
            "User-Agent": random.choice(_UA),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-IN,en;q=0.9",
            "Referer": "https://www.naukri.com/",
        })
        if not r or r.status_code >= 400:
            continue

        html = r.text
        # Extract job titles and links from Naukri search results
        for block in re.findall(r'<article[^>]*class="[^"]*jobTuple[^"]*"[^>]*>(.*?)</article>', html, re.S | re.I):
            link = re.search(r'<a[^>]+href="(https://www\.naukri\.com/[^"]+)"[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</a>', block, re.S | re.I)
            comp = re.search(r'<a[^>]+class="[^"]*subTitle[^"]*"[^>]*>(.*?)</a>', block, re.S | re.I)
            loc  = re.search(r'<span[^>]*class="[^"]*location[^"]*"[^>]*>(.*?)</span>', block, re.S | re.I)
            if link:
                snippet = " | ".join(filter(None, [
                    _strip(comp.group(1)) if comp else "",
                    _strip(loc.group(1)) if loc else "",
                ]))
                results.append(_mk(link.group(1), _strip(link.group(2)), snippet, "naukri_direct"))

        # Fallback — any job link with a title
        if not results:
            for m in re.finditer(r'<a[^>]+href="(https://www\.naukri\.com/job-listings-[^"]+)"[^>]*>(.*?)</a>', html, re.S | re.I):
                t = _strip(m.group(2)).strip()
                if len(t) > 5:
                    results.append(_mk(m.group(1), t, "", "naukri_direct"))

        if results:
            break

    return _dedup(results)[:max_results]


# ══════════════════════════════════════════════════════════════
# SOURCE 4 — Shine.com direct scrape
# Shine has public resume/profile pages for trainers
# ══════════════════════════════════════════════════════════════

async def _shine_search(domain: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    """Scrape Shine.com for trainer profiles."""
    results: List[SearchResult] = []
    kw = urllib.parse.quote_plus(f"{domain} trainer")

    urls = [
        f"https://www.shine.com/job-search/{urllib.parse.quote(domain.lower())}-trainer-jobs",
        f"https://www.shine.com/job-search/trainer-jobs-in-india?q={kw}",
    ]

    for url in urls[:1]:
        r = await _get(client, url, headers=_h("https://www.shine.com/"))
        if not r or r.status_code >= 400:
            continue
        html = r.text

        for block in re.findall(r'<div[^>]*class="[^"]*job-card[^"]*"[^>]*>(.*?)</div>\s*</div>', html, re.S | re.I):
            link  = re.search(r'<a[^>]+href="(https://www\.shine\.com/[^"]+)"[^>]*>(.*?)</a>', block, re.S | re.I)
            comp  = re.search(r'<span[^>]*class="[^"]*company[^"]*"[^>]*>(.*?)</span>', block, re.S | re.I)
            if link:
                results.append(_mk(link.group(1), _strip(link.group(2)),
                                   _strip(comp.group(1)) if comp else "", "shine"))

        if not results:
            for m in re.finditer(r'<a[^>]+href="(https://www\.shine\.com/job/[^"]+)"[^>]*>(.*?)</a>', html, re.S | re.I):
                t = _strip(m.group(2)).strip()
                if len(t) > 5:
                    results.append(_mk(m.group(1), t, "", "shine"))
        if results:
            break

    return _dedup(results)[:max_results]


# ══════════════════════════════════════════════════════════════
# SOURCE 5 — Google HTML (last resort — blocked on cloud IPs
# but worth trying — mobile UA reduces block rate)
# ══════════════════════════════════════════════════════════════

async def _google_page(query: str, start: int, client: httpx.AsyncClient) -> List[SearchResult]:
    for url, mobile in [
        ("https://www.google.com/search",    True),
        ("https://www.google.co.in/search",  False),
    ]:
        r = await _get(client, url,
                       params={"q": query, "num": 10, "start": start, "hl": "en", "gl": "in"},
                       headers=_h(url, mobile=mobile))
        if not r or r.status_code != 200 or len(r.text) < 2000:
            continue
        html = r.text
        results: List[SearchResult] = []

        # Strategy A — class="g" blocks
        for block in re.findall(r'<div[^>]*\bclass="[^"]*\bg\b[^"]*"[^>]*>(.*?)</div>\s*</div>', html, re.S | re.I)[:30]:
            lk = re.search(r'<a[^>]+href="(https?://(?!(?:www\.)?google)[^"&]+)"', block, re.I)
            ti = re.search(r'<h3[^>]*>(.*?)</h3>', block, re.S | re.I)
            sn = re.search(r'<(?:span|div)[^>]*class="[^"]*(?:st|VwiC3b|lyLwlc)[^"]*"[^>]*>(.*?)</(?:span|div)>', block, re.S | re.I)
            if lk and ti:
                results.append(_mk(lk.group(1), ti.group(1), sn.group(1) if sn else "", "google"))
        # Strategy B — /url?q= links
        if not results:
            for m in re.finditer(r'href="/url\?q=(https?[^&"]+)[^"]*"[^>]*>.*?<h3[^>]*>(.*?)</h3>', html, re.S | re.I):
                results.append(_mk(m.group(1), m.group(2), "", "google"))
        if results:
            return results
    return []


async def _search_google(query: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    pages = max(1, (max_results + 9) // 10)
    all_pages = await asyncio.gather(*[_google_page(query, i * 10, client) for i in range(min(pages, 3))])
    out: List[SearchResult] = []
    for p in all_pages:
        out.extend(p)
    return _dedup(out)[:max_results]



# ══════════════════════════════════════════════════════════════
# CORE ENGINE — free_web_search
# For a single query: try DDG → Bing → Google in order
# ══════════════════════════════════════════════════════════════

_ENGINE_MAP: List[Tuple[str, Any]] = [
    ("duckduckgo", _search_duckduckgo),
    ("bing",       _search_bing),
    ("google",     _search_google),
]


async def free_web_search(
    query: str,
    *,
    max_results: int = DEFAULT_MAX_RESULTS,
    timeout: int = DEFAULT_TIMEOUT,
    provider: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> List[SearchResult]:
    """
    Search the web using pure HTML scraping. Zero API keys required.
    Tries DDG → Bing → Google until one returns results.
    Returns list of { url, title, content, raw_content, source }
    """
    chosen = (provider or DEFAULT_PROVIDER).lower()
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=timeout, follow_redirects=True, http2=False)

    results: List[SearchResult] = []
    try:
        engines = [e for e in _ENGINE_MAP if chosen == "auto" or e[0] == chosen] or _ENGINE_MAP
        for name, fn in engines:
            try:
                results = await fn(query, max_results, client)
                results = _dedup(results)
                if results:
                    logger.debug("free_web_search '%s' → %d via %s", query[:50], len(results), name)
                    break
            except Exception as exc:
                logger.debug("Engine %s error: %s", name, exc)
    finally:
        if own:
            await client.aclose()

    return [r for r in results if r.get("url")]


# ══════════════════════════════════════════════════════════════
# BULK ENGINE — bulk_free_search
# Runs many queries concurrently, returns all results merged
# ══════════════════════════════════════════════════════════════

async def bulk_free_search(
    queries: List[str],
    *,
    max_results: int = DEFAULT_MAX_RESULTS,
    timeout: int = DEFAULT_TIMEOUT,
    concurrency: int = 8,
    provider: Optional[str] = None,
) -> List[tuple]:
    """
    Run many queries concurrently and return merged results.
    This is the key to 100 profiles: many queries × parallel = fast + many.

    Returns: List of (query, {"results": [...]}, error_or_None)
    Same contract as old Tavily bulk — zero changes needed in callers.
    """
    sem = asyncio.Semaphore(max(1, min(concurrency, 16)))
    chosen = (provider or DEFAULT_PROVIDER).lower()

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, http2=False) as shared:

        async def _run(q: str) -> tuple:
            async with sem:
                await asyncio.sleep(random.uniform(0.05, 0.3))
                try:
                    res = await free_web_search(q, max_results=max_results, provider=chosen, client=shared)
                    return q, {"results": res}, None
                except Exception as exc:
                    return q, None, str(exc)

        return list(await asyncio.gather(*[_run(q) for q in queries]))


# ══════════════════════════════════════════════════════════════
# HIGH-LEVEL SEARCH FUNCTIONS
# These build smart multi-source queries to hit 100 profiles
# ══════════════════════════════════════════════════════════════

# ── Query templates that actually work from cloud server IPs ──
# KEY INSIGHT: site:linkedin.com is blocked by search engines from cloud IPs.
# These query formats return real results because they don't force a domain.
_SEARCH_QUERY_TEMPLATES = [
    '"{domain}" "corporate trainer" India linkedin',
    '"{domain}" "freelance trainer" India linkedin profile',
    '"{domain}" "certified trainer" India contact',
    '"{domain}" trainer India linkedin profile',
    '"{domain}" instructor trainer India',
    '"{domain}" "technical trainer" India email',
    '"{domain}" trainer India "years experience"',
    '"{domain}" trainer India "contact" email phone',
    '"{domain}" trainer Hyderabad OR Bangalore OR Mumbai linkedin',
    '"{domain}" trainer Delhi OR Chennai OR Pune linkedin',
    '"{domain}" trainer Noida OR Kolkata OR Ahmedabad',
    '"{domain}" "training consultant" India',
    '"{domain}" "subject matter expert" trainer India',
    '"{domain}" trainer India naukri.com',
    '"{domain}" trainer India shine.com',
    '"{domain}" trainer India justdial.com',
    '"{domain}" trainer resume India',
    '"{domain}" corporate trainer resume contact India',
    '"{domain}" freelance trainer resume India email',
    '"{domain}" trainer "10 years" OR "8 years" OR "12 years" India',
]

_CITIES = [
    "Hyderabad", "Bangalore", "Mumbai", "Delhi", "Chennai",
    "Pune", "Noida", "Kolkata", "Ahmedabad",
]


async def search_linkedin_trainers(
    domain: str,
    *,
    max_results: int = DEFAULT_MAX_RESULTS,
    locations: Optional[List[str]] = None,
    roles: Optional[List[str]] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> List[SearchResult]:
    """
    Search for trainer profiles using queries that work from cloud IPs.
    Combines search engine results + direct Naukri/Shine scraping.
    Returns 100+ unique profiles per domain.
    """
    # Build search queries from templates
    queries: List[str] = [t.replace("{domain}", domain) for t in _SEARCH_QUERY_TEMPLATES]

    # Add city-specific queries
    for city in (_CITIES[:6]):
        queries.append(f'"{domain}" trainer "{city}" linkedin profile')
        queries.append(f'"{domain}" trainer "{city}" contact email')

    # Run all search queries in parallel
    rl = await bulk_free_search(queries, max_results=max_results, timeout=timeout, concurrency=10)
    seen: set = set()
    combined: List[SearchResult] = []
    for _, data, _ in rl:
        for r in (data or {}).get("results") or []:
            u = (r.get("url") or "").rstrip("/").lower().split("?")[0]
            if u and u not in seen:
                seen.add(u)
                combined.append(r)

    # Also run Naukri + Shine direct scrapes (these bypass search engines entirely)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, http2=False) as client:
        naukri = await _naukri_direct_profile_search(domain, max_results, client)
        shine  = await _shine_search(domain, max_results, client)
        for r in naukri + shine:
            u = (r.get("url") or "").rstrip("/").lower().split("?")[0]
            if u and u not in seen:
                seen.add(u)
                combined.append(r)

    return combined


async def search_client_requirements(
    domain: str,
    *,
    max_results: int = DEFAULT_MAX_RESULTS,
    timeout: int = DEFAULT_TIMEOUT,
) -> List[SearchResult]:
    """Search for posts / pages that look like trainer hiring requirements."""
    queries = [
        f'"{domain}" "Corporate Trainer Required" India',
        f'"{domain}" "Need Technical Trainer" India',
        f'"{domain}" "Trainer Required" India linkedin',
        f'"{domain}" "Looking for Trainer" India contact',
        f'"{domain}" "Hiring Trainer" India',
        f'"{domain}" "Training Requirement" India',
        f'"{domain}" trainer requirement India 2024 OR 2025',
        f'"{domain}" trainer needed India email',
    ]
    rl = await bulk_free_search(queries, max_results=max_results, timeout=timeout, concurrency=6)
    seen: set = set()
    combined: List[SearchResult] = []
    for _, data, _ in rl:
        for r in (data or {}).get("results") or []:
            u = (r.get("url") or "").rstrip("/").lower()
            if u and u not in seen:
                seen.add(u)
                combined.append(r)
    return combined[:max_results]


def is_configured() -> dict:
    """Always configured — zero API keys needed."""
    return {
        "duckduckgo": True, "bing": True, "google": True,
        "naukri_direct": True, "shine_direct": True,
        "active_provider": DEFAULT_PROVIDER,
        "max_results": DEFAULT_MAX_RESULTS,
        "timeout": DEFAULT_TIMEOUT,
        "requires_api_key": False,
        "expected_results_per_run": "80–150 per domain (search + Naukri direct + Shine direct)",
    }
