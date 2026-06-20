"""
apollo_agent.py — Apollo.io contact search and enrichment for Clahan Technologies.

Flow (credit-safe):
  1. search_apollo()   — search by title/location (FREE, no credits)
  2. filter_best()     — filter to highest-quality matches (FREE, pure Python)
  3. enrich_contact()  — get full name + email + phone (1 CREDIT per person)
  4. find_contacts()   — master function combining all 3 steps

Credit protection:
  - Never enrich more than max_credits at once
  - Only enrich contacts that have BOTH has_email=true AND has_direct_phone="Yes"
  - Skips stale data (>6 months old) to avoid wasted credits
  - Returns credit_used count in every response

Supports two Clahan use cases:
  - TRAINER search: find freelance/corporate trainers for domain matching
  - CLIENT search:  find HR/L&D managers at companies for business development
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

APOLLO_BASE_URL   = "https://api.apollo.io/v1"
APOLLO_TIMEOUT    = 20          # seconds per HTTP call
MAX_CREDITS_HARD  = 50          # absolute hard cap per single call (free plan = 50/month)
FREE_PLAN_MONTHLY = 50          # Apollo free plan monthly limit

# ─── Job title presets ────────────────────────────────────────────────────────

TRAINER_TITLES = [
    "Corporate Trainer",
    "Technical Trainer",
    "Freelance Trainer",
    "IT Trainer",
    "Training Consultant",
    "Subject Matter Expert",
    "Learning Specialist",
    "Soft Skills Trainer",
    "Leadership Trainer",
    "SAP Trainer",
    "Python Trainer",
    "DevOps Trainer",
    "Cloud Trainer",
    "Data Science Trainer",
]

CLIENT_TITLES = [
    "Training Manager",
    "L&D Manager",
    "Learning and Development Manager",
    "HR Manager",
    "Human Resources Manager",
    "Talent Development Manager",
    "L&D Head",
    "Head of Learning",
    "HR Business Partner",
    "People Development Manager",
]

# ─── Helpers ─────────────────────────────────────────────────────────────────

def _api_key() -> str:
    key = os.getenv("APOLLO_API_KEY", "").strip()
    if not key:
        raise ValueError(
            "APOLLO_API_KEY is not set. Add it to your .env file."
        )
    return key


def _is_fresh(refreshed_at: str, max_age_days: int = 180) -> bool:
    """Return True if data was refreshed within max_age_days."""
    if not refreshed_at:
        return True          # unknown age — assume fresh
    try:
        dt = datetime.fromisoformat(refreshed_at.replace("Z", "+00:00")).replace(tzinfo=None)
        return dt >= datetime.utcnow() - timedelta(days=max_age_days)
    except Exception:
        return True


def _safe_phone(phone_numbers: Any) -> str:
    """Extract first raw phone number from Apollo phone_numbers list."""
    if not phone_numbers:
        return ""
    if isinstance(phone_numbers, list) and phone_numbers:
        first = phone_numbers[0]
        if isinstance(first, dict):
            return str(first.get("raw_number") or first.get("sanitized_number") or "")
        return str(first)
    return ""


def _normalise_person(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise a raw Apollo person dict into Clahan's lead schema."""
    org = raw.get("organization") or {}
    return {
        "apollo_id":    raw.get("id", ""),
        "first_name":   raw.get("first_name", ""),
        "last_name":    raw.get("last_name", ""),
        "name":         f"{raw.get('first_name', '')} {raw.get('last_name', '')}".strip(),
        "title":        raw.get("title") or "",
        "company":      org.get("name") or raw.get("organization_name") or "",
        "email":        raw.get("email") or "",
        "phone":        _safe_phone(raw.get("phone_numbers")),
        "linkedin_url": raw.get("linkedin_url") or "",
        "city":         raw.get("city") or "",
        "state":        raw.get("state") or "",
        "country":      raw.get("country") or "",
        "last_refreshed_at": raw.get("last_refreshed_at") or "",
        "has_email":    bool(raw.get("email") or raw.get("has_email")),
        "has_phone":    bool(_safe_phone(raw.get("phone_numbers")) or raw.get("has_direct_phone") == "Yes"),
    }


# ─── Step 1: Search (FREE) ────────────────────────────────────────────────────

async def search_apollo(
    *,
    titles: List[str],
    locations: Optional[List[str]] = None,
    domains: Optional[List[str]] = None,
    keywords: Optional[List[str]] = None,
    page: int = 1,
    per_page: int = 25,
) -> List[Dict[str, Any]]:
    """
    Search Apollo people — FREE, no credits consumed.

    Args:
        titles     : list of job titles to search
        locations  : list of city/country strings e.g. ["Bangalore, India"]
        domains    : list of company domains e.g. ["infosys.com"]
        keywords   : extra keyword filters
        page       : pagination page (1-indexed)
        per_page   : results per page (max 25 on free plan)

    Returns list of raw Apollo person dicts (last_name obfuscated, no email/phone).
    """
    payload: Dict[str, Any] = {
        "api_key":    _api_key(),
        "page":       page,
        "per_page":   min(per_page, 25),
    }

    if titles:
        payload["q_person_title"] = titles
    if locations:
        payload["person_locations"] = locations
    if domains:
        payload["q_organization_domains"] = domains
    if keywords:
        payload["q_keywords"] = " ".join(keywords)

    try:
        async with httpx.AsyncClient(timeout=APOLLO_TIMEOUT) as client:
            response = await client.post(
                f"{APOLLO_BASE_URL}/mixed_people/search",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        people = data.get("people") or []
        logger.info("Apollo search: %d results (page %d)", len(people), page)
        return people

    except httpx.HTTPStatusError as exc:
        logger.error("Apollo search HTTP error %s: %s", exc.response.status_code, exc.response.text[:300])
        raise
    except Exception as exc:
        logger.error("Apollo search failed: %s", exc)
        raise


async def search_apollo_pages(
    *,
    titles: List[str],
    locations: Optional[List[str]] = None,
    domains: Optional[List[str]] = None,
    keywords: Optional[List[str]] = None,
    max_pages: int = 4,
    per_page: int = 25,
) -> List[Dict[str, Any]]:
    """
    Search multiple pages (all FREE).
    max_pages=4 gives up to 100 results at zero cost.
    """
    all_people: List[Dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        people = await search_apollo(
            titles=titles,
            locations=locations,
            domains=domains,
            keywords=keywords,
            page=page,
            per_page=per_page,
        )
        all_people.extend(people)
        if len(people) < per_page:
            break           # no more pages
    logger.info("Apollo search total: %d results across %d pages", len(all_people), max_pages)
    return all_people


# ─── Step 2: Filter best matches (FREE) ──────────────────────────────────────

def filter_best(
    people: List[Dict[str, Any]],
    max_results: int = 25,
    require_phone: bool = True,
    max_age_days: int = 180,
) -> List[Dict[str, Any]]:
    """
    Filter raw Apollo search results to highest-quality candidates.
    Zero cost — pure Python logic.

    Keeps only:
      - has_email = true
      - has_direct_phone = "Yes" (if require_phone=True)
      - has a job title
      - belongs to a real company (has employee count)
      - data refreshed within max_age_days

    Sorts newest-first and returns top max_results.
    """
    qualified: List[Dict[str, Any]] = []

    for p in people:
        # Must have email
        if not p.get("has_email"):
            continue

        # Must have phone (if required)
        if require_phone and p.get("has_direct_phone") != "Yes":
            continue

        # Must have a title
        if not (p.get("title") or "").strip():
            continue

        # Must have a real company
        org = p.get("organization") or {}
        if not (org.get("name") or "").strip():
            continue
        if not org.get("has_employee_count"):
            continue

        # Must have fresh data
        if not _is_fresh(p.get("last_refreshed_at", ""), max_age_days):
            continue

        qualified.append(p)

    # Sort by recency — newest first
    qualified.sort(
        key=lambda x: x.get("last_refreshed_at") or "",
        reverse=True,
    )

    top = qualified[:max_results]
    logger.info(
        "Apollo filter: %d qualified from %d total, returning top %d",
        len(qualified), len(people), len(top),
    )
    return top


# ─── Step 3: Enrich single contact (COSTS 1 CREDIT) ──────────────────────────

async def enrich_contact(person_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch full contact details for one person.
    COSTS 1 APOLLO CREDIT.

    Returns normalised contact dict or None if email not returned.
    """
    payload = {
        "api_key":                _api_key(),
        "id":                     person_id,
        "reveal_personal_emails": False,   # business emails only
        "reveal_phone_number":    True,
    }

    try:
        async with httpx.AsyncClient(timeout=APOLLO_TIMEOUT) as client:
            response = await client.post(
                f"{APOLLO_BASE_URL}/people/match",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        person = data.get("person") or {}

        if not person:
            logger.warning("Apollo enrich: no person returned for id=%s", person_id)
            return None

        contact = _normalise_person(person)

        # If no email came back, credit was spent but useless — log and skip
        if not contact["email"]:
            logger.warning(
                "Apollo enrich: credit used but no email returned for %s (%s)",
                contact.get("name"), person_id,
            )
            return None

        logger.info(
            "Apollo enrich: ✅ %s — %s — %s",
            contact["name"], contact["email"], contact["phone"] or "no phone",
        )
        return contact

    except httpx.HTTPStatusError as exc:
        logger.error("Apollo enrich HTTP error %s: %s", exc.response.status_code, exc.response.text[:300])
        return None
    except Exception as exc:
        logger.error("Apollo enrich failed for %s: %s", person_id, exc)
        return None


# ─── Step 4: Master function ──────────────────────────────────────────────────

async def find_contacts(
    *,
    titles: Optional[List[str]] = None,
    locations: Optional[List[str]] = None,
    domains: Optional[List[str]] = None,
    keywords: Optional[List[str]] = None,
    mode: str = "trainer",
    max_credits: int = 10,
    require_phone: bool = True,
    max_search_pages: int = 4,
) -> Dict[str, Any]:
    """
    Full Apollo pipeline:
      search (free) → filter (free) → enrich (credits).

    Args:
        titles         : job titles to search (defaults to TRAINER_TITLES or CLIENT_TITLES)
        locations      : location filters e.g. ["Bangalore, India", "Mumbai, India"]
        domains        : company domain filters e.g. ["infosys.com"]
        keywords       : extra keyword filters e.g. ["Python", "SAP"]
        mode           : "trainer" or "client" — used for default titles
        max_credits    : max enrichment credits to spend (hard capped at MAX_CREDITS_HARD)
        require_phone  : only enrich contacts with a phone number
        max_search_pages: how many search pages to fetch (each page = 25 results, free)

    Returns:
        {
            contacts      : list of enriched contact dicts
            searched      : total search results fetched (free)
            qualified     : contacts that passed quality filter
            credits_used  : number of enrichment API calls made
            credits_saved : how many were filtered out before spending credits
            errors        : list of any error messages
        }
    """
    # Enforce hard credit cap
    max_credits = min(max_credits, MAX_CREDITS_HARD)

    # Default titles by mode
    if not titles:
        titles = TRAINER_TITLES if mode == "trainer" else CLIENT_TITLES

    # Default location
    if not locations:
        locations = ["India"]

    errors: List[str] = []
    contacts: List[Dict[str, Any]] = []

    # ── Step 1: Search (FREE) ─────────────────────────────────────────────────
    try:
        raw_people = await search_apollo_pages(
            titles=titles,
            locations=locations,
            domains=domains,
            keywords=keywords,
            max_pages=max_search_pages,
            per_page=25,
        )
    except Exception as exc:
        error_msg = f"Apollo search failed: {exc}"
        logger.error(error_msg)
        return {
            "contacts":      [],
            "searched":      0,
            "qualified":     0,
            "credits_used":  0,
            "credits_saved": 0,
            "errors":        [error_msg],
        }

    searched = len(raw_people)

    # ── Step 2: Filter (FREE) ─────────────────────────────────────────────────
    best = filter_best(
        raw_people,
        max_results=max_credits,
        require_phone=require_phone,
    )
    qualified = len(best)
    credits_saved = searched - qualified

    # ── Step 3: Enrich (COSTS CREDITS) ───────────────────────────────────────
    credits_used = 0
    for person in best:
        person_id = person.get("id", "")
        if not person_id:
            continue

        contact = await enrich_contact(person_id)
        credits_used += 1           # count the API call regardless of result

        if contact:
            contacts.append(contact)

    logger.info(
        "Apollo find_contacts: mode=%s searched=%d qualified=%d credits_used=%d contacts=%d",
        mode, searched, qualified, credits_used, len(contacts),
    )

    return {
        "contacts":      contacts,
        "searched":      searched,
        "qualified":     qualified,
        "credits_used":  credits_used,
        "credits_saved": credits_saved,
        "errors":        errors,
    }


# ─── Convert Apollo contact → Clahan lead document ───────────────────────────

def apollo_contact_to_lead(
    contact: Dict[str, Any],
    mode: str = "trainer",
    domain_keyword: str = "",
) -> Dict[str, Any]:
    """
    Convert an enriched Apollo contact dict into a Clahan lead document
    compatible with /trainer-profile-leads and /client-leads collections.
    """
    import uuid
    from datetime import timezone

    name  = contact.get("name") or f"{contact.get('first_name','')} {contact.get('last_name','')}".strip()
    title = contact.get("title") or ""
    company = contact.get("company") or ""
    city    = contact.get("city") or contact.get("state") or ""
    country = contact.get("country") or "India"
    location_str = ", ".join(filter(None, [city, country]))
    email   = contact.get("email") or ""
    phone   = contact.get("phone") or ""
    linkedin = contact.get("linkedin_url") or ""

    headline = f"{title} at {company}" if title and company else title or company

    if mode == "trainer":
        return {
            "lead_id":            str(uuid.uuid4()),
            "source":             "apollo",
            "status":             "new",
            "trainer_name":       name,
            "headline":           headline,
            "domain":             domain_keyword or "General",
            "profile_text":       f"{name} — {headline}. Location: {location_str}.",
            "contact_email":      email,
            "contact_phone":      phone,
            "source_url":         linkedin,
            "company_name":       company,
            "location":           location_str,
            "confidence":         0.92 if email and phone else (0.80 if email else 0.50),
            "verification_tier":  "apollo_enriched",
            "verification_status": "verified" if email else "unverified",
            "verification_source": f"Apollo.io — {title} at {company}",
            "apollo_id":          contact.get("apollo_id") or "",
            "created_at":         datetime.now(timezone.utc),
        }
    else:
        return {
            "lead_id":       str(uuid.uuid4()),
            "source":        "apollo",
            "status":        "new",
            "contact_name":  name,
            "company_name":  company,
            "domain":        domain_keyword or "General",
            "post_text":     f"{name} — {headline}. Location: {location_str}.",
            "contact_email": email,
            "contact_phone": phone,
            "source_url":    linkedin,
            "location":      location_str,
            "confidence":    0.92 if email and phone else (0.80 if email else 0.50),
            "apollo_id":     contact.get("apollo_id") or "",
            "created_at":    datetime.now(timezone.utc),
            "draft": {
                "subject": f"Training Partnership Opportunity — Clahan Technologies",
                "body": (
                    f"Dear {name},\n\n"
                    "I am reaching out from Clahan Technologies, a training consultancy specialising in "
                    "corporate learning and development programmes.\n\n"
                    "We work with leading organisations across India to provide expert trainers for "
                    "technology and professional skills training. If you are looking for training resources "
                    "for your team, we would love to connect and understand your requirements.\n\n"
                    "Please feel free to reach out and we will be happy to share relevant trainer profiles.\n\n"
                    "Best Regards,\nRecruitment Team\nClahan Technologies"
                ),
            },
        }


# ─── Credit tracker (simple in-memory for free plan awareness) ───────────────

class CreditTracker:
    """
    Simple in-memory credit usage tracker.
    Resets at start of each month.
    For production, persist this to MongoDB.
    """

    def __init__(self):
        self._used: int = 0
        self._month: int = datetime.utcnow().month

    def _check_month_rollover(self):
        current_month = datetime.utcnow().month
        if current_month != self._month:
            self._used = 0
            self._month = current_month

    def record(self, count: int = 1):
        self._check_month_rollover()
        self._used += count

    @property
    def used(self) -> int:
        self._check_month_rollover()
        return self._used

    @property
    def remaining(self) -> int:
        return max(0, FREE_PLAN_MONTHLY - self.used)

    def can_spend(self, amount: int) -> bool:
        return self.remaining >= amount

    def status(self) -> Dict[str, int]:
        return {
            "used_this_month":      self.used,
            "remaining_this_month": self.remaining,
            "monthly_limit":        FREE_PLAN_MONTHLY,
        }


# Singleton tracker — import and use this across the app
credit_tracker = CreditTracker()
