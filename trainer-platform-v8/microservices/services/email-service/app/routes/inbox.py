"""Gmail inbox polling and inbound client requirement processing."""
import asyncio
import html
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.database import get_db
from app.gmail_client import check_imap_replies, send_email_async

router = APIRouter()
logger = logging.getLogger(__name__)

CORE_API_URL = "http://core-api:8001"
TRAINER_SERVICE_URL = "http://trainer-service:8004"

FINAL_CLIENT_STATUSES = {"auto_sent", "sent", "approved", "rejected", "spam"}
TRAINING_SIGNALS = (
    "trainer",
    "training",
    "requirement",
    "workshop",
    "profiles",
    "profile",
    "commercials",
    "duration",
    "audience level",
    "mode",
)
KNOWN_TECHNOLOGIES = (
    "DevOps",
    "AWS",
    "Azure",
    "GCP",
    "Kubernetes",
    "Docker",
    "Python",
    "Java",
    "React",
    "Angular",
    "Salesforce",
    "SAP",
    "ServiceNow",
    "Power BI",
    "Tableau",
    "Machine Learning",
    "Generative AI",
    "Gen AI",
)
NON_TECH_CANDIDATE_WORDS = {
    "availability",
    "budget",
    "commercials",
    "date",
    "dates",
    "duration",
    "hour",
    "hours",
    "mode",
    "next",
    "participants",
    "profile",
    "profiles",
    "rate",
    "resume",
    "schedule",
    "slot",
    "slots",
    "today",
    "tomorrow",
    "week",
}
AUTOMATED_SENDER_LOCALS = {
    "bounce",
    "do-not-reply",
    "donotreply",
    "mail",
    "mailer-daemon",
    "newsletter",
    "no-reply",
    "noreply",
    "notification",
    "notifications",
    "onlinecourses",
    "postmaster",
    "recommendationnc",
    "updates",
    "updates-noreply",
}
BULK_SENDER_DOMAINS = {
    "alison.com",
    "github.com",
    "linkedin.com",
    "naukri.com",
    "nptel.iitm.ac.in",
    "reliancedigital.in",
}
NON_CLIENT_BULK_SIGNALS = (
    "unsubscribe",
    "manage your preferences",
    "view in browser",
    "exclusive deals",
    "newsletter",
    "promotion",
    "promotional",
    "sale",
    "offer",
    "password reset",
    "otp",
    "verification code",
    "reacted to this",
    "commented a post",
    "join our whatsapp channel",
)
DIRECT_REQUEST_PATTERNS = (
    r"\b(?:need|require|required|looking\s+for|seeking|want|hire)\b.{0,90}\b(?:trainer|training|workshop|instructor|profiles?|resource|consultant)\b",
    r"\b(?:trainer|training|workshop|instructor)\b.{0,90}\b(?:need|required|requirement|profiles?|commercials?|available|availability|share|send|provide)\b",
    r"\brequirement\s+(?:for|of)\b.{0,90}\b(?:trainer|training|workshop|instructor|facilitator)\b",
    r"\bplease\s+(?:share|send|provide)\b.{0,90}\b(?:trainer|profiles?|resume|commercials?|availability)\b",
    r"\b(?:corporate|classroom|online|offline|virtual|onsite|on-site)\s+training\s+(?:requirement|program|session|workshop)\b",
)
PROCEED_NOW_PATTERNS = (
    r"\b(?:please\s+)?proceed(?:\s+(?:now|further|ahead|with))?\b",
    r"\bgo\s+ahead\b",
    r"\bmove\s+ahead\b",
    r"\bstart\b.{0,40}\b(?:search|shortlist|process|trainer)\b",
    r"\bbegin\b.{0,40}\b(?:search|shortlist|process|trainer)\b",
)
DETAILS_LATER_PATTERNS = (
    r"\b(?:send|sent|share|provide)\b.{0,50}\blater\b",
    r"\blater\b.{0,50}\b(?:send|share|provide|details?)\b",
    r"\bdetails?\s+(?:later|will\s+follow|to\s+follow)\b",
    r"\bremaining\s+details?\b",
    r"\bonce\s+.*\b(?:available|finali[sz]ed)\b",
)
OPEN_REQUIREMENT_EXCLUDED_STATUSES = {"closed", "completed", "cancelled", "canceled", "inactive", "deleted"}


class PollRequest(BaseModel):
    since_days: int = 7
    max_messages: int = 50
    from_emails: Optional[list] = None


class ProcessPendingRequest(BaseModel):
    limit: int = 100


def _now() -> datetime:
    return datetime.utcnow()


def _clean(value: Any) -> str:
    value = re.sub(r"[*_`]+", "", str(value or ""))
    return re.sub(r"\s+", " ", value).strip(" \t\r\n:-")


def _plain_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return default


def _parse_retry_after(value: Any) -> Optional[datetime]:
    match = re.search(r"Retry after\s+([0-9T:.\-+Z]+)", str(value or ""), flags=re.IGNORECASE)
    if not match:
        return None
    try:
        parsed = datetime.fromisoformat(match.group(1).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _auto_send_retry_due(email_doc: Dict[str, Any]) -> bool:
    retry_after = email_doc.get("auto_send_retry_after")
    if isinstance(retry_after, str):
        retry_after = _parse_retry_after(f"Retry after {retry_after}")
    return not retry_after or retry_after <= _now()


def _is_reply_thread(subject: str, email_doc: Dict[str, Any]) -> bool:
    if email_doc.get("in_reply_to"):
        return True
    return bool(re.match(r"^\s*(?:re|fw|fwd)\s*:", subject or "", flags=re.IGNORECASE))


def _should_attempt_auto_reply(
    email_doc: Dict[str, Any],
    settings: Dict[str, Any],
    auto_send_eligible: bool,
    reply: Dict[str, str],
) -> bool:
    return (
        bool(reply)
        and settings["enabled"]
        and auto_send_eligible
        and not email_doc.get("reply_sent")
        and email_doc.get("status") not in FINAL_CLIENT_STATUSES
        and email_doc.get("reply_status") not in FINAL_CLIENT_STATUSES
        and _auto_send_retry_due(email_doc)
    )


def _field_value(text: str, labels: List[str]) -> str:
    label_pattern = "|".join(re.escape(label) for label in labels)
    pattern = re.compile(
        rf"(?im)^\s*(?:[-*\u2022]\s*)?(?:\*\*)?\s*(?:{label_pattern})"
        rf"\s*(?:\*\*)?\s*[:\-]\s*(.+?)\s*$"
    )
    match = pattern.search(text or "")
    return _clean(match.group(1)) if match else ""


def _has_direct_training_request_language(subject: str, body: str) -> bool:
    text = _plain_text(f"{subject}\n{body}").lower()
    return any(re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL) for pattern in DIRECT_REQUEST_PATTERNS)


def _client_wants_to_proceed_now(subject: str, body: str) -> bool:
    text = _plain_text(f"{subject}\n{body}").lower()
    has_proceed_signal = any(
        re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        for pattern in PROCEED_NOW_PATTERNS
    )
    if not has_proceed_signal:
        return False
    has_details_later_signal = any(
        re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        for pattern in DETAILS_LATER_PATTERNS
    )
    return has_details_later_signal or "proceed now" in text or "go ahead" in text


def _is_obvious_non_client_email(sender_email: str, subject: str, body: str) -> bool:
    email = (sender_email or "").strip().lower()
    local = email.split("@", 1)[0] if "@" in email else email
    domain = email.split("@", 1)[1] if "@" in email else ""
    automated_sender = (
        local in AUTOMATED_SENDER_LOCALS
        or local.startswith(("bounce", "no-reply", "noreply", "donotreply", "do-not-reply"))
        or "mailer-daemon" in local
    )
    bulk_domain = any(domain == item or domain.endswith(f".{item}") for item in BULK_SENDER_DOMAINS)
    if automated_sender or bulk_domain:
        return True

    if _has_direct_training_request_language(subject, body):
        return False
    text = _plain_text(f"{subject}\n{body}").lower()
    bulk_content = any(signal in text for signal in NON_CLIENT_BULK_SIGNALS)
    return bulk_content


def _client_company_from_email(email: str, fallback: str = "") -> str:
    domain = (email or "").split("@")[-1].lower()
    if not domain or domain in {"gmail.com", "outlook.com", "hotmail.com", "yahoo.com"}:
        return _clean(fallback) or _clean((email or "").split("@")[0])
    return _clean(domain.split(".")[0]).title()


def _infer_technology(subject: str, body: str) -> str:
    text = f"{subject}\n{body}"
    explicit = _field_value(text, ["Technology", "Tech", "Domain", "Course", "Topic"])
    candidates = [explicit]

    phrase_patterns = [
        r"requirement\s+for\s+(?:an?\s+|the\s+)?([A-Za-z0-9][A-Za-z0-9 .+#/&-]{1,70}?)\s+(?:trainer|training|course|workshop)\b",
        r"(?:need|require|looking\s+for)\s+(?:an?\s+)?([A-Za-z0-9][A-Za-z0-9 .+#/&-]{1,70}?)\s+(?:trainer|training|course|workshop)\b",
        r"(?:trainer|training|course|workshop)\s+(?:for|on|in)\s+([A-Za-z0-9][A-Za-z0-9 .+#/&-]{1,70})\b",
        r"(?:need|require|looking\s+for)\s+(?:an?\s+)?(?:trainer|training|course|workshop)\s+(?:for|on|in)\s+([A-Za-z0-9][A-Za-z0-9 .+#/&-]{1,70})\b",
    ]
    for pattern in phrase_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            candidates.append(match.group(1))

    for tech in KNOWN_TECHNOLOGIES:
        if re.search(rf"\b{re.escape(tech)}\b", text, flags=re.IGNORECASE):
            candidates.append(tech)

    for candidate in candidates:
        candidate = re.split(r"[.;,\n\r]|\bplease\b", _clean(candidate), maxsplit=1, flags=re.IGNORECASE)[0]
        candidate = re.sub(
            r"\b(?:trainer|training|course|workshop|profiles?|requirement)\b.*$",
            "",
            candidate,
            flags=re.IGNORECASE,
        )
        candidate_words = {word.lower() for word in re.findall(r"[A-Za-z]+", candidate)}
        if candidate_words & NON_TECH_CANDIDATE_WORDS:
            continue
        if 1 < len(candidate) <= 60:
            return candidate
    return ""


def _extract_duration(text: str) -> Dict[str, Any]:
    raw = _field_value(text, ["Duration", "Training Duration"])
    source = raw or text
    match = re.search(r"(\d+(?:\.\d+)?)\s*(days?|weeks?|months?|hours?|hrs?)", source, flags=re.IGNORECASE)
    if not match:
        return {"duration_text": raw}

    amount = _safe_float(match.group(1))
    unit = match.group(2).lower()
    result: Dict[str, Any] = {"duration_text": raw or match.group(0)}
    if unit.startswith("hour") or unit.startswith("hr"):
        result["duration_hours"] = amount
        result["duration_days"] = max(1, round(amount / 7, 2))
    elif unit.startswith("week"):
        result["duration_days"] = int(amount * 5)
    elif unit.startswith("month"):
        result["duration_days"] = int(amount * 20)
    else:
        result["duration_days"] = int(amount) if amount.is_integer() else amount
    return result


def _extract_budget(text: str) -> Dict[str, Any]:
    rupee = re.escape(chr(0x20B9))
    pattern = re.compile(
        r"(?:budget|commercials?|rate|cost|price)[^\n\r\d]{0,30}"
        rf"(?:INR|Rs\.?|{rupee}|USD|\$)?\s*([\d,]+(?:\.\d+)?)",
        flags=re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return {}
    amount = _safe_float(match.group(1))
    if amount <= 0:
        return {}
    currency = "USD" if "$" in match.group(0) or "USD" in match.group(0).upper() else "INR"
    per_day = bool(re.search(r"per\s*day|/day|daily", match.group(0), flags=re.IGNORECASE))
    return {
        "budget_per_day" if per_day else "budget_total": amount,
        "budget_currency": currency,
    }


def _extract_requirement_from_email(subject: str, body: str, sender_email: str = "", sender_name: str = "") -> Dict[str, Any]:
    body_text = _plain_text(body)
    text = f"Subject: {subject}\n{body_text}"
    lower = text.lower()
    direct_request = _has_direct_training_request_language(subject, body_text)
    non_client_email = _is_obvious_non_client_email(sender_email, subject, body_text)
    technology = _infer_technology(subject, body_text)
    mode = _field_value(text, ["Mode", "Delivery Mode", "Training Mode"])
    if not mode:
        if "online" in lower or "virtual" in lower:
            mode = "Online"
        elif "offline" in lower or "onsite" in lower or "on-site" in lower:
            mode = "Offline"
        elif "hybrid" in lower:
            mode = "Hybrid"

    audience_level = _field_value(text, ["Audience Level", "Level", "Audience"])
    timing = _field_value(text, ["Timings", "Timing", "Time", "Schedule"])
    duration = _extract_duration(text)
    budget = _extract_budget(text)

    participants = None
    participant_text = _field_value(text, ["Participants", "Participant Count", "Learners", "Trainees"])
    participant_match = re.search(
        r"(\d+)\s*(?:participants?|learners?|trainees?|people|pax)",
        participant_text or text,
        flags=re.IGNORECASE,
    )
    if participant_match:
        participants = _safe_int(participant_match.group(1))

    signals = sum(1 for signal in TRAINING_SIGNALS if signal in lower)
    confidence = 0.15
    if technology:
        confidence += 0.4
    if direct_request:
        confidence += 0.2
    if "trainer" in lower:
        confidence += 0.15
    if "requirement" in lower:
        confidence += 0.1
    if duration.get("duration_days") or duration.get("duration_hours"):
        confidence += 0.08
    if mode:
        confidence += 0.06
    if "share suitable trainer profiles" in lower or "trainer profiles" in lower:
        confidence += 0.08
    confidence = min(0.98, confidence + min(signals, 4) * 0.02)
    if non_client_email:
        confidence = min(confidence, 0.25)

    requested_details = []
    detail_map = {
        "resume": "Updated Resume",
        "total experience": "Total Experience",
        "relevant training experience": "Relevant Training Experience",
        "availability": "Availability",
        "commercials": "Commercials Per Day",
        "linkedin": "LinkedIn Profile",
    }
    for needle, label in detail_map.items():
        if needle in lower:
            requested_details.append(label)

    needs_clarification = []
    if not budget:
        needs_clarification.append("Commercials not provided by client")
    if not timing:
        needs_clarification.append("Exact dates not provided")
    if participants is None:
        needs_clarification.append("Participant count not provided")

    is_training_request = bool(technology) and direct_request and not non_client_email and confidence >= 0.55
    return {
        "technology_needed": technology,
        "technology": technology,
        "domain": technology,
        "required_skills": [technology] if technology else [],
        "mode": mode,
        "delivery_mode": mode,
        "audience_level": audience_level,
        "timing": timing,
        "participant_count": participants,
        "client_company": _client_company_from_email(sender_email, sender_name),
        "client_name": _clean(sender_name) or _clean((sender_email or "").split("@")[0]) or "Client",
        "client_email": _clean(sender_email),
        "email_summary": _build_summary(technology, mode, duration.get("duration_text"), timing),
        "requested_details": requested_details,
        "needs_clarification": needs_clarification,
        "urgency": "urgent" if "immediate" in lower or "earliest" in lower or "urgent" in lower else "normal",
        "confidence": round(confidence, 2),
        "is_training_request": is_training_request,
        "direct_request_language": direct_request,
        "is_non_client_email": non_client_email,
        "extraction_method": "deterministic_email_parser",
        **duration,
        **budget,
    }


def _build_summary(technology: str, mode: str, duration: Any, timing: str) -> str:
    parts = [part for part in [technology, mode, duration, timing] if part]
    return " / ".join(parts) if parts else "Training requirement details pending"


def _client_salutation(extracted: Dict[str, Any]) -> str:
    name = _clean(extracted.get("client_name"))
    if not name or name.lower() in {"client", "team"} or "@" in name:
        return "Client"
    return name[:1].upper() + name[1:]


def _client_reply_for_requirement(extracted: Dict[str, Any]) -> Dict[str, str]:
    technology = extracted.get("technology_needed") or "training"
    client_name = _client_salutation(extracted)
    body = (
        f"Dear {client_name},\n\n"
        f"Thank you for sharing your {technology} training requirement.\n\n"
        "To help us identify and recommend the most suitable trainers, kindly provide the following details:\n\n"
        "* Training duration\n"
        "* Preferred training dates\n"
        "* Daily training timings\n"
        "* Participant count\n"
        "* Location / Mode\n"
        "* Audience level (Beginner / Intermediate / Advanced)\n"
        f"* Any specific {technology} tools or topics to be covered\n\n"
        f"Meanwhile, we will keep the {technology} requirement ready for the initial trainer search. "
        "Once we receive the above details, we will refine the shortlist and share suitable trainer profiles "
        "with experience, certifications, availability, and commercials for your review.\n\n"
        "We look forward to your response.\n\n"
        "Regards,\nRecruitment Team\nClahan Technologies"
    )
    return {"subject": f"Re: {technology} Trainer Requirement", "body": body}


def _client_proceed_ack_reply(extracted: Dict[str, Any]) -> Dict[str, str]:
    technology = extracted.get("technology_needed") or "training"
    client_name = _client_salutation(extracted)
    body = (
        f"Dear {client_name},\n\n"
        "Thank you for your confirmation.\n\n"
        f"Sure, we will proceed with the initial trainer search for your {technology} training requirement "
        "based on the information currently available.\n\n"
        "Once you share the remaining details, we will refine the shortlist further and share the most suitable "
        "trainer profiles with experience, certifications, availability, and commercials for your review.\n\n"
        "Regards,\nRecruitment Team\nClahan Technologies"
    )
    return {"subject": f"Re: {technology} Trainer Requirement", "body": body}


def _client_clarification_reply(extracted: Dict[str, Any]) -> Dict[str, str]:
    client_name = _client_salutation(extracted)
    body = (
        f"Dear {client_name},\n\n"
        "Thank you for sharing the training requirement. To shortlist the right trainer profiles, "
        "please confirm the technology/topic, delivery mode, expected dates or duration, participant count, "
        "and commercials or budget range.\n\n"
        "Once we have these details, we will share suitable profiles for your review.\n\n"
        "Regards,\nRecruitment Team\nClahan Technologies"
    )
    return {"subject": "Re: Training Requirement Details", "body": body}


def _trainer_mail_for_requirement(extracted: Dict[str, Any], requirement_id: str) -> Dict[str, str]:
    # sanitize extracted technology to avoid accidental verb phrases like "conducting a corporate"
    raw_tech = _clean(extracted.get("technology_needed") or extracted.get("technology") or "").strip()
    tech = raw_tech
    if not tech or re.search(r"\bconduct(?:ing|ed)?\b|\blooking for\b|\brequirement for\b", tech, flags=re.IGNORECASE) or len(tech) > 60:
        tech = "Training"

    lines = [
        f"Technology: {tech}",
        f"Mode: {extracted.get('mode') or 'To be confirmed'}",
        f"Audience Level: {extracted.get('audience_level') or 'To be confirmed'}",
        f"Duration: {extracted.get('duration_text') or (str(extracted.get('duration_days')) + ' days' if extracted.get('duration_days') else 'To be confirmed')}",
        f"Timings: {extracted.get('timing') or 'To be confirmed'}",
    ]

    # Use a concise, single-render template matching the requested clean version.
    body = (
        f"Dear Trainer,\n\n"
        f"We have an immediate corporate training requirement and would like to check your interest and availability.\n\n"
        f"Requirement Details:\n"
        + "\n".join(f"- {line}" for line in lines)
        + "\n\nPlease share the following details if you are interested and available:\n"
        "- Updated resume/profile\n"
        "- Total experience\n"
        "- Relevant training experience\n"
        "- Availability\n"
        "- Commercials per day\n"
        "- LinkedIn profile, if available\n\n"
        f"Reference: {requirement_id}\n\n"
        "Regards,\nRecruitment Team\nClahan Technologies"
    )
    return {"subject": f"Corporate Training Requirement - {tech}", "body": body}


def _client_email_status_for_reply(reply: dict) -> dict:
    return {
        "status": "received",
        "reply_status": "received",
        "auto_send_eligible": False,
        "confidence": 0,
        "auto_send_confidence": 0,
    }


async def _auto_send_settings(db: AsyncIOMotorDatabase) -> Dict[str, Any]:
    settings = await db["admin_settings"].find_one({"settings_id": "default"}, {"_id": 0}) or {}
    inbox_cfg = settings.get("clientInboxCfg") or {}
    return {
        "enabled": inbox_cfg.get("autoSendEnabled", True) is not False,
        "threshold": _safe_float(inbox_cfg.get("autoSendThreshold", 70), 70) / 100,
    }


async def _send_client_auto_reply(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
    reply: Dict[str, str],
    requirement_id: str = "",
) -> Dict[str, Any]:
    to = _clean(email_doc.get("from_email"))
    body = reply.get("body") or ""
    subject = reply.get("subject") or email_doc.get("subject") or "Training Requirement"
    if subject and not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"

    if not to:
        return {"success": False, "error": "No recipient address available"}
    if not body:
        return {"success": False, "error": "No reply body available"}

    success, error = await send_email_async(to=to, subject=subject, body=body)
    now = _now()
    if success:
        await db["email_logs"].insert_one({
            "email_id": f"RPL-{uuid.uuid4().hex[:10].upper()}",
            "direction": "outbound",
            "recipient": to,
            "to_email": to,
            "subject": subject,
            "body": body,
            "body_snippet": body[:300],
            "status": "sent",
            "mail_type": "client_auto_reply",
            "source_email_id": email_doc.get("email_id"),
            "requirement_id": requirement_id,
            "sent_at": now,
            "created_at": now,
            "updated_at": now,
        })

    return {
        "success": success,
        "error": error or "",
        "to": to,
        "subject": subject,
        "sent_at": now,
    }


def _requirement_payload_from_email(email_doc: Dict[str, Any], extracted: Dict[str, Any]) -> Dict[str, Any]:
    technology = extracted.get("technology_needed") or extracted.get("technology")
    return {
        "title": f"{technology} Trainer",
        "technology_needed": technology,
        "domain": technology,
        "required_skills": extracted.get("required_skills") or [technology],
        "mode": extracted.get("mode"),
        "audience_level": extracted.get("audience_level"),
        "duration_days": extracted.get("duration_days"),
        "duration_hours": extracted.get("duration_hours"),
        "timing": extracted.get("timing"),
        "budget": extracted.get("budget_total") or extracted.get("budget_per_day"),
        "budget_per_day": extracted.get("budget_per_day"),
        "budget_currency": extracted.get("budget_currency"),
        "participant_count": extracted.get("participant_count"),
        "client_name": extracted.get("client_name"),
        "client_company": extracted.get("client_company"),
        "client_email": extracted.get("client_email"),
        "top_n": 10,
        "send_emails": False,
        "status": "active",
        "priority": "high" if extracted.get("urgency") == "urgent" else "medium",
        "customer_id": extracted.get("client_email") or "client-inbox",
        "metadata": {
            "source": "client_inbox",
            "source_email_id": email_doc.get("email_id"),
            "gmail_message_id": email_doc.get("gmail_message_id"),
            "original_subject": email_doc.get("subject"),
            "requested_details": extracted.get("requested_details", []),
            "parser": extracted.get("extraction_method"),
        },
    }


async def _find_existing_client_requirement(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
    extracted: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    technology = _clean(extracted.get("technology_needed") or extracted.get("technology"))
    client_email = _clean(extracted.get("client_email") or email_doc.get("from_email"))
    if not technology or not client_email:
        return None

    status_filter = {"$nin": list(OPEN_REQUIREMENT_EXCLUDED_STATUSES)}
    query = {
        "client_email": {"$regex": f"^{re.escape(client_email)}$", "$options": "i"},
        "technology_needed": {"$regex": f"^{re.escape(technology)}$", "$options": "i"},
        "status": status_filter,
    }
    existing = await db["requirements"].find_one(query, {"_id": 0}, sort=[("created_at", -1)])
    if existing:
        return existing

    source_email_id = email_doc.get("email_id")
    prior_email = await db["client_emails"].find_one(
        {
            "email_id": {"$ne": source_email_id},
            "from_email": {"$regex": f"^{re.escape(client_email)}$", "$options": "i"},
            "extracted.technology_needed": {"$regex": f"^{re.escape(technology)}$", "$options": "i"},
            "requirement_id": {"$exists": True, "$nin": ["", None]},
        },
        {"_id": 0, "requirement_id": 1},
        sort=[("created_at", -1)],
    )
    if not prior_email:
        return None
    return await db["requirements"].find_one(
        {"requirement_id": prior_email.get("requirement_id"), "status": status_filter},
        {"_id": 0},
    )


async def _create_requirement(
    email_doc: Dict[str, Any],
    extracted: Dict[str, Any],
    db: AsyncIOMotorDatabase,
    reuse_existing_client_requirement: bool = False,
) -> Dict[str, Any]:
    email_id = email_doc.get("email_id")
    if email_doc.get("requirement_id"):
        return {"requirement_id": email_doc["requirement_id"], "existing": True}

    existing = await db["requirements"].find_one({"metadata.source_email_id": email_id}, {"_id": 0})
    if existing:
        return {"requirement_id": existing.get("requirement_id"), "existing": True, "requirement": existing}

    if reuse_existing_client_requirement:
        existing = await _find_existing_client_requirement(db, email_doc, extracted)
        if existing:
            return {"requirement_id": existing.get("requirement_id"), "existing": True, "requirement": existing}

    payload = _requirement_payload_from_email(email_doc, extracted)
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(f"{CORE_API_URL}/api/v1/requirements", json=payload)
        response.raise_for_status()
        return response.json()


async def _send_initial_trainer_mail(
    requirement_id: str,
    extracted: Dict[str, Any],
) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            f"{TRAINER_SERVICE_URL}/api/v1/shortlists/send-mail",
            json={
                "requirement_id": requirement_id,
                "mail_type": "mail1",
            },
        )
        response.raise_for_status()
        return response.json()


async def _start_trainer_search_after_client_reply(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
) -> Dict[str, Any]:
    extracted = email_doc.get("extracted") or {}
    if not extracted:
        extracted = _extract_requirement_from_email(
            subject=email_doc.get("subject") or "",
            body=email_doc.get("clean_body") or email_doc.get("raw_body") or email_doc.get("body") or "",
            sender_email=email_doc.get("from_email") or "",
            sender_name=email_doc.get("from_name") or "",
        )

    requirement_result = await _create_requirement(
        email_doc,
        extracted,
        db,
        reuse_existing_client_requirement=True,
    )
    requirement_id = requirement_result.get("requirement_id")
    if not requirement_id:
        raise RuntimeError("No requirement_id available for trainer automation")

    send_result = await _send_initial_trainer_mail(requirement_id, extracted)
    sent_count = _safe_int(send_result.get("sent"), 0)
    return {
        "requirement_id": requirement_id,
        "requirement_created": True,
        "trainer_automation_status": "started" if sent_count > 0 else "no_trainers_emailed",
        "trainer_automation_started_at": _now(),
        "pending_trainer_automation": False,
        "mail_automation": send_result,
        "status": "auto_sent" if sent_count > 0 else "trainer_email_failed",
    }


async def _process_client_requirement_email(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
) -> Dict[str, Any]:
    subject = email_doc.get("subject") or ""
    body = email_doc.get("clean_body") or email_doc.get("raw_body") or email_doc.get("body") or ""
    extracted = _extract_requirement_from_email(
        subject=subject,
        body=body,
        sender_email=email_doc.get("from_email") or "",
        sender_name=email_doc.get("from_name") or "",
    )
    client_authorized_search = _client_wants_to_proceed_now(subject, body)
    reply: Dict[str, str] = {}
    if extracted.get("is_training_request"):
        reply = _client_proceed_ack_reply(extracted) if client_authorized_search else _client_reply_for_requirement(extracted)
    elif extracted.get("direct_request_language") and not extracted.get("is_non_client_email"):
        reply = _client_clarification_reply(extracted)

    now = _now()
    settings = await _auto_send_settings(db)
    is_initial_requirement_request = (
        extracted.get("direct_request_language")
        and not extracted.get("is_non_client_email")
        and not _is_reply_thread(subject, email_doc)
    )
    auto_send_eligible = bool(reply) and (
        extracted.get("is_training_request")
        or is_initial_requirement_request
    )
    base_update = {
        "extracted": extracted,
        "confidence": extracted.get("confidence", 0),
        "auto_send_confidence": extracted.get("confidence", 0),
        "auto_send_eligible": auto_send_eligible,
        "updated_at": now,
    }
    if reply:
        base_update.update({
            "generated_reply": reply,
            "ai_reply": reply["body"],
            "draft_reply": reply["body"],
        })

    if not extracted.get("is_training_request"):
        status = "pending_approval" if reply else "spam"
        reason = "needs_requirement_clarification" if reply else "ignored_non_client_email"
        set_update: Dict[str, Any] = {
            **base_update,
            "status": status,
            "reply_status": "pending_review" if reply else "spam",
            "processed": True,
            "processed_at": now,
            "classification_reason": reason,
        }
        if reply:
            send_result: Dict[str, Any] = {
                "auto_send_enabled": settings["enabled"],
                "auto_send_eligible": auto_send_eligible,
                "client_authorized_search": False,
                "pending_client_reply": False,
                "sent": 0,
                "total": 0,
            }
            set_update["mail_automation"] = send_result
            if _should_attempt_auto_reply(email_doc, settings, auto_send_eligible, reply):
                auto_reply_result = await _send_client_auto_reply(db, email_doc, reply)
                send_result["client_reply"] = {
                    "sent": bool(auto_reply_result.get("success")),
                    "to": auto_reply_result.get("to"),
                    "subject": auto_reply_result.get("subject"),
                    "error": auto_reply_result.get("error", ""),
                }
                if auto_reply_result.get("success"):
                    set_update.update({
                        "status": "auto_sent",
                        "reply_status": "auto_sent",
                        "reply_sent": True,
                        "reply_sent_at": auto_reply_result.get("sent_at"),
                        "auto_sent_at": auto_reply_result.get("sent_at"),
                        "auto_send_error": "",
                        "auto_send_retry_after": None,
                        "processed": True,
                        "processed_at": auto_reply_result.get("sent_at"),
                    })
                else:
                    error = auto_reply_result.get("error", "Send failed")
                    retry_after = _parse_retry_after(error)
                    set_update.update({
                        "status": "pending_approval" if retry_after else "needs_manual_review",
                        "reply_status": "pending_review" if retry_after else "needs_manual_review",
                        "reply_sent": False,
                        "auto_send_error": error,
                        "reply_error": error,
                        "auto_send_retry_after": retry_after,
                        "processed": True,
                        "processed_at": now,
                    })
        unset_update = {} if reply else {"generated_reply": "", "ai_reply": "", "draft_reply": ""}
        await db["client_emails"].update_one(
            {"email_id": email_doc.get("email_id")},
            {"$set": set_update, **({"$unset": unset_update} if unset_update else {})},
        )
        return {
            "processed": True,
            "reason": reason,
            "status": set_update.get("status"),
            "mail_automation": set_update.get("mail_automation"),
            "extracted": extracted,
        }

    status_update: Dict[str, Any] = {
        **base_update,
        "auto_send_eligible": auto_send_eligible,
        "status": "pending_approval",
        "reply_status": "pending_review",
    }
    await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": status_update})

    try:
        requirement_result = await _create_requirement(
            email_doc,
            extracted,
            db,
            reuse_existing_client_requirement=client_authorized_search,
        )
        requirement_id = requirement_result.get("requirement_id")
        if not requirement_id:
            raise RuntimeError("Core API did not return a requirement_id")

        send_result: Dict[str, Any] = {
            "auto_send_enabled": settings["enabled"],
            "auto_send_eligible": auto_send_eligible,
            "client_authorized_search": client_authorized_search,
            "pending_client_reply": client_authorized_search,
            "sent": 0,
            "total": 0,
        }
        final_status = "pending_approval"
        reply_status = "pending_approval"
        reply_sent_update: Dict[str, Any] = {}

        should_auto_send_reply = _should_attempt_auto_reply(email_doc, settings, auto_send_eligible, reply)
        if should_auto_send_reply:
            auto_reply_result = await _send_client_auto_reply(db, email_doc, reply, requirement_id)
            send_result["client_reply"] = {
                "sent": bool(auto_reply_result.get("success")),
                "to": auto_reply_result.get("to"),
                "subject": auto_reply_result.get("subject"),
                "error": auto_reply_result.get("error", ""),
            }
            if auto_reply_result.get("success"):
                final_status = "auto_sent"
                reply_status = "auto_sent"
                reply_sent_update.update({
                    "reply_sent": True,
                    "reply_sent_at": auto_reply_result.get("sent_at"),
                    "auto_sent_at": auto_reply_result.get("sent_at"),
                    "auto_send_error": "",
                    "auto_send_retry_after": None,
                })
                if client_authorized_search:
                    try:
                        trainer_send_result = await _send_initial_trainer_mail(requirement_id, extracted)
                        trainer_sent_count = _safe_int(trainer_send_result.get("sent"), 0)
                        send_result["trainer_mail"] = trainer_send_result
                        send_result["sent"] = trainer_sent_count
                        send_result["total"] = _safe_int(trainer_send_result.get("total"), trainer_sent_count)
                        reply_sent_update.update({
                            "trainer_automation_status": "started" if trainer_sent_count > 0 else "no_trainers_emailed",
                            "trainer_automation_started_at": _now(),
                            "pending_trainer_automation": False,
                        })
                    except Exception as exc:
                        logger.exception("Trainer automation failed after auto client reply for %s", email_doc.get("email_id"))
                        send_result["trainer_mail"] = {"sent": 0, "error": str(exc)}
                        final_status = "trainer_email_failed"
                        reply_sent_update.update({
                            "trainer_automation_status": "failed",
                            "trainer_automation_error": str(exc),
                            "trainer_automation_failed_at": _now(),
                        })
            else:
                error = auto_reply_result.get("error", "Send failed")
                retry_after = _parse_retry_after(error)
                final_status = "pending_approval" if retry_after else "needs_manual_review"
                reply_status = "pending_review" if retry_after else "needs_manual_review"
                reply_sent_update.update({
                    "reply_sent": False,
                    "auto_send_error": error,
                    "reply_error": error,
                    "auto_send_retry_after": retry_after,
                })

        update = {
            "requirement_id": requirement_id,
            "requirement_created": True,
            "requirement_created_at": now,
            "client_authorized_trainer_search": client_authorized_search,
            "pending_trainer_automation": client_authorized_search,
            "mail_automation": send_result,
            "processed": True,
            "processed_at": now,
            "status": final_status,
            "reply_status": reply_status,
            "updated_at": now,
            **reply_sent_update,
        }
        await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": update})
        return {
            "processed": True,
            "requirement_id": requirement_id,
            "status": final_status,
            "mail_automation": send_result,
        }
    except Exception as exc:
        logger.exception("Client requirement automation failed for %s", email_doc.get("email_id"))
        await db["client_emails"].update_one(
            {"email_id": email_doc.get("email_id")},
            {"$set": {
                "status": "needs_manual_review",
                "reply_status": "needs_manual_review",
                "automation_error": str(exc),
                "updated_at": _now(),
            }},
        )
        return {"processed": False, "reason": "automation_failed", "error": str(exc)}


async def _persist_client_email_from_reply(db: AsyncIOMotorDatabase, reply: dict) -> None:
    msg_id_hdr = reply.get("message_id_header", "")
    query = {}
    if msg_id_hdr:
        query["gmail_message_id"] = msg_id_hdr
    elif reply.get("in_reply_to"):
        query["in_reply_to"] = reply.get("in_reply_to")

    existing = await db["client_emails"].find_one(query) if query else None
    now = _now()
    update_fields = {
        "from_email": reply.get("from_email"),
        "from_name": (reply.get("from_email") or "").split("@")[0],
        "subject": reply.get("subject"),
        "body": (reply.get("body") or "")[:2000],
        "raw_body": reply.get("body") or "",
        "clean_body": reply.get("body") or "",
        "body_snippet": (reply.get("body") or "")[:500],
        "gmail_message_id": msg_id_hdr,
        "in_reply_to": reply.get("in_reply_to"),
        "sentiment": reply.get("sentiment"),
        "action": reply.get("action"),
        "received_at": reply.get("received_at"),
        "updated_at": now,
    }
    if not existing or existing.get("status") not in FINAL_CLIENT_STATUSES:
        update_fields.update(_client_email_status_for_reply(reply))

    if existing:
        await db["client_emails"].update_one(
            {"email_id": existing["email_id"]},
            {"$set": update_fields},
        )
        merged = {**existing, **update_fields}
        should_process_proceed_reply = (
            _client_wants_to_proceed_now(
                merged.get("subject") or "",
                merged.get("clean_body") or merged.get("raw_body") or merged.get("body") or "",
            )
            and not merged.get("client_authorized_trainer_search")
            and not merged.get("pending_trainer_automation")
        )
        if not merged.get("requirement_id") or should_process_proceed_reply:
            await _process_client_requirement_email(db, merged)
        return

    doc = {
        "email_id": f"CLH-{uuid.uuid4().hex[:10].upper()}",
        "created_at": now,
        "processed": False,
        **update_fields,
    }
    await db["client_emails"].insert_one(doc)
    await _process_client_requirement_email(db, doc)


async def _process_and_store_replies(db: AsyncIOMotorDatabase, replies: list) -> int:
    """Persist inbound replies to email logs and process client requirements."""
    stored = 0
    for reply in replies:
        msg_id_hdr = reply.get("message_id_header", "")
        if msg_id_hdr:
            existing = await db.email_logs.find_one({"gmail_message_id": msg_id_hdr})
            if existing:
                await _persist_client_email_from_reply(db, reply)
                continue

        now = _now()
        doc = {
            "email_id": f"INB-{uuid.uuid4().hex[:10].upper()}",
            "direction": "inbound",
            "sender": reply.get("from_email"),
            "subject": reply.get("subject"),
            "body_snippet": (reply.get("body") or "")[:500],
            "gmail_message_id": msg_id_hdr,
            "in_reply_to": reply.get("in_reply_to"),
            "sentiment": reply.get("sentiment"),
            "action": reply.get("action"),
            "status": "received",
            "processed": False,
            "received_at": reply.get("received_at"),
            "created_at": now,
            "updated_at": now,
        }
        await db.email_logs.insert_one(doc)
        await _persist_client_email_from_reply(db, reply)
        stored += 1
    return stored


async def _process_pending_client_emails(db: AsyncIOMotorDatabase, limit: int = 100) -> Dict[str, Any]:
    now = _now()
    query = {
        "$or": [
            {"processed": {"$ne": True}},
            {"extracted": {"$exists": False}},
            {
                "reply_sent": {"$ne": True},
                "auto_send_eligible": True,
                "$and": [
                    {
                        "$or": [
                            {"status": {"$in": ["pending_approval", "pending_review"]}},
                            {"reply_status": {"$in": ["pending_approval", "pending_review"]}},
                        ],
                    },
                    {
                        "$or": [
                            {"auto_send_retry_after": {"$exists": False}},
                            {"auto_send_retry_after": None},
                            {"auto_send_retry_after": {"$lte": now}},
                        ],
                    },
                ],
            },
        ]
    }
    cursor = (
        db["client_emails"]
        .find(query, {"_id": 0})
        .sort("created_at", -1)
        .limit(max(1, min(limit, 500)))
    )
    items = [doc async for doc in cursor]
    results = [await _process_client_requirement_email(db, doc) for doc in items]
    return {
        "checked": len(items),
        "requirements_created": sum(1 for item in results if item.get("requirement_id")),
        "auto_sent": sum(1 for item in results if item.get("status") == "auto_sent"),
        "failed": sum(1 for item in results if item.get("reason") == "automation_failed"),
        "results": results,
    }


async def _poll_and_store(
    db: AsyncIOMotorDatabase,
    since_days: int = 7,
    max_messages: int = 50,
    from_emails: Optional[list] = None,
) -> int:
    """Poll IMAP and persist/process messages."""
    loop = asyncio.get_event_loop()
    replies = await loop.run_in_executor(
        None,
        lambda: check_imap_replies(since_days=since_days, max_messages=max_messages, from_emails=from_emails),
    )
    return await _process_and_store_replies(db, replies)


@router.post("/poll")
async def poll_inbox(
    payload: PollRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
):
    """Trigger a Gmail IMAP poll. Processing runs in background."""

    async def _run():
        await _poll_and_store(
            db,
            since_days=payload.since_days,
            max_messages=payload.max_messages,
            from_emails=payload.from_emails,
        )

    background_tasks.add_task(_run)
    return {"message": "Inbox poll triggered", "since_days": payload.since_days}


@router.post("/poll/sync")
async def poll_inbox_sync(
    payload: PollRequest,
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
):
    """Synchronous poll - waits for completion and returns counts."""
    stored = await _poll_and_store(
        db,
        since_days=payload.since_days,
        max_messages=payload.max_messages,
        from_emails=payload.from_emails,
    )
    pending = await _process_pending_client_emails(db, limit=payload.max_messages)
    return {"stored": stored, **pending}


@router.post("/process-pending")
async def process_pending_client_emails(
    payload: ProcessPendingRequest,
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
):
    """Re-run client requirement extraction/automation for stored inbox emails."""
    return {"success": True, **await _process_pending_client_emails(db, payload.limit)}


@router.get("/unprocessed")
async def get_unprocessed(
    limit: int = 50,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Return inbound emails not yet processed by the pipeline."""
    cursor = db.email_logs.find(
        {"direction": "inbound", "processed": False},
        {"_id": 0},
    ).limit(limit).sort("created_at", 1)
    items = [doc async for doc in cursor]
    return {"items": items, "count": len(items)}


@router.patch("/{email_id}/mark-processed")
async def mark_processed(
    email_id: str,
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
):
    now = _now()
    await db.email_logs.update_one(
        {"email_id": email_id},
        {"$set": {"processed": True, "processed_at": now, "updated_at": now}},
    )
    return {"message": "Marked as processed", "email_id": email_id}
