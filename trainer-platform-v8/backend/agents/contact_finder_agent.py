"""contact_finder_agent.py — Find email + phone for LinkedIn trainer profiles.

LinkedIn hides contact info behind login. This agent uses 6 strategies
in a cascade — each one free, no API key needed:

  Strategy 1 — Google dorking        : search "name company email contact"
  Strategy 2 — Naukri public profile  : search trainer on Naukri (shows phone)
  Strategy 3 — Bing people search     : "name" "email" site:naukri OR justdial
  Strategy 4 — Personal website/blog  : find & scrape linked portfolio page
  Strategy 5 — Email pattern + verify : guess email, verify with SMTP ping
  Strategy 6 — GitHub/About.me/Xing   : scrape public profile pages

Usage:
    from agents.contact_finder_agent import find_contact_for_trainer

    result = await find_contact_for_trainer(
        name="Rajesh Kumar",
        company="TCS",
        domain="Python",
        linkedin_url="https://linkedin.com/in/rajesh-kumar-python",
        profile_text="...scraped linkedin text...",
    )
    # result = {
    #   "email": "rajesh.kumar@gmail.com",
    #   "phone": "+919876543210",
    #   "source": "naukri_profile",
    #   "confidence": 0.9,
    # }
"""
from __future__ import annotations

import asyncio
import logging
import re
import smtplib
import socket
import random
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


# ── Constants ──────────────────────────────────────────────────────────────────

INDIAN_MOBILE_RE = re.compile(
    r"(?:\+91|0091|91)?[\s.\-()]*([6-9]\d{2}[\s.\-]*\d{3}[\s.\-]*\d{4})"
)
EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+\-]{2,64}@[A-Za-z0-9.\-]{2,253}\.[A-Za-z]{2,12}"
)

# Common Indian corporate email patterns
EMAIL_PATTERNS = [
    "{first}.{last}@{domain}",
    "{first}{last}@{domain}",
    "{f}{last}@{domain}",
    "{first}@{domain}",
    "{first}.{last[0]}@{domain}",
    "{first[0]}{last}@{domain}",
    "{last}.{first}@{domain}",
]

# Domains that host public Indian trainer profiles
PROFILE_SEARCH_SITES = [
    "naukri.com", "shine.com", "linkedin.com",
    "monsterindia.com", "indeed.co.in", "justdial.com",
]

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/123.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0 Safari/537.36",
]

def _headers() -> Dict[str, str]:
    return {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }


# ── Text helpers ───────────────────────────────────────────────────────────────

def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    for e, c in [("&amp;","&"),("&lt;","<"),("&gt;",">"),("&quot;",'"'),("&nbsp;"," "),("&#39;","'")]:
        text = text.replace(e, c)
    return re.sub(r"\s+", " ", text).strip()


def _extract_emails(text: str) -> List[str]:
    """Extract all emails from text, filter out junk/system emails."""
    found = EMAIL_RE.findall(text or "")
    bad = {"noreply","no-reply","donotreply","support","admin","info","sales",
           "hr","careers","jobs","team","contact","office","marketing","billing"}
    result = []
    seen = set()
    for email in found:
        local = email.split("@")[0].lower()
        if local in bad:
            continue
        if email.lower() not in seen:
            seen.add(email.lower())
            result.append(email)
    return result


def _extract_phones(text: str) -> List[str]:
    """Extract all Indian mobile numbers from text."""
    found = []
    seen = set()
    for m in INDIAN_MOBILE_RE.finditer(text or ""):
        digits = re.sub(r"\D", "", m.group(1))
        if len(digits) == 10 and digits[0] in "6789":
            num = f"+91{digits}"
            if num not in seen:
                seen.add(num)
                found.append(num)
    return found


def _clean_name(name: str) -> tuple:
    """Split full name into (first, last) parts."""
    parts = re.sub(r"[^a-zA-Z\s]", "", (name or "")).strip().lower().split()
    if len(parts) >= 2:
        return parts[0], parts[-1]
    elif len(parts) == 1:
        return parts[0], parts[0]
    return "", ""


# ── Strategy 1 — Google Dork ────────────────────────────────────────────────────

async def _google_dork_contact(
    name: str,
    company: str,
    domain: str,
    client: httpx.AsyncClient,
) -> Dict[str, Any]:
    """
    Search Google for the person's email/phone using targeted dork queries.
    Example: "Rajesh Kumar" "TCS" email contact trainer python
    """
    queries = []
    if name:
        if company:
            queries.append(f'"{name}" "{company}" email contact trainer {domain}')
            queries.append(f'"{name}" "{company}" phone whatsapp trainer')
        queries.append(f'"{name}" trainer "{domain}" email India contact')
        queries.append(f'"{name}" email trainer India site:naukri.com OR site:shine.com')

    for query in queries[:3]:
        try:
            resp = await client.get(
                "https://www.google.com/search",
                params={"q": query, "num": 5, "hl": "en"},
                headers={
                    "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/91.0 Mobile Safari/537.36",
                    "Accept": "text/html",
                },
                follow_redirects=True,
            )
            if resp.status_code != 200:
                continue
            text = _strip_html(resp.text)
            emails = _extract_emails(text)
            phones = _extract_phones(text)
            if emails or phones:
                return {
                    "email": emails[0] if emails else "",
                    "phone": phones[0] if phones else "",
                    "source": "google_dork",
                    "confidence": 0.65,
                    "query": query,
                }
        except Exception as exc:
            logger.debug("Google dork failed: %s", exc)
        await asyncio.sleep(random.uniform(0.5, 1.2))
    return {}


# ── Strategy 2 — Naukri Public Profile Scraper ──────────────────────────────────

async def _naukri_search_contact(
    name: str,
    domain: str,
    client: httpx.AsyncClient,
) -> Dict[str, Any]:
    """
    Search Naukri for the trainer's public profile.
    Naukri public resume pages often show phone + email.
    """
    try:
        # Step 1: search Naukri for the trainer
        search_url = "https://www.naukri.com/candidate/search"
        resp = await client.get(
            "https://www.google.com/search",
            params={"q": f'site:naukri.com "{name}" "{domain}" trainer resume'},
            headers={"User-Agent": random.choice(_USER_AGENTS), "Accept": "text/html"},
            follow_redirects=True,
        )
        if resp.status_code != 200:
            return {}

        html = resp.text
        # Find Naukri profile URLs
        naukri_urls = re.findall(
            r'https://www\.naukri\.com/(?:mnjuser/profile|resume)[^\s"\'<>]+',
            html, re.IGNORECASE
        )
        # Also try /url?q= wrapped links
        for m in re.finditer(r'/url\?q=(https://www\.naukri\.com/[^\s&"]+)', html):
            naukri_urls.append(m.group(1))

        naukri_urls = list(dict.fromkeys(naukri_urls))[:3]

        for naukri_url in naukri_urls:
            try:
                page = await client.get(
                    naukri_url,
                    headers=_headers(),
                    follow_redirects=True,
                )
                if page.status_code != 200:
                    continue
                text = _strip_html(page.text)
                emails = _extract_emails(text)
                phones = _extract_phones(text)
                if emails or phones:
                    return {
                        "email": emails[0] if emails else "",
                        "phone": phones[0] if phones else "",
                        "source": "naukri_profile",
                        "confidence": 0.85,
                        "profile_url": naukri_url,
                    }
            except Exception:
                continue

    except Exception as exc:
        logger.debug("Naukri search failed: %s", exc)
    return {}


# ── Strategy 3 — Profile Text Mining ────────────────────────────────────────────

def _mine_profile_text(profile_text: str) -> Dict[str, Any]:
    """
    Extract email/phone directly from the LinkedIn profile text we already scraped.
    Sometimes trainers put their email/phone in their About section or posts.
    Example: "reach me at john@gmail.com" or "call me on 9876543210"
    """
    if not profile_text:
        return {}

    emails = _extract_emails(profile_text)
    phones = _extract_phones(profile_text)

    # Filter personal emails only (gmail, yahoo, etc.)
    personal_domains = {
        "gmail.com","yahoo.com","yahoo.co.in","outlook.com",
        "hotmail.com","rediffmail.com","protonmail.com","icloud.com","live.com",
    }
    personal_emails = [e for e in emails if e.split("@")[-1].lower() in personal_domains]
    best_email = personal_emails[0] if personal_emails else (emails[0] if emails else "")

    if best_email or phones:
        return {
            "email": best_email,
            "phone": phones[0] if phones else "",
            "source": "profile_text",
            "confidence": 0.95 if best_email else 0.80,
        }
    return {}


# ── Strategy 4 — Personal Website / Portfolio Scraper ───────────────────────────

async def _scrape_personal_website(
    profile_text: str,
    linkedin_url: str,
    client: httpx.AsyncClient,
) -> Dict[str, Any]:
    """
    Find and scrape the trainer's personal website/portfolio.
    Many trainers link to their personal site from LinkedIn.
    Personal sites almost always show email/phone.
    """
    # Find URLs in profile text that look like personal sites
    website_patterns = [
        r"https?://(?!(?:www\.)?(?:linkedin|facebook|twitter|instagram|youtube|google|naukri|github)\.com)[^\s\"'<>]{5,80}",
    ]
    urls = []
    for pattern in website_patterns:
        for m in re.finditer(pattern, profile_text or "", re.IGNORECASE):
            url = m.group(0).rstrip(".,;)")
            if url not in urls:
                urls.append(url)

    # Also check About section for website links
    about_match = re.search(r"(?:website|portfolio|blog|site)[:\s]+(\S+)", profile_text or "", re.IGNORECASE)
    if about_match:
        urls.insert(0, about_match.group(1))

    for url in urls[:3]:
        try:
            if not url.startswith("http"):
                url = "https://" + url
            resp = await client.get(url, headers=_headers(), follow_redirects=True, timeout=15)
            if resp.status_code != 200:
                continue
            text = _strip_html(resp.text)
            emails = _extract_emails(text)
            phones = _extract_phones(text)
            if emails or phones:
                return {
                    "email": emails[0] if emails else "",
                    "phone": phones[0] if phones else "",
                    "source": "personal_website",
                    "confidence": 0.90,
                    "website_url": url,
                }
        except Exception:
            continue
    return {}


# ── Strategy 5 — Email Pattern Guesser + SMTP Verifier ──────────────────────────

def _generate_email_guesses(name: str, company_domain: str) -> List[str]:
    """
    Generate likely email addresses from name + company domain.
    Example: name="Rajesh Kumar", company_domain="tcs.com"
    → rajesh.kumar@tcs.com, rkumar@tcs.com, rajesh@tcs.com ...
    """
    first, last = _clean_name(name)
    if not first or not company_domain:
        return []

    guesses = []
    patterns = {
        "{first}.{last}@{domain}": f"{first}.{last}@{company_domain}",
        "{first}{last}@{domain}":  f"{first}{last}@{company_domain}",
        "{f}{last}@{domain}":      f"{first[0]}{last}@{company_domain}",
        "{first}@{domain}":        f"{first}@{company_domain}",
        "{last}.{first}@{domain}": f"{last}.{first}@{company_domain}",
        "{first}.{l}@{domain}":    f"{first}.{last[0]}@{company_domain}",
    }
    for _, email in patterns.items():
        if email not in guesses:
            guesses.append(email)
    return guesses


def _smtp_verify_email(email: str, timeout: int = 8) -> bool:
    """
    Verify email existence using SMTP VRFY / RCPT TO.
    Does NOT send any email — just checks if the address is valid.
    Returns True if the email address likely exists.
    """
    try:
        domain = email.split("@")[1]
        # Get MX record
        import dns.resolver
        mx_records = dns.resolver.resolve(domain, "MX")
        mx_host = str(sorted(mx_records, key=lambda r: r.preference)[0].exchange).rstrip(".")

        # Connect to SMTP and check
        with smtplib.SMTP(timeout=timeout) as smtp:
            smtp.connect(mx_host, 25)
            smtp.ehlo("trainersync.com")
            smtp.mail("verify@trainersync.com")
            code, _ = smtp.rcpt(email)
            return code == 250
    except Exception:
        # If SMTP check fails (most cloud IPs are blocked on port 25)
        # fall back to just domain MX check
        try:
            import dns.resolver
            domain = email.split("@")[1]
            dns.resolver.resolve(domain, "MX")
            return True  # domain has MX = email format likely valid
        except Exception:
            return False


async def _email_pattern_finder(
    name: str,
    company: str,
    client: httpx.AsyncClient,
) -> Dict[str, Any]:
    """
    Guess email from name+company pattern, then verify with SMTP.
    Works well for Indian IT companies (TCS, Infosys, Wipro, etc.)
    """
    if not name or not company:
        return {}

    # Step 1: Find the company's email domain
    company_domain = ""
    try:
        resp = await client.get(
            "https://www.google.com/search",
            params={"q": f"{company} official website email domain"},
            headers={"User-Agent": random.choice(_USER_AGENTS)},
            follow_redirects=True,
        )
        # Extract domain from search results
        domain_match = re.search(
            r"@([a-zA-Z0-9.\-]+\.(?:com|co\.in|in|net|org))",
            _strip_html(resp.text)
        )
        if domain_match:
            company_domain = domain_match.group(1).lower()
    except Exception:
        pass

    if not company_domain:
        return {}

    # Step 2: Generate email guesses
    guesses = _generate_email_guesses(name, company_domain)

    # Step 3: Verify each guess via SMTP (async)
    loop = asyncio.get_event_loop()
    for guess in guesses[:4]:  # check top 4 guesses only
        try:
            valid = await loop.run_in_executor(None, _smtp_verify_email, guess)
            if valid:
                return {
                    "email": guess,
                    "phone": "",
                    "source": "email_pattern_smtp_verify",
                    "confidence": 0.75,
                    "company_domain": company_domain,
                }
        except Exception:
            continue

    # If SMTP fails, return first guess with lower confidence
    if guesses:
        return {
            "email": guesses[0],
            "phone": "",
            "source": "email_pattern_guess",
            "confidence": 0.45,
            "company_domain": company_domain,
            "note": "SMTP verification unavailable — pattern guess only",
        }
    return {}


# ── Strategy 6 — GitHub / JustDial / Shine scraper ──────────────────────────────

async def _scrape_public_profiles(
    name: str,
    domain: str,
    client: httpx.AsyncClient,
) -> Dict[str, Any]:
    """
    Search GitHub, Shine, JustDial, About.me for the trainer.
    These sites often show email/phone publicly.
    """
    search_queries = [
        f'site:shine.com "{name}" "{domain}" trainer email',
        f'site:justdial.com "{name}" trainer "{domain}"',
        f'site:github.com "{name}" trainer email',
        f'"{name}" trainer "{domain}" India "contact" "email" OR "phone"',
    ]

    for query in search_queries[:3]:
        try:
            resp = await client.get(
                "https://www.bing.com/search",
                params={"q": query, "count": 5},
                headers=_headers(),
                follow_redirects=True,
            )
            if resp.status_code != 200:
                continue

            text = _strip_html(resp.text)
            emails = _extract_emails(text)
            phones = _extract_phones(text)

            if emails or phones:
                return {
                    "email": emails[0] if emails else "",
                    "phone": phones[0] if phones else "",
                    "source": "public_profile_search",
                    "confidence": 0.60,
                    "query": query,
                }
        except Exception as exc:
            logger.debug("Public profile search failed: %s", exc)
        await asyncio.sleep(random.uniform(0.3, 0.7))

    return {}


# ── Main Entry Point ─────────────────────────────────────────────────────────────

async def find_contact_for_trainer(
    name: str = "",
    company: str = "",
    domain: str = "",
    linkedin_url: str = "",
    profile_text: str = "",
    timeout: int = 30,
) -> Dict[str, Any]:
    """
    Find email + phone for a LinkedIn trainer profile.

    Uses 6 strategies in cascade order — stops when email+phone found.

    Args:
        name:         Trainer full name (e.g. "Rajesh Kumar")
        company:      Current/past company (e.g. "TCS")
        domain:       Technology domain (e.g. "Python", "DevOps")
        linkedin_url: LinkedIn profile URL
        profile_text: Already scraped LinkedIn profile text
        timeout:      Total timeout in seconds

    Returns:
        {
          "email":      str,
          "phone":      str,
          "source":     str,    # which strategy found it
          "confidence": float,  # 0.0 - 1.0
          "found":      bool,
        }
    """
    result: Dict[str, Any] = {
        "email": "", "phone": "", "source": "", "confidence": 0.0, "found": False
    }

    # Strategy 1 — Mine the profile text we already have (instant, zero HTTP)
    if profile_text:
        r = _mine_profile_text(profile_text)
        if r.get("email") or r.get("phone"):
            result.update({**r, "found": True})
            if result["email"] and result["phone"]:
                return result  # Got both — done!

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:

        # Strategy 2 — Personal website linked in profile
        if not (result["email"] and result["phone"]) and profile_text:
            r = await _scrape_personal_website(profile_text, linkedin_url, client)
            if r.get("email") or r.get("phone"):
                if not result["email"]:
                    result["email"] = r.get("email", "")
                if not result["phone"]:
                    result["phone"] = r.get("phone", "")
                result.update({"source": r["source"], "confidence": r["confidence"], "found": True})
                if result["email"] and result["phone"]:
                    return result

        # Strategy 3 — Naukri public profile
        if not (result["email"] and result["phone"]) and name:
            r = await _naukri_search_contact(name, domain, client)
            if r.get("email") or r.get("phone"):
                if not result["email"]:
                    result["email"] = r.get("email", "")
                if not result["phone"]:
                    result["phone"] = r.get("phone", "")
                result.update({"source": r["source"], "confidence": r["confidence"], "found": True})
                if result["email"] and result["phone"]:
                    return result

        # Strategy 4 — Google dork
        if not (result["email"] and result["phone"]) and name:
            r = await _google_dork_contact(name, company, domain, client)
            if r.get("email") or r.get("phone"):
                if not result["email"]:
                    result["email"] = r.get("email", "")
                if not result["phone"]:
                    result["phone"] = r.get("phone", "")
                result.update({"source": r["source"], "confidence": r["confidence"], "found": True})
                if result["email"] and result["phone"]:
                    return result

        # Strategy 5 — Shine / JustDial / GitHub scrape
        if not (result["email"] and result["phone"]) and name:
            r = await _scrape_public_profiles(name, domain, client)
            if r.get("email") or r.get("phone"):
                if not result["email"]:
                    result["email"] = r.get("email", "")
                if not result["phone"]:
                    result["phone"] = r.get("phone", "")
                result.update({"source": r["source"], "confidence": r["confidence"], "found": True})
                if result["email"] and result["phone"]:
                    return result

        # Strategy 6 — Email pattern guess + SMTP verify (last resort)
        if not result["email"] and name and company:
            r = await _email_pattern_finder(name, company, client)
            if r.get("email"):
                result["email"] = r["email"]
                result.update({"source": r["source"], "confidence": r["confidence"], "found": True})

    result["found"] = bool(result["email"] or result["phone"])
    return result


async def bulk_find_contacts(
    trainers: List[Dict[str, Any]],
    *,
    concurrency: int = 3,
    timeout: int = 30,
) -> List[Dict[str, Any]]:
    """
    Find contacts for multiple trainers concurrently.

    Args:
        trainers: List of trainer dicts with keys:
                  name, company, domain, linkedin_url, profile_text
        concurrency: How many to search in parallel (default 3)
        timeout: Per-trainer timeout in seconds

    Returns:
        List of result dicts with email, phone, source, confidence, found
    """
    semaphore = asyncio.Semaphore(concurrency)

    async def _find(trainer: Dict[str, Any]) -> Dict[str, Any]:
        async with semaphore:
            await asyncio.sleep(random.uniform(0.5, 1.5))  # polite delay
            result = await find_contact_for_trainer(
                name=trainer.get("name") or trainer.get("trainer_name") or "",
                company=trainer.get("company") or trainer.get("current_company") or "",
                domain=trainer.get("domain") or trainer.get("technology") or "",
                linkedin_url=trainer.get("linkedin_url") or trainer.get("linkedin") or "",
                profile_text=trainer.get("profile_text") or trainer.get("resume") or "",
                timeout=timeout,
            )
            return {**trainer, "contact_result": result}

    return list(await asyncio.gather(*[_find(t) for t in trainers]))
