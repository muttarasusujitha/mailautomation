"""Contact finder — cascades through 6 strategies to find email/phone."""
import asyncio
import logging
import random
import re
import smtplib
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.database import get_db
from app.clients.tavily import get_client

router = APIRouter()
logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]{2,64}@[A-Za-z0-9.\-]{2,253}\.[A-Za-z]{2,12}")
PHONE_RE = re.compile(r"(?:\+91|0091|91)?[\s.\-()]*([6-9]\d{2}[\s.\-]*\d{3}[\s.\-]*\d{4})")

_UA = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/123.0 Safari/537.36",
]

BAD_LOCALS = {"noreply", "no-reply", "donotreply", "support", "admin", "info", "sales", "hr", "careers", "jobs"}


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    for e, c in [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&nbsp;", " ")]:
        text = text.replace(e, c)
    return re.sub(r"\s+", " ", text).strip()


def _emails(text: str) -> List[str]:
    found = EMAIL_RE.findall(text or "")
    seen: set = set()
    out = []
    for e in found:
        local = e.split("@")[0].lower()
        if local in BAD_LOCALS or e.lower() in seen:
            continue
        seen.add(e.lower())
        out.append(e)
    return out


def _phones(text: str) -> List[str]:
    found = []
    seen: set = set()
    for m in PHONE_RE.finditer(text or ""):
        d = re.sub(r"\D", "", m.group(1))
        if len(d) == 10 and d[0] in "6789":
            n = f"+91{d}"
            if n not in seen:
                seen.add(n)
                found.append(n)
    return found


def _mine_text(profile_text: str) -> Dict[str, Any]:
    emails = _emails(profile_text)
    phones = _phones(profile_text)
    personal = [e for e in emails if e.split("@")[-1].lower() in {
        "gmail.com", "yahoo.com", "yahoo.co.in", "outlook.com", "hotmail.com", "rediffmail.com",
    }]
    best = personal[0] if personal else (emails[0] if emails else "")
    if best or phones:
        return {"email": best, "phone": phones[0] if phones else "", "source": "profile_text", "confidence": 0.95 if best else 0.80}
    return {}


async def _google_search(name: str, company: str, domain: str, client: httpx.AsyncClient) -> Dict[str, Any]:
    queries = []
    if name and company:
        queries.append(f'"{name}" "{company}" email contact trainer {domain}')
    if name:
        queries.append(f'"{name}" trainer "{domain}" email India contact')
    for q in queries[:2]:
        try:
            resp = await client.get(
                "https://www.google.com/search",
                params={"q": q, "num": 5, "hl": "en"},
                headers={"User-Agent": random.choice(_UA), "Accept": "text/html"},
                follow_redirects=True,
            )
            if resp.status_code != 200:
                continue
            text = _strip_html(resp.text)
            es, ps = _emails(text), _phones(text)
            if es or ps:
                return {"email": es[0] if es else "", "phone": ps[0] if ps else "", "source": "google_dork", "confidence": 0.65}
        except Exception as exc:
            logger.debug("Google search failed: %s", exc)
        await asyncio.sleep(random.uniform(0.5, 1.2))
    return {}


async def _bing_search(name: str, domain: str, client: httpx.AsyncClient) -> Dict[str, Any]:
    queries = [
        f'site:shine.com "{name}" "{domain}" trainer email',
        f'"{name}" trainer "{domain}" India "contact" "email" OR "phone"',
    ]
    for q in queries[:2]:
        try:
            resp = await client.get(
                "https://www.bing.com/search", params={"q": q, "count": 5},
                headers={"User-Agent": random.choice(_UA), "Accept": "text/html"},
                follow_redirects=True,
            )
            if resp.status_code != 200:
                continue
            text = _strip_html(resp.text)
            es, ps = _emails(text), _phones(text)
            if es or ps:
                return {"email": es[0] if es else "", "phone": ps[0] if ps else "", "source": "bing_search", "confidence": 0.60}
        except Exception as exc:
            logger.debug("Bing search failed: %s", exc)
        await asyncio.sleep(random.uniform(0.3, 0.7))
    return {}


class FindContactRequest(BaseModel):
    name: str = ""
    company: str = ""
    domain: str = ""
    linkedin_url: str = ""
    profile_text: str = ""
    timeout: int = 30


class BulkFindRequest(BaseModel):
    trainers: List[Dict[str, Any]]
    concurrency: int = 3
    timeout: int = 30


@router.post("/find")
async def find_contact(payload: FindContactRequest):
    result: Dict[str, Any] = {"email": "", "phone": "", "source": "", "confidence": 0.0, "found": False}

    if payload.profile_text:
        r = _mine_text(payload.profile_text)
        if r:
            result.update({**r, "found": True})
            if result["email"] and result["phone"]:
                return result

    async with httpx.AsyncClient(timeout=payload.timeout, follow_redirects=True) as client:
        if not (result["email"] and result["phone"]) and payload.name:
            r = await _google_search(payload.name, payload.company, payload.domain, client)
            if r:
                if not result["email"]:
                    result["email"] = r.get("email", "")
                if not result["phone"]:
                    result["phone"] = r.get("phone", "")
                result.update({"source": r["source"], "confidence": r["confidence"], "found": True})
                if result["email"] and result["phone"]:
                    return result

        if not (result["email"] and result["phone"]) and payload.name:
            r = await _bing_search(payload.name, payload.domain, client)
            if r:
                if not result["email"]:
                    result["email"] = r.get("email", "")
                if not result["phone"]:
                    result["phone"] = r.get("phone", "")
                result.update({"source": r["source"], "confidence": r["confidence"], "found": True})

    result["found"] = bool(result["email"] or result["phone"])
    return result


@router.post("/find/bulk")
async def bulk_find_contacts(payload: BulkFindRequest):
    sem = asyncio.Semaphore(payload.concurrency)

    async def _find(t: Dict[str, Any]) -> Dict[str, Any]:
        async with sem:
            await asyncio.sleep(random.uniform(0.5, 1.5))
            req = FindContactRequest(
                name=t.get("name") or t.get("trainer_name") or "",
                company=t.get("company") or "",
                domain=t.get("domain") or t.get("technology") or "",
                linkedin_url=t.get("linkedin_url") or t.get("linkedin") or "",
                profile_text=t.get("profile_text") or t.get("resume") or "",
                timeout=payload.timeout,
            )
            result = await find_contact(req)
            return {**t, "contact_result": result}

    results = await asyncio.gather(*[_find(t) for t in payload.trainers])
    return {"results": list(results), "total": len(results)}



class FindAndSendRequest(BaseModel):
    name: str = ""
    company: str = ""
    domain: str = ""
    linkedin_url: str = ""
    profile_text: str = ""
    subject: str = ""
    body: str = ""
    smtp_config: Optional[Dict[str, Any]] = None


class LinkedInSearchRequest(BaseModel):
    query: str
    limit: int = 10
    params: Optional[Dict[str, Any]] = None


@router.post("/linkedin/search")
async def linkedin_search(payload: LinkedInSearchRequest):
    """Proxy endpoint to perform LinkedIn-style searches via Tavily.

    Uses a thread executor to call the synchronous Tavily client without
    blocking the event loop.
    """
    try:
        tavily = get_client()
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(None, lambda: tavily.search_linkedin(payload.query, limit=payload.limit, **(payload.params or {})))
        return {"success": True, "results": results}
    except Exception as exc:
        logger.exception("Tavily /linkedin/search failed: %s", exc)
        return {"success": False, "error": str(exc)}


@router.post("/find-and-send-mail")
async def find_and_send_mail(payload: FindAndSendRequest):
    """Find contact details then immediately send an outreach email."""
    import httpx as _httpx
    find_req = FindContactRequest(
        name=payload.name, company=payload.company, domain=payload.domain,
        linkedin_url=payload.linkedin_url, profile_text=payload.profile_text,
    )
    contact = await find_contact(find_req)
    to_email = contact.get("email", "")
    if not to_email:
        return {"success": False, "found": False, "reason": "No email found", "contact": contact}

    subject = payload.subject or f"Training Opportunity — {payload.domain or 'Your Domain'}"
    body = payload.body or (
        f"Dear {payload.name or 'Trainer'},\n\nWe have a training requirement matching your profile.\n"
        "Please revert if interested.\n\nRegards,\nTrainerSync Team"
    )
    try:
        async with _httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                "https://email-service:8002/api/v1/email/send",
                json={"to": to_email, "subject": subject, "body": body, "smtp_config": payload.smtp_config},
            )
        email_sent = r.status_code < 400
    except Exception as exc:
        email_sent = False
        logger.warning("find-and-send-mail email failed: %s", exc)

    return {"success": email_sent, "found": True, "email": to_email,
            "contact": contact, "email_sent": email_sent}
