"""contact_finder_agent.py — Find email + phone for trainer profiles. Zero API keys.

Strategy (10 cascading methods — stops when email + phone found):

  1. Profile text mining     — extract directly from already-scraped text (instant)
  2. Personal website scrape — scrape portfolio/blog linked in profile
  3. Naukri profile scrape   — fetch actual Naukri profile page (shows phone + email)
  4. Shine profile scrape    — fetch actual Shine.com profile page
  5. JustDial scrape         — search JustDial for trainer name + city
  6. GitHub scrape           — find GitHub profile, scrape contact from README/bio
  7. Bing people search      — search Bing for name + email + phone
  8. DDG people search       — search DuckDuckGo for name + email + phone
  9. Email pattern + MX check— guess email from name+company, verify domain has MX
 10. WhatsApp number search  — search for trainer name + WhatsApp India

Key difference from old version:
  Old: just searched for profile URLs, never fetched the actual pages
  New: FETCHES the actual Naukri/Shine/JustDial/GitHub pages and scrapes
       email + phone directly from the page HTML
"""
from __future__ import annotations

import asyncio
import logging
import re
import smtplib
import random
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# ── Regex patterns ────────────────────────────────────────────
_MOB_RE = re.compile(r"(?:\+91|0091|91)?[\s.\-()]*([6-9]\d{2}[\s.\-]*\d{3}[\s.\-]*\d{4})")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]{2,64}@[A-Za-z0-9.\-]{2,253}\.[A-Za-z]{2,12}")
_BAD_LOCAL = {"noreply","no-reply","donotreply","support","admin","info","sales",
              "hr","careers","jobs","team","contact","office","marketing","billing",
              "hello","help","feedback","enquiry","enquiries","query","privacy"}

_UA = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/123.0 Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 Chrome/124.0 Mobile Safari/537.36",
]

def _h(referer: str = "") -> Dict[str, str]:
    return {
        "User-Agent": random.choice(_UA),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,hi;q=0.7",
        "Referer": referer or "https://www.google.com/",
        "DNT": "1",
    }


# ── Text helpers ──────────────────────────────────────────────

def _strip(html: str) -> str:
    t = re.sub(r"<script[^>]*>.*?</script>", " ", html or "", flags=re.S | re.I)
    t = re.sub(r"<style[^>]*>.*?</style>", " ", t, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    for e, c in [("&amp;","&"),("&lt;","<"),("&gt;",">"),("&quot;",'"'),("&nbsp;"," "),("&#39;","'")]:
        t = t.replace(e, c)
    return re.sub(r"\s+", " ", t).strip()


def _emails(text: str) -> List[str]:
    found, seen = [], set()
    for e in _EMAIL_RE.findall(text or ""):
        local = e.split("@")[0].lower()
        if local not in _BAD_LOCAL and e.lower() not in seen:
            seen.add(e.lower())
            found.append(e)
    return found


def _phones(text: str) -> List[str]:
    found, seen = [], set()
    for m in _MOB_RE.finditer(text or ""):
        d = re.sub(r"\D", "", m.group(1))
        if len(d) == 10 and d[0] in "6789":
            n = f"+91{d}"
            if n not in seen:
                seen.add(n)
                found.append(n)
    return found


def _name_parts(name: str):
    parts = re.sub(r"[^a-zA-Z\s]", "", name or "").strip().lower().split()
    if len(parts) >= 2:
        return parts[0], parts[-1]
    if parts:
        return parts[0], parts[0]
    return "", ""


async def _fetch(client: httpx.AsyncClient, url: str, referer: str = "") -> str:
    """Fetch a URL and return stripped text. Returns '' on failure."""
    try:
        r = await client.get(url, headers=_h(referer), follow_redirects=True)
        if r.status_code == 200 and len(r.text) > 200:
            return _strip(r.text)
    except Exception as exc:
        logger.debug("fetch %s: %s", url[:80], exc)
    return ""


async def _search_engine(
    client: httpx.AsyncClient,
    query: str,
    engine: str = "bing",
) -> str:
    """Run a search query on Bing or DDG and return the stripped result text."""
    try:
        if engine == "bing":
            r = await client.get(
                "https://www.bing.com/search",
                params={"q": query, "count": 10, "mkt": "en-IN"},
                headers=_h("https://www.bing.com/"),
                follow_redirects=True,
            )
        else:
            r = await client.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query, "kl": "in-en"},
                headers=_h("https://duckduckgo.com/"),
                follow_redirects=True,
            )
        if r.status_code == 200:
            return _strip(r.text)
    except Exception as exc:
        logger.debug("search_engine %s: %s", engine, exc)
    return ""



# ══════════════════════════════════════════════════════════════
# METHOD 1 — Mine profile text already scraped (zero HTTP)
# ══════════════════════════════════════════════════════════════

def _mine_text(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    emails = _emails(text)
    phones = _phones(text)
    personal = {"gmail.com","yahoo.com","yahoo.co.in","outlook.com","hotmail.com",
                "rediffmail.com","protonmail.com","icloud.com","live.com"}
    best_email = next((e for e in emails if e.split("@")[-1].lower() in personal), emails[0] if emails else "")
    if best_email or phones:
        return {"email": best_email, "phone": phones[0] if phones else "",
                "source": "profile_text", "confidence": 0.95}
    return {}


# ══════════════════════════════════════════════════════════════
# METHOD 2 — Personal website / portfolio linked in profile
# ══════════════════════════════════════════════════════════════

async def _personal_website(text: str, client: httpx.AsyncClient) -> Dict[str, Any]:
    """Find and scrape any personal website linked in the profile text."""
    urls = []
    # Find external URLs that are not social/job sites
    for m in re.finditer(
        r"https?://(?!(?:www\.)?(?:linkedin|facebook|twitter|instagram|youtube|google|naukri|shine|github)\.com)[^\s\"'<>]{5,80}",
        text or "", re.I
    ):
        u = m.group(0).rstrip(".,;)")
        if u not in urls:
            urls.append(u)
    # Check About section for website mention
    about = re.search(r"(?:website|portfolio|blog|site)[:\s]+(\S+)", text or "", re.I)
    if about:
        urls.insert(0, about.group(1))

    for url in urls[:4]:
        if not url.startswith("http"):
            url = "https://" + url
        page = await _fetch(client, url, url)
        if not page:
            continue
        emails, phones = _emails(page), _phones(page)
        if emails or phones:
            return {"email": emails[0] if emails else "", "phone": phones[0] if phones else "",
                    "source": "personal_website", "confidence": 0.90}
    return {}


# ══════════════════════════════════════════════════════════════
# METHOD 3 — Naukri.com direct profile page scrape
# Naukri public profile pages show phone + email in plain text.
# We search Naukri directly for the trainer name + skill, then
# fetch each profile page and extract contact info.
# ══════════════════════════════════════════════════════════════

async def _naukri_profile(name: str, domain: str, client: httpx.AsyncClient) -> Dict[str, Any]:
    """
    Search Naukri for the trainer, then scrape each profile page.
    Naukri public pages often contain phone number and email in the HTML.
    """
    # Step 1: Find Naukri profile URLs via Bing search (more reliable than Google for Naukri)
    search_text = await _search_engine(
        client,
        f'site:naukri.com "{name}" "{domain}" trainer',
        engine="bing",
    )

    naukri_urls: List[str] = []
    # Extract profile URLs from search results
    for pattern in [
        r"https://www\.naukri\.com/mnjuser/profile\?[^\s\"'<>]+",
        r"https://www\.naukri\.com/(?:resume|profile)/[^\s\"'<>]+",
        r"/url\?q=(https://www\.naukri\.com/[^\s&\"]+)",
    ]:
        for m in re.finditer(pattern, search_text, re.I):
            url = m.group(1) if "url?q=" in pattern else m.group(0)
            if url not in naukri_urls:
                naukri_urls.append(url)

    # Also try Naukri's own search
    kw = urllib.parse.quote_plus(f"{name} {domain} trainer")
    naukri_search_url = f"https://www.naukri.com/jobsearch/v2?noOfResults=5&urlType=search_by_keyword&searchType=adv&keyword={kw}&jobAge=30"
    try:
        r = await client.get(naukri_search_url, headers=_h("https://www.naukri.com/"), follow_redirects=True)
        if r.status_code == 200:
            for m in re.finditer(r'"jobUrl":"([^"]+)"', r.text):
                url = m.group(1).replace(r"\u002F", "/")
                if "naukri.com" in url and url not in naukri_urls:
                    naukri_urls.append(url)
    except Exception:
        pass

    naukri_urls = list(dict.fromkeys(naukri_urls))[:5]

    # Step 2: Fetch each profile page and extract contact
    for url in naukri_urls:
        page = await _fetch(client, url, "https://www.naukri.com/")
        if not page:
            continue
        emails, phones = _emails(page), _phones(page)
        # Naukri sometimes encodes phone as data attributes
        for m in re.finditer(r'data-(?:mobile|phone|contact)["\s]*[=:]["\s]*["\']?(\+?[6-9]\d{9})', page, re.I):
            d = re.sub(r"\D", "", m.group(1))
            if len(d) == 10:
                phones.insert(0, f"+91{d}")
        if emails or phones:
            return {"email": emails[0] if emails else "", "phone": phones[0] if phones else "",
                    "source": "naukri_profile_page", "confidence": 0.88, "profile_url": url}
    return {}


# ══════════════════════════════════════════════════════════════
# METHOD 4 — Shine.com direct profile page scrape
# ══════════════════════════════════════════════════════════════

async def _shine_profile(name: str, domain: str, client: httpx.AsyncClient) -> Dict[str, Any]:
    """Search Shine.com for the trainer, then scrape the profile page."""
    text = await _search_engine(client, f'site:shine.com "{name}" "{domain}" trainer', engine="bing")
    urls = []
    for m in re.finditer(r"https://www\.shine\.com/(?:profile|resume)/[^\s\"'<>]+", text, re.I):
        u = m.group(0).split("?")[0]
        if u not in urls:
            urls.append(u)

    for url in urls[:3]:
        page = await _fetch(client, url, "https://www.shine.com/")
        if not page:
            continue
        emails, phones = _emails(page), _phones(page)
        if emails or phones:
            return {"email": emails[0] if emails else "", "phone": phones[0] if phones else "",
                    "source": "shine_profile_page", "confidence": 0.82}
    return {}


# ══════════════════════════════════════════════════════════════
# METHOD 5 — JustDial direct scrape
# JustDial lists freelance trainers with phone numbers publicly
# ══════════════════════════════════════════════════════════════

async def _justdial_search(name: str, domain: str, client: httpx.AsyncClient) -> Dict[str, Any]:
    """Search JustDial for trainer. JustDial often shows phone numbers."""
    kw = urllib.parse.quote_plus(f"{domain} trainer")
    urls = [
        f"https://www.justdial.com/India/{urllib.parse.quote(domain)}-Trainer/nct-11071476",
        f"https://www.justdial.com/jdmart/India/{kw}",
    ]
    for url in urls[:1]:
        page = await _fetch(client, url, "https://www.justdial.com/")
        if not page:
            continue
        # JustDial encodes phone in spans — look for patterns near the trainer name
        if name.split()[0].lower() in page.lower():
            phones = _phones(page)
            emails = _emails(page)
            if phones or emails:
                return {"email": emails[0] if emails else "", "phone": phones[0] if phones else "",
                        "source": "justdial", "confidence": 0.75}
    return {}



# ══════════════════════════════════════════════════════════════
# METHOD 6 — GitHub profile scrape
# Many Indian trainers have GitHub. GitHub shows email in bio.
# ══════════════════════════════════════════════════════════════

async def _github_scrape(name: str, domain: str, client: httpx.AsyncClient) -> Dict[str, Any]:
    """Search GitHub for the trainer, then scrape their profile page."""
    text = await _search_engine(client, f'site:github.com "{name}" trainer "{domain}"', engine="bing")
    urls = []
    for m in re.finditer(r"https://github\.com/([a-zA-Z0-9\-]+)(?:/[^\s\"'<>]*)?", text, re.I):
        u = f"https://github.com/{m.group(1)}"
        if u not in urls:
            urls.append(u)

    for url in urls[:3]:
        page = await _fetch(client, url, "https://github.com/")
        if not page:
            continue
        emails = _emails(page)
        phones = _phones(page)
        if emails or phones:
            return {"email": emails[0] if emails else "", "phone": phones[0] if phones else "",
                    "source": "github_profile", "confidence": 0.78}
    return {}


# ══════════════════════════════════════════════════════════════
# METHOD 7 — Bing people search
# Search Bing: "Name" "email" "phone" site:naukri OR shine
# ══════════════════════════════════════════════════════════════

async def _bing_people_search(name: str, company: str, domain: str, client: httpx.AsyncClient) -> Dict[str, Any]:
    queries = [
        f'"{name}" "{domain}" trainer email phone India',
        f'"{name}" trainer email contact India site:naukri.com OR site:shine.com OR site:linkedin.com',
    ]
    if company:
        queries.insert(0, f'"{name}" "{company}" email contact trainer')

    for q in queries[:3]:
        text = await _search_engine(client, q, engine="bing")
        emails, phones = _emails(text), _phones(text)
        if emails or phones:
            return {"email": emails[0] if emails else "", "phone": phones[0] if phones else "",
                    "source": "bing_people_search", "confidence": 0.65, "query": q}
        await asyncio.sleep(random.uniform(0.3, 0.6))
    return {}


# ══════════════════════════════════════════════════════════════
# METHOD 8 — DuckDuckGo people search
# ══════════════════════════════════════════════════════════════

async def _ddg_people_search(name: str, domain: str, client: httpx.AsyncClient) -> Dict[str, Any]:
    queries = [
        f'"{name}" trainer "{domain}" email India',
        f'"{name}" trainer India contact phone whatsapp',
    ]
    for q in queries[:2]:
        text = await _search_engine(client, q, engine="ddg")
        emails, phones = _emails(text), _phones(text)
        if emails or phones:
            return {"email": emails[0] if emails else "", "phone": phones[0] if phones else "",
                    "source": "ddg_people_search", "confidence": 0.60}
        await asyncio.sleep(random.uniform(0.2, 0.5))
    return {}


# ══════════════════════════════════════════════════════════════
# METHOD 9 — Email pattern guess + MX record verification
# Works well for Indian IT companies: TCS, Infosys, Wipro, etc.
# ══════════════════════════════════════════════════════════════

def _guess_emails(name: str, company_domain: str) -> List[str]:
    first, last = _name_parts(name)
    if not first or not company_domain:
        return []
    guesses = []
    for pattern in [
        f"{first}.{last}@{company_domain}",
        f"{first}{last}@{company_domain}",
        f"{first[0]}{last}@{company_domain}",
        f"{first}@{company_domain}",
        f"{last}.{first}@{company_domain}",
        f"{first}.{last[0]}@{company_domain}",
    ]:
        if pattern not in guesses:
            guesses.append(pattern)
    return guesses


def _mx_check(domain: str, timeout: int = 5) -> bool:
    """Check if domain has MX records (means email likely exists)."""
    try:
        import dns.resolver
        dns.resolver.resolve(domain, "MX")
        return True
    except Exception:
        pass
    # Fallback: try socket lookup for common mail servers
    try:
        import socket
        socket.setdefaulttimeout(timeout)
        socket.gethostbyname(f"mail.{domain}")
        return True
    except Exception:
        return False


async def _email_pattern(name: str, company: str, client: httpx.AsyncClient) -> Dict[str, Any]:
    if not name or not company:
        return {}
    # Find the company domain
    company_domain = ""
    text = await _search_engine(client, f"{company} official website email", engine="bing")
    m = re.search(r"@([a-zA-Z0-9.\-]+\.(?:com|co\.in|in|net|org))", text)
    if m:
        company_domain = m.group(1).lower()

    if not company_domain:
        return {}

    guesses = _guess_emails(name, company_domain)
    loop = asyncio.get_event_loop()
    for guess in guesses[:4]:
        try:
            valid = await loop.run_in_executor(None, _mx_check, guess.split("@")[1])
            if valid:
                return {"email": guess, "phone": "", "source": "email_pattern_mx_verified",
                        "confidence": 0.70, "company_domain": company_domain}
        except Exception:
            continue

    if guesses:
        return {"email": guesses[0], "phone": "", "source": "email_pattern_guess",
                "confidence": 0.40, "company_domain": company_domain,
                "note": "Pattern guess — not verified"}
    return {}


# ══════════════════════════════════════════════════════════════
# METHOD 10 — WhatsApp / phone number search
# Many Indian trainers advertise on WhatsApp groups —
# their number appears in search results
# ══════════════════════════════════════════════════════════════

async def _whatsapp_search(name: str, domain: str, client: httpx.AsyncClient) -> Dict[str, Any]:
    queries = [
        f'"{name}" trainer "{domain}" whatsapp India phone number',
        f'"{name}" freelance trainer India +91 contact',
    ]
    for q in queries[:2]:
        text = await _search_engine(client, q, engine="bing")
        phones = _phones(text)
        if phones:
            return {"email": "", "phone": phones[0], "source": "whatsapp_search", "confidence": 0.55}
        await asyncio.sleep(0.2)
    return {}



# ══════════════════════════════════════════════════════════════
# MAIN ENTRY POINTS
# ══════════════════════════════════════════════════════════════

import urllib.parse  # needed by naukri method


async def find_contact_for_trainer(
    name: str = "",
    company: str = "",
    domain: str = "",
    linkedin_url: str = "",
    profile_text: str = "",
    timeout: int = 45,
) -> Dict[str, Any]:
    """
    Find email + phone for a trainer using 10 cascading methods.
    Stops as soon as both email AND phone are found.
    Falls through all methods if only one or neither is found.

    Returns:
        {
          "email":      str,
          "phone":      str,
          "source":     str,
          "confidence": float,
          "found":      bool,
        }
    """
    result: Dict[str, Any] = {
        "email": "", "phone": "", "source": "", "confidence": 0.0, "found": False
    }

    def _merge(r: Dict[str, Any]) -> bool:
        """Merge a sub-result into the main result. Returns True if both email+phone now found."""
        if r.get("email") and not result["email"]:
            result["email"] = r["email"]
            result["source"] = r.get("source", "")
            result["confidence"] = r.get("confidence", 0.5)
            result["found"] = True
        if r.get("phone") and not result["phone"]:
            result["phone"] = r["phone"]
            if not result["source"]:
                result["source"] = r.get("source", "")
            result["found"] = True
        return bool(result["email"] and result["phone"])

    # Method 1 — instant, zero HTTP
    r = _mine_text(profile_text)
    if _merge(r) and result["email"] and result["phone"]:
        return result

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, http2=False) as client:

        # Method 2 — personal website
        r = await _personal_website(profile_text, client)
        if _merge(r) and result["email"] and result["phone"]:
            return result

        # Method 3 — Naukri profile page (BEST for Indian trainers)
        if name:
            r = await _naukri_profile(name, domain, client)
            if _merge(r) and result["email"] and result["phone"]:
                return result

        # Method 4 — Shine profile page
        if name:
            r = await _shine_profile(name, domain, client)
            if _merge(r) and result["email"] and result["phone"]:
                return result

        # Method 5 — JustDial
        if name:
            r = await _justdial_search(name, domain, client)
            if _merge(r) and result["email"] and result["phone"]:
                return result

        # Method 6 — GitHub
        if name:
            r = await _github_scrape(name, domain, client)
            if _merge(r) and result["email"] and result["phone"]:
                return result

        # Method 7 — Bing people search
        if name:
            r = await _bing_people_search(name, company, domain, client)
            if _merge(r) and result["email"] and result["phone"]:
                return result

        # Method 8 — DDG people search
        if name:
            r = await _ddg_people_search(name, domain, client)
            if _merge(r) and result["email"] and result["phone"]:
                return result

        # Method 9 — Email pattern + MX check (last resort for email)
        if not result["email"] and name and company:
            r = await _email_pattern(name, company, client)
            _merge(r)

        # Method 10 — WhatsApp / phone search (last resort for phone)
        if not result["phone"] and name:
            r = await _whatsapp_search(name, domain, client)
            _merge(r)

    result["found"] = bool(result["email"] or result["phone"])
    return result


async def bulk_find_contacts(
    trainers: List[Dict[str, Any]],
    *,
    concurrency: int = 5,
    timeout: int = 45,
) -> List[Dict[str, Any]]:
    """
    Find contacts for a list of trainers concurrently.

    Args:
        trainers:    List of trainer dicts (name, company, domain, linkedin_url, profile_text)
        concurrency: How many trainers to process in parallel
        timeout:     Per-trainer timeout in seconds

    Returns:
        List of trainer dicts each with a "contact_result" key added
    """
    sem = asyncio.Semaphore(concurrency)

    async def _one(trainer: Dict[str, Any]) -> Dict[str, Any]:
        async with sem:
            await asyncio.sleep(random.uniform(0.2, 0.8))
            res = await find_contact_for_trainer(
                name=trainer.get("name") or trainer.get("trainer_name") or "",
                company=trainer.get("company") or trainer.get("current_company") or "",
                domain=trainer.get("domain") or trainer.get("technology") or "",
                linkedin_url=trainer.get("linkedin_url") or trainer.get("linkedin") or "",
                profile_text=trainer.get("profile_text") or trainer.get("resume") or "",
                timeout=timeout,
            )
            return {**trainer, "contact_result": res}

    return list(await asyncio.gather(*[_one(t) for t in trainers]))
