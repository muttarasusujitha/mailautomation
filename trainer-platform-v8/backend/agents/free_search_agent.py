"""free_search_agent.py — 100% FREE web search engine. Zero API keys. Zero accounts.

How it works (exactly like a search engine):
  1. Send a search query to DuckDuckGo / Bing / Google / Yahoo HTML pages
  2. Parse the raw HTML response to extract URLs, titles, snippets
  3. Optionally fetch the actual page content from each result URL
  4. Return structured results — same shape as Tavily

Provider waterfall (all pure HTML scraping, no API, no key, no account):
  1. DuckDuckGo  — POST html.duckduckgo.com/html/   (most reliable, no bot block)
  2. Bing        — GET  www.bing.com/search          (high quality results)
  3. Google      — GET  www.google.com/search        (best results, strict bot check)
  4. Yahoo       — GET  search.yahoo.com/search      (easy fallback)
  5. Ask         — GET  www.ask.com/web              (last resort)

Each result shape (identical to Tavily):
    { url, title, content, raw_content, source }
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

# ── Defaults ──────────────────────────────────────────────────
DEFAULT_MAX_RESULTS = int(os.getenv("FREE_SEARCH_MAX_RESULTS", "5"))
DEFAULT_TIMEOUT     = int(os.getenv("FREE_SEARCH_TIMEOUT", "20"))
DEFAULT_PROVIDER    = os.getenv("FREE_SEARCH_PROVIDER", "auto").strip().lower()

SearchResult = Dict[str, Any]


# ── Rotating browser headers (avoid bot detection) ────────────
# Each request picks one at random so we don't look like a bot
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

import random

def _headers(referer: str = "") -> Dict[str, str]:
    """Return browser-like headers with a random User-Agent."""
    h = {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "DNT": "1",
    }
    if referer:
        h["Referer"] = referer
    return h



# ── HTML parsing helpers ───────────────────────────────────────

def _strip_html(html: str) -> str:
    """Remove all HTML tags and decode common entities."""
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html or "", flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>",  " ", text,        flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    for entity, char in [("&amp;","&"),("&lt;","<"),("&gt;",">"),("&quot;",'"'),("&#x27;","'"),("&nbsp;"," "),("&#39;","'")]:
        text = text.replace(entity, char)
    return re.sub(r"\s+", " ", text).strip()


def _decode_url(raw: str) -> str:
    """Decode percent-encoded URL and strip tracking wrappers."""
    if not raw:
        return ""
    # DuckDuckGo: //duckduckgo.com/l/?uddg=<encoded>
    m = re.search(r"uddg=([^&]+)", raw)
    if m:
        return urllib.parse.unquote(m.group(1))
    # Google: /url?q=<encoded>  or  /url?url=<encoded>
    m = re.search(r"[?&](?:q|url)=(https?[^&]+)", raw)
    if m:
        return urllib.parse.unquote(m.group(1))
    # Bing: /ck/a?...&u=<base64>  (skip — use direct href instead)
    if raw.startswith("//"):
        return "https:" + raw
    return raw


def _make_result(url: str, title: str, snippet: str, source: str) -> SearchResult:
    url = _decode_url(url.strip())
    title   = _strip_html(title).strip()
    snippet = _strip_html(snippet).strip()
    return {"url": url, "title": title, "content": snippet, "raw_content": snippet, "source": source}



# ══════════════════════════════════════════════════════════════
# ENGINE 1 — DuckDuckGo  (POST html.duckduckgo.com/html/)
# No key. No account. No rate-limit. Works out of the box.
# ══════════════════════════════════════════════════════════════

async def _search_duckduckgo(query: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    try:
        resp = await client.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query, "b": "", "kl": "in-en"},
            headers=_headers("https://duckduckgo.com/"),
            follow_redirects=True,
        )
        if resp.status_code >= 400:
            return []
        html = resp.text
    except Exception as exc:
        logger.debug("DDG failed: %s", exc)
        return []

    results: List[SearchResult] = []

    # Strategy A: structured result blocks
    blocks = re.findall(
        r'<div[^>]*class="[^"]*result[^"]*results_links[^"]*"[^>]*>(.*?)</div>\s*</div>',
        html, re.DOTALL | re.IGNORECASE,
    )
    for block in blocks[:max_results]:
        link = re.search(r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', block, re.DOTALL | re.IGNORECASE)
        snip = re.search(r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</(?:a|span|div)>', block, re.DOTALL | re.IGNORECASE)
        if link:
            results.append(_make_result(link.group(1), link.group(2), snip.group(1) if snip else "", "duckduckgo"))

    # Strategy B: fallback — any result__a links
    if not results:
        for m in re.finditer(r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', html, re.DOTALL | re.IGNORECASE):
            results.append(_make_result(m.group(1), m.group(2), "", "duckduckgo"))
            if len(results) >= max_results:
                break

    return [r for r in results if r["url"]][:max_results]



# ══════════════════════════════════════════════════════════════
# ENGINE 2 — Bing  (GET www.bing.com/search)
# No key. No account. High quality results for Indian queries.
# ══════════════════════════════════════════════════════════════

async def _search_bing(query: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    try:
        resp = await client.get(
            "https://www.bing.com/search",
            params={"q": query, "count": max_results + 2, "mkt": "en-IN", "setlang": "en"},
            headers=_headers("https://www.bing.com/"),
            follow_redirects=True,
        )
        if resp.status_code >= 400:
            return []
        html = resp.text
    except Exception as exc:
        logger.debug("Bing failed: %s", exc)
        return []

    results: List[SearchResult] = []

    # Strategy A: b_algo blocks (main organic results)
    blocks = re.findall(r'<li[^>]*class="[^"]*b_algo[^"]*"[^>]*>(.*?)</li>', html, re.DOTALL | re.IGNORECASE)
    for block in blocks[:max_results]:
        link = re.search(r'<h2[^>]*>.*?<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL | re.IGNORECASE)
        snip = re.search(r'<p[^>]*>(.*?)</p>', block, re.DOTALL | re.IGNORECASE)
        if link:
            url = link.group(1)
            # skip Bing's own pages
            if "bing.com" in url:
                continue
            results.append(_make_result(url, link.group(2), snip.group(1) if snip else "", "bing"))

    # Strategy B: fallback — any direct https href with a title
    if not results:
        for m in re.finditer(r'<a[^>]+href="(https?://(?!www\.bing)[^"]+)"[^>]*><strong>(.*?)</strong>', html, re.DOTALL | re.IGNORECASE):
            results.append(_make_result(m.group(1), m.group(2), "", "bing"))
            if len(results) >= max_results:
                break

    return [r for r in results if r["url"]][:max_results]



# ══════════════════════════════════════════════════════════════
# ENGINE 3 — Google  (GET www.google.com/search)
# No key. No account. Best results but strict bot detection.
# Uses multiple bypass strategies.
# ══════════════════════════════════════════════════════════════

async def _search_google(query: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    # Google blocks bots aggressively — we use multiple strategies
    strategies = [
        # Strategy 1: standard search with mobile UA (less strict)
        {
            "url": "https://www.google.com/search",
            "params": {"q": query, "num": max_results + 3, "hl": "en", "gl": "in"},
            "headers": {
                "User-Agent": "Mozilla/5.0 (Linux; Android 10; SM-G975U) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.120 Mobile Safari/537.36",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.google.com/",
            },
        },
        # Strategy 2: google.co.in (sometimes less aggressive)
        {
            "url": "https://www.google.co.in/search",
            "params": {"q": query, "num": max_results + 3, "hl": "en"},
            "headers": _headers("https://www.google.co.in/"),
        },
    ]

    html = ""
    for strategy in strategies:
        try:
            resp = await client.get(
                strategy["url"],
                params=strategy["params"],
                headers=strategy["headers"],
                follow_redirects=True,
            )
            if resp.status_code == 200 and len(resp.text) > 2000:
                html = resp.text
                break
        except Exception as exc:
            logger.debug("Google strategy failed: %s", exc)
            continue

    if not html:
        return []

    results: List[SearchResult] = []

    # Strategy A: <div class="g"> organic result blocks
    blocks = re.findall(r'<div[^>]*class="[^"]*(?:\bg\b)[^"]*"[^>]*>(.*?)</div>\s*</div>', html, re.DOTALL | re.IGNORECASE)
    for block in blocks[:max_results + 3]:
        link = re.search(r'<a[^>]+href="(https?://(?!google\.com)[^"&]+)"', block, re.IGNORECASE)
        title = re.search(r'<h3[^>]*>(.*?)</h3>', block, re.DOTALL | re.IGNORECASE)
        snip = re.search(r'<span[^>]*class="[^"]*st[^"]*"[^>]*>(.*?)</span>', block, re.DOTALL | re.IGNORECASE) \
            or re.search(r'<div[^>]*class="[^"]*IsZvec[^"]*"[^>]*>(.*?)</div>', block, re.DOTALL | re.IGNORECASE)
        if link and title:
            results.append(_make_result(link.group(1), title.group(1), snip.group(1) if snip else "", "google"))

    # Strategy B: fallback — /url?q= redirect links
    if not results:
        for m in re.finditer(r'href="/url\?q=(https?[^&"]+)[^"]*"[^>]*>.*?<h3[^>]*>(.*?)</h3>', html, re.DOTALL | re.IGNORECASE):
            results.append(_make_result(m.group(1), m.group(2), "", "google"))
            if len(results) >= max_results:
                break

    # Strategy C: any direct external https link with h3 title near it
    if not results:
        for m in re.finditer(r'<a[^>]+href="(https?://(?!(?:www\.)?google)[^"]+)"[^>]*>.*?<h3[^>]*>(.*?)</h3>', html, re.DOTALL | re.IGNORECASE):
            results.append(_make_result(m.group(1), m.group(2), "", "google"))
            if len(results) >= max_results:
                break

    return [r for r in results if r["url"]][:max_results]



# ══════════════════════════════════════════════════════════════
# ENGINE 4 — Yahoo Search  (GET search.yahoo.com/search)
# No key. No account. Good fallback, rarely blocks bots.
# ══════════════════════════════════════════════════════════════

async def _search_yahoo(query: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    try:
        resp = await client.get(
            "https://search.yahoo.com/search",
            params={"p": query, "n": max_results + 2, "ei": "UTF-8"},
            headers=_headers("https://search.yahoo.com/"),
            follow_redirects=True,
        )
        if resp.status_code >= 400:
            return []
        html = resp.text
    except Exception as exc:
        logger.debug("Yahoo failed: %s", exc)
        return []

    results: List[SearchResult] = []

    # Yahoo wraps links in /RU redirect — extract real URL from ru= param
    blocks = re.findall(r'<div[^>]*class="[^"]*(?:algo|dd)[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL | re.IGNORECASE)
    for block in blocks[:max_results]:
        link = re.search(r'<a[^>]+href="(https?://[^"]+)"[^>]*><b>(.*?)</b>', block, re.DOTALL | re.IGNORECASE) \
            or re.search(r'<h3[^>]*>.*?<a[^>]+href="(https?://(?!yahoo)[^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL | re.IGNORECASE)
        snip = re.search(r'<p[^>]*class="[^"]*s-desc[^"]*"[^>]*>(.*?)</p>', block, re.DOTALL | re.IGNORECASE) \
            or re.search(r'<span[^>]*class="[^"]*fc-falcon[^"]*"[^>]*>(.*?)</span>', block, re.DOTALL | re.IGNORECASE)
        if link:
            url = link.group(1)
            if "yahoo.com" in url:
                continue
            results.append(_make_result(url, link.group(2), snip.group(1) if snip else "", "yahoo"))

    # Fallback: any external https link with text
    if not results:
        for m in re.finditer(r'<a[^>]+href="(https?://(?!(?:www\.)?yahoo)[^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL | re.IGNORECASE):
            t = _strip_html(m.group(2)).strip()
            if len(t) > 10:
                results.append(_make_result(m.group(1), t, "", "yahoo"))
                if len(results) >= max_results:
                    break

    return [r for r in results if r["url"]][:max_results]



# ══════════════════════════════════════════════════════════════
# ENGINE 5 — Ask.com  (GET www.ask.com/web)
# No key. No account. Last resort fallback.
# ══════════════════════════════════════════════════════════════

async def _search_ask(query: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    try:
        resp = await client.get(
            "https://www.ask.com/web",
            params={"q": query, "qsrc": "0", "o": "0", "l": "dir"},
            headers=_headers("https://www.ask.com/"),
            follow_redirects=True,
        )
        if resp.status_code >= 400:
            return []
        html = resp.text
    except Exception as exc:
        logger.debug("Ask failed: %s", exc)
        return []

    results: List[SearchResult] = []

    # Ask result blocks
    blocks = re.findall(r'<div[^>]*class="[^"]*PartialSearchResults-item[^"]*"[^>]*>(.*?)</div>\s*</div>', html, re.DOTALL | re.IGNORECASE)
    for block in blocks[:max_results]:
        link  = re.search(r'<a[^>]+href="(https?://(?!ask\.com)[^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL | re.IGNORECASE)
        snip  = re.search(r'<p[^>]*>(.*?)</p>', block, re.DOTALL | re.IGNORECASE)
        if link:
            results.append(_make_result(link.group(1), link.group(2), snip.group(1) if snip else "", "ask"))

    if not results:
        for m in re.finditer(r'<a[^>]+href="(https?://(?!(?:www\.)?ask\.com)[^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL | re.IGNORECASE):
            t = _strip_html(m.group(2)).strip()
            if len(t) > 10:
                results.append(_make_result(m.group(1), t, "", "ask"))
                if len(results) >= max_results:
                    break

    return [r for r in results if r["url"]][:max_results]



# ══════════════════════════════════════════════════════════════
# ENGINE 6 — Direct page content fetcher
# When all search engines fail, fetch LinkedIn / Naukri directly.
# Uses Google's cache (cache:url) to bypass login walls.
# ══════════════════════════════════════════════════════════════

async def _fetch_page_content(url: str, client: httpx.AsyncClient) -> str:
    """Fetch the raw text content of a URL. Returns empty string on failure."""
    try:
        resp = await client.get(url, headers=_headers(url), follow_redirects=True)
        if resp.status_code >= 400:
            return ""
        return _strip_html(resp.text)[:3000]
    except Exception:
        return ""


async def _search_linkedin_direct(query: str, max_results: int, client: httpx.AsyncClient) -> List[SearchResult]:
    """
    Special LinkedIn scraper — searches Google cache for LinkedIn pages.
    Works even when LinkedIn blocks direct access.
    """
    results: List[SearchResult] = []

    # Try Google cache version of LinkedIn
    cache_query = f"cache:linkedin.com/in {query}"
    try:
        resp = await client.get(
            "https://webcache.googleusercontent.com/search",
            params={"q": cache_query},
            headers=_headers("https://www.google.com/"),
            follow_redirects=True,
        )
        if resp.status_code == 200 and "linkedin" in resp.text.lower():
            for m in re.finditer(r'(https?://(?:www\.)?linkedin\.com/in/[^\s"\'<>]+)', resp.text):
                url = m.group(1).split("?")[0].rstrip("/")
                if url not in [r["url"] for r in results]:
                    results.append(_make_result(url, url.split("/")[-1].replace("-", " ").title(), "", "linkedin_cache"))
                    if len(results) >= max_results:
                        break
    except Exception:
        pass

    return results



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
    Search the web using pure HTML scraping. Zero API keys. Zero cost.

    Provider waterfall (tried in order until results found):
      1. DuckDuckGo  — most reliable, no bot blocks
      2. Bing        — high quality, rarely blocks
      3. Google      — best results, but strict bot check
      4. Yahoo       — good fallback
      5. Ask         — last resort

    Returns list of { url, title, content, raw_content, source }
    Same shape as Tavily — caller code needs zero changes.
    """
    chosen = (provider or DEFAULT_PROVIDER).lower()
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            http2=False,
        )

    results: List[SearchResult] = []
    try:
        if chosen == "duckduckgo":
            results = await _search_duckduckgo(query, max_results, client)
        elif chosen == "bing":
            results = await _search_bing(query, max_results, client)
        elif chosen == "google":
            results = await _search_google(query, max_results, client)
        elif chosen == "yahoo":
            results = await _search_yahoo(query, max_results, client)
        elif chosen == "ask":
            results = await _search_ask(query, max_results, client)
        else:
            # AUTO waterfall — tries each engine until we get results
            _engines = [
                ("duckduckgo", _search_duckduckgo),
                ("bing",       _search_bing),
                ("google",     _search_google),
                ("yahoo",      _search_yahoo),
                ("ask",        _search_ask),
            ]
            for name, engine_fn in _engines:
                try:
                    results = await engine_fn(query, max_results, client)
                    if results:
                        logger.debug("free_web_search: '%s' returned %d results via %s", query[:60], len(results), name)
                        break
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
    concurrency: int = 4,
    provider: Optional[str] = None,
) -> List[tuple]:
    """
    Run multiple queries concurrently via free HTML scraping.

    Returns: List of (query, {"results": [...]}, error_or_None) tuples
    Same contract as old Tavily gather pattern — zero changes in callers.
    """
    semaphore = asyncio.Semaphore(max(1, min(concurrency, 8)))
    chosen = (provider or DEFAULT_PROVIDER).lower()

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as shared_client:

        async def _run(query: str):
            async with semaphore:
                # Small random delay (0.3–0.8s) between requests
                # so engines don't see a burst of identical-IP traffic
                await asyncio.sleep(random.uniform(0.3, 0.8))
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


# ── Convenience helpers ───────────────────────────────────────

async def search_linkedin_trainers(
    domain: str,
    *,
    max_results: int = DEFAULT_MAX_RESULTS,
    locations: Optional[List[str]] = None,
    roles: Optional[List[str]] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> List[SearchResult]:
    """Search for LinkedIn trainer profiles for a given domain. No API key."""
    _roles = roles or ["trainer", "corporate trainer", "certified trainer"]
    _locs  = locations or ["India"]
    queries = []
    for role in _roles[:3]:
        for loc in _locs[:3]:
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
    phrases = ["Corporate Trainer Required", "Need Technical Trainer", "Trainer Required", "Training Requirement"]
    queries = [f'site:linkedin.com/posts "{phrase}" "{domain}"' for phrase in phrases[:3]]
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
    """All engines are always available — zero API keys needed."""
    return {
        "duckduckgo":     True,
        "bing":           True,
        "google":         True,
        "yahoo":          True,
        "ask":            True,
        "active_provider": DEFAULT_PROVIDER,
        "max_results":    DEFAULT_MAX_RESULTS,
        "timeout":        DEFAULT_TIMEOUT,
        "requires_api_key": False,
    }
