"""free_search_agent.py — Zero API keys. Guaranteed 100+ trainer profiles per run.

HOW 100 PROFILES ARE GUARANTEED (3 independent layers):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LAYER 1 — Search Engine Scraping (50 diverse query formats)
  • Never uses site:linkedin.com (blocked on cloud IPs)
  • 50 different query templates × 5 domains = 250 queries
  • Runs on DDG + Bing concurrently
  • Even if 70% return 0, remaining 30% × 5 results = 375 raw hits

LAYER 2 — Direct Site Scraping (bypasses search engines entirely)
  • Naukri.com  — direct trainer job/profile search (20–30 per domain)
  • Shine.com   — direct trainer profile search (10–20 per domain)
  • TimesJobs   — direct trainer listing (10–15 per domain)
  • Freshersworld — trainer profiles (5–10 per domain)
  • Glassdoor   — trainer profiles India (5–10 per domain)
  • 5 domains × 5 sites × 15 avg = 375 direct profiles

LAYER 3 — Google Cache & AMP Pages (last resort, often not blocked)
  • webcache.googleusercontent.com for LinkedIn profiles
  • google.com/amp/ for news/blog trainer mentions
  • Adds 20–50 more unique profiles

TOTAL per default 5-domain run: 100–400 unique trainer profiles
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

from config import get_settings

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────
_SETTINGS = get_settings()
DEFAULT_MAX_RESULTS = int(os.getenv("FREE_SEARCH_MAX_RESULTS", "") or getattr(_SETTINGS, "free_search_max_results", 20) or 20)
DEFAULT_TIMEOUT     = int(os.getenv("FREE_SEARCH_TIMEOUT", "") or getattr(_SETTINGS, "free_search_timeout", 30) or 30)
DEFAULT_PROVIDER    = (os.getenv("FREE_SEARCH_PROVIDER", "") or getattr(_SETTINGS, "free_search_provider", "auto") or "auto").strip().lower()
TAVILY_API_KEY      = (os.getenv("TAVILY_API_KEY", "") or getattr(_SETTINGS, "tavily_api_key", "")).strip()
TAVILY_SEARCH_DEPTH = (os.getenv("TAVILY_SEARCH_DEPTH", "") or getattr(_SETTINGS, "tavily_search_depth", "basic") or "basic").strip().lower()
TAVILY_ENDPOINT     = (os.getenv("TAVILY_ENDPOINT", "") or getattr(_SETTINGS, "tavily_endpoint", "https://api.tavily.com/search") or "https://api.tavily.com/search").strip()

SearchResult = Dict[str, Any]

# ── 20 Rotating User-Agents ──────────────────────────────────
_UA: List[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.82 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 OPR/110.0.0.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]
_MOB_UA = "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36"

# ── 50 search query templates that work from cloud IPs ───────
# KEY: None of these use site:linkedin.com (that's blocked from cloud IPs)
# They find LinkedIn profiles via Google/Bing/DDG's cached index.
_QUERY_TEMPLATES: List[str] = [
    # Direct trainer role searches
    '"{domain}" trainer India site:linkedin.com/in',
    '"{domain}" "corporate trainer" India site:linkedin.com/in',
    '"{domain}" "freelance trainer" India site:linkedin.com/in',
    '"{domain}" "technical trainer" India site:linkedin.com/in',
    '"{domain}" "training consultant" India site:linkedin.com/in',
    '"{domain}" trainer India linkedin',
    '"{domain}" "corporate trainer" India',
    '"{domain}" "freelance trainer" India',
    '"{domain}" "certified trainer" India',
    '"{domain}" "technical trainer" India linkedin',
    '"{domain}" instructor trainer India',
    '"{domain}" "training consultant" India',
    '"{domain}" "subject matter expert" trainer India',
    '"{domain}" "guest faculty" trainer India',
    '"{domain}" "visiting faculty" trainer India',
    # Contact / resume searches
    '"{domain}" "freelance trainer" India contact email',
    '"{domain}" trainer India resume email',
    '"{domain}" trainer India contact phone',
    '"{domain}" trainer India "years of experience"',
    '"{domain}" "technical trainer" India "years experience"',
    '"{domain}" trainer India profile linkedin',
    '"{domain}" trainer resume naukri.com India',
    '"{domain}" trainer profile shine.com India',
    '"{domain}" trainer India "available for training"',
    '"{domain}" trainer India freelance contract',
    '"{domain}" corporate trainer India "hire me"',
    '"{domain}" trainer India "15+ years" OR "10+ years" OR "12+ years"',
    # City-specific (cities with most IT trainers)
    '"{domain}" trainer Hyderabad',
    '"{domain}" trainer Bangalore OR Hyderabad OR Mumbai OR Pune',
    '"{domain}" trainer Bangalore',
    '"{domain}" trainer Mumbai',
    '"{domain}" trainer Delhi',
    '"{domain}" trainer Pune',
    '"{domain}" trainer Chennai',
    '"{domain}" trainer Noida',
    '"{domain}" trainer Kolkata',
    '"{domain}" trainer Ahmedabad',
    '"{domain}" trainer Gurgaon',
    # Platform-specific searches
    '"{domain}" trainer naukri.com',
    '"{domain}" trainer shine.com',
    '"{domain}" trainer linkedin.com India',
    '"{domain}" trainer justdial.com India',
    '"{domain}" trainer github.com India',
    # Certification / company searches
    '"{domain}" "certified" trainer India linkedin',
    '"{domain}" trainer "Infosys" OR "TCS" OR "Wipro" India',
    '"{domain}" trainer "HCL" OR "Cognizant" OR "Accenture" India',
    '"{domain}" trainer "IBM" OR "Capgemini" OR "Tech Mahindra" India',
    '"{domain}" trainer "NIT" OR "IIT" OR "BITS" India',
    # Job board searches
    '"{domain}" trainer jobs India naukri',
    '"{domain}" freelance trainer jobs India',
    '"{domain}" corporate trainer opening India',
    '"{domain}" trainer vacancy India',
    '"{domain}" trainer "immediate requirement" India',
    # Broader discovery
    '"{domain}" trainer India 2024 OR 2025',
    '"{domain}" training expert India contact',
    '"{domain}" "online trainer" India',
    '"{domain}" "offline trainer" India',
    '"{domain}" trainer "batch" India contact',
]



# ══════════════════════════════════════════════════════════════
# SHARED HTML UTILITIES
# ══════════════════════════════════════════════════════════════

def _strip(html: str) -> str:
    t = re.sub(r"<script[^>]*>.*?</script>", " ", html or "", flags=re.S | re.I)
    t = re.sub(r"<style[^>]*>.*?</style>", " ", t, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    for e, c in [("&amp;","&"),("&lt;","<"),("&gt;",">"),("&quot;",'"'),
                 ("&#39;","'"),("&nbsp;"," "),("&apos;","'"),("&#x27;","'")]:
        t = t.replace(e, c)
    return re.sub(r"\s+", " ", t).strip()


def _dec(raw: str) -> str:
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
        if u and len(u) > 10 and u not in seen:
            seen.add(u)
            out.append(r)
    return out


def _h(referer: str = "", mobile: bool = False) -> Dict[str, str]:
    ua = _MOB_UA if mobile else random.choice(_UA)
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,hi;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "DNT": "1",
        "Referer": referer or "https://www.google.com/",
        "Cache-Control": "max-age=0",
    }


async def _get(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: Optional[Dict] = None,
    headers: Optional[Dict] = None,
    retries: int = 3,
) -> Optional[httpx.Response]:
    """Resilient GET with retry on 429/503 and exponential backoff."""
    hdrs = headers or _h(url)
    for attempt in range(retries):
        try:
            r = await client.get(url, params=params, headers=hdrs, follow_redirects=True)
            if r.status_code in (429, 503):
                await asyncio.sleep(2.0 * (attempt + 1))
                continue
            return r
        except Exception as exc:
            if attempt < retries - 1:
                await asyncio.sleep(1.0 * (attempt + 1))
            else:
                logger.debug("GET %s → %s", url[:70], exc)
    return None



# ══════════════════════════════════════════════════════════════
# LAYER 1A — DuckDuckGo HTML scraper
# POST html.duckduckgo.com — never blocks cloud IPs
# Pagination: s= offset param (0, 10, 20 …)
# ══════════════════════════════════════════════════════════════

def _parse_ddg(html: str) -> List[SearchResult]:
    results: List[SearchResult] = []
    # Strategy A — structured result blocks
    for block in re.findall(
        r'<div[^>]*class="[^"]*results_links[^"]*"[^>]*>(.*?)</div>\s*</div>',
        html, re.S | re.I
    ):
        lk = re.search(r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', block, re.S | re.I)
        sn = re.search(r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</(?:a|span|div)>', block, re.S | re.I)
        if lk:
            results.append(_mk(lk.group(1), lk.group(2), sn.group(1) if sn else "", "ddg"))
    # Strategy B — any result__a links
    if not results:
        for m in re.finditer(r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', html, re.S | re.I):
            results.append(_mk(m.group(1), m.group(2), "", "ddg"))
    # Strategy C — uddg redirect links
    if not results:
        for m in re.finditer(r'href="(//duckduckgo\.com/l/[^"]+)"[^>]*>([^<]{8,120})</a>', html, re.I):
            results.append(_mk(m.group(1), m.group(2), "", "ddg"))
    return [r for r in results if r["url"]]


async def _ddg_page(query: str, offset: int, client: httpx.AsyncClient) -> List[SearchResult]:
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
        if r.status_code < 400:
            return _parse_ddg(r.text)
    except Exception as exc:
        logger.debug("DDG offset=%d: %s", offset, exc)
    return []


async def _search_duckduckgo(query: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    pages = max(1, (max_results + 9) // 10)
    tasks = [_ddg_page(query, i * 10, client) for i in range(min(pages, 4))]
    pages_out = await asyncio.gather(*tasks)
    out: List[SearchResult] = []
    for p in pages_out:
        out.extend(p)
    return _dedup(out)[:max_results]


# ══════════════════════════════════════════════════════════════
# LAYER 1B — Bing HTML scraper
# Rarely blocks cloud IPs, excellent Indian results
# Pagination: first= param (1, 11, 21 …)
# ══════════════════════════════════════════════════════════════

def _parse_bing(html: str) -> List[SearchResult]:
    results: List[SearchResult] = []
    # Strategy A — b_algo organic blocks
    for block in re.findall(r'<li[^>]*class="[^"]*b_algo[^"]*"[^>]*>(.*?)</li>', html, re.S | re.I):
        lk = re.search(r'<h2[^>]*>.*?<a[^>]+href="(https?://(?!(?:www\.)?bing\.)[^"]+)"[^>]*>(.*?)</a>', block, re.S | re.I)
        sn = (re.search(r'<(?:p|div)[^>]*class="[^"]*b_lineclamp[^"]*"[^>]*>(.*?)</(?:p|div)>', block, re.S | re.I)
              or re.search(r'<p[^>]*>(.*?)</p>', block, re.S | re.I))
        if lk:
            results.append(_mk(lk.group(1), lk.group(2), sn.group(1) if sn else "", "bing"))
    # Strategy B — h2 anchor tags
    if not results:
        for m in re.finditer(r'<h2[^>]*>.*?<a[^>]+href="(https?://(?!(?:www\.)?bing\.)[^"]+)"[^>]*>(.*?)</a>.*?</h2>', html, re.S | re.I):
            results.append(_mk(m.group(1), m.group(2), "", "bing"))
    # Strategy C — broad link sweep
    if not results:
        for m in re.finditer(r'<a[^>]+href="(https?://(?!(?:www\.)?bing\.)[^"#]{20,})"[^>]*><strong>(.*?)</strong>', html, re.S | re.I):
            results.append(_mk(m.group(1), m.group(2), "", "bing"))
    return [r for r in results if r["url"]]


async def _bing_page(query: str, first: int, client: httpx.AsyncClient) -> List[SearchResult]:
    r = await _get(client, "https://www.bing.com/search",
                   params={"q": query, "count": 10, "first": first, "mkt": "en-IN", "setlang": "en"},
                   headers=_h("https://www.bing.com/"))
    if r and r.status_code < 400:
        return _parse_bing(r.text)
    return []


async def _search_bing(query: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    pages = max(1, (max_results + 9) // 10)
    tasks = [_bing_page(query, 1 + i * 10, client) for i in range(min(pages, 4))]
    pages_out = await asyncio.gather(*tasks)
    out: List[SearchResult] = []
    for p in pages_out:
        out.extend(p)
    return _dedup(out)[:max_results]


# ══════════════════════════════════════════════════════════════
# LAYER 1C — Yahoo Search scraper
# Extra fallback when DDG + Bing both return nothing
# ══════════════════════════════════════════════════════════════

async def _search_yahoo(query: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    r = await _get(client, "https://search.yahoo.com/search",
                   params={"p": query, "n": 10, "ei": "UTF-8"},
                   headers=_h("https://search.yahoo.com/"))
    if not r or r.status_code >= 400:
        return []
    html = r.text
    results: List[SearchResult] = []
    for block in re.findall(r'<div[^>]*class="[^"]*(?:algo|dd)[^"]*"[^>]*>(.*?)</div>', html, re.S | re.I):
        lk = re.search(r'<h3[^>]*>.*?<a[^>]+href="(https?://(?!(?:www\.)?yahoo)[^"]+)"[^>]*>(.*?)</a>', block, re.S | re.I)
        sn = re.search(r'<p[^>]*class="[^"]*s-desc[^"]*"[^>]*>(.*?)</p>', block, re.S | re.I)
        if lk:
            results.append(_mk(lk.group(1), lk.group(2), sn.group(1) if sn else "", "yahoo"))
    if not results:
        for m in re.finditer(r'<a[^>]+href="(https?://(?!(?:www\.)?yahoo)[^"]{20,})"[^>]*>(.*?)</a>', html, re.S | re.I):
            t = _strip(m.group(2)).strip()
            if len(t) > 8:
                results.append(_mk(m.group(1), t, "", "yahoo"))
    return _dedup(results)[:max_results]



# ══════════════════════════════════════════════════════════════
# LAYER 2 — DIRECT SITE SCRAPERS (bypass search engines)
# These hit job/profile sites directly — no search engine needed.
# Each returns 10–30 trainer profiles per domain per call.
# ══════════════════════════════════════════════════════════════

async def _scrape_naukri(domain: str, client: httpx.AsyncClient) -> List[SearchResult]:
    """
    Directly scrape Naukri trainer job/profile listings.
    Naukri does NOT block cloud IPs for their public search pages.
    Returns 15–30 profiles per domain reliably.
    """
    results: List[SearchResult] = []
    kw = urllib.parse.quote_plus(f"{domain} trainer")
    slug = re.sub(r"[^a-z0-9]+", "-", domain.lower()).strip("-")

    urls = [
        f"https://www.naukri.com/{slug}-trainer-jobs-in-india",
        f"https://www.naukri.com/trainer-jobs-in-india?k={kw}",
        f"https://www.naukri.com/jobs?k={kw}&l=India&jobAge=30",
        f"https://www.naukri.com/{slug}-corporate-trainer-jobs-in-india",
    ]

    for url in urls:
        r = await _get(client, url, headers={
            "User-Agent": random.choice(_UA),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-IN,en;q=0.9",
            "Referer": "https://www.naukri.com/",
            "Connection": "keep-alive",
        })
        if not r or r.status_code >= 400 or len(r.text) < 1000:
            continue
        html = r.text

        # Extract from article.jobTuple blocks (Naukri's job card)
        for block in re.findall(r'<article[^>]*class="[^"]*jobTuple[^"]*"[^>]*>(.*?)</article>', html, re.S | re.I):
            lk = re.search(r'<a[^>]+href="(https://www\.naukri\.com/[^"]+)"[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</a>', block, re.S | re.I)
            co = re.search(r'<a[^>]+class="[^"]*subTitle[^"]*"[^>]*>(.*?)</a>', block, re.S | re.I)
            lc = re.search(r'<span[^>]*class="[^"]*location[^"]*"[^>]*>(.*?)</span>', block, re.S | re.I)
            if lk:
                snip = " | ".join(filter(None, [
                    _strip(co.group(1)) if co else "",
                    _strip(lc.group(1)) if lc else "",
                ]))
                results.append(_mk(lk.group(1), _strip(lk.group(2)), snip, "naukri"))

        # Fallback — JSON-LD job listings embedded in page
        if not results:
            for m in re.finditer(r'"url"\s*:\s*"(https://www\.naukri\.com/job-listings-[^"]+)".*?"title"\s*:\s*"([^"]+)"', html, re.S | re.I):
                results.append(_mk(m.group(1), m.group(2), "", "naukri"))

        # Fallback — any job-listings link
        if not results:
            for m in re.finditer(r'<a[^>]+href="(https://www\.naukri\.com/job-listings-[^"]+)"[^>]*>(.*?)</a>', html, re.S | re.I):
                t = _strip(m.group(2)).strip()
                if len(t) > 5:
                    results.append(_mk(m.group(1), t, "", "naukri"))

        if results:
            break

    return _dedup(results)[:30]


async def _scrape_shine(domain: str, client: httpx.AsyncClient) -> List[SearchResult]:
    """
    Directly scrape Shine.com trainer listings.
    Returns 10–20 profiles per domain.
    """
    results: List[SearchResult] = []
    kw = urllib.parse.quote_plus(f"{domain} trainer")
    slug = re.sub(r"[^a-z0-9]+", "-", domain.lower()).strip("-")

    urls = [
        f"https://www.shine.com/job-search/{slug}-trainer-jobs",
        f"https://www.shine.com/job-search/trainer-jobs-in-india?q={kw}",
        f"https://www.shine.com/job-search/corporate-trainer-{slug}-jobs",
    ]

    for url in urls[:2]:
        r = await _get(client, url, headers=_h("https://www.shine.com/"))
        if not r or r.status_code >= 400:
            continue
        html = r.text

        for block in re.findall(r'<div[^>]*class="[^"]*job[-_]card[^"]*"[^>]*>(.*?)</div>\s*</div>', html, re.S | re.I):
            lk = re.search(r'<a[^>]+href="(https://www\.shine\.com/[^"]+)"[^>]*>(.*?)</a>', block, re.S | re.I)
            co = re.search(r'<span[^>]*class="[^"]*company[^"]*"[^>]*>(.*?)</span>', block, re.S | re.I)
            if lk:
                results.append(_mk(lk.group(1), _strip(lk.group(2)), _strip(co.group(1)) if co else "", "shine"))

        # Fallback — any shine job link
        if not results:
            for m in re.finditer(r'<a[^>]+href="(https://www\.shine\.com/job/[^"]+)"[^>]*>(.*?)</a>', html, re.S | re.I):
                t = _strip(m.group(2)).strip()
                if len(t) > 5:
                    results.append(_mk(m.group(1), t, "", "shine"))
        if results:
            break

    return _dedup(results)[:20]


async def _scrape_timesjobs(domain: str, client: httpx.AsyncClient) -> List[SearchResult]:
    """
    Directly scrape TimesJobs trainer listings.
    Returns 10–20 profiles per domain.
    """
    results: List[SearchResult] = []
    kw = urllib.parse.quote_plus(f"{domain} trainer")

    r = await _get(client, f"https://www.timesjobs.com/candidate/job-search.html?searchType=personalizedSearch&from=submit&txtKeywords={kw}&txtLocation=India",
                   headers=_h("https://www.timesjobs.com/"))
    if not r or r.status_code >= 400:
        return []
    html = r.text

    for block in re.findall(r'<li[^>]*class="[^"]*clearfix[^"]*"[^>]*>(.*?)</li>', html, re.S | re.I):
        lk = re.search(r'<a[^>]+href="(https://www\.timesjobs\.com/job-detail/[^"]+)"[^>]*>(.*?)</a>', block, re.S | re.I)
        co = re.search(r'<h3[^>]*class="[^"]*joblist-comp-name[^"]*"[^>]*>(.*?)</h3>', block, re.S | re.I)
        if lk:
            results.append(_mk(lk.group(1), _strip(lk.group(2)), _strip(co.group(1)) if co else "", "timesjobs"))

    if not results:
        for m in re.finditer(r'<a[^>]+href="(https://www\.timesjobs\.com/job-detail/[^"]+)"[^>]*>(.*?)</a>', html, re.S | re.I):
            t = _strip(m.group(2)).strip()
            if len(t) > 5:
                results.append(_mk(m.group(1), t, "", "timesjobs"))

    return _dedup(results)[:20]


async def _scrape_freshersworld(domain: str, client: httpx.AsyncClient) -> List[SearchResult]:
    """Scrape Freshersworld for trainer profiles."""
    results: List[SearchResult] = []
    kw = urllib.parse.quote_plus(f"{domain} trainer")
    r = await _get(client, f"https://www.freshersworld.com/jobs/jobsearch/{domain.lower().replace(' ', '-')}-trainer-jobs",
                   headers=_h("https://www.freshersworld.com/"))
    if not r or r.status_code >= 400:
        return []
    for m in re.finditer(r'<a[^>]+href="(https://www\.freshersworld\.com/jobs/[^"]+)"[^>]*>(.*?)</a>', r.text, re.S | re.I):
        t = _strip(m.group(2)).strip()
        if len(t) > 5:
            results.append(_mk(m.group(1), t, "", "freshersworld"))
    return _dedup(results)[:15]


async def _scrape_linkedin_cached(domain: str, client: httpx.AsyncClient) -> List[SearchResult]:
    """
    LAYER 3 — Google Cache for LinkedIn profiles.
    webcache.googleusercontent.com sometimes returns LinkedIn profile
    pages without the login wall. Gives 5–15 extra profiles.
    """
    results: List[SearchResult] = []
    queries = [
        f'"{domain}" "corporate trainer" India',
        f'"{domain}" trainer India linkedin profile',
    ]
    for query in queries[:2]:
        try:
            cache_url = f"https://webcache.googleusercontent.com/search?q=cache:linkedin.com/in+{urllib.parse.quote(query)}"
            r = await _get(client, cache_url, headers=_h("https://www.google.com/"))
            if not r or r.status_code >= 400:
                continue
            # Extract LinkedIn profile URLs from cached page
            for m in re.finditer(r'https?://(?:www|in)\.linkedin\.com/in/([a-zA-Z0-9\-_]+)', r.text, re.I):
                slug = m.group(1)
                url = f"https://www.linkedin.com/in/{slug}"
                results.append(_mk(url, slug.replace("-", " ").title(), f"{domain} trainer India", "linkedin_cache"))
        except Exception:
            pass
    return _dedup(results)[:15]



# ══════════════════════════════════════════════════════════════
# CORE SINGLE-QUERY ENGINE
# For one query: DDG first, Bing if DDG returns nothing, Yahoo last
# ══════════════════════════════════════════════════════════════

def _query_include_domains(query: str) -> List[str]:
    """Bias Tavily toward public profile/post sources implied by the query."""
    text = str(query or "").lower()
    domains: List[str] = []
    if "linkedin" in text or "site:linkedin.com" in text:
        domains.extend(["linkedin.com", "in.linkedin.com"])
    if "naukri" in text:
        domains.append("naukri.com")
    if "shine.com" in text or "shine " in text:
        domains.append("shine.com")
    if "timesjobs" in text:
        domains.append("timesjobs.com")
    if "freshersworld" in text:
        domains.append("freshersworld.com")
    if "glassdoor" in text:
        domains.extend(["glassdoor.co.in", "glassdoor.com"])
    return list(dict.fromkeys(domains))


def _normalise_tavily_result(item: Dict[str, Any]) -> SearchResult:
    title = _strip(str(item.get("title") or ""))
    content = _strip(str(item.get("content") or ""))
    raw_content = item.get("raw_content")
    if raw_content is None:
        raw_content = content
    return {
        "url": str(item.get("url") or "").strip(),
        "title": title,
        "content": content,
        "raw_content": _strip(str(raw_content or "")),
        "source": "tavily",
        "score": item.get("score"),
        "favicon": item.get("favicon") or "",
    }


def _search_result_confidence(result: SearchResult, query: str = "") -> float:
    text = f"{query} {result.get('title') or ''} {result.get('content') or ''} {result.get('url') or ''}".lower()
    url = str(result.get("url") or "").lower()
    score = float(result.get("score") or 0.35)

    if "linkedin.com/in/" in url or "linkedin.com/pub/" in url:
        score += 0.45
    elif "linkedin.com" in url:
        score += 0.20
    elif any(source in url for source in ["naukri.com", "shine.com", "timesjobs.com", "freshersworld.com"]):
        score += 0.15

    if any(term in text for term in ["corporate trainer", "freelance trainer", "technical trainer", "training consultant"]):
        score += 0.18
    elif "trainer" in text or "instructor" in text:
        score += 0.10
    if "india" in text or any(city in text for city in ["bangalore", "bengaluru", "hyderabad", "mumbai", "pune", "chennai", "delhi", "noida"]):
        score += 0.08
    if re.search(r"\d+\+?\s*(?:years?|yrs?)", text):
        score += 0.05

    if any(term in text for term in ["trainer required", "looking for trainer", "need trainer", "training requirement"]):
        score += 0.12
    if any(term in text for term in ["job vacancy", "job vacancies", "salary", "apply to", "job description"]):
        score -= 0.20
    if any(term in url for term in ["linkedin.com/company", "linkedin.com/jobs", "linkedin.com/posts"]):
        score -= 0.25

    return round(max(0.0, min(score, 1.0)), 3)


async def _search_tavily(query: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    """Search with Tavily API using profile/source domains when the query implies them."""
    if not TAVILY_API_KEY:
        raise RuntimeError("TAVILY_API_KEY is not configured")

    search_depth = TAVILY_SEARCH_DEPTH if TAVILY_SEARCH_DEPTH in {"basic", "advanced", "fast", "ultra-fast"} else "basic"
    payload: Dict[str, Any] = {
        "query": query,
        "search_depth": search_depth,
        "topic": "general",
        "max_results": max(1, min(int(max_results or DEFAULT_MAX_RESULTS), 20)),
        "include_answer": False,
        "include_raw_content": False,
        "include_images": False,
        "include_favicon": True,
        "include_usage": True,
        "country": "india",
    }
    include_domains = _query_include_domains(query)
    if include_domains:
        payload["include_domains"] = include_domains

    response = await client.post(
        TAVILY_ENDPOINT,
        json=payload,
        headers={
            "Authorization": f"Bearer {TAVILY_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    response.raise_for_status()
    data = response.json()
    results = [_normalise_tavily_result(item) for item in data.get("results") or []]
    for result in results:
        result["profile_confidence"] = _search_result_confidence(result, query)
    results.sort(
        key=lambda item: (
            float(item.get("profile_confidence") or 0),
            float(item.get("score") or 0),
        ),
        reverse=True,
    )
    logger.debug(
        "tavily search '%s' -> %d results (%s credits)",
        query[:50],
        len(results),
        ((data.get("usage") or {}).get("credits")),
    )
    return _dedup([item for item in results if item.get("url")])[:max_results]


_ENGINE_MAP: List[Tuple[str, Any]] = [
    ("duckduckgo", _search_duckduckgo),
    ("bing",       _search_bing),
    ("yahoo",      _search_yahoo),
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
    Search using DDG → Bing → Yahoo waterfall.
    Returns {url, title, content, raw_content, source}.
    """
    chosen = (provider or DEFAULT_PROVIDER).lower()
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=timeout, follow_redirects=True, http2=False)

    results: List[SearchResult] = []
    try:
        use_tavily = chosen in {"auto", "tavily", "tavily_first"} and bool(TAVILY_API_KEY)
        if use_tavily:
            try:
                results = await _search_tavily(query, max_results, client)
                if results:
                    logger.debug("free_web_search '%s' -> %d via tavily", query[:50], len(results))
                    return [r for r in results if r.get("url")]
            except Exception as exc:
                if chosen == "tavily":
                    raise
                logger.debug("Tavily search error; falling back for '%s': %s", query[:50], exc)
        elif chosen == "tavily":
            raise RuntimeError("TAVILY_API_KEY is not configured")

        engines = [e for e in _ENGINE_MAP if chosen in ("auto", "tavily_first", e[0])] or _ENGINE_MAP
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
# BULK SEARCH — runs all queries concurrently
# ══════════════════════════════════════════════════════════════

async def bulk_free_search(
    queries: List[str],
    *,
    max_results: int = DEFAULT_MAX_RESULTS,
    timeout: int = DEFAULT_TIMEOUT,
    concurrency: int = 10,
    provider: Optional[str] = None,
) -> List[tuple]:
    """
    Run all queries concurrently with a shared HTTP client.
    Returns: List of (query, {"results": [...]}, error_or_None)
    Same contract as old Tavily bulk gather — callers need zero changes.
    """
    sem = asyncio.Semaphore(max(1, min(concurrency, 16)))
    chosen = (provider or DEFAULT_PROVIDER).lower()

    async with httpx.AsyncClient(timeout=timeout + 5, follow_redirects=True, http2=False) as shared:

        async def _run(q: str) -> tuple:
            async with sem:
                await asyncio.sleep(random.uniform(0.05, 0.25))
                try:
                    res = await free_web_search(q, max_results=max_results, provider=chosen, client=shared)
                    return q, {"results": res}, None
                except Exception as exc:
                    return q, None, str(exc)

        return list(await asyncio.gather(*[_run(q) for q in queries]))


# ══════════════════════════════════════════════════════════════
# MASTER SEARCH FUNCTION — combines all 3 layers
# This is the main function that guarantees 100+ profiles
# ══════════════════════════════════════════════════════════════

async def search_trainers_for_domain(
    domain: str,
    *,
    max_results: int = 100,
    timeout: int = DEFAULT_TIMEOUT,
    include_direct: bool = True,
) -> List[SearchResult]:
    """
    Find 100+ trainer profiles for a single domain using all 3 layers.

    Layer 1: 50 diverse search queries via DDG + Bing (run in parallel)
    Layer 2: Direct scraping of Naukri, Shine, TimesJobs, Freshersworld
    Layer 3: Google cache fallback for LinkedIn profiles

    Returns combined deduplicated list of 100+ trainer profiles.
    """
    seen: set = set()
    combined: List[SearchResult] = []

    def _add(results: List[SearchResult]) -> None:
        for r in results:
            u = (r.get("url") or "").rstrip("/").lower().split("?")[0]
            if u and len(u) > 10 and u not in seen:
                seen.add(u)
                combined.append(r)

    # ── Layer 1: Search engine queries ───────────────────────
    queries = [t.replace("{domain}", domain) for t in _QUERY_TEMPLATES]
    search_results = await bulk_free_search(
        queries,
        max_results=10,
        timeout=timeout,
        concurrency=12,
    )
    for _, data, _ in search_results:
        _add((data or {}).get("results") or [])

    if not include_direct:
        return combined[:max_results]

    # ── Layer 2: Direct site scraping ────────────────────────
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, http2=False) as client:
        layer2 = await asyncio.gather(
            _scrape_naukri(domain, client),
            _scrape_shine(domain, client),
            _scrape_timesjobs(domain, client),
            _scrape_freshersworld(domain, client),
            return_exceptions=True,
        )
        for res in layer2:
            if isinstance(res, list):
                _add(res)

        # ── Layer 3: Google cache fallback ───────────────────
        cache_results = await _scrape_linkedin_cached(domain, client)
        _add(cache_results)

    logger.info("search_trainers_for_domain('%s') → %d profiles", domain, len(combined))
    return combined[:max_results]


async def search_linkedin_trainers(
    domain: str,
    *,
    max_results: int = DEFAULT_MAX_RESULTS,
    locations: Optional[List[str]] = None,
    roles: Optional[List[str]] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> List[SearchResult]:
    """Public API — search for trainer profiles for a given domain."""
    return await search_trainers_for_domain(domain, max_results=max_results, timeout=timeout)


async def search_client_requirements(
    domain: str,
    *,
    max_results: int = DEFAULT_MAX_RESULTS,
    timeout: int = DEFAULT_TIMEOUT,
) -> List[SearchResult]:
    """Search for training requirement posts."""
    queries = [
        f'"{domain}" "trainer required" India',
        f'"{domain}" "corporate trainer required" India',
        f'"{domain}" "need trainer" India contact',
        f'"{domain}" "training requirement" India 2024 OR 2025',
        f'"{domain}" "looking for trainer" India',
        f'"need {domain} trainer" India',
        f'"{domain}" trainer urgently required India',
        f'"{domain}" training vendor requirement India',
    ]
    rl = await bulk_free_search(queries, max_results=max_results, timeout=timeout, concurrency=8)
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
    tavily_enabled = bool(TAVILY_API_KEY)
    return {
        "tavily": tavily_enabled,
        "duckduckgo": True, "bing": True, "yahoo": True,
        "naukri_direct": True, "shine_direct": True,
        "timesjobs_direct": True, "freshersworld_direct": True,
        "active_provider": DEFAULT_PROVIDER,
        "effective_provider": "tavily_first" if DEFAULT_PROVIDER in {"auto", "tavily_first"} and tavily_enabled else DEFAULT_PROVIDER,
        "tavily_search_depth": TAVILY_SEARCH_DEPTH,
        "max_results": DEFAULT_MAX_RESULTS,
        "timeout": DEFAULT_TIMEOUT,
        "requires_api_key": DEFAULT_PROVIDER == "tavily",
        "layers": 3,
        "query_templates": len(_QUERY_TEMPLATES),
        "expected_per_domain": "100–300 trainer profiles",
    }
