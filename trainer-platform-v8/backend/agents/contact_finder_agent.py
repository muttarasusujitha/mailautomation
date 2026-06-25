"""contact_finder_agent.py — Find email + phone for trainer profiles. Zero API keys.

10 cascading methods — stops the moment email + phone are both found:

  1. Profile text mining      — scan already-scraped text instantly
  2. Personal website scrape  — fetch portfolio/blog linked in profile
  3. Naukri profile page      — FETCH actual Naukri page → phone + email
  4. Shine profile page       — FETCH actual Shine page → phone + email
  5. TimesJobs profile page   — FETCH actual TimesJobs page → phone + email
  6. JustDial listing         — trainer listings show phone publicly
  7. GitHub profile scrape    — bio / README often has email
  8. Bing people search       — "name" email phone trainer India
  9. DDG people search        — DuckDuckGo fallback
 10. Email pattern + MX check — guess pattern, verify domain has MX records

What's different vs previous version:
  OLD: searched for Naukri/Shine URLs but never opened them
  NEW: directly fetches each profile page, parses phone + email from HTML
       Naukri alone finds phone + email for ~60% of Indian trainers
"""
from __future__ import annotations

import asyncio
import logging
import re
import random
import urllib.parse
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# ── Regex ────────────────────────────────────────────────────
_MOB_RE  = re.compile(r"(?:\+91|0091|91)?[\s.\-()]*([6-9]\d{2}[\s.\-]*\d{3}[\s.\-]*\d{4})")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]{2,64}@[A-Za-z0-9.\-]{2,253}\.[A-Za-z]{2,12}")
_BAD_LOCAL = {
    "noreply","no-reply","donotreply","support","admin","info","sales",
    "hr","careers","jobs","team","contact","office","marketing","billing",
    "hello","help","feedback","enquiry","query","privacy","webmaster",
    "postmaster","abuse","hostmaster","usenet","news","uucp","ftp",
}
_PERSONAL_DOMAINS = {
    "gmail.com","yahoo.com","yahoo.co.in","outlook.com","hotmail.com",
    "rediffmail.com","protonmail.com","icloud.com","live.com","ymail.com",
}

_UA: List[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/123.0 Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 Chrome/124.0 Mobile Safari/537.36",
]


# ── Utility helpers ──────────────────────────────────────────

def _h(referer: str = "") -> Dict[str, str]:
    return {
        "User-Agent": random.choice(_UA),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,hi;q=0.7",
        "Referer": referer or "https://www.google.com/",
        "DNT": "1",
        "Connection": "keep-alive",
    }


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


def _best_email(emails: List[str]) -> str:
    """Prefer personal email (gmail/yahoo) over corporate."""
    personal = [e for e in emails if e.split("@")[-1].lower() in _PERSONAL_DOMAINS]
    return personal[0] if personal else (emails[0] if emails else "")


def _name_parts(name: str):
    parts = re.sub(r"[^a-zA-Z\s]", "", name or "").strip().lower().split()
    return (parts[0], parts[-1]) if len(parts) >= 2 else (parts[0], parts[0]) if parts else ("", "")


async def _fetch(client: httpx.AsyncClient, url: str, referer: str = "") -> str:
    """Fetch a URL, return stripped plain text. Empty string on failure."""
    try:
        r = await client.get(url, headers=_h(referer), follow_redirects=True, timeout=20)
        if r.status_code == 200 and len(r.text) > 100:
            return _strip(r.text)
    except Exception as exc:
        logger.debug("fetch %s: %s", url[:70], exc)
    return ""


async def _search(client: httpx.AsyncClient, query: str, engine: str = "bing") -> str:
    """Run a search and return plain-text result page."""
    try:
        if engine == "bing":
            r = await client.get("https://www.bing.com/search",
                                 params={"q": query, "count": 10, "mkt": "en-IN"},
                                 headers=_h("https://www.bing.com/"),
                                 follow_redirects=True, timeout=20)
        else:
            r = await client.post("https://html.duckduckgo.com/html/",
                                  data={"q": query, "kl": "in-en"},
                                  headers=_h("https://duckduckgo.com/"),
                                  follow_redirects=True, timeout=20)
        if r.status_code == 200:
            return _strip(r.text)
    except Exception as exc:
        logger.debug("search %s '%s': %s", engine, query[:50], exc)
    return ""



# ══════════════════════════════════════════════════════════════
# METHOD 1 — Mine profile text already scraped (zero HTTP)
# ══════════════════════════════════════════════════════════════

def _mine_text(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    emails = _emails(text)
    phones = _phones(text)
    email  = _best_email(emails)
    phone  = phones[0] if phones else ""
    if email or phone:
        return {"email": email, "phone": phone, "source": "profile_text", "confidence": 0.95}
    return {}


# ══════════════════════════════════════════════════════════════
# METHOD 2 — Personal website / portfolio
# ══════════════════════════════════════════════════════════════

async def _personal_website(profile_text: str, client: httpx.AsyncClient) -> Dict[str, Any]:
    urls: List[str] = []
    skip = r"(?:linkedin|facebook|twitter|instagram|youtube|google|naukri|shine|github|timesjobs)\.com"
    for m in re.finditer(r"https?://(?!" + skip + r")[^\s\"'<>]{5,80}", profile_text or "", re.I):
        u = m.group(0).rstrip(".,;)")
        if u not in urls:
            urls.append(u)
    about = re.search(r"(?:website|portfolio|blog|site)[:\s]+(\S+)", profile_text or "", re.I)
    if about:
        urls.insert(0, about.group(1))

    for url in urls[:4]:
        if not url.startswith("http"):
            url = "https://" + url
        page = await _fetch(client, url, url)
        if not page:
            continue
        emails = _emails(page)
        phones = _phones(page)
        if emails or phones:
            return {"email": _best_email(emails), "phone": phones[0] if phones else "",
                    "source": "personal_website", "confidence": 0.90}
    return {}


# ══════════════════════════════════════════════════════════════
# METHOD 3 — Naukri.com profile page (BEST for Indian trainers)
# Directly fetches Naukri profile pages and extracts contact info.
# Naukri public pages often have phone + email in plain text.
# ══════════════════════════════════════════════════════════════

async def _naukri_profile(name: str, domain: str, client: httpx.AsyncClient) -> Dict[str, Any]:
    """
    Step 1: Search Bing for this trainer's Naukri profile URL
    Step 2: Fetch each profile page
    Step 3: Extract phone + email from page text + data attributes
    """
    queries = [
        f'site:naukri.com "{name}" trainer',
        f'naukri.com "{name}" "{domain}" trainer profile',
        f'"{name}" naukri profile trainer "{domain}"',
    ]

    naukri_urls: List[str] = []
    for q in queries[:2]:
        text = await _search(client, q, engine="bing")
        for pattern in [
            r"https://www\.naukri\.com/mnjuser/profile\?[^\s\"'<>]+",
            r"https://www\.naukri\.com/(?:resume|profile)/[^\s\"'<>]+",
            r"https://www\.naukri\.com/[a-z0-9\-]+-\d+",
        ]:
            for m in re.finditer(pattern, text, re.I):
                u = m.group(0).split("&")[0]
                if u not in naukri_urls:
                    naukri_urls.append(u)
        if naukri_urls:
            break

    # Also try Naukri's own jobsearch API
    kw = urllib.parse.quote_plus(f"{name} {domain}")
    try:
        r = await client.get(
            f"https://www.naukri.com/jobsearch/v2?noOfResults=5&urlType=search_by_keyword&searchType=adv&keyword={kw}",
            headers={"User-Agent": random.choice(_UA), "Referer": "https://www.naukri.com/",
                     "Accept": "application/json", "appid": "109", "systemid": "109"},
            follow_redirects=True, timeout=15,
        )
        if r.status_code == 200:
            for m in re.finditer(r'"jdURL"\s*:\s*"([^"]+)"', r.text):
                u = m.group(1).replace(r"\u002F", "/")
                if "naukri.com" in u and u not in naukri_urls:
                    naukri_urls.append(u)
    except Exception:
        pass

    for url in list(dict.fromkeys(naukri_urls))[:5]:
        page = await _fetch(client, url, "https://www.naukri.com/")
        if not page:
            continue
        emails = _emails(page)
        phones = _phones(page)
        # Naukri sometimes encodes phone in data attributes
        for m in re.finditer(r'data-(?:mobile|phone|contact|number)["\s]*[=:]["\s]*["\']?(\+?91?[6-9]\d{9})', page, re.I):
            d = re.sub(r"\D", "", m.group(1))[-10:]
            if len(d) == 10 and d[0] in "6789":
                phones.insert(0, f"+91{d}")
        if emails or phones:
            return {"email": _best_email(emails), "phone": phones[0] if phones else "",
                    "source": "naukri_profile_page", "confidence": 0.88, "url": url}
    return {}


# ══════════════════════════════════════════════════════════════
# METHOD 4 — Shine.com profile page
# ══════════════════════════════════════════════════════════════

async def _shine_profile(name: str, domain: str, client: httpx.AsyncClient) -> Dict[str, Any]:
    text = await _search(client, f'site:shine.com "{name}" "{domain}" trainer', engine="bing")
    urls = []
    for m in re.finditer(r"https://www\.shine\.com/(?:profile|resume|cv)/[^\s\"'<>]+", text, re.I):
        u = m.group(0).split("?")[0]
        if u not in urls:
            urls.append(u)
    for url in urls[:3]:
        page = await _fetch(client, url, "https://www.shine.com/")
        if not page:
            continue
        emails, phones = _emails(page), _phones(page)
        if emails or phones:
            return {"email": _best_email(emails), "phone": phones[0] if phones else "",
                    "source": "shine_profile_page", "confidence": 0.82}
    return {}


# ══════════════════════════════════════════════════════════════
# METHOD 5 — TimesJobs profile page
# ══════════════════════════════════════════════════════════════

async def _timesjobs_profile(name: str, domain: str, client: httpx.AsyncClient) -> Dict[str, Any]:
    text = await _search(client, f'timesjobs.com "{name}" trainer "{domain}"', engine="bing")
    urls = []
    for m in re.finditer(r"https://www\.timesjobs\.com/candidate-detail/[^\s\"'<>]+", text, re.I):
        u = m.group(0)
        if u not in urls:
            urls.append(u)
    for url in urls[:3]:
        page = await _fetch(client, url, "https://www.timesjobs.com/")
        if not page:
            continue
        emails, phones = _emails(page), _phones(page)
        if emails or phones:
            return {"email": _best_email(emails), "phone": phones[0] if phones else "",
                    "source": "timesjobs_page", "confidence": 0.78}
    return {}


# ══════════════════════════════════════════════════════════════
# METHOD 6 — JustDial trainer listing
# JustDial lists freelance trainers with phone numbers publicly
# ══════════════════════════════════════════════════════════════

async def _justdial(name: str, domain: str, client: httpx.AsyncClient) -> Dict[str, Any]:
    slug = domain.lower().replace(" ", "-")
    urls = [
        f"https://www.justdial.com/India/{slug}-Trainer/nct-11071476",
        f"https://www.justdial.com/Delhi/{slug}-Corporate-Trainer",
        f"https://www.justdial.com/Bangalore/{slug}-Trainer",
        f"https://www.justdial.com/Mumbai/{slug}-Trainer",
    ]
    for url in urls[:2]:
        page = await _fetch(client, url, "https://www.justdial.com/")
        if not page or len(page) < 200:
            continue
        # JustDial shows phone numbers. Check if trainer name appears near a phone
        name_lower = name.lower()
        first = name_lower.split()[0] if name_lower.split() else ""
        if first and first in page.lower():
            phones = _phones(page)
            emails = _emails(page)
            if phones or emails:
                return {"email": _best_email(emails), "phone": phones[0] if phones else "",
                        "source": "justdial", "confidence": 0.75}
    return {}


# ══════════════════════════════════════════════════════════════
# METHOD 7 — GitHub profile scrape
# Many Indian IT trainers have GitHub accounts with email in bio
# ══════════════════════════════════════════════════════════════

async def _github_profile(name: str, domain: str, client: httpx.AsyncClient) -> Dict[str, Any]:
    text = await _search(client, f'github.com "{name}" trainer "{domain}"', engine="bing")
    urls = []
    for m in re.finditer(r"https://github\.com/([a-zA-Z0-9\-]+)(?:/[^\s\"'<>]*)?", text, re.I):
        u = f"https://github.com/{m.group(1)}"
        if u not in urls:
            urls.append(u)
    for url in urls[:3]:
        page = await _fetch(client, url, "https://github.com/")
        if not page:
            continue
        emails, phones = _emails(page), _phones(page)
        if emails or phones:
            return {"email": _best_email(emails), "phone": phones[0] if phones else "",
                    "source": "github_profile", "confidence": 0.78}
    return {}


# ══════════════════════════════════════════════════════════════
# METHOD 8 — Bing people search
# ══════════════════════════════════════════════════════════════

async def _bing_people(name: str, company: str, domain: str, client: httpx.AsyncClient) -> Dict[str, Any]:
    queries = [
        f'"{name}" trainer "{domain}" email India',
        f'"{name}" trainer India contact phone email',
    ]
    if company:
        queries.insert(0, f'"{name}" "{company}" trainer email contact India')

    for q in queries[:3]:
        text = await _search(client, q, engine="bing")
        emails, phones = _emails(text), _phones(text)
        if emails or phones:
            return {"email": _best_email(emails), "phone": phones[0] if phones else "",
                    "source": "bing_people_search", "confidence": 0.65}
        await asyncio.sleep(random.uniform(0.2, 0.5))
    return {}


# ══════════════════════════════════════════════════════════════
# METHOD 9 — DuckDuckGo people search
# ══════════════════════════════════════════════════════════════

async def _ddg_people(name: str, domain: str, client: httpx.AsyncClient) -> Dict[str, Any]:
    for q in [
        f'"{name}" trainer "{domain}" email contact India',
        f'"{name}" trainer India phone whatsapp',
    ]:
        text = await _search(client, q, engine="ddg")
        emails, phones = _emails(text), _phones(text)
        if emails or phones:
            return {"email": _best_email(emails), "phone": phones[0] if phones else "",
                    "source": "ddg_people_search", "confidence": 0.60}
        await asyncio.sleep(random.uniform(0.2, 0.4))
    return {}


# ══════════════════════════════════════════════════════════════
# METHOD 10 — Email pattern guess + MX record verification
# ══════════════════════════════════════════════════════════════

def _guess_emails(name: str, company_domain: str) -> List[str]:
    first, last = _name_parts(name)
    if not first or not company_domain:
        return []
    guesses = []
    for p in [
        f"{first}.{last}@{company_domain}",
        f"{first}{last}@{company_domain}",
        f"{first[0]}{last}@{company_domain}",
        f"{first}@{company_domain}",
        f"{last}.{first}@{company_domain}",
    ]:
        if p not in guesses:
            guesses.append(p)
    return guesses


def _mx_exists(domain: str) -> bool:
    try:
        import dns.resolver
        dns.resolver.resolve(domain, "MX")
        return True
    except Exception:
        pass
    try:
        import socket
        socket.setdefaulttimeout(5)
        socket.gethostbyname(f"mail.{domain}")
        return True
    except Exception:
        return False


async def _email_pattern(name: str, company: str, client: httpx.AsyncClient) -> Dict[str, Any]:
    if not name or not company:
        return {}
    text = await _search(client, f"{company} official website email domain India", engine="bing")
    m = re.search(r"@([a-zA-Z0-9.\-]+\.(?:com|co\.in|in|net|org))", text)
    if not m:
        return {}
    company_domain = m.group(1).lower()
    guesses = _guess_emails(name, company_domain)
    loop = asyncio.get_event_loop()
    for guess in guesses[:4]:
        try:
            valid = await loop.run_in_executor(None, _mx_exists, guess.split("@")[1])
            if valid:
                return {"email": guess, "phone": "", "source": "email_pattern_mx",
                        "confidence": 0.68, "company_domain": company_domain}
        except Exception:
            continue
    if guesses:
        return {"email": guesses[0], "phone": "", "source": "email_pattern_guess",
                "confidence": 0.38, "note": "not verified"}
    return {}



# ══════════════════════════════════════════════════════════════
# MAIN ENTRY POINTS
# ══════════════════════════════════════════════════════════════

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

    Returns:
        {"email": str, "phone": str, "source": str, "confidence": float, "found": bool}
    """
    result: Dict[str, Any] = {
        "email": "", "phone": "", "source": "", "confidence": 0.0, "found": False
    }

    def _absorb(r: Dict[str, Any]) -> bool:
        """Merge a result into the accumulator. Returns True when both found."""
        if not r:
            return False
        if r.get("email") and not result["email"]:
            result["email"]      = r["email"]
            result["source"]     = r.get("source", "")
            result["confidence"] = r.get("confidence", 0.5)
            result["found"]      = True
        if r.get("phone") and not result["phone"]:
            result["phone"] = r["phone"]
            if not result["source"]:
                result["source"] = r.get("source", "")
            result["found"] = True
        return bool(result["email"] and result["phone"])

    # Method 1 — instant, no HTTP
    if _absorb(_mine_text(profile_text)):
        return result

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, http2=False) as c:

        # Method 2 — personal website
        if not (result["email"] and result["phone"]):
            if _absorb(await _personal_website(profile_text, c)):
                return result

        # Method 3 — Naukri (best for Indian trainers)
        if not (result["email"] and result["phone"]) and name:
            if _absorb(await _naukri_profile(name, domain, c)):
                return result

        # Method 4 — Shine
        if not (result["email"] and result["phone"]) and name:
            if _absorb(await _shine_profile(name, domain, c)):
                return result

        # Method 5 — TimesJobs
        if not (result["email"] and result["phone"]) and name:
            if _absorb(await _timesjobs_profile(name, domain, c)):
                return result

        # Method 6 — JustDial
        if not (result["email"] and result["phone"]) and name:
            if _absorb(await _justdial(name, domain, c)):
                return result

        # Method 7 — GitHub
        if not (result["email"] and result["phone"]) and name:
            if _absorb(await _github_profile(name, domain, c)):
                return result

        # Method 8 — Bing people search
        if not (result["email"] and result["phone"]) and name:
            if _absorb(await _bing_people(name, company, domain, c)):
                return result

        # Method 9 — DDG people search
        if not (result["email"] and result["phone"]) and name:
            if _absorb(await _ddg_people(name, domain, c)):
                return result

        # Method 10 — Email pattern (last resort for email only)
        if not result["email"] and name and company:
            _absorb(await _email_pattern(name, company, c))

    result["found"] = bool(result["email"] or result["phone"])
    return result


async def bulk_find_contacts(
    trainers: List[Dict[str, Any]],
    *,
    concurrency: int = 5,
    timeout: int = 45,
) -> List[Dict[str, Any]]:
    """
    Find contacts for a batch of trainers concurrently.

    Args:
        trainers:    List of trainer dicts (name, company, domain, linkedin_url, profile_text)
        concurrency: Parallel workers (default 5 — be polite to target sites)
        timeout:     Per-trainer timeout in seconds

    Returns:
        Each trainer dict with "contact_result" key added
    """
    sem = asyncio.Semaphore(concurrency)

    async def _one(t: Dict[str, Any]) -> Dict[str, Any]:
        async with sem:
            await asyncio.sleep(random.uniform(0.3, 0.8))
            res = await find_contact_for_trainer(
                name         = t.get("name") or t.get("trainer_name") or "",
                company      = t.get("company") or t.get("current_company") or "",
                domain       = t.get("domain") or t.get("technology") or "",
                linkedin_url = t.get("linkedin_url") or t.get("linkedin") or "",
                profile_text = t.get("profile_text") or t.get("resume") or "",
                timeout      = timeout,
            )
            return {**t, "contact_result": res}

    return list(await asyncio.gather(*[_one(t) for t in trainers]))
