"""Shortlist management — send mail, send interview link, send client slots."""
import asyncio
import base64
from html import escape
import logging
import math
import re
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from shared.database.service import get_db
from app.config import get_settings
from app.toc_pdf_template import build_toc_html

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()
LOCAL_TZ = timezone(timedelta(hours=5, minutes=30))

EMAIL_SVC = settings.EMAIL_SERVICE_URL.rstrip("/")
DOC_SVC = settings.DOCUMENT_SERVICE_URL.rstrip("/")
NOTIF_SVC = settings.NOTIFICATION_SERVICE_URL.rstrip("/")
CORE_API_SVC = settings.CORE_API_URL.rstrip("/")


def _client_time_greeting(name: str) -> str:
    clean_name = _clean(name) or "Client"
    hour = datetime.now(LOCAL_TZ).hour
    if hour < 12:
        greeting = "Good morning"
    elif hour < 17:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"
    return f"{greeting} {clean_name}"
LOCAL_SERVICE_FALLBACKS = {
    "https://email-service:8002": "http://email-service:8002",
    "http://127.0.0.1:8002": "http://email-service:8002",
    "http://core-api:8001": "http://127.0.0.1:8001",
    "https://document-service:8006": "http://document-service:8006",
    "https://notification-service:8003": "http://notification-service:8003",
}
EXCLUDED_TRAINER_STATUSES = {"interested", "confirmed", "declined"}
PIPELINE_VERSION = "trainer-match-microservice-v1"
MIN_TRAINER_DAY_RATE_VISIBLE = 10000
TRAINER_COMMERCIAL_MIN_VISIBLE = 12000
TRAINER_COMMERCIAL_MAX_VISIBLE = 15000
DEFAULT_TRAINER_SHARE = 0.70
CLIENT_COMMERCIAL_MARKUP = 0.30
PROPOSAL_SHORTLIST_COMMERCIAL = "INR 13,000 per day/session"
# The client-facing proposal quote is a single normal, rounded amount. Do not
# expose the trainer range or exact margin arithmetic such as INR 16,900.
PROPOSAL_CLIENT_QUOTE_RANGE = (17000,)
# A client that explicitly asks for lab costing receives the generated
# workbook during the profile/slot handoff.  The workbook uses the client ToC
# where one was provided, otherwise the system-generated ToC; it never mixes
# trainer commercial margin into the lab-cost calculation.
AUTO_ATTACH_LAB_COST_WORKBOOK = True
ACTIVE_PIPELINE_STAGES = {
    "mail1",
    "waiting_reply1",
    "mail1_replied",
    "mail2",
    "waiting_reply2",
    "details_received",
    "mail3",
    "slot_booked",
    "interview_scheduled",
    "selected",
    "toc_requested",
    "toc_received_pending",
    "training_confirmed",
}
# Mail 2 is the trainer slot request.  Only its explicit follow-up may ask
# for a genuinely missing trainer detail.
MAIL2_TYPES = {"mail2", "mail2_followup"}
DETAIL_FOLLOWUP_TYPES = {"mail2_followup"}
CLIENT_COMMERCIAL_MAIL_TYPES = {
    "trainer_commercials_to_client",
    "commercial_details_notification",
}
POSITIVE_REPLY_SIGNALS = (
    "interested",
    "i am interested",
    "i'm interested",
    "available",
    "yes",
    "confirm",
    "okay",
    "ok",
    "fine",
    "share details",
    "send details",
)
NEGATIVE_REPLY_SIGNALS = (
    "not interested",
    "not available",
    "decline",
    "cannot",
    "can't",
    "no",
)


class SendMailRequest(BaseModel):
    requirement_id: str
    trainer_id: Optional[str] = ""
    trainer_ids: Optional[List[str]] = None
    to_email: Optional[str] = ""
    to_name: Optional[str] = ""
    trainer_name: Optional[str] = ""
    mail_type: str = "mail1"
    subject: Optional[str] = ""
    body: Optional[str] = ""
    smtp_config: Optional[Dict[str, Any]] = None


class SendInterviewLinkRequest(BaseModel):
    requirement_id: str
    trainer_id: str
    to_email: Optional[str] = ""
    trainer_name: Optional[str] = ""
    interview_link: str
    interview_date: Optional[str] = ""
    date_time: Optional[str] = ""
    platform: Optional[str] = "Google Meet"
    technology: Optional[str] = ""
    client_email: Optional[str] = ""
    client_name: Optional[str] = ""
    smtp_config: Optional[Dict[str, Any]] = None


class SendClientSlotsRequest(BaseModel):
    requirement_id: str
    trainer_id: str
    slots: List[Dict[str, Any]] = []
    slot_text: Optional[str] = ""
    trainer_details_text: Optional[str] = ""
    trainer_name: Optional[str] = ""
    client_email: Optional[str] = ""
    client_name: Optional[str] = ""
    mail_type: Optional[str] = "mail4"
    smtp_config: Optional[Dict[str, Any]] = None


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _email_address(value: Any) -> str:
    """Return a stable bare email for idempotency keys and comparisons."""
    raw = _clean(value)
    _display_name, parsed = parseaddr(raw)
    return _clean(parsed or raw).lower()


def _requested_reschedule_date_from_body(value: Any) -> str:
    """Persist the manual client date without guessing a different date."""
    text = _clean(value)
    match = re.search(
        r"\b(?:on|for)\s+(\d{1,2}(?:st|nd|rd|th)?\s+"
        r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{4})\b",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return _clean(match.group(1))
    match = re.search(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b", text)
    return _clean(match.group(1)) if match else ""


def _clean_duration_text(value: Any) -> str:
    text = _clean(value)
    text = re.sub(r"(?i)^to\s+be\s*:?\s*(?=\d)", "", text).strip()
    return text


def _client_interview_message(
    *,
    client_name: str,
    trainer_name: str,
    technology: str,
    requirement_id: str,
    interview_date: str,
    platform: str,
    interview_link: str,
) -> Dict[str, str]:
    subject = f"Interview Schedule Confirmation - {technology} | Ref: {requirement_id}"
    date_line = f"Date & Time: {interview_date}\n" if interview_date else ""
    link = _clean(interview_link)
    body = (
        f"Dear {client_name or 'Team'},\n\n"
        f"The interview/discussion for the shortlisted {technology} trainer is confirmed.\n\n"
        "Interview Details:\n"
        f"{date_line}"
        f"Platform: {platform or 'Google Meet'}\n"
        f"Meeting Link: {link}\n\n"
        "Kindly join on time and let us know if any change is required.\n\n"
        "Regards,\n"
        "Clahan Technologies\n"
        "sujithaofficial585@gmail.com"
    )
    return {"subject": subject, "body": body}


def _is_mail_quota_error(value: Any) -> bool:
    text = str(value or "").lower()
    return any(marker in text for marker in (
        "daily user sending limit exceeded",
        "user-rate limit exceeded",
        "ratelimitexceeded",
        "mail sending",
        "gmail sending quota exceeded",
    ))


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw = value
    elif isinstance(value, (tuple, set)):
        raw = list(value)
    elif isinstance(value, str):
        raw = re.split(r",|;|\n|\|", value)
    else:
        raw = [value]
    cleaned: List[str] = []
    seen = set()
    for item in raw:
        text = _clean(item)
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            cleaned.append(text)
    return cleaned


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _round_commercial_amount(value: Any) -> int:
    numeric = _safe_float(value, 0)
    if numeric <= 0:
        return 0
    # The approved trainer amount is an exact 70% share, not a rounded offer.
    return int(round(numeric))


def _trainer_visible_commercial_amount(value: Any) -> int:
    # Preserve the calculated commercial.  The historic 12k–15k display cap
    # made high-value and longer engagements appear as INR 15,000/day.
    return _round_commercial_amount(value)


def _money_to_int(raw_amount: Any, suffix: str = "") -> int:
    amount = _safe_float(str(raw_amount or "").replace(",", ""), 0)
    suffix = str(suffix or "").lower()
    if suffix in {"k", "thousand"}:
        amount *= 1000
    elif suffix in {"lakh", "lakhs"}:
        amount *= 100000
    return int(round(amount))


def _commercial_amounts_from_text(text: Any) -> List[int]:
    raw = _clean(text)
    if not raw:
        return []
    rupee = re.escape(chr(0x20B9))
    amounts: List[int] = []
    range_pattern = (
        rf"(?:INR|Rs\.?|{rupee}|commercials?|rates?|charges?|fees?|cost|quote|quoted)?\D{{0,30}}"
        r"([0-9][0-9,]*(?:\.\d+)?)\s*(k|thousand|lakh|lakhs)?\s*(?:-|to|–|—)\s*"
        r"([0-9][0-9,]*(?:\.\d+)?)\s*(k|thousand|lakh|lakhs)?"
    )
    patterns = [
        (rf"(?:INR|Rs\.?|{rupee})\s*([0-9][0-9,]*(?:\.\d+)?)\s*(k|thousand|lakh|lakhs)?", False),
        (r"\b(?:commercials?|rates?|charges?|fees?|cost|quote|quoted)\b\D{0,80}([0-9][0-9,]*(?:\.\d+)?)\s*(k|thousand|lakh|lakhs)?", False),
        (r"([0-9][0-9,]*(?:\.\d+)?)\s*(k|thousand|lakh|lakhs)?\s*(?:/-)?\s*(?:per\s*(?:day|session|hour|hr)|/day|/session|/hour|/hr)", True),
    ]
    contextual_line = re.compile(r"\b(?:commercials?|rates?|charges?|fees?|cost|quote|quoted)\b", flags=re.IGNORECASE)
    for line in raw.splitlines():
        line_has_money_context = bool(contextual_line.search(line))
        for match in re.finditer(range_pattern, line, flags=re.IGNORECASE):
            suffix = match.group(4) or match.group(2)
            for raw_amount, raw_suffix in ((match.group(1), suffix), (match.group(3), suffix)):
                amount = _money_to_int(raw_amount, raw_suffix)
                if amount >= 1000 and amount not in amounts:
                    amounts.append(amount)
        for pattern, requires_context in patterns:
            for match in re.finditer(pattern, line, flags=re.IGNORECASE):
                if requires_context and not line_has_money_context:
                    continue
                amount = _money_to_int(match.group(1), match.group(2) if len(match.groups()) > 1 else "")
                if amount >= 1000 and amount not in amounts:
                    amounts.append(amount)
    return amounts


def _trainer_mail1_commercial_text(requirement: Dict[str, Any]) -> str:
    daily_client_amount = 0.0
    total_client_amount = 0.0
    days = _safe_int(requirement.get("duration_days"), 0) or _safe_int(requirement.get("commercial_working_days"), 0)
    if requirement.get("budget_total") not in (None, "", []):
        total_client_amount = _safe_float(requirement.get("budget_total"))
        daily_client_amount = total_client_amount / days if days else 0.0
    if not daily_client_amount:
        daily_client_amount = _safe_float(
            requirement.get("client_budget_per_day") or requirement.get("budget_per_day"),
        )
        total_client_amount = daily_client_amount * days if daily_client_amount and days else total_client_amount
    if not daily_client_amount and not total_client_amount:
        return ""
    # A client daily commercial below INR 10,000 is one small engagement:
    # send the trainer one 70% total, never a misleading day-wise amount.
    if daily_client_amount and daily_client_amount < MIN_TRAINER_DAY_RATE_VISIBLE and total_client_amount:
        return f"INR {_trainer_visible_commercial_amount(total_client_amount * DEFAULT_TRAINER_SHARE):,} total commercial, inclusive of applicable TDS"
    if daily_client_amount:
        return f"INR {_trainer_visible_commercial_amount(daily_client_amount * DEFAULT_TRAINER_SHARE):,} per day/session, inclusive of applicable TDS"
    return f"INR {_trainer_visible_commercial_amount(total_client_amount * DEFAULT_TRAINER_SHARE):,} total commercial, inclusive of applicable TDS"


def _client_mail1_budget_text(requirement: Dict[str, Any]) -> str:
    """Return the recorded client commercial without asking the trainer to quote."""
    per_day_amount = _safe_float(
        requirement.get("client_budget_per_day") or requirement.get("budget_per_day"),
    )
    total_amount = _safe_float(requirement.get("budget_total"))
    if per_day_amount:
        # The agreed rule treats a value below INR 10,000 as one total-course
        # commercial, rather than incorrectly presenting it as a daily rate.
        if per_day_amount < MIN_TRAINER_DAY_RATE_VISIBLE:
            amount = total_amount or per_day_amount
            return f"INR {_round_commercial_amount(amount):,} total-course commercial"
        return f"INR {_round_commercial_amount(per_day_amount):,} per day/session"
    if total_amount:
        return f"INR {_round_commercial_amount(total_amount):,} total-course commercial"
    return _clean(requirement.get("budget_range"))


def _trainer_mail1_commercial_section(requirement: Dict[str, Any]) -> List[str]:
    """Show only the trainer's offer; client pricing and margin are internal."""
    lines: List[str] = []
    trainer_allocation = _trainer_mail1_commercial_text(requirement)
    if trainer_allocation:
        lines.append(f"- Offered trainer commercial: {trainer_allocation}")
    elif _is_proposal_requirement(requirement):
        # A proposal commonly has no client budget or final duration yet.
        # Still give the trainer the approved engagement range so Mail 1 is
        # commercially meaningful, while keeping the client quote and margin
        # strictly internal.
        lines.append(
            "- Offered trainer commercial: "
            f"INR {TRAINER_COMMERCIAL_MIN_VISIBLE:,}-{TRAINER_COMMERCIAL_MAX_VISIBLE:,} "
            "per day/session, inclusive of applicable TDS"
        )
    return lines


def _ensure_trainer_mail1_commercial_section(body: str, requirement: Dict[str, Any]) -> str:
    """Keep AI Mail 1 factual when it omits the recorded commercial lines."""
    section = _trainer_mail1_commercial_section(requirement)
    if not section:
        return body
    text = _clean(body)
    if "offered trainer commercial:" in text.lower():
        return text
    marker = "Please let us know whether you are available"
    insert = "\n".join(section) + "\n\n"
    if marker in text:
        return text.replace(marker, insert + marker, 1)
    return f"{text.rstrip()}\n\n{insert.rstrip()}"


def _replace_trainer_mail1_commercial(body: str, requirement: Dict[str, Any]) -> str:
    commercial_text = _trainer_mail1_commercial_text(requirement)
    if not commercial_text:
        return body
    line = f"Commercials/Budget: {commercial_text}"
    if re.search(r"(?im)^Commercials/Budget:\s*.*$", body or ""):
        return re.sub(r"(?im)^Commercials/Budget:\s*.*$", line, body or "")
    if "Training Details:" in (body or ""):
        return (body or "").replace("Training Details:", f"Training Details:\n\n{line}", 1)
    return f"{(body or '').rstrip()}\n\n{line}"


def _mail1_requested_items(requirement: Dict[str, Any]) -> List[str]:
    source = " ".join(
        _clean(value).lower()
        for value in (
            requirement.get("client_requirement_text"),
            requirement.get("requirement_text"),
            requirement.get("description"),
            (requirement.get("metadata") or {}).get("original_body"),
        )
        if _clean(value)
    )
    toc_label = (
        "Detailed day-wise ToC/course agenda"
        if any(term in source for term in ("day-wise", "day wise", "detailed", "topics and subtopics"))
        else "ToC/course agenda"
    )
    commercial_label = (
        "Commercials for the complete training engagement"
        if re.search(r"commercials?.{0,40}(?:complete|entire|total)|(?:complete|entire|total).{0,40}commercials?", source)
        else "Commercial expectation per hour/day"
    )
    checks = [
        ("Updated trainer profile/CV", ("cv", "resume", "profile")),
        ("LinkedIn profile", ("linkedin",)),
        (f"Relevant {(_clean(requirement.get('domain')) or _clean(requirement.get('technology')) or 'technology')} corporate training experience", ("training experience", "relevant experience", "corporate training experience")),
        ("Availability for the specified dates and timings", ("availability", "available", "slots")),
        (toc_label, ("toc", "table of contents", "agenda", "course outline", "proposal")),
        ("Day-wise hands-on lab plan", ("lab plan", "hands-on lab", "hands on lab")),
        (commercial_label, ("commercial", "budget", "rate", "charges", "cost")),
        ("Relevant certifications", ("certification", "certifications", "certified")),
    ]
    items = [label for label, needles in checks if any(needle in source for needle in needles)]
    toc_action = _clean(requirement.get("toc_action") or (requirement.get("extracted") or {}).get("toc_action")).lower()
    scope_attached = bool(requirement.get("scope_attached") or (requirement.get("extracted") or {}).get("scope_attached"))
    if toc_action == "generate_by_clahan" and not scope_attached:
        items = [
            item for item in items
            if not any(term in item.lower() for term in ("toc", "course agenda", "day-wise"))
        ]
    flow_value = _clean(
        requirement.get("batch_flow") or requirement.get("batch_type") or requirement.get("requirement_type")
    ).lower()
    if "proposal" in flow_value:
        # The proposal trainer mail contains only the profile information the
        # client requested.  ToC and lab-cost are created by Clahan, and the
        # displayed commercial range is an offer, never a trainer quote request.
        managed_terms = (
            "commercial", "toc", "course agenda", "day-wise", "lab plan", "lab support", "lab cost",
            "experience", "current location",
        )
        items = [item for item in items if not any(term in item.lower() for term in managed_terms)]
    return items or ["Updated trainer profile/CV", "LinkedIn profile", "Availability"]


def _mail1_source_value(requirement: Dict[str, Any], label_pattern: str) -> str:
    source = _client_requirement_text(requirement)
    match = re.search(rf"(?im)^\s*(?:{label_pattern})\s*:\s*([^\r\n]+)", source)
    return _clean(match.group(1)).strip("* ") if match else ""


def _trainer_has_verified_detail(trainer: Dict[str, Any], detail: str) -> bool:
    """Return whether the requested item is already available in our trainer record."""
    detail = detail.lower()
    profile_text = " ".join(_clean(trainer.get(key)) for key in (
        "resume_text", "resume_summary", "resume", "profile", "profile_summary", "bio", "summary",
    )).strip()
    if detail == "profile":
        return bool(
            profile_text
            or _clean(trainer.get("resume_url"))
            or _clean(trainer.get("resume_link"))
            or _clean(trainer.get("cv_url"))
            or _clean(trainer.get("cv_link"))
            or _clean(trainer.get("resume_filename"))
            or _clean(trainer.get("source_file"))
        )
    if detail == "linkedin":
        return bool(_clean(trainer.get("linkedin")) or _clean(trainer.get("linkedin_url")))
    if detail == "experience":
        return bool(
            _safe_float(trainer.get("experience_years"), 0) > 0
            or _clean(trainer.get("experience"))
            or _clean(trainer.get("experience_summary"))
            or profile_text
        )
    if detail == "commercial":
        return any(_safe_float(trainer.get(key), 0) > 0 for key in (
            "commercial_amount", "commercial_rate", "day_rate", "rate_per_day", "per_day_rate", "rate",
        ))
    return False


def _trainer_missing_followup_details(trainer: Dict[str, Any], requirement: Dict[str, Any]) -> List[str]:
    """Return only details the platform cannot already source from the trainer record."""
    requested = _mail1_requested_items(requirement)
    missing: List[str] = []
    profile_text = " ".join(_clean(trainer.get(key)) for key in (
        "resume_text", "resume_summary", "resume", "profile", "profile_summary", "bio", "summary",
    )).strip()
    availability = _clean(
        trainer.get("availability")
        or trainer.get("available_dates")
        or trainer.get("availability_text")
        or trainer.get("slot_reply_text")
        or trainer.get("slots")
    )

    for item in requested:
        label = item.lower()
        if "availability" in label or "slot" in label:
            if not availability:
                missing.append("Availability for the specified training dates")
        elif ("profile" in label or "cv" in label or "resume" in label) and not (
            profile_text or _clean(trainer.get("resume_url")) or _clean(trainer.get("cv_url"))
        ):
            missing.append("Updated trainer profile/CV")
        elif "linkedin" in label and not _trainer_has_verified_detail(trainer, "linkedin"):
            missing.append("LinkedIn profile")
        elif "experience" in label and not _trainer_has_verified_detail(trainer, "experience"):
            missing.append("Relevant corporate training experience")
        # Commercials are platform-calculated and are never requested again.

    return list(dict.fromkeys(missing))


def _clean_confirmed_mail1_body(trainer_name: str, requirement: Dict[str, Any], domain: str, trainer: Optional[Dict[str, Any]] = None) -> str:
    if domain.lower() == "devops":
        domain = "DevOps"
    duration = _clean_duration_text(
        requirement.get("duration_text")
        or requirement.get("duration")
        or (f"{requirement.get('duration_days')} Days" if requirement.get("duration_days") else "")
        or (f"{requirement.get('duration_hours')} Hours" if requirement.get("duration_hours") else "")
    )
    dates = _clean(
        requirement.get("training_dates")
        or requirement.get("preferred_dates")
        or requirement.get("dates")
        or requirement.get("date_time_text")
        or requirement.get("timeline")
        or requirement.get("schedule")
        or requirement.get("training_schedule")
        or requirement.get("timing")
        or requirement.get("session_timing")
        or " to ".join(part for part in [requirement.get("timeline_start"), requirement.get("timeline_end")] if part)
    )
    mode = _clean(requirement.get("mode") or requirement.get("training_mode") or requirement.get("delivery_mode"))
    participants = _clean(requirement.get("participant_count") or requirement.get("participants") or requirement.get("audience_level"))
    training_time = _clean(requirement.get("training_time") or requirement.get("session_timing") or _mail1_source_value(requirement, r"training\s+time|timings?"))
    hands_on_lab = _clean(requirement.get("hands_on_lab") or _mail1_source_value(requirement, r"hands[-\s]?on\s+lab|lab\s+duration"))
    required_skills = requirement.get("required_skills") or requirement.get("skills") or []
    if isinstance(required_skills, str):
        required_skills = [item.strip() for item in re.split(r"[,;/]+", required_skills) if item.strip()]
    skills = [
        _clean(item) for item in required_skills
        if _clean(item) and _clean(item).lower() != domain.lower()
    ]
    technology_detail = domain + (f" including {', '.join(dict.fromkeys(skills[:6]))}" if skills else "")
    details = [f"- Technology: {technology_detail}"]
    if dates:
        details.append(f"- Training dates: {dates}")
    if duration:
        details.append(f"- Duration: {duration}")
    if training_time:
        details.append(f"- Training time: {training_time}")
    if hands_on_lab:
        details.append(f"- Hands-on lab: {hands_on_lab}")
    if mode:
        details.append(f"- Mode: {mode}")
    if participants:
        details.append(f"- Participants: {participants}")
    details.extend(_trainer_mail1_commercial_section(requirement))
    requested_items = _mail1_requested_items(requirement)
    trainer = trainer or {}
    selected = []
    for label, needle in [
        ("updated profile", "profile"),
        (f"relevant {domain} experience", "experience"),
        ("day-wise TOC", "toc"),
    ]:
        if any(needle in item.lower() for item in requested_items):
            selected.append(label)
    if "day-wise TOC" in selected:
        selected = [item for item in selected if item.lower() != "toc"]
    if not selected:
        selected = ["updated profile", f"relevant {domain} experience"]
    # Do not ask a trainer to repeat information we have already analysed and
    # stored. Availability and interview slots remain the only operational
    # response needed for a complete trainer record.
    selected = [
        item for item in selected
        if not (
            ("profile" in item.lower() and _trainer_has_verified_detail(trainer, "profile"))
            or ("linkedin" in item.lower() and _trainer_has_verified_detail(trainer, "linkedin"))
            or ("experience" in item.lower() and _trainer_has_verified_detail(trainer, "experience"))
            # Commercial is a Clahan-controlled calculation. It is never
            # requested from a trainer in Mail 1.
            or "commercial" in item.lower()
        )
    ]
    ask = ", ".join(dict.fromkeys(selected))
    request_line = (
        f"Please let us know whether you are available for these dates and share your {ask}.\n\n"
        if ask else
        "Please let us know whether you are available for these dates.\n\n"
    )
    slot_context = f" during {dates}" if dates else ""
    return (
        f"Hi {trainer_name or 'Trainer'},\n\n"
        "Hope you are doing well.\n\n"
        "We are reaching out regarding the following corporate training requirement.\n\n"
        "Requirement details noted:\n\n"
        f"{chr(10).join(details)}\n\n"
        f"{request_line}"
        f"Please also share three convenient interview/discussion slots{slot_context}, with the date, time, and time zone.\n"
        "Example:\n"
        "- 01 November 2026, 10:00 AM IST\n"
        "- 03 November 2026, 2:00 PM IST\n"
        "- 05 November 2026, 4:00 PM IST\n\n"
        "Once a slot is finalized, we will share the confirmed meeting invitation with you.\n\n"
        "Regards,\n"
        "Clahan Technologies"
    )


def _trainer_mail2_followup_body(
    trainer_name: str,
    requirement: Dict[str, Any],
    domain: str,
    missing_items: List[str],
) -> str:
    """The only permitted follow-up: ask solely for verified missing items."""
    technology = domain or _clean(requirement.get("technology_needed") or requirement.get("domain")) or "training"
    items = [f"- {item}" for item in missing_items if _clean(item)]
    if not items:
        raise ValueError("Mail 2 requires at least one verified missing trainer detail")
    return (
        f"Hi {trainer_name or 'Trainer'},\n\n"
        "Thank you for your response.\n\n"
        f"For the {technology} training requirement, please share only the following outstanding item(s):\n\n"
        f"{chr(10).join(items)}\n\n"
        "You do not need to resend any information already shared. Once this is available, we will proceed with the next coordination step.\n\n"
        "Regards,\n"
        "Clahan Technologies"
    )


def _has_raw_client_mail_leak(body: str) -> bool:
    text = _clean(body).lower()
    return any(marker in text for marker in (
        "requirement snapshot",
        "client requirement details",
        "appears aligned with your profile",
        "dear team,\nwe have",
    ))


def _client_requirement_text(requirement: Dict[str, Any]) -> str:
    metadata = requirement.get("metadata") or {}
    return _clean(
        requirement.get("requirement_source_text")
        or metadata.get("requirement_source_text")
        or requirement.get("client_requirement_text")
        or metadata.get("original_body")
        or requirement.get("original_body")
        or requirement.get("requirement_text")
        or requirement.get("description")
    )


def _trainer_slot_mail_toc_text(requirement: Dict[str, Any], trainer: Dict[str, Any], technology: str) -> str:
    toc_text = _clean(
        trainer.get("toc_reply_text")
        or trainer.get("toc_text")
        or trainer.get("toc")
        or trainer.get("course_agenda")
        or trainer.get("agenda")
    )
    if toc_text:
        return toc_text[:1200].strip()
    source_topics = (
        requirement.get("topics")
        or requirement.get("scope")
        or requirement.get("requested_topics")
        or (requirement.get("extracted") or {}).get("topics")
        or trainer.get("skills")
        or []
    )
    if isinstance(source_topics, str):
        topics = [part.strip(" -") for part in re.split(r"[,;\n]+", source_topics) if part.strip(" -")]
    elif isinstance(source_topics, list):
        topics = [_clean(item) for item in source_topics if _clean(item)]
    else:
        topics = []
    topics = topics[:8] or [technology]
    return "\n".join(f"- {item}" for item in topics)


def _trainer_commercial_amounts(trainer: Any) -> List[int]:
    if not isinstance(trainer, dict):
        return _commercial_amounts_from_text(trainer)
    amounts: List[int] = []
    for key in (
        "commercial_amount",
        "commercial_rate",
        "quoted_amount",
        "quoted_rate",
        "day_rate",
        "rate",
        "trainer_target_rate",
    ):
        amount = _money_to_int(trainer.get(key))
        if amount >= 1000 and amount not in amounts:
            amounts.append(amount)
    for key in (
        "commercials",
        "commercial_text",
        "commercial_details",
        "reply_text",
        "last_reply_snippet",
    ):
        for amount in _commercial_amounts_from_text(trainer.get(key)):
            if amount not in amounts:
                amounts.append(amount)
    return amounts


def _is_positive_reply_doc(reply: Dict[str, Any]) -> bool:
    sentiment = _clean(reply.get("sentiment") or reply.get("reply_sentiment")).lower()
    action = _clean(reply.get("action")).lower()
    scenario = _clean(reply.get("office_mail_category") or reply.get("scenario")).lower()
    if sentiment == "positive" or action == "mark_interested":
        return True
    if scenario in {"trainer_details_sent", "trainer_commercials_sent"}:
        return True
    text = _clean(reply.get("body") or reply.get("body_snippet") or reply.get("reply_text")).lower()
    if any(signal in text for signal in NEGATIVE_REPLY_SIGNALS):
        return False
    return any(signal in text for signal in POSITIVE_REPLY_SIGNALS)


def _client_email_from_requirement(requirement: Dict[str, Any], shortlist: Dict[str, Any]) -> str:
    return _clean(
        requirement.get("client_email")
        or requirement.get("email")
        or shortlist.get("client_email")
        or shortlist.get("client_contact_email")
    )


def _is_proposal_requirement(requirement: Dict[str, Any]) -> bool:
    flow_value = _clean(
        requirement.get("batch_flow")
        or requirement.get("batch_type")
        or requirement.get("requirement_type")
    ).lower()
    if "proposal" in flow_value:
        return True
    # Explicit workflow classification is authoritative.  Client prose such
    # as "upcoming corporate training" must not downgrade a confirmed batch
    # and suppress the mandatory Mail 1 ToC attachment.
    if "confirmed" in flow_value:
        return False
    request_text = _client_requirement_text(requirement).lower()
    return any(marker in request_text for marker in (
        "mode: to be confirmed",
        "duration: to be confirmed",
        "location: to be confirmed",
        "upcoming corporate training",
        "immediate requirement",
    ))


def _proposal_client_commercial_section(requirement: Dict[str, Any]) -> str:
    """Client quote for a proposal: trainer range plus the 30% Clahan margin."""
    if not _is_proposal_requirement(requirement):
        return ""
    quoted_rates = PROPOSAL_CLIENT_QUOTE_RANGE
    duration_days = _safe_int(
        requirement.get("duration_days")
        or requirement.get("commercial_working_days")
        or requirement.get("number_of_days"),
        0,
    )
    lines = []
    for amount in quoted_rates:
        line = f"- INR {amount:,.0f} per day/session"
        if duration_days > 1:
            line += f" x {duration_days} days = INR {amount * duration_days:,.0f} total"
        lines.append(line)
    return "Commercials for your review:\n" + "\n".join(lines) + "\n\n"


def _client_commercial_message(
    requirement: Dict[str, Any],
    shortlist: Dict[str, Any],
    trainer: Dict[str, Any],
    amounts: List[int],
) -> Dict[str, str]:
    technology = _clean(
        requirement.get("technology_needed")
        or requirement.get("technology")
        or requirement.get("domain")
        or shortlist.get("technology_needed")
        or "training"
    )
    client_name = _clean(requirement.get("client_name") or requirement.get("client_company") or shortlist.get("client_name")) or "Client"
    trainer_name = _clean(trainer.get("name") or trainer.get("trainer_name")) or "Trainer"
    client_amounts = sorted({round(amount * (1 + CLIENT_COMMERCIAL_MARKUP)) for amount in amounts})
    duration_days = _safe_int(
        requirement.get("duration_days")
        or requirement.get("commercial_working_days")
        or requirement.get("number_of_days"),
        0,
    )
    rate_lines_list = []
    for amount in client_amounts:
        line = f"- INR {amount:,.0f} per day/session"
        if duration_days > 1:
            line += f" x {duration_days} days = INR {amount * duration_days:,.0f} total"
        rate_lines_list.append(line)
    rate_lines = "\n".join(rate_lines_list)
    subject = f"Shortlisted Trainer Profile - {technology}"
    body = (
        f"{_client_time_greeting(client_name)},\n\n"
        f"Trainer {trainer_name} has shared the required details and commercials for the {technology} requirement.\n\n"
        "Trainer Summary:\n"
        f"- Trainer: {trainer_name}\n"
        f"- Technology: {technology}\n\n"
        "Commercials for your review:\n"
        f"{rate_lines}\n\n"
        "Please review and confirm if we can proceed with this trainer. Once approved, we will move ahead with interview/slot coordination.\n\n"
        "Regards,\nClahan Technologies\nsujithaofficial585@gmail.com"
    )
    return {"subject": subject, "body": body}


def _trainer_interview_message(
    *,
    trainer_name: str,
    technology: str,
    requirement_id: str,
    interview_date: str,
    platform: str,
    interview_link: str,
) -> Dict[str, str]:
    subject = f"Interview Schedule Confirmation - {technology} | Ref: {requirement_id}"
    date_line = f"Date & Time: {interview_date}\n" if interview_date else ""
    body = (
        f"Dear {trainer_name or 'Trainer'},\n\n"
        f"Your interview/discussion for the {technology} training requirement is confirmed.\n\n"
        "Interview Details:\n"
        f"{date_line}"
        f"Platform: {platform or 'Google Meet'}\n"
        f"Meeting Link: {_clean(interview_link)}\n\n"
        "Please join at the scheduled time and let us know promptly if you need a change.\n\n"
        "Regards,\n"
        "Clahan Technologies"
    )
    return {"subject": subject, "body": body}


def _interview_calendar_invite(
    *,
    attendee_name: str,
    attendee_email: str,
    technology: str,
    interview_date: str,
    interview_link: str,
) -> Optional[Dict[str, str]]:
    """Create the invite data locally; no email template endpoint is involved."""
    raw_start = _clean(interview_date)
    if not raw_start:
        return None
    try:
        start = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
        if start.tzinfo is not None:
            start = start.astimezone(LOCAL_TZ).replace(tzinfo=None)
        end = start + timedelta(hours=1)
    except ValueError:
        # The confirmation email still contains the client-selected slot;
        # only an .ics attachment requires an ISO-compatible date/time.
        return None
    return {
        "summary": f"Interview Discussion - {technology}",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "timezone": "Asia/Kolkata",
        "location": "Google Meet",
        "description": f"Clahan Technologies interview discussion for {technology}.\n\nMeeting link: {_clean(interview_link)}",
        "organizer_name": "Clahan Technologies",
        "organizer_email": _clean(getattr(settings, "FROM_EMAIL", None) or "sujithaofficial585@gmail.com"),
        "attendee_name": attendee_name,
        "attendee_email": attendee_email,
        "meeting_url": _clean(interview_link),
    }


def _requested_client_attachments(requirement: Dict[str, Any]) -> tuple[bool, bool, bool]:
    """Return whether the client requested a profile, TOC, and/or lab-cost workbook."""
    requested = [
        _clean(item).lower()
        for item in (
            requirement.get("requested_details")
            or (requirement.get("extracted") or {}).get("requested_details")
            or []
        )
        if _clean(item)
    ]
    request_text = "\n".join([*requested, _client_requirement_text(requirement).lower()])
    wants_profile = any(term in request_text for term in ("trainer profile", "profile/cv", "profile / cv", "resume", "curriculum vitae", "cv"))
    wants_toc = any(term in request_text for term in ("toc", "table of content", "table of contents", "course agenda", "curriculum"))
    explicit_lab_cost_request = any(
        term in request_text for term in (
            "lab cost", "lab-cost", "lab charges", "lab estimate", "lab quotation",
            "lab quote", "lab pricing", "cost for lab", "price for lab", "lab price",
        )
    )
    # In a confirmed batch, a request for lab requirements/tools, lab access,
    # setup, or a local/cloud lab choice is also a request for the associated
    # lab estimate. That is the business rule used by the automatic handoff;
    # clients do not always write the phrase "lab cost".
    lab_delivery_request = bool(re.search(
        r"\blab(?:oratory)?\s+(?:requirements?|required\s+tools?|setup|access|support|availability|preference|environment)\b"
        r"|\b(?:local|cloud)\s+lab(?:oratory)?\b"
        r"|\blab(?:oratory)?\b.{0,80}\b(?:required\s+tools?|local|cloud|access)\b",
        request_text,
        flags=re.IGNORECASE | re.DOTALL,
    ))
    managed_lab_request = any(
        "lab" in _clean(item).lower() and any(
            word in _clean(item).lower() for word in ("cost", "availability", "setup", "tool")
        )
        for item in (requirement.get("clahan_managed_details") or [])
    )
    structured_lab_request = any(
        _clean(item.get("category")) in {"lab_requirements", "lab_delivery_preference"}
        for item in (requirement.get("requirement_items") or [])
        if isinstance(item, dict)
    )
    wants_lab_cost = bool(requirement.get("lab_cost_requested")) or explicit_lab_cost_request or lab_delivery_request or managed_lab_request or structured_lab_request
    return wants_profile, wants_toc, wants_lab_cost


def _has_client_supplied_toc(requirement: Dict[str, Any]) -> bool:
    for item in requirement.get("source_attachments") or []:
        if not isinstance(item, dict) or not item.get("safe_client_scope"):
            continue
        analysis = item.get("analysis") or {}
        filename = _clean(item.get("filename")).lower()
        if analysis.get("attachment_type") == "toc" or re.search(
            r"\b(?:toc|agenda|curriculum|syllabus|course[ _-]?outline)\b", filename,
        ):
            return True
    return False


def _client_supplied_toc_topics(requirement: Dict[str, Any]) -> List[str]:
    """Return client agenda topics supplied as a safe source attachment.

    Client-owned ToCs are authoritative: they are used for lab costing and
    must never be replaced by a generated trainer ToC in the client handoff.
    """
    topics: List[str] = []
    for item in requirement.get("source_attachments") or []:
        if not isinstance(item, dict) or not item.get("safe_client_scope"):
            continue
        filename = _clean(item.get("filename")).lower()
        analysis = item.get("analysis") or {}
        is_toc = analysis.get("attachment_type") == "toc" or bool(re.search(
            r"\b(?:toc|agenda|curriculum|syllabus|course[ _-]?outline)\b", filename,
        ))
        if not is_toc:
            continue
        candidates = analysis.get("topic_candidates") or analysis.get("toc_rows") or []
        if not candidates:
            candidates = str(analysis.get("extracted_text") or "").splitlines()
        for topic in candidates:
            value = _clean(topic.get("text") if isinstance(topic, dict) else topic)
            if value and value.lower() not in {existing.lower() for existing in topics}:
                topics.append(value)
    return topics[:180]


def _client_training_summary(requirement: Dict[str, Any]) -> str:
    rows: List[str] = []
    for label, keys in (
        ("Technology", ("technology_needed", "technology", "domain")),
        ("Training dates", ("training_dates", "date_range", "training_date", "dates")),
        ("Duration", ("duration", "duration_days", "number_of_days")),
        ("Timings", ("timing", "timings", "training_timing", "time")),
    ):
        value = ""
        for key in keys:
            value = _clean(requirement.get(key))
            if value:
                break
        if value:
            rows.append(f"- {label}: {value}")
    return "\n".join(rows)


def _trainer_scope_attachments(requirement: Dict[str, Any]) -> List[Dict[str, str]]:
    """Forward only bounded, explicitly captured client scope documents to trainers."""
    allowed_extensions = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt")
    subtype_by_extension = {
        ".pdf": "pdf", ".doc": "msword", ".docx": "vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xls": "vnd.ms-excel", ".xlsx": "vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".csv": "csv", ".txt": "plain",
    }
    forwarded: List[Dict[str, str]] = []
    total_bytes = 0
    for item in requirement.get("source_attachments") or []:
        if not isinstance(item, dict) or not item.get("safe_client_scope"):
            continue
        filename = re.sub(r"[\r\n\\/]+", "_", _clean(item.get("filename")))[:160]
        content_base64 = _clean(item.get("content_base64"))
        extension = next((ext for ext in allowed_extensions if filename.lower().endswith(ext)), "")
        size_bytes = int(item.get("size_bytes") or 0)
        if not filename or not content_base64 or not extension or size_bytes <= 0 or size_bytes > 4 * 1024 * 1024:
            continue
        if total_bytes + size_bytes > 6 * 1024 * 1024:
            break
        forwarded.append({
            "filename": filename,
            "content_base64": content_base64,
            "subtype": subtype_by_extension[extension],
        })
        total_bytes += size_bytes
    return forwarded


def _client_toc_scope_attachments(requirement: Dict[str, Any]) -> List[Dict[str, str]]:
    """Return only the client-owned ToC attachment for the client handoff."""
    allowed_extensions = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt")
    subtype_by_extension = {
        ".pdf": "pdf", ".doc": "msword", ".docx": "vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xls": "vnd.ms-excel", ".xlsx": "vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".csv": "csv", ".txt": "plain",
    }
    attachments: List[Dict[str, str]] = []
    for item in requirement.get("source_attachments") or []:
        if not isinstance(item, dict) or not item.get("safe_client_scope"):
            continue
        analysis = item.get("analysis") or {}
        filename = re.sub(r"[\r\n\\/]+", "_", _clean(item.get("filename")))[:160]
        is_toc = analysis.get("attachment_type") == "toc" or bool(re.search(
            r"\b(?:toc|agenda|curriculum|syllabus|course[ _-]?outline)\b", filename.lower(),
        ))
        extension = next((ext for ext in allowed_extensions if filename.lower().endswith(ext)), "")
        content_base64 = _clean(item.get("content_base64"))
        size_bytes = int(item.get("size_bytes") or 0)
        if not is_toc or not filename or not content_base64 or not extension or size_bytes <= 0 or size_bytes > 4 * 1024 * 1024:
            continue
        attachments.append({
            "filename": filename,
            "content_base64": content_base64,
            "subtype": subtype_by_extension[extension],
        })
        break
    return attachments


def _requested_toc_output_format(requirement: Dict[str, Any]) -> str:
    """Match an explicit client format; otherwise send the editable Excel TOC."""
    attachment_names = list(
        requirement.get("attachment_names")
        or (requirement.get("extracted") or {}).get("attachment_names")
        or []
    )
    source_attachments = requirement.get("source_attachments") or (requirement.get("extracted") or {}).get("source_attachments") or []
    for item in source_attachments:
        if isinstance(item, dict) and item.get("filename"):
            attachment_names.append(item.get("filename"))
    request_text = "\n".join([
        _client_requirement_text(requirement),
        *[_clean(item) for item in (requirement.get("requested_details") or [])],
        *[_clean(item) for item in attachment_names],
    ]).lower()
    if re.search(r"\b(?:xlsx|xls|excel|spreadsheet)\b", request_text) or any(
        _clean(name).lower().endswith((".xlsx", ".xls")) for name in attachment_names
    ):
        return "xlsx"
    if re.search(r"\b(?:pdf|docx|doc|word document)\b", request_text) or any(
        _clean(name).lower().endswith((".pdf", ".docx", ".doc")) for name in attachment_names
    ):
        return "pdf"
    return "xlsx"


def _requested_trainer_details_for_client(
    requirement: Dict[str, Any],
    trainer: Dict[str, Any],
    *,
    profile_attached: bool = False,
    toc_attached: bool = False,
    client_toc_supplied: bool = False,
) -> str:
    requested = {
        _clean(item).lower()
        for item in (
            requirement.get("requested_details")
            or (requirement.get("extracted") or {}).get("requested_details")
            or []
        )
        if _clean(item)
    }
    if not requested:
        requested = {"trainer profile", "cv", "resume", "linkedin profile", "availability", "commercials"}

    def wanted(*needles: str) -> bool:
        return any(any(needle in item for needle in needles) for item in requested)

    def first_value(*keys: str) -> str:
        for key in keys:
            value = trainer.get(key)
            if isinstance(value, list):
                text = ", ".join(_clean(item) for item in value if _clean(item))
            else:
                text = _clean(value)
            if text:
                return text
        return ""

    def clean_reply_text(value: str) -> str:
        text = _clean(value)
        text = re.split(r"(?im)^\s*on .+ wrote:\s*$", text)[0]
        text = re.split(r"(?im)^\s*from:\s*", text)[0]
        lines = []
        for line in text.splitlines():
            stripped = _clean(line)
            if not stripped or stripped.startswith(">"):
                continue
            if re.search(r"(?i)\b(dear|regards),?\s*(clahan|team|trainer|megha|mohit)?\b", stripped):
                continue
            lines.append(stripped)
        return "\n".join(lines).strip()

    reply_detail_text = clean_reply_text(first_value("details_reply_text", "trainer_details_text", "mail1_reply_text", "mail2_reply_text", "reply_text", "last_reply_snippet"))

    def extract_links(text: str) -> List[str]:
        links = re.findall(r"https?://[^\s<>)]+", text or "", flags=re.IGNORECASE)
        cleaned: List[str] = []
        for link in links:
            clean_link = link.rstrip(".,;:")
            if clean_link not in cleaned:
                cleaned.append(clean_link)
        return cleaned

    def linkedin_link(text: str) -> str:
        for link in extract_links(text):
            if "linkedin.com" in link.lower():
                return link
        return ""

    def reply_lines(*needles: str, limit: int = 3) -> str:
        matches: List[str] = []
        for line in reply_detail_text.splitlines():
            text = _clean(line)
            if not text:
                continue
            lower = text.lower()
            if any(needle in lower for needle in needles):
                matches.append(text)
            if len(matches) >= limit:
                break
        return "; ".join(matches)

    lines: List[str] = []
    trainer_name = _clean(trainer.get("name") or trainer.get("trainer_name"))
    if trainer_name:
        lines.append(f"- Trainer: {trainer_name}")
    if wanted("trainer profile", "profile"):
        resume = first_value("resume_url", "resume_link", "cv_url", "cv_link", "resume_filename", "source_file")
        if profile_attached:
            lines.append("- Trainer profile/CV: attached for review")
        elif resume:
            lines.append(f"- Trainer profile/CV: {resume}")
    if wanted("cv", "resume"):
        resume = first_value("resume_url", "resume_link", "cv_url", "cv_link", "resume_filename", "source_file")
        if profile_attached:
            resume_line = "- CV/resume: attached for review"
            if resume_line not in lines:
                lines.append(resume_line)
        elif resume:
            resume_line = f"- CV/resume: {resume}"
            if resume_line not in lines:
                lines.append(resume_line)
    if wanted("linkedin", "linked in"):
        linkedin = first_value("linkedin", "linkedin_url", "linkedin_profile") or linkedin_link(reply_detail_text)
        if linkedin:
            lines.append(f"- LinkedIn profile: {linkedin}")
    if wanted("availability", "available", "slot"):
        availability = first_value("availability", "available_dates", "availability_text")
        if availability:
            lines.append(f"- Availability: {clean_reply_text(availability)[:300]}")
    if wanted("commercial", "rate"):
        amounts = _trainer_commercial_amounts(trainer.get("commercials") or trainer.get("commercial_text") or trainer.get("commercial_details") or reply_detail_text)
        if amounts:
            lines.append("- Commercials: " + ", ".join(f"INR {amount:,.0f} per day/session" for amount in amounts))
        else:
            commercial_text = first_value("commercials", "commercial_text", "commercial_details") or reply_lines("commercial", "rate", "charges", "fee", "inr", "rs", "₹")
            if commercial_text:
                lines.append(f"- Commercials: {commercial_text[:400]}")
    if toc_attached:
        lines.append("- ToC/course agenda: attached for review")
    elif wanted("toc", "agenda", "curriculum") and not client_toc_supplied:
        toc = first_value("toc_reply_text", "toc_text", "toc", "course_agenda", "agenda")
        if toc:
            lines.append(f"- ToC/course agenda: {toc[:800]}")
    if wanted("certification"):
        certifications = first_value("certifications", "certification")
        if certifications:
            lines.append(f"- Certifications: {certifications}")
    if wanted("lab"):
        lab = first_value("lab_support", "lab_details", "lab_cost")
        if lab:
            lines.append(f"- Lab support: {lab}")
    return "\n".join(lines)


async def _post_with_local_fallback(
    client: httpx.AsyncClient,
    url: str,
    **kwargs: Any,
) -> httpx.Response:
    try:
        return await client.post(url, **kwargs)
    except httpx.RequestError:
        for service_base, local_base in LOCAL_SERVICE_FALLBACKS.items():
            if url.startswith(service_base):
                fallback_url = local_base + url[len(service_base):]
                return await client.post(fallback_url, **kwargs)
        raise


async def _get_with_local_fallback(
    client: httpx.AsyncClient,
    url: str,
    **kwargs: Any,
) -> httpx.Response:
    try:
        return await client.get(url, **kwargs)
    except httpx.RequestError:
        for service_base, local_base in LOCAL_SERVICE_FALLBACKS.items():
            if url.startswith(service_base):
                fallback_url = local_base + url[len(service_base):]
                return await client.get(fallback_url, **kwargs)
        raise


async def _load_requirement_from_core(requirement_id: str, db: AsyncIOMotorDatabase) -> Optional[Dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await _get_with_local_fallback(client, f"{CORE_API_SVC}/api/v1/requirements/{requirement_id}")
        if response.status_code >= 400:
            return None
        requirement = response.json()
        if not isinstance(requirement, dict) or not requirement.get("requirement_id"):
            return None
        requirement.pop("_id", None)
        await db["requirements"].update_one(
            {"requirement_id": requirement["requirement_id"]},
            {"$set": {**requirement, "updated_at": datetime.utcnow()}},
            upsert=True,
        )
        return requirement
    except Exception:
        logger.exception("Failed to load requirement %s from core-api", requirement_id)
        return None


def _norm(value: Any) -> str:
    if isinstance(value, list):
        value = " ".join(_clean(item) for item in value)
    elif isinstance(value, dict):
        value = " ".join(f"{key} {val}" for key, val in value.items())
    return re.sub(r"[^a-z0-9+#.]+", " ", _clean(value).lower()).strip()


def _tokens(value: Any) -> set[str]:
    return {token for token in _norm(value).split() if len(token) > 1}


def _technology_tokens(value: Any) -> List[str]:
    stopwords = {"and", "with", "the", "for", "training", "trainer", "requirement"}
    tokens: List[str] = []
    for token in re.findall(r"[a-z0-9+#.]+", _clean(value).lower()):
        if len(token) > 1 and token not in stopwords and token not in tokens:
            tokens.append(token)
    return tokens


def _date_tokens(value: Any) -> set[str]:
    text = _clean(value).lower()
    tokens: set[str] = set()
    for match in re.finditer(r"\b\d{1,2}\s*[/-]\s*\d{1,2}(?:\s*[/-]\s*\d{2,4})?\b", text):
        tokens.add(re.sub(r"\s+", "", match.group(0)))
    for match in re.finditer(
        r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*(?:\s+\d{2,4})?\b",
        text,
    ):
        tokens.add(re.sub(r"\s+", " ", match.group(0)))
    return tokens


def _requirement_date_tokens(requirement: Dict[str, Any]) -> set[str]:
    tokens: set[str] = set()
    for key in ("training_dates", "preferred_dates", "timeline_start", "timeline_end", "dates"):
        tokens |= _date_tokens(requirement.get(key))
    return tokens


async def _trainer_has_date_conflict(db: AsyncIOMotorDatabase, trainer_id: str, requirement: Dict[str, Any]) -> bool:
    required_tokens = _requirement_date_tokens(requirement)
    if not trainer_id or not required_tokens:
        return False
    active_stages = {"slot_booked", "interview_scheduled", "selected", "toc_requested", "toc_received_pending", "training_confirmed"}
    cursor = db["shortlists"].find(
        {"top_trainers.trainer_id": trainer_id},
        {"_id": 0, "requirement_id": 1, "training_dates": 1, "timeline_start": 1, "timeline_end": 1, "top_trainers": 1},
    )
    async for shortlist in cursor:
        if shortlist.get("requirement_id") == requirement.get("requirement_id"):
            continue
        linked_req = await db["requirements"].find_one({"requirement_id": shortlist.get("requirement_id")}, {"_id": 0}) or {}
        for trainer in shortlist.get("top_trainers") or []:
            if _clean(trainer.get("trainer_id")) != _clean(trainer_id):
                continue
            stage = _clean(trainer.get("pipeline_status") or trainer.get("status")).lower()
            if stage not in active_stages:
                continue
            conflict_text = " ".join(_clean(v) for v in [
                trainer.get("interview_date"),
                trainer.get("training_dates"),
                trainer.get("slot_reply_text"),
                shortlist.get("training_dates"),
                shortlist.get("timeline_start"),
                shortlist.get("timeline_end"),
            ])
            if required_tokens & (_date_tokens(conflict_text) | _requirement_date_tokens(linked_req)):
                return True
    return False


def _profile_text(trainer: Dict[str, Any]) -> str:
    parts = [
        trainer.get("name"),
        trainer.get("trainer_name"),
        trainer.get("title"),
        trainer.get("role_designation"),
        trainer.get("technologies"),
        trainer.get("skills"),
        trainer.get("certifications"),
        trainer.get("primary_category"),
        trainer.get("technology_category"),
        trainer.get("category"),
        trainer.get("domain"),
        trainer.get("secondary_categories"),
        trainer.get("specialisation_tags"),
        trainer.get("specialty_tags"),
        trainer.get("industry_focus"),
        trainer.get("summary"),
        trainer.get("past_clients"),
        trainer.get("combined_text", "")[:8000] if isinstance(trainer.get("combined_text"), str) else "",
        trainer.get("resume", "")[:5000] if isinstance(trainer.get("resume"), str) else "",
    ]
    return _norm(parts)


def _profile_evidence_text(trainer: Dict[str, Any]) -> str:
    return _norm([
        _profile_text(trainer),
        trainer.get("details_reply_text"),
        trainer.get("trainer_details_text"),
        trainer.get("mail1_reply_text"),
        trainer.get("mail2_reply_text"),
        trainer.get("reply_text"),
        trainer.get("last_reply_snippet"),
    ])


def _client_profile_evidence_items(trainer: Dict[str, Any], technology: str) -> List[str]:
    evidence_text = _profile_evidence_text(trainer)
    items: List[str] = []
    missing: List[str] = []
    technology_tokens = _technology_tokens(technology)
    matched_tokens = [token for token in technology_tokens if token in evidence_text]
    if technology_tokens and len(matched_tokens) == len(technology_tokens):
        items.append(f"Confirmed technology alignment: {_clean(technology)}")
    elif matched_tokens:
        items.append(f"Partial technology evidence found: {', '.join(matched_tokens)}")
        missing.append(f"Additional {_clean(technology)} evidence should be confirmed with trainer")
    elif technology:
        missing.append(f"{_clean(technology)} evidence not found in available trainer data")

    if re.search(r"\b(?:training|trained|trainer|workshop|bootcamp|session|facilitat|delivered)\w*\b", evidence_text):
        items.append("Training delivery experience: confirmed from trainer profile or reply")
    else:
        missing.append("Training delivery experience proof not found")

    if re.search(r"\b(?:implementation|implemented|deploy(?:ed|ment)?|project|migration|pipeline|production|devops|automation|iac|infrastructure)\w*\b", evidence_text):
        items.append("Implementation/project exposure: confirmed from trainer profile or reply")
    else:
        missing.append("Implementation/project proof not found")

    approved_bullets = [
        _clean(value) for value in _as_list(trainer.get("approved_profile_bullets")) if _clean(value)
    ] if trainer.get("profile_enhancement_status") == "approved" else []
    if approved_bullets:
        items.extend(f"Approved client-fit point: {value}" for value in approved_bullets[:4])

    items.extend(f"Needs confirmation: {value}" for value in missing[:3])
    return items


def _client_profile_ready_for_handoff(trainer: Dict[str, Any], technology: str) -> bool:
    """Client TOC/profile handoff is allowed only with requirement-aligned trainer evidence."""
    evidence_items = _client_profile_evidence_items(trainer, technology)
    return bool(evidence_items) and not any(str(item).startswith("Needs confirmation:") for item in evidence_items)


def _resume_confirms_domain_experience(trainer: Dict[str, Any], domain: str) -> bool:
    resume_text = _norm([
        trainer.get("combined_text", "")[:8000] if isinstance(trainer.get("combined_text"), str) else "",
        trainer.get("resume", "")[:5000] if isinstance(trainer.get("resume"), str) else "",
        trainer.get("summary"),
        trainer.get("experience_raw"),
    ])
    domain_terms = [term.lower() for term in re.findall(r"[a-z0-9+#.]+", _clean(domain)) if len(term) > 1]
    has_domain = bool(domain_terms) and all(term in resume_text for term in domain_terms)
    has_experience = bool(re.search(r"\b(?:experience|implementation|implemented|training|trained|delivered|facilitat)\w*\b", resume_text))
    return has_domain and has_experience


def _category_text(trainer: Dict[str, Any]) -> str:
    return _norm([
        trainer.get("primary_category"),
        trainer.get("technology_category"),
        trainer.get("category"),
        trainer.get("domain"),
        trainer.get("secondary_categories"),
        trainer.get("specialisation_tags"),
        trainer.get("specialty_tags"),
        trainer.get("technologies"),
        trainer.get("skills"),
    ])


def _trainer_experience(trainer: Dict[str, Any]) -> float:
    direct = _safe_float(trainer.get("experience_years"), -1)
    if direct >= 0:
        return direct
    raw = " ".join([
        _clean(trainer.get("experience_raw")),
        _clean(trainer.get("summary")),
        _clean(trainer.get("resume")),
    ])
    match = re.search(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)", raw, flags=re.IGNORECASE)
    return _safe_float(match.group(1), 0.0) if match else 0.0


def _has_resume(trainer: Dict[str, Any]) -> bool:
    return bool(
        trainer.get("resume")
        or trainer.get("resume_url")
        or trainer.get("upload_id")
        or trainer.get("source_sheet") == "resume_upload"
    )


def _term_matches(terms: List[str], text: str) -> List[str]:
    matches: List[str] = []
    for term in terms:
        norm = _norm(term)
        if norm and f" {norm} " in f" {text} ":
            matches.append(term)
    return matches


def _quality(score: float) -> str:
    if score >= 80:
        return "excellent"
    if score >= 60:
        return "strong"
    if score >= 40:
        return "good"
    return "exploratory"


def _score_trainer(trainer: Dict[str, Any], requirement: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if requirement.get("must_have_linkedin") and not trainer.get("linkedin"):
        return None
    if requirement.get("must_have_resume") and not _has_resume(trainer):
        return None

    technology = _clean(
        requirement.get("technology_needed")
        or requirement.get("domain")
        or requirement.get("title")
        or requirement.get("job_title")
    )
    required_skills = _as_list(requirement.get("required_skills") or requirement.get("skills"))
    preferred_skills = _as_list(requirement.get("preferred_skills"))
    required_terms = [term for term in [technology, *required_skills] if term]

    profile = _profile_text(trainer)
    category = _category_text(trainer)
    score = 0.0
    breakdown: Dict[str, Any] = {}

    technology_tokens = _tokens(technology)
    all_tokens = set(category.split()) | set(profile.split())
    if technology:
        norm_technology = _norm(technology)
        if f" {norm_technology} " in f" {category} ":
            tech_score = 35.0
        elif f" {norm_technology} " in f" {profile} ":
            tech_score = 28.0
        else:
            tech_score = 18.0 * (len(technology_tokens & all_tokens) / max(len(technology_tokens), 1))
        score += tech_score
        breakdown["technology"] = round(tech_score, 2)

    required_matches = _term_matches(required_skills, profile)
    preferred_matches = _term_matches(preferred_skills, profile)
    skill_score = 25.0 * (len(required_matches) / max(len(required_skills), 1)) if required_skills else 0.0
    skill_score += min(8.0, 2.0 * len(preferred_matches))
    score += skill_score
    breakdown["skills"] = round(skill_score, 2)
    breakdown["matched_required_skills"] = required_matches
    breakdown["matched_preferred_skills"] = preferred_matches

    min_exp = _safe_float(requirement.get("min_experience_years"), 0.0)
    exp = _trainer_experience(trainer)
    if min_exp > 0 and exp < min_exp:
        return None
    exp_score = 15.0 if min_exp and exp >= min_exp else min(exp * 1.5, 15.0)
    score += exp_score
    breakdown["experience"] = round(exp_score, 2)

    preferred_location = _clean(requirement.get("preferred_location") or requirement.get("location"))
    trainer_location = _clean(trainer.get("location"))
    location_score = 10.0 if preferred_location and _norm(preferred_location) in _norm(trainer_location) else 0.0
    score += location_score
    breakdown["location"] = round(location_score, 2)

    credibility_score = 0.0
    if trainer.get("linkedin"):
        credibility_score += 2.0
    if _has_resume(trainer):
        credibility_score += 3.0
    if _as_list(trainer.get("certifications")):
        credibility_score += 2.0
    if trainer.get("training_count") or trainer.get("past_clients"):
        credibility_score += 2.0
    credibility_score += min(_safe_float(trainer.get("resume_rank_score"), 0.0) * 0.1, 3.0)
    score += credibility_score
    breakdown["credibility"] = round(credibility_score, 2)

    if required_terms and not _term_matches(required_terms, profile) and score < 20:
        return None

    public = {k: v for k, v in trainer.items() if k not in {"_id", "combined_text"}}
    public["trainer_id"] = _clean(public.get("trainer_id")) or f"TR-{uuid.uuid4().hex[:8].upper()}"
    public["name"] = _clean(public.get("name") or public.get("trainer_name") or "Trainer")
    public["email"] = _clean(public.get("email") or public.get("trainer_email"))
    public["title"] = _clean(public.get("role_designation") or public.get("title"))
    public["technologies"] = _clean(public.get("technologies") or public.get("technology_category") or public.get("domain"))
    public["experience_years"] = exp
    public["match_score"] = round(min(score, 100.0), 2)
    public["score_breakdown"] = breakdown
    public["match_quality"] = _quality(public["match_score"])
    public["recommended_next_action"] = "Contact trainer and confirm availability"
    return public


def _merge_pipeline_state(new_trainer: Dict[str, Any], old_trainer: Dict[str, Any]) -> Dict[str, Any]:
    preserve_keys = {
        "pipeline_status",
        "status",
        "last_mail_type",
        "last_mailed_at",
        "email_stage",
        "reply_received",
        "reply_text",
        "reply_sentiment",
        "slots",
        "selected",
        "client_slot_sent",
        "client_slot_sent_at",
        "commercial_status",
        "toc_status",
        "interview_date",
        "interview_link",
    }
    merged = dict(new_trainer)
    for key, value in old_trainer.items():
        if key in preserve_keys or key.startswith("last_") or key.endswith("_at"):
            merged[key] = value
    return merged


def _is_active_pipeline_trainer(trainer: Dict[str, Any]) -> bool:
    stage = _clean(trainer.get("pipeline_status") or trainer.get("status")).lower()
    return stage in ACTIVE_PIPELINE_STAGES


async def _ai_trainer_mail1(
    db: AsyncIOMotorDatabase,
    *,
    trainer_name: str,
    domain: str,
    requirement: Dict[str, Any],
    fallback_subject: str,
    fallback_body: str,
) -> Optional[Dict[str, str]]:
    """Write Mail 1 from workflow facts when the shared AI wording switch is enabled."""
    setting = await db["automation_settings"].find_one({"key": "generation_mode"}, {"_id": 0}) or {}
    if _clean(setting.get("value")).lower() != "ai" or not _clean(settings.OPENAI_API_KEY):
        return None
    # Keep Mail 1 grounded in the complete client scope.  The deterministic
    # parser may not have extracted every item from a naturally-written mail,
    # so include the original client request as an authoritative fact too.
    facts = {
        key: requirement.get(key) for key in (
            "technology_needed", "domain", "duration_days", "duration_hours", "duration_text",
            "training_dates", "preferred_dates", "timing", "mode", "location", "preferred_location",
            "participant_count", "audience_level", "topics", "custom_topics", "scope_text",
            "batch_flow", "requested_details", "clahan_managed_details", "toc_requested",
            "toc_action", "hands_on_lab", "lab_duration_hours", "lab_hours_per_day",
            "total_lab_duration_hours",
        ) if requirement.get(key) not in (None, "", [], {})
    }
    trainer_offer = _trainer_mail1_commercial_text(requirement)
    if trainer_offer:
        facts["offered_trainer_commercial"] = trainer_offer
    try:
        from openai import AsyncOpenAI

        response = await AsyncOpenAI(api_key=settings.OPENAI_API_KEY).responses.create(
            model=settings.OPENAI_MODEL or "gpt-5.5",
            reasoning={"effort": "low"},
            text={"verbosity": "low"},
            instructions=(
                "Write a concise, natural professional trainer Mail 1 for Clahan Technologies from the supplied "
                "workflow facts only. Do not use, imitate, or mention a template. For a confirmed batch, accurately "
                "cover the client's requested scope: ask for the updated CV/profile, LinkedIn profile, relevant "
                "training experience, delivery availability, and exactly three convenient interview/discussion slots "
                "with date, time, and time zone. Include this clear slot-format example in the email: 04 September "
                "2026, 10:00 AM IST; 04 September 2026, 2:00 PM IST; 04 September 2026, 4:00 PM IST. If the client "
                "requested a ToC, say the attached/generated ToC is to "
                "be reviewed and confirmed for delivery; do not invent its contents. Mention known lab requirements "
                "only as delivery scope, never ask the trainer to quote lab cost. If an offered trainer commercial "
                "is present, state only that offer. Never mention client pricing, margins, percentages, internal "
                "calculations, internal IDs, or internal workflow. Never invent dates, rates, client names, "
                "attachments, slots, or commitments. Address the trainer by name and finish "
                "with exactly: Regards, Clahan Technologies. "
                "Return exactly: SUBJECT: <subject> followed by BODY: <body>."
            ),
            input=(
                f"Trainer: {trainer_name}\nDomain: {domain}\nTrainer-safe requirement facts: {facts}\n"
                "Mail 1 workflow rule: request availability and exactly three interview/discussion slots."
            ),
            max_output_tokens=650,
        )
        text = _clean(response.output_text)
        subject_match = re.search(r"SUBJECT:\s*(.+)", text, flags=re.IGNORECASE)
        body_match = re.search(r"BODY:\s*([\s\S]+)", text, flags=re.IGNORECASE)
        body = _clean(body_match.group(1) if body_match else text)
        if not body:
            return None
        return {"subject": _clean(subject_match.group(1) if subject_match else fallback_subject) or fallback_subject, "body": body}
    except Exception as exc:
        logger.warning("AI Mail 1 generation failed; using approved template: %s", exc)
        return None


def _ensure_mail1_slot_examples(body: str) -> str:
    """Keep the required slot format visible even when the LLM omits it."""
    text = _clean(body)
    # The approved Mail 1 template already contains the request and examples.
    # Do not append a second slot block when an AI/manual body has equivalent
    # wording or examples with different dates.
    if (
        re.search(r"three convenient interview/discussion slots", text, flags=re.IGNORECASE)
        or re.search(r"three slots in this format", text, flags=re.IGNORECASE)
        or len(re.findall(r"^\s*-\s*\d{1,2}\s+\w+\s+\d{4},", text, flags=re.MULTILINE)) >= 3
    ):
        return text
    slot_examples = (
        "\n\nPlease share the three slots in this format:\n"
        "- 04 September 2026, 10:00 AM IST\n"
        "- 04 September 2026, 2:00 PM IST\n"
        "- 04 September 2026, 4:00 PM IST"
    )
    closing = re.search(r"\n\s*Regards,\s*Clahan Technologies\.?\s*$", text, flags=re.IGNORECASE)
    if closing:
        return f"{text[:closing.start()].rstrip()}{slot_examples}{text[closing.start():]}"
    return f"{text.rstrip()}{slot_examples}"


def _insert_before_signature(body: str, note: str) -> str:
    """Keep attachment/next-step notes inside the message, before its sign-off."""
    text = _clean(body)
    closing = re.search(r"\n\s*Regards,\s*\n\s*Clahan Technologies\.?", text, flags=re.IGNORECASE)
    if closing:
        return f"{text[:closing.start()].rstrip()}\n\n{note.strip()}\n\n{text[closing.start():].lstrip()}"
    return f"{text.rstrip()}\n\n{note.strip()}"


def _normalize_trainer_mail1_body(body: str) -> str:
    """Remove repeated blocks and cap generated slot examples at three."""
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", _clean(body)) if part.strip()]
    unique: List[str] = []
    seen = set()
    for paragraph in paragraphs:
        key = re.sub(r"\s+", " ", paragraph).strip().lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(paragraph)
    text = "\n\n".join(unique)
    slot_line = re.compile(r"^\s*-\s*\d{1,2}\s+[A-Za-z]+\s+\d{4},", flags=re.IGNORECASE)
    kept_lines: List[str] = []
    slot_count = 0
    for line in text.splitlines():
        if slot_line.search(line):
            slot_count += 1
            if slot_count > 3:
                continue
        kept_lines.append(line)
    return "\n".join(kept_lines).strip()


def _dated_slot_option_count(slot_text: Any, structured_slots: Optional[List[Dict[str, Any]]] = None) -> int:
    """Count complete, client-facing interview options; exactly three are required."""
    if structured_slots:
        return sum(
            1
            for slot in structured_slots
            if _clean(slot.get("date_display") or slot.get("date"))
            and _clean(slot.get("time_display") or slot.get("time"))
        )
    date_pattern = re.compile(
        r"(?:\b\d{1,2}\s*[/-]\s*\d{1,2}(?:\s*[/-]\s*\d{2,4})?\b|"
        r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b|"
        r"\b(?:mon|tue|wed|thu|fri|sat|sun)(?:day)?\b)",
        flags=re.IGNORECASE,
    )
    time_pattern = re.compile(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", flags=re.IGNORECASE)
    chunks = [part.strip() for part in re.split(r"[\r\n;]+", _clean(slot_text)) if part.strip()]
    return sum(1 for chunk in chunks if date_pattern.search(chunk) and time_pattern.search(chunk))


async def _build_toc(requirement: Dict[str, Any], trainer: Dict[str, Any], db: AsyncIOMotorDatabase) -> Optional[Dict[str, Any]]:
    try:
        from app.routes.toc import TocRequest, generate_toc
        mode_setting = await db["automation_settings"].find_one({"key": "generation_mode"}, {"_id": 0}) or {}
        generation_mode = "ai" if _clean(mode_setting.get("value")).lower() == "ai" else "template"
        domain = _clean(requirement.get("technology_needed") or requirement.get("domain") or requirement.get("title") or requirement.get("job_title") or "Training")
        duration = _safe_int(requirement.get("duration_days"), 3) or 3
        training_dates = (
            _clean(requirement.get("training_dates"))
            or " to ".join(part for part in [requirement.get("timeline_start"), requirement.get("timeline_end")] if part)
            or _clean(requirement.get("preferred_dates"))
        )
        toc_req = TocRequest(
            domain=domain,
            duration_days=duration,
            level=_clean(requirement.get("level") or "intermediate") or "intermediate",
            requirement_id=_clean(requirement.get("requirement_id")),
            trainer_id=_clean(trainer.get("trainer_id")),
            trainer_name=_clean(trainer.get("name") or trainer.get("trainer_name")),
            mode=_clean(requirement.get("mode") or "Online") or "Online",
            audience_level=_clean(requirement.get("audience_level") or requirement.get("participant_level")),
            training_dates=training_dates,
            timing=_clean(requirement.get("timing") or requirement.get("session_timing")),
            hours_per_day=_safe_float(requirement.get("hours_per_day") or requirement.get("training_hours_per_day") or requirement.get("lab_hours_per_day"), 0) or None,
            participant_count=_safe_int(requirement.get("participant_count") or requirement.get("participants"), 0) or None,
            cloud_provider=_clean(requirement.get("cloud_provider")),
            cloud_region=_clean(requirement.get("cloud_region") or requirement.get("region")),
            lab_type=_clean(requirement.get("lab_type") or requirement.get("lab_environment_type")),
            # Follow the same pipeline-wide AI switch as the Shortlist UI.
            generation_mode=generation_mode,
            custom_topics="; ".join(
                str(value).strip()
                for value in (
                    requirement.get("technology_needed"),
                    requirement.get("domain"),
                    requirement.get("skills"),
                    requirement.get("required_skills"),
                    requirement.get("requested_topics"),
                )
                if value
            ),
            client_notes=_clean(requirement.get("client_notes") or requirement.get("notes") or requirement.get("description")),
        )
        response = await generate_toc(toc_req, db)
        toc_data = response.get("toc_data") or response.get("toc")
        if not toc_data:
            return None
        toc_data = dict(toc_data)
        client_toc_topics = _client_supplied_toc_topics(requirement)
        if client_toc_topics:
            # This object is used only by the lab-cost engine.  Preserve the
            # client agenda line items as the cost source instead of pricing a
            # newly invented curriculum.
            for index, day in enumerate(toc_data.get("days") or []):
                source_topic = client_toc_topics[index] if index < len(client_toc_topics) else client_toc_topics[-1]
                day["focus_area"] = source_topic
                day["title"] = f"Day {day.get('day') or index + 1}: {source_topic}"
                day["category"] = source_topic
                day["client_toc_source"] = True
            toc_data["source"] = "client_supplied_toc"
            toc_data["client_toc_topics"] = client_toc_topics
        trainer_name = _clean(trainer.get("name") or trainer.get("trainer_name"))
        if trainer_name:
            toc_data.setdefault("trainer_name", trainer_name)
        toc_data.setdefault("domain", domain)
        toc_data.setdefault("duration_days", duration)
        return toc_data
    except Exception:
        logger.exception("Failed to build TOC")
        return None


async def _generate_toc_pdf(toc: Dict[str, Any]) -> Optional[bytes]:
    title = toc.get("title", "Training Programme")
    html = build_toc_html(toc)

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"{DOC_SVC}/api/v1/documents/pdf/html-to-pdf",
            params={"filename": f"{title}.pdf"},
            content=html,
            headers={"Content-Type": "text/html"},
        )
    if r.status_code >= 400:
        logger.error("TOC PDF generation failed: %s", r.text[:300])
        return None
    return r.content


async def _generate_trainer_profile_pdf(trainer: Dict[str, Any], technology: str) -> Optional[bytes]:
    """Create a client-ready profile attachment from the vetted trainer record."""
    trainer_name = _clean(trainer.get("name") or trainer.get("trainer_name")) or "Trainer"
    def value_text(value: Any) -> str:
        if isinstance(value, dict):
            return " - ".join(_clean(part) for part in value.values() if _clean(part))
        return _clean(value)

    def section(title: str, value: Any, fallback: str = "") -> str:
        items = [value_text(item) for item in _as_list(value) if value_text(item)]
        if not items and fallback:
            items = [fallback]
        if not items:
            return f'<section><div class="label">{escape(title)}</div><div class="value muted">Not available in verified trainer data.</div></section>'
        content = "".join(f"<li>{escape(item)}</li>" for item in items)
        return f'<section><div class="label">{escape(title)}</div><div class="value"><ul class="detail-list">{content}</ul></div></section>'

    email = _clean(trainer.get("email") or trainer.get("trainer_email"))
    phone = _clean(trainer.get("phone") or trainer.get("mobile") or trainer.get("contact_number"))
    location = _clean(trainer.get("location") or trainer.get("current_location"))
    linkedin = _clean(trainer.get("linkedin") or trainer.get("linkedin_url") or trainer.get("linkedin_profile"))
    experience_years = _clean(trainer.get("experience_years") or trainer.get("experience_raw"))
    summary = _clean(trainer.get("summary") or trainer.get("bio") or trainer.get("professional_summary"))
    skills = [_clean(value) for value in _as_list(trainer.get("skills") or trainer.get("technologies")) if _clean(value)]
    primary_role = _clean(trainer.get("title") or trainer.get("role_designation") or f"{technology} Trainer")
    contact_items = [value for value in (email, location, phone, linkedin) if value]
    contact_html = "".join(f"<span>{escape(value)}</span>" for value in contact_items)
    skill_html = "".join(f'<span class="skill">{escape(skill)}</span>' for skill in skills)
    approved_bullets = [
        _clean(value) for value in _as_list(trainer.get("approved_profile_bullets")) if _clean(value)
    ] if trainer.get("profile_enhancement_status") == "approved" else []
    evidence_items = _client_profile_evidence_items(trainer, technology)
    evidence_html = section("Verified Requirement Fit", evidence_items)
    enhancement_html = ""
    if approved_bullets:
        bullet_items = "".join(f"<li>{escape(value)}</li>" for value in approved_bullets)
        enhancement_html = (
            '<section><div class="label">Requirement-Aligned Highlights</div><div class="value">'
            '<p class="note">Reviewed for this client requirement and supported by profile or trainer-confirmed evidence.</p>'
            f'<ul class="detail-list">{bullet_items}</ul></div></section>'
        )
    experience_html = section("Employment / Training History", trainer.get("experience") or trainer.get("work_experience") or trainer.get("employment_history") or trainer.get("training_experience"))
    projects_html = section("Relevant Projects / Implementation Experience", trainer.get("projects") or trainer.get("implementation_experience") or trainer.get("project_experience"))
    certifications_html = section("Certifications", trainer.get("certifications"))
    education_html = section("Education", trainer.get("education") or trainer.get("qualifications"))
    experience_meta_html = f'<div class="meta">Experience: {escape(experience_years)}</div>' if experience_years else ""
    summary_html = (
        f'<section><div class="label">Profile</div><div class="value"><p class="summary">{escape(summary)}</p></div></section>'
        if summary
        else '<section><div class="label">Profile</div><div class="value muted">Not available in verified trainer data.</div></section>'
    )
    skills_html = (
        f'<section><div class="label">Skills</div><div class="value"><div class="skills">{skill_html}</div></div></section>'
        if skill_html
        else '<section><div class="label">Skills</div><div class="value muted">Not available in verified trainer data.</div></section>'
    )
    availability = _clean(trainer.get("availability") or trainer.get("available_dates") or trainer.get("availability_text") or trainer.get("slot_reply_text"))
    availability_html = (
        f'<section><div class="label">Availability / Interview Slots</div><div class="value"><p class="summary">{escape(availability)}</p></div></section>'
        if availability
        else '<section><div class="label">Availability / Interview Slots</div><div class="value muted">Pending trainer-confirmed slots.</div></section>'
    )
    if not any((summary, skills, experience_html, projects_html, certifications_html, education_html, approved_bullets)):
        return None
    html = (
        "<html><head><meta charset='utf-8'><style>"
        "@page{size:Letter;margin:12mm 14mm;}*{box-sizing:border-box;}"
        "body{font-family:Arial,Helvetica,sans-serif;color:#252525;font-size:9.5pt;line-height:1.42;margin:0;background:#fff;}"
        ".masthead{border-bottom:3px solid #2e2e2e;padding-bottom:5mm;margin-bottom:3mm;}"
        "h1{font-size:24pt;font-weight:700;letter-spacing:0;margin:0 0 2mm;color:#111;}"
        ".role{font-size:11pt;color:#555;margin:0 0 3mm;}"
        ".contact{font-size:8.7pt;color:#333;border-top:1px solid #d8d8d8;padding-top:2mm;}"
        ".contact span:not(:last-child):after{content:' | ';color:#888;margin:0 2mm;}"
        ".document-label{text-align:right;font-size:8pt;letter-spacing:1.5px;color:#777;text-transform:uppercase;margin-bottom:5mm;}"
        "section{display:grid;grid-template-columns:22% 78%;gap:5mm;border-bottom:1px solid #e2e2e2;"
        "padding:4mm 0;break-inside:avoid;}"
        ".label{font-size:8.4pt;letter-spacing:1.2px;text-transform:uppercase;font-weight:700;color:#111;}"
        ".value{min-width:0;}.summary{margin:0;white-space:pre-line;}.meta{color:#555;font-size:9pt;margin:0 0 1mm;}"
        ".skills{display:flex;flex-wrap:wrap;gap:5px;}.skill{border:1px solid #cfc8bb;"
        "display:inline-block;font-size:8.5pt;padding:2px 7px;color:#333;background:#fff;}"
        ".detail-list{margin:0;padding-left:18px;}.detail-list li{margin:0 0 3mm;white-space:pre-line;}"
        ".note,.muted{color:#666;font-size:8.2pt;margin:0 0 3mm;}.footer-note{color:#666;font-size:7.6pt;margin-top:5mm;}"
        "</style></head><body>"
        f'<header class="masthead"><h1>{escape(trainer_name)}</h1><p class="role">{escape(primary_role)}</p>'
        f'{experience_meta_html}<div class="contact">{contact_html}</div></header>'
        '<div class="document-label">Client Aligned Trainer Profile</div><main>'
        f"{summary_html}{evidence_html}{experience_html}{projects_html}{skills_html}{enhancement_html}{certifications_html}{education_html}{availability_html}"
        '<p class="footer-note">Client-specific presentation copy. Generated only from stored trainer data, CV extraction, or trainer-confirmed details.</p>'
        "</main>"
        "</body></html>"
    )
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{DOC_SVC}/api/v1/documents/pdf/html-to-pdf",
                params={"filename": f"{trainer_name} Trainer Profile.pdf"},
                content=html,
                headers={"Content-Type": "text/html"},
            )
        if response.status_code >= 400 or not response.content:
            logger.error("Trainer profile PDF generation failed: %s", response.text[:300])
            return None
        return response.content
    except Exception:
        logger.exception("Failed to generate trainer profile PDF")
        return None


def _submitted_resume_suits_requirement(
    submitted_resume: Optional[Dict[str, Any]],
    trainer: Dict[str, Any],
    technology: str,
) -> bool:
    if not submitted_resume:
        return False
    approved_bullets = [
        _clean(value) for value in _as_list(trainer.get("approved_profile_bullets")) if _clean(value)
    ] if trainer.get("profile_enhancement_status") == "approved" else []
    if approved_bullets:
        return True
    technology_tokens = _technology_tokens(technology)
    if not technology_tokens:
        return True
    evidence_text = _norm([
        submitted_resume.get("extracted_text"),
        submitted_resume.get("parsed_text"),
        submitted_resume.get("resume_text"),
        submitted_resume.get("text"),
    ])
    if not evidence_text:
        evidence_text = _profile_text(trainer)
    return all(token in evidence_text for token in technology_tokens)


def _edit_submitted_trainer_pdf(
    original_pdf: bytes,
    trainer: Dict[str, Any],
    technology: str,
) -> Optional[bytes]:
    """Return a client-specific copy of the submitted PDF; original pages remain byte-content intact."""
    approved_bullets = [
        _clean(value) for value in _as_list(trainer.get("approved_profile_bullets")) if _clean(value)
    ] if trainer.get("profile_enhancement_status") == "approved" else []
    if not original_pdf or not approved_bullets:
        return original_pdf or None
    try:
        import fitz

        document = fitz.open(stream=original_pdf, filetype="pdf")
        if document.page_count < 1:
            return None
        source_page = document[document.page_count - 1]
        width, height = source_page.rect.width, source_page.rect.height
        trainer_name = _clean(trainer.get("name") or trainer.get("trainer_name")) or "Trainer"
        chunks = [approved_bullets[index:index + 7] for index in range(0, len(approved_bullets), 7)]
        for page_number, chunk in enumerate(chunks, 1):
            page = document.new_page(width=width, height=height)
            continuation = " (continued)" if page_number > 1 else ""
            margin = 48
            page.insert_textbox(
                fitz.Rect(margin, margin, width - margin, 92),
                f"Requirement-Aligned Profile Addendum{continuation}",
                fontsize=19, fontname="hebo", color=(0.09, 0.15, 0.33),
            )
            page.draw_line((margin, 98), (width - margin, 98), color=(0.15, 0.39, 0.92), width=2)
            page.insert_textbox(
                fitz.Rect(margin, 112, width - margin, 150),
                f"{trainer_name}\n{technology} requirement",
                fontsize=11, fontname="hebo", color=(0.14, 0.2, 0.3), lineheight=1.35,
            )
            notice_rect = fitz.Rect(margin, 166, width - margin, 228)
            page.draw_rect(notice_rect, color=(0.8, 0.84, 0.9), fill=(0.97, 0.98, 0.99), width=0.7)
            page.insert_textbox(
                fitz.Rect(margin + 10, 176, width - margin - 10, 220),
                "This client-specific addendum contains only reviewed additions supported by the submitted "
                "profile or explicit trainer confirmation. The original resume pages preceding this addendum "
                "have not been rewritten.",
                fontsize=9, fontname="helv", color=(0.3, 0.37, 0.48), lineheight=1.35,
            )
            page.insert_text((margin, 258), "APPROVED HIGHLIGHTS", fontsize=12, fontname="hebo", color=(0.09, 0.15, 0.33))
            page.draw_line((margin, 268), (width - margin, 268), color=(0.8, 0.84, 0.9), width=0.7)
            y = 286
            for bullet in chunk:
                page.insert_text((margin + 2, y + 9), chr(8226), fontsize=11, fontname="symb", color=(0.15, 0.39, 0.92))
                page.insert_textbox(
                    fitz.Rect(margin + 18, y, width - margin, y + 58),
                    bullet, fontsize=10.5, fontname="helv", color=(0.14, 0.2, 0.3), lineheight=1.4,
                )
                y += 66
            page.insert_text(
                (margin, height - 36),
                "Client-specific copy - trainer master resume preserved unchanged",
                fontsize=7.5, fontname="helv", color=(0.4, 0.47, 0.58),
            )
        output = document.tobytes(garbage=4, deflate=True)
        document.close()
        return output
    except Exception:
        logger.exception("Failed to edit submitted trainer PDF")
        return None


async def _sync_shortlist_with_trainers(
    db: AsyncIOMotorDatabase,
    requirement: Dict[str, Any],
    existing: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    req_id = requirement.get("requirement_id")
    if not req_id:
        raise HTTPException(400, "Requirement id missing")

    client_emails = {
        _clean(value).lower()
        for value in (
            requirement.get("client_email"),
            requirement.get("contact_email"),
            requirement.get("email"),
        )
        if _clean(value)
    }
    all_trainers = await db["trainers"].find({}, {"_id": 0}).to_list(10000)
    available_trainers = [
        trainer for trainer in all_trainers
        if (
            _clean(trainer.get("status")).lower() not in EXCLUDED_TRAINER_STATUSES
            and _clean(trainer.get("email") or trainer.get("trainer_email")).lower() not in client_emails
        )
    ]
    scored = [
        scored_trainer
        for trainer in available_trainers
        if (scored_trainer := _score_trainer(trainer, requirement)) is not None
    ]
    if _requirement_date_tokens(requirement):
        scored = [
            trainer for trainer in scored
            if not await _trainer_has_date_conflict(db, _clean(trainer.get("trainer_id")), requirement)
        ]
    scored.sort(
        key=lambda trainer: (
            _safe_float(trainer.get("match_score"), 0),
            _safe_float(trainer.get("experience_years"), 0),
            1 if trainer.get("email") else 0,
        ),
        reverse=True,
    )

    # Keep shortlist state aligned with the system-wide one-trainer policy.
    # A stale requirement may still carry an older top_n value, so do not use
    # it to expand the active shortlist.
    top_n = 1
    existing = existing or {}
    old_trainers = existing.get("top_trainers", []) or []
    old_by_id = {
        _clean(trainer.get("trainer_id")): trainer
        for trainer in old_trainers
        if trainer.get("trainer_id")
    }
    top_trainers = scored[:top_n]
    new_ids = {_clean(trainer.get("trainer_id")) for trainer in top_trainers}
    for index, trainer in enumerate(top_trainers, start=1):
        trainer["rank"] = index
        trainer["pipeline_status"] = trainer.get("pipeline_status") or "shortlisted"
        old = old_by_id.get(_clean(trainer.get("trainer_id")))
        if old:
            trainer.update(_merge_pipeline_state(trainer, old))

    # Do not retain previously shortlisted trainers when the ranking is
    # refreshed: the shortlist must contain only the current top candidate.

    now = datetime.utcnow()
    warnings = [] if all_trainers else ["No trainers available in database."]
    doc = {
        "shortlist_id": existing.get("shortlist_id") or f"SL-{uuid.uuid4().hex[:8].upper()}",
        "requirement_id": req_id,
        "technology_needed": requirement.get("technology_needed", ""),
        "top_trainers": top_trainers,
        "total_matched": len(scored),
        "total_trainers_scanned": len(all_trainers),
        "total_available": len(available_trainers),
        "category_filter_applied": False,
        "no_category_match": bool(requirement.get("technology_needed")) and len(scored) == 0,
        "category_match_count": len(scored),
        "pipeline_summary": {
            "pipeline_version": PIPELINE_VERSION,
            # Matching is only the first workflow phase.  Do not report the
            # end-to-end workflow as complete before the client handoff and
            # downstream selection/training stages have actually happened.
            "status": "in_progress",
            "matching_status": "completed",
            "current_stage": "contacting_trainers",
            "client_handoff_completed": False,
            "total_candidates": len(available_trainers),
            "ranked_count": len(scored),
            "top_count": len(top_trainers),
            "warnings": warnings,
            "errors": [],
        },
        "pipeline_stage_log": [
            {
                "stage": "trainer_db_sync",
                "status": "completed",
                "detail": {
                    "total_trainers_scanned": len(all_trainers),
                    "available_trainers": len(available_trainers),
                    "ranked_count": len(scored),
                    "top_count": len(top_trainers),
                },
                "at": now.isoformat(),
            }
        ],
        "matching_pipeline_version": PIPELINE_VERSION,
        "pipeline_warnings": warnings,
        "pipeline_errors": [],
        "auto_created": True,
        "updated_at": now,
        "created_at": existing.get("created_at") or now,
    }
    set_doc = {k: v for k, v in doc.items() if k not in {"shortlist_id", "created_at"}}
    await db["shortlists"].update_one(
        {"requirement_id": req_id},
        {
            "$set": set_doc,
            "$setOnInsert": {
                "shortlist_id": doc["shortlist_id"],
                "created_at": doc["created_at"],
            },
        },
        upsert=True,
    )
    await db["requirements"].update_one(
        {"requirement_id": req_id},
        {"$set": {
            "total_matched": len(scored),
            "top_count": len(top_trainers),
            "updated_at": now,
        }},
    )
    return doc


def _workflow_summary(doc: Dict[str, Any]) -> Dict[str, Any]:
    trainers = doc.get("top_trainers", []) or []
    stages = {
        _clean(trainer.get("pipeline_status") or trainer.get("status")).lower()
        for trainer in trainers
    }
    mail_types = {
        _clean(trainer.get("last_mail_type") or trainer.get("last_mail_type_attempted")).lower()
        for trainer in trainers
    }
    delivered = [
        trainer for trainer in trainers
        if trainer.get("client_slots_sent") is True
        and _clean(trainer.get("client_slots_email_id"))
        and _clean(trainer.get("slot_status")).lower() == "sent_to_client"
    ]
    handoff_retry_pending = [
        trainer for trainer in trainers
        if not trainer.get("client_slots_sent")
        and _clean(trainer.get("slot_status")).lower() in {
            "client_handoff_retry_pending",
            "client_slot_send_failed",
        }
    ]
    if "training_confirmed" in stages:
        status, current_stage = "completed", "training_confirmed"
    elif "interview_scheduled" in stages:
        status, current_stage = "in_progress", "interview_link_sent"
    elif "selected" in stages:
        status, current_stage = "in_progress", "trainer_selected"
    elif delivered:
        status, current_stage = "in_progress", "client_handoff_sent"
    elif handoff_retry_pending:
        status, current_stage = "in_progress", "client_handoff_retry_pending"
    elif stages & {"slot_booked", "waiting_reply3"} or mail_types & {"mail3", "mail3_slot_booking"}:
        status, current_stage = "in_progress", "awaiting_trainer_slots"
    elif stages & {"details_received", "waiting_reply2", "mail1_replied"}:
        status, current_stage = "in_progress", "collecting_trainer_details"
    else:
        status, current_stage = "in_progress", "contacting_trainers"
    return {
        **(doc.get("pipeline_summary") or {}),
        "status": status,
        "matching_status": "completed",
        "current_stage": current_stage,
        "client_handoff_completed": bool(delivered),
        "client_handoff_count": len(delivered),
        "client_handoff_retry_pending": bool(handoff_retry_pending),
    }


def _shortlist_response(doc: Dict[str, Any]) -> Dict[str, Any]:
    trainers = doc.get("top_trainers", []) or []
    response_doc = {**doc, "pipeline_summary": _workflow_summary(doc)}
    return {
        "success": True,
        **response_doc,
        "shortlist": response_doc,
        "top_trainers": trainers,
        "trainers": trainers,
    }


def _thread_log_response(log: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(log)
    if item.get("direction") == "outbound":
        item["direction"] = "sent"
    elif item.get("direction") == "inbound":
        item["direction"] = "received"
    if not item.get("body") and item.get("body_snippet"):
        item["body"] = item.get("body_snippet")
    return item


def _log_text_for_thread(log: Dict[str, Any]) -> str:
    return "\n".join(
        _clean(log.get(key))
        for key in ("subject", "body", "body_snippet", "raw_body", "clean_body")
        if log.get(key)
    )


def _log_matches_trainer_thread(log: Dict[str, Any], trainer_id: str, trainer_name: str) -> bool:
    if trainer_id and _clean(log.get("trainer_id")) == trainer_id:
        return True
    text = _log_text_for_thread(log)
    if trainer_id and re.search(rf"\bRef\s*:\s*REQ-[A-Z0-9-]+\s*/\s*{re.escape(trainer_id)}\b", text, flags=re.IGNORECASE):
        return True
    if trainer_name and re.search(rf"\bDear\s+{re.escape(trainer_name)}\b", text, flags=re.IGNORECASE):
        return True
    return False


@router.get("/thread")
async def get_shortlist_thread(
    requirement_id: str = Query(...),
    trainer_id: str = Query(""),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    trainer_email = ""
    trainer_name = ""
    if trainer_id:
        shortlist = await db["shortlists"].find_one(
            {"requirement_id": requirement_id},
            {"_id": 0, "top_trainers": 1},
        ) or {}
        for trainer in shortlist.get("top_trainers") or []:
            if str(trainer.get("trainer_id") or "") == str(trainer_id):
                trainer_email = _clean(trainer.get("email") or trainer.get("trainer_email"))
                trainer_name = _clean(trainer.get("name") or trainer.get("trainer_name"))
                break

    logs = await (
        db["email_logs"]
        .find({"requirement_id": requirement_id}, {"_id": 0})
        .sort("created_at", -1)
        .to_list(500)
    )
    if trainer_id:
        email_logs: List[Dict[str, Any]] = []
        if trainer_email:
            email_regex = {"$regex": f"^{re.escape(trainer_email)}$", "$options": "i"}
            email_logs = await (
                db["email_logs"]
                .find(
                    {
                        "$or": [
                            {"from_email": email_regex},
                            {"sender": email_regex},
                            {"sender_email": email_regex},
                            {"recipient": email_regex},
                            {"to_email": email_regex},
                        ]
                    },
                    {"_id": 0},
                )
                .sort("created_at", -1)
                .to_list(200)
            )
        specific_logs = [
            log for log in logs
            if _log_matches_trainer_thread(log, trainer_id, trainer_name)
        ]
        if specific_logs:
            seen_keys = set()
            merged_logs = []
            for log in [*specific_logs, *email_logs]:
                key = (
                    _clean(log.get("email_id"))
                    or _clean(log.get("gmail_message_id"))
                    or _clean(log.get("message_id_header"))
                    or f"{_clean(log.get('direction'))}:{_clean(log.get('subject'))}:{_clean(log.get('created_at'))}"
                )
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                merged_logs.append(log)
            logs = merged_logs
        elif email_logs:
            logs = email_logs
    messages = []
    for log in logs:
        item = _thread_log_response(log)
        if trainer_id and not item.get("trainer_id") and trainer_email and _log_matches_trainer_thread(log, trainer_id, trainer_name):
            sender = _clean(item.get("from_email") or item.get("sender") or item.get("sender_email")).lower()
            recipient = _clean(item.get("recipient") or item.get("to_email")).lower()
            if sender == trainer_email.lower() or recipient == trainer_email.lower():
                item["trainer_id"] = trainer_id
                item["trainer_name"] = item.get("trainer_name") or trainer_name
        if requirement_id and not item.get("requirement_id"):
            item["requirement_id"] = requirement_id
        messages.append(item)
    return {"success": True, "requirement_id": requirement_id, "thread": messages, "messages": messages}


@router.get("/thread-states")
async def get_thread_states(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Return pipeline stage counts across all active shortlists."""
    pipeline = [
        {"$unwind": "$top_trainers"},
        {"$group": {"_id": "$top_trainers.pipeline_status", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    stages = {r["_id"]: r["count"] async for r in db["shortlists"].aggregate(pipeline) if r["_id"]}
    return {"success": True, "stage_counts": stages}


@router.get("/{requirement_id}")
async def get_shortlist(requirement_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    doc = await db["shortlists"].find_one({"requirement_id": requirement_id}, {"_id": 0})
    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0})
    if not requirement:
        requirement = await _load_requirement_from_core(requirement_id, db)
    if requirement:
        doc = await _sync_shortlist_with_trainers(db, requirement, doc)
    elif not doc:
        now = datetime.utcnow()
        doc = {
            "shortlist_id": f"SL-{uuid.uuid4().hex[:8].upper()}",
            "requirement_id": requirement_id,
            "technology_needed": "",
            "top_trainers": [],
            "total_matched": 0,
            "total_trainers_scanned": 0,
            "total_available": 0,
            "category_filter_applied": False,
            "no_category_match": False,
            "category_match_count": 0,
            "pipeline_summary": {
                "pipeline_version": PIPELINE_VERSION,
                "status": "missing_requirement",
                "total_candidates": 0,
                "ranked_count": 0,
                "top_count": 0,
                "warnings": ["Requirement not found for this shortlist id."],
                "errors": [],
            },
            "pipeline_warnings": ["Requirement not found for this shortlist id."],
            "pipeline_errors": [],
            "auto_created": False,
            "missing_requirement": True,
            "created_at": now,
            "updated_at": now,
        }
    top_trainers = doc.get("top_trainers") or []
    changed = False
    for trainer in top_trainers:
        stage = _clean(trainer.get("pipeline_status") or trainer.get("last_mail_type")).lower()
        trainer_id = _clean(trainer.get("trainer_id"))
        trainer_email = _clean(trainer.get("email") or trainer.get("trainer_email"))
        waiting_for_mail1_reply = stage in {"waiting_reply1", "mail1", "mail1_sent", "mail1_reminder"}
        if waiting_for_mail1_reply:
            reply_terms: List[Dict[str, Any]] = [
                {
                    "requirement_id": requirement_id,
                    "direction": {"$in": ["inbound", "received"]},
                    "source_outbound_mail_type": {"$in": ["mail1", "mail1_reminder"]},
                }
            ]
            if trainer_id:
                reply_terms[0]["trainer_id"] = trainer_id
            elif trainer_email:
                email_regex = {"$regex": f"^{re.escape(trainer_email)}$", "$options": "i"}
                reply_terms[0]["$or"] = [
                    {"from_email": email_regex},
                    {"sender": email_regex},
                    {"sender_email": email_regex},
                ]
            else:
                reply_terms = []

            if reply_terms:
                inbound_reply = await db["email_logs"].find_one(
                    reply_terms[0],
                    {
                        "_id": 0,
                        "created_at": 1,
                        "received_at": 1,
                        "body": 1,
                        "body_snippet": 1,
                        "sentiment": 1,
                        "reply_sentiment": 1,
                        "action": 1,
                        "office_mail_category": 1,
                        "scenario": 1,
                        "classification_reason": 1,
                    },
                    sort=[("created_at", -1)],
                )
                if inbound_reply:
                    reply_category = _clean(
                        inbound_reply.get("office_mail_category") or inbound_reply.get("scenario")
                    ).lower()
                    reply_reason = _clean(inbound_reply.get("classification_reason")).lower()
                    if (
                        reply_category in {"trainer_general_question", "trainer_content_doubt", "trainer_logistics_query"}
                        or reply_reason.startswith("trainer_question_")
                    ):
                        # Trainer questions are a separate side-flow. They must
                        # remain visible in email history without moving the
                        # Shortlist1 pipeline away from its existing stage.
                        continue
                    positive_reply = _is_positive_reply_doc(inbound_reply)
                    mail2_query: Dict[str, Any] = {
                        "requirement_id": requirement_id,
                        "mail_type": {"$in": ["mail2", "mail2_followup"]},
                        "status": "sent",
                    }
                    if trainer_id:
                        mail2_query["trainer_id"] = trainer_id
                    elif trainer_email:
                        mail2_query["recipient"] = {"$regex": f"^{re.escape(trainer_email)}$", "$options": "i"}
                    mail2_sent = await db["email_logs"].find_one(mail2_query, {"_id": 0, "email_id": 1})
                    trainer["pipeline_status"] = "waiting_reply2" if mail2_sent else ("mail1_replied" if positive_reply else "mail1_question")
                    trainer["mail1_replied_at"] = inbound_reply.get("received_at") or inbound_reply.get("created_at")
                    trainer["last_reply_snippet"] = _clean(inbound_reply.get("body_snippet") or inbound_reply.get("body"))[:500]
                    trainer["reply_sentiment"] = "positive" if positive_reply else "needs_review"
                    changed = True
                    continue

        if stage not in {"waiting_reply1", "mail1", "mail1_sent", "mail1_reminder"}:
            continue

        sent_query: Dict[str, Any] = {
            "requirement_id": requirement_id,
            "mail_type": {"$in": ["mail1", "mail1_reminder"]},
            "status": "sent",
        }
        if trainer_id:
            sent_query["trainer_id"] = trainer_id
        elif trainer_email:
            sent_query["recipient"] = {"$regex": f"^{re.escape(trainer_email)}$", "$options": "i"}

        sent_log = await db["email_logs"].find_one(sent_query, {"_id": 0, "email_id": 1})
        if sent_log and not _clean(trainer.get("last_mail_error")):
            continue

        trainer["pipeline_status"] = "shortlisted"
        trainer.pop("last_mail_type", None)
        trainer["last_mail_error"] = trainer.get("last_mail_error") or "Mail 1 was not delivered"
        changed = True

    if changed:
        doc["top_trainers"] = top_trainers
        doc["updated_at"] = datetime.utcnow()
        await db["shortlists"].update_one(
            {"requirement_id": requirement_id},
            {"$set": {"top_trainers": top_trainers, "updated_at": doc["updated_at"]}},
        )

    return _shortlist_response(doc)


@router.post("/send-mail")
async def send_shortlist_mail(
    payload: SendMailRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Send the configured mail_type email to one or all trainers on a shortlist."""
    shortlist = await db["shortlists"].find_one({"requirement_id": payload.requirement_id}, {"_id": 0}) or {}
    requirement = await db["requirements"].find_one({"requirement_id": payload.requirement_id}, {"_id": 0}) or {}
    if not requirement:
        requirement = await _load_requirement_from_core(payload.requirement_id, db) or {}
    if requirement:
        shortlist = await _sync_shortlist_with_trainers(db, requirement, shortlist)
    elif not shortlist:
        raise HTTPException(404, "Shortlist not found")

    top_trainers: List[Dict[str, Any]] = shortlist.get("top_trainers") or []

    if payload.to_email:
        matched = next(
            (t for t in top_trainers if str(t.get("trainer_id") or "") == str(payload.trainer_id or "")),
            {},
        )
        targets = [{
            "trainer_id": payload.trainer_id or "",
            "email": payload.to_email,
            "name": payload.to_name or payload.trainer_name or matched.get("name") or matched.get("trainer_name") or "Trainer",
        }]
    elif payload.trainer_ids:
        targets = [t for t in top_trainers if t.get("trainer_id") in payload.trainer_ids]
    else:
        targets = [t for t in top_trainers if t.get("pipeline_status") not in ("stopped_selected", "declined")]

    mail_type = _clean(payload.mail_type).lower()
    if mail_type in {"trainer_acknowledgment", "trainer_ack", "trainer_rate_accepted"}:
        raise HTTPException(
            400,
            "Trainer thank-you acknowledgements are disabled. Send Mail 3 slot booking or a missing-details request instead.",
        )
    if mail_type == "mail2":
        raise HTTPException(
            400,
            "Generic Mail 2 is disabled. Mail 1 collects profile, availability and exactly three slots; only mail2_followup may request a genuinely missing item once.",
        )
    if mail_type in {
        "mail3", "mail3_slot_booking", "mail3_slot_followup",
        "mail3_too_many", "mail3_too_many_slots", "mail3_too_few", "mail3_too_few_slots",
    }:
        raise HTTPException(
            400,
            "Mail 3 slot templates are retired. Mail 1 requests exactly three slots; after a valid reply, use the client handoff instead.",
        )
    if mail_type in {"mail6", "mail6_toc", "toc-request"}:
        raise HTTPException(
            400,
            "A separate ToC request is retired. The client or generated ToC is attached in Mail 1 for trainer delivery review.",
        )
    if mail_type in {"commercial_negotiation", "trainer_rate_discussion", "trainer_rate_rejected"}:
        raise HTTPException(
            400,
            "Trainer commercial-request templates are retired. Client commercial is the source of truth and trainer allocation is calculated by Clahan.",
        )
    if (
        not _clean(payload.body)
        and mail_type not in {"mail1", "first"}
        and mail_type not in CLIENT_COMMERCIAL_MAIL_TYPES
    ):
        # Do not let an empty request select an old email-service template.
        # The live workflow creates its one permitted Mail 2 follow-up in the
        # reply processor, where it knows the exact missing item.  Other
        # manual stages must supply their reviewed message explicitly.
        raise HTTPException(
            409,
            "Automatic template generation is retired for this stage. Use the current reply workflow, or provide a reviewed manual message.",
        )
    elif mail_type in DETAIL_FOLLOWUP_TYPES and not payload.to_email:
        targets = [
            t for t in targets
            if _clean(t.get("pipeline_status")).lower() in {"mail1_replied", "waiting_reply2", "details_received"}
            or _clean(t.get("reply_sentiment")).lower() == "positive"
        ]
        # Never ask again unless the analysed record has a specific missing
        # item requested by the client.
        targets = [t for t in targets if _trainer_missing_followup_details(t, requirement)]
    elif mail_type in CLIENT_COMMERCIAL_MAIL_TYPES and not payload.to_email:
        commercial_targets = []
        for t in targets:
            amounts = _trainer_commercial_amounts(t)
            if not amounts:
                continue
            enriched = dict(t)
            enriched["_commercial_amounts"] = amounts
            enriched["_lowest_commercial_amount"] = min(amounts)
            commercial_targets.append(enriched)
        targets = sorted(commercial_targets, key=lambda item: item.get("_lowest_commercial_amount", 0))

    if not targets:
        if mail_type == "mail2":
            return {"success": True, "sent": 0, "message": "No positive Mail 1 trainer replies found for slot booking"}
        if mail_type in DETAIL_FOLLOWUP_TYPES:
            return {"success": True, "sent": 0, "message": "No trainer has a client-requested missing detail to follow up"}
        if mail_type in CLIENT_COMMERCIAL_MAIL_TYPES:
            return {"success": True, "sent": 0, "message": "No trainers with commercial amounts found for client commercial mail"}
        return {"success": True, "sent": 0, "message": "No eligible trainers found"}

    results = []
    attempted_recipients = set()
    quota_blocked = False
    for t in targets:
        auto_toc_sent = False
        trainer_email = t.get("email") or t.get("trainer_email") or ""
        trainer_name = payload.to_name or t.get("name") or t.get("trainer_name") or "Trainer"
        if payload.to_email:
            trainer_email = payload.to_email
            trainer_name = payload.to_name or trainer_name
        elif mail_type in CLIENT_COMMERCIAL_MAIL_TYPES:
            trainer_email = _client_email_from_requirement(requirement, shortlist)
        if not trainer_email:
            reason = "skipped_no_client_email" if mail_type in CLIENT_COMMERCIAL_MAIL_TYPES else "skipped_no_email"
            results.append({"trainer_id": t.get("trainer_id"), "status": reason})
            continue
        if quota_blocked:
            results.append({
                "trainer_id": t.get("trainer_id"),
                "email": trainer_email,
                "status": "skipped_quota_blocked",
                "error_message": "Gmail sending quota exceeded; remaining sends were not attempted.",
            })
            continue
        recipient_key = trainer_email.strip().lower()
        if recipient_key in attempted_recipients:
            results.append({
                "trainer_id": t.get("trainer_id"),
                "email": trainer_email,
                "status": "skipped_duplicate_recipient",
            })
            continue

        trainer_id = _clean(t.get("trainer_id") or payload.trainer_id)
        missing_followup_details = _trainer_missing_followup_details(t, requirement) if mail_type in DETAIL_FOLLOWUP_TYPES else []
        if mail_type in DETAIL_FOLLOWUP_TYPES and not missing_followup_details:
            results.append({
                "trainer_id": trainer_id,
                "email": trainer_email,
                "status": "skipped_details_already_available",
            })
            continue
        if mail_type in DETAIL_FOLLOWUP_TYPES:
            # A missing item may remain unresolved for some time, but that is
            # never permission to resend the same Mail 2 on every automation
            # pass.  A human can deliberately use the separate follow-up
            # action after reviewing the outstanding detail.
            existing_followup = await db["email_logs"].find_one(
                {
                    "direction": "outbound",
                    "status": "sent",
                    "requirement_id": payload.requirement_id,
                    "mail_type": payload.mail_type,
                    "$or": [
                        {"trainer_id": trainer_id} if trainer_id else {"recipient": {"$regex": f"^{re.escape(trainer_email)}$", "$options": "i"}},
                        {"recipient": {"$regex": f"^{re.escape(trainer_email)}$", "$options": "i"}},
                    ],
                },
                {"_id": 0, "email_id": 1, "sent_at": 1},
            )
            if existing_followup:
                results.append({
                    "trainer_id": trainer_id,
                    "email": trainer_email,
                    "status": "skipped_already_sent",
                    "email_id": existing_followup.get("email_id", ""),
                    "sent_at": existing_followup.get("sent_at"),
                })
                continue
        if mail_type in {"mail1", "first"}:
            duplicate_terms: List[Dict[str, Any]] = [
                {
                    "direction": "outbound",
                    "status": "sent",
                    "mail_type": {"$in": ["mail1", "first"]},
                    "requirement_id": payload.requirement_id,
                    "recipient": {"$regex": f"^{re.escape(trainer_email)}$", "$options": "i"},
                }
            ]
            if trainer_id:
                duplicate_terms.append({
                    "direction": "outbound",
                    "status": "sent",
                    "mail_type": {"$in": ["mail1", "first"]},
                    "requirement_id": payload.requirement_id,
                    "trainer_id": trainer_id,
                })
            existing_mail1 = await db["email_logs"].find_one(
                {"$or": duplicate_terms},
                {"_id": 0, "email_id": 1, "sent_at": 1},
            )
            if existing_mail1:
                results.append({
                    "trainer_id": trainer_id,
                    "email": trainer_email,
                    "status": "skipped_already_sent",
                    "email_id": existing_mail1.get("email_id", ""),
                    "sent_at": existing_mail1.get("sent_at"),
                })
                continue

        attempted_recipients.add(recipient_key)

        guarded_mail_type = (payload.mail_type or "").strip()
        trainer_selected = bool(t.get("selected") or t.get("selection_status") == "selected")
        if guarded_mail_type in {"mail5", "mail5_ok", "mail5_selection"}:
            results.append({
                "trainer_id": trainer_id,
                "email": trainer_email,
                "status": "skipped_template_removed",
                "error": "Trainer selection/onboarding email template has been removed.",
            })
            continue
        if guarded_mail_type in {"mail7", "mail7_confirm", "training_confirmation"}:
            if not trainer_selected:
                results.append({
                    "trainer_id": trainer_id,
                    "email": trainer_email,
                    "status": "skipped_not_selected_by_client",
                    "error": "Mail 7 confirmation can be sent only after explicit client selection.",
                })
                continue

        error_message = ""
        sent_email_id = ""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                domain = _clean(
                    requirement.get("technology_needed")
                    or requirement.get("domain")
                    or shortlist.get("technology_needed")
                    or "Training"
                )
                duration = _clean_duration_text(
                    requirement.get("duration_text")
                    or (f"{requirement.get('duration_days')} day(s)" if requirement.get("duration_days") else "")
                    or (f"{requirement.get('duration_hours')} hour(s)" if requirement.get("duration_hours") else "")
                )
                dates = _clean(
                    requirement.get("training_dates")
                    or requirement.get("preferred_dates")
                    or requirement.get("dates")
                    or requirement.get("date_time_text")
                    or requirement.get("timeline")
                    or requirement.get("schedule")
                    or requirement.get("training_schedule")
                    or requirement.get("timing")
                    or requirement.get("session_timing")
                    or " to ".join(part for part in [requirement.get("timeline_start"), requirement.get("timeline_end")] if part)
                )
                if not dates:
                    raw_requirement_text = _client_requirement_text(requirement)
                    date_match = re.search(
                        r"(?im)^\s*(?:training\s*)?(?:dates?|schedule|timings?)\s*[:\-]\s*(.+)$",
                        raw_requirement_text or "",
                    )
                    if date_match:
                        dates = _clean(date_match.group(1))
                location = _clean(requirement.get("preferred_location") or requirement.get("location"))
                # Keep the Mail 1 route on the same proposal detector as the
                # client handoff.  Do not fall back to the confirmed template
                # merely because an older requirement lacks batch_flow.
                is_proposal_flow = _is_proposal_requirement(requirement)
                subject = payload.subject or f"Training Opportunity - {domain}"
                body = payload.body or (
                    f"Dear {trainer_name},\n\n"
                    "We have a training requirement matching your profile. Please revert if interested.\n\n"
                    f"Regards,\nClahan Technologies\n{getattr(settings, 'FROM_EMAIL', None) or 'sujithaofficial585@gmail.com'}"
                )
                if not payload.body and mail_type in CLIENT_COMMERCIAL_MAIL_TYPES:
                    commercial_message = _client_commercial_message(
                        requirement,
                        shortlist,
                        t,
                        t.get("_commercial_amounts") or _trainer_commercial_amounts(t),
                    )
                    subject = payload.subject or commercial_message["subject"]
                    body = commercial_message["body"]
                if mail_type in ("mail1", "first"):
                    # Mail 1 now starts from the analysed requirement, never
                    # from an old frontend preview. If AI wording is enabled
                    # below it receives this verified body only as its
                    # fact-preserving fallback.
                    body = _clean_confirmed_mail1_body(trainer_name, requirement, domain, t)
                elif mail_type in DETAIL_FOLLOWUP_TYPES:
                    # Mail 2 is never a broad template. The calculated list
                    # contains only the still-missing client-requested detail.
                    subject = f"Training Requirement - {domain} | Additional Details Required"
                    body = _trainer_mail2_followup_body(
                        trainer_name,
                        requirement,
                        domain,
                        missing_followup_details,
                    )
                ai_mail1_used = False
                # The automatic pipeline can pass a preview/template body in
                # its payload.  In AI mode that body is the grounded fallback,
                # not a reason to skip AI generation.
                if mail_type in ("mail1", "first"):
                    ai_mail1 = await _ai_trainer_mail1(
                        db,
                        trainer_name=trainer_name,
                        domain=domain,
                        requirement=requirement,
                        fallback_subject=subject,
                        fallback_body=body,
                    )
                    if ai_mail1:
                        subject = ai_mail1["subject"]
                        body = ai_mail1["body"]
                        ai_mail1_used = True
                if payload.mail_type in ("mail1", "first") and not ai_mail1_used:
                    # Always build Mail 1 from the analysed trainer record so
                    # it cannot request profile, experience, or commercials
                    # which are already stored in the platform.
                    body = _clean_confirmed_mail1_body(trainer_name, requirement, domain, t)
                if payload.mail_type in ("mail1", "first"):
                    if not is_proposal_flow:
                        body = _ensure_trainer_mail1_commercial_section(body, requirement)
                    body = _ensure_mail1_slot_examples(body)
                send_payload = {
                    "to": trainer_email,
                    "subject": subject,
                    "body": body,
                    "mail_type": payload.mail_type,
                    "trainer_id": t.get("trainer_id"),
                    "trainer_name": trainer_name,
                    "requirement_id": payload.requirement_id,
                    "smtp_config": payload.smtp_config,
                }
                if payload.mail_type in ("mail1", "first"):
                    scope_attachments = _trainer_scope_attachments(requirement)
                    # Proposal batches are still collecting scope.  Clahan
                    # generates/manages the ToC and lab cost only after the
                    # client confirms dates, duration and delivery details;
                    # do not manufacture or request a ToC at this shortlist
                    # stage.  A client-supplied scope may still be forwarded.
                    if is_proposal_flow and not _has_client_supplied_toc(requirement):
                        scope_attachments = []
                    if _has_client_supplied_toc(requirement):
                        if "approved toc/course agenda is attached" not in body.lower():
                            body = _insert_before_signature(
                                body,
                                "The approved ToC/course agenda is attached. Please use this scope when "
                                "confirming availability and delivery feasibility.",
                            )
                            send_payload["body"] = body
                    elif not is_proposal_flow:
                        # No client agenda was supplied. Generate the ToC once
                        # for Mail 1 so the trainer receives the proposed scope
                        # before responding. The same approved ToC is also
                        # included with the later client profile/slot handoff.
                        generated_toc = await _build_toc(requirement, t, db)
                        if generated_toc:
                            try:
                                toc_response = await _post_with_local_fallback(
                                    client,
                                    f"{DOC_SVC}/api/v1/documents/excel/toc",
                                    json={"toc": generated_toc},
                                )
                                if toc_response.status_code == 200 and toc_response.content:
                                    scope_attachments.append({
                                        "filename": f"{domain} - Proposed TOC.xlsx",
                                        "content_base64": base64.b64encode(toc_response.content).decode(),
                                        "subtype": "vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                    })
                                    if "the proposed toc/course agenda is attached" not in body.lower():
                                        body = _insert_before_signature(
                                            body,
                                            "The proposed ToC/course agenda is attached. Please review this scope and "
                                            "confirm availability and delivery feasibility.",
                                        )
                                        send_payload["body"] = body
                                else:
                                    raise RuntimeError(
                                        f"Mail 1 ToC workbook generation failed: {toc_response.status_code} "
                                        f"{toc_response.text[:300]}"
                                    )
                            except Exception:
                                # A confirmed-batch Mail 1 is incomplete without its
                                # ToC.  Stop this delivery rather than sending a
                                # partial email and creating a duplicate follow-up.
                                logger.exception("Could not attach generated ToC to Mail 1")
                                raise
                        else:
                            raise RuntimeError("Mail 1 ToC generation returned no ToC data")
                    if not is_proposal_flow and not scope_attachments:
                        raise RuntimeError("Confirmed Mail 1 requires a client or generated ToC attachment")
                    if scope_attachments:
                        send_payload["attachments"] = scope_attachments
                if mail_type in {"mail1", "first"}:
                    body = _normalize_trainer_mail1_body(body)
                send_payload["body"] = body
                if mail_type not in {"mail1", "first"}:
                    # All later workflow emails may use the enabled LLM for
                    # natural wording. The body above remains the controlled
                    # fallback and all operational facts stay fixed.
                    send_payload["ai_generate"] = True
                    send_payload["ai_context"] = {
                        "workflow": "trainer_pipeline",
                        "stage": mail_type,
                        "requirement_id": payload.requirement_id,
                        "trainer_name": trainer_name,
                        "technology": domain,
                        "missing_items": missing_followup_details,
                    }
                if mail_type == "mail4_reschedule_request" and payload.requirement_id:
                    # The same client-requested date must reach the trainer
                    # once only. A different date deliberately creates a new
                    # reschedule request and therefore a new key.
                    requested_date = _requested_reschedule_date_from_body(body)
                    date_key = re.sub(r"[^a-z0-9]+", "-", requested_date.lower()).strip("-") or "unspecified-date"
                    base_key = f"trainer-reschedule:{payload.requirement_id}:{trainer_id or trainer_email.lower()}:{date_key}"
                    send_payload["idempotency_key"] = base_key
                elif payload.mail_type in ("mail1", "first") and payload.requirement_id:
                    base_key = f"trainer-mail1:{payload.requirement_id}:{trainer_id or trainer_email.lower()}"
                    send_payload["idempotency_key"] = base_key
                r = await _post_with_local_fallback(client, f"{EMAIL_SVC}/api/v1/email/send", json=send_payload)
                ok = r.status_code < 400
                if not ok:
                    error_message = f"{r.status_code}: {r.text[:300]}"
                else:
                    try:
                        sent_email_id = (r.json() or {}).get("email_id", "")
                    except Exception:
                        sent_email_id = ""
                    if not sent_email_id:
                        sent_log = await db["email_logs"].find_one(
                            {
                                "direction": "outbound",
                                "status": "sent",
                                "requirement_id": payload.requirement_id,
                                "trainer_id": t.get("trainer_id"),
                                "mail_type": payload.mail_type,
                                "$or": [
                                    {"recipient": {"$regex": f"^{re.escape(trainer_email)}$", "$options": "i"}},
                                    {"to_email": {"$regex": f"^{re.escape(trainer_email)}$", "$options": "i"}},
                                ],
                            },
                            {"_id": 0, "email_id": 1},
                            sort=[("created_at", -1)],
                        )
                        sent_email_id = (sent_log or {}).get("email_id", "")
                    await asyncio.sleep(1.5)
        except Exception as exc:
            logger.error("Email send failed for %s: %s", trainer_email, exc)
            ok = False
            error_message = str(exc)

        results.append({
            "trainer_id": t.get("trainer_id"),
            "email": trainer_email,
            "status": "sent" if ok else "failed",
            "email_id": sent_email_id,
            "error_message": error_message,
        })
        if not ok and _is_mail_quota_error(error_message):
            quota_blocked = True

        now = datetime.utcnow()
        set_fields = {
            "top_trainers.$.last_mail_type_attempted": payload.mail_type,
            "top_trainers.$.last_mail_attempted_at": now,
        }
        if ok:
            waiting_stage_by_mail_type = {
                "mail1": "waiting_reply1",
                "first": "waiting_reply1",
                "mail1_reminder": "waiting_reply1",
                "mail1_question_redirect": "waiting_reply1",
                "mail2": "waiting_reply2",
                "mail2_followup": "waiting_reply2",
                "commercial_negotiation": "waiting_reply2",
                "trainer_rate_discussion": "waiting_reply2",
            }
            final_pipeline_status = "toc_requested" if auto_toc_sent else waiting_stage_by_mail_type.get(payload.mail_type, payload.mail_type)
            current_status = _clean(t.get("pipeline_status")).lower()
            has_details = bool(t.get("trainer_details_received_at") or t.get("mail2_replied_at"))
            has_client_commercial = bool(
                t.get("client_commercial_sent")
                or t.get("client_commercial_sent_at")
                or _clean(t.get("commercial_status")).lower() in {"sent_to_client", "accepted_by_trainer", "approved_by_client"}
            )
            if final_pipeline_status == "waiting_reply2" and (
                current_status in {"details_received", "slot_booked", "interview_scheduled", "selected", "toc_requested", "training_confirmed"}
                or has_details
                or has_client_commercial
            ):
                final_pipeline_status = current_status if current_status in {"slot_booked", "interview_scheduled", "selected", "toc_requested", "training_confirmed"} else "details_received"
            final_mail_type = "mail6_toc" if auto_toc_sent else payload.mail_type
            set_fields.update({
                "top_trainers.$.pipeline_status": final_pipeline_status,
                "top_trainers.$.last_mail_type": final_mail_type,
                "top_trainers.$.last_mailed_at": now,
                "top_trainers.$.last_mail_error": "",
            })
            if sent_email_id:
                set_fields[f"top_trainers.$.{final_mail_type}_email_id"] = sent_email_id
                if final_mail_type in {"mail1", "mail1_reminder"}:
                    set_fields["top_trainers.$.mail1_email_id"] = sent_email_id
                    set_fields["top_trainers.$.mail1_sent_at"] = now
            if mail_type == "mail4_reschedule_request":
                # Manual and automatic reschedules use the same downstream
                # state machine: trainer supplies exactly three slots, client
                # chooses one, then email-service creates the replacement Meet.
                set_fields.update({
                    "top_trainers.$.pipeline_status": "interview_reschedule_requested",
                    "top_trainers.$.slot_status": "reschedule_waiting_trainer",
                    "top_trainers.$.reschedule_requested": True,
                    "top_trainers.$.reschedule_requested_by": "client",
                    "top_trainers.$.reschedule_requested_date": _requested_reschedule_date_from_body(payload.body),
                    "top_trainers.$.reschedule_forward_email_id": sent_email_id,
                    "top_trainers.$.last_mail_type": "mail4_reschedule_request",
                })
        else:
            set_fields["top_trainers.$.last_mail_error"] = error_message or "Email delivery failed"

        await db["shortlists"].update_one(
            {"requirement_id": payload.requirement_id, "top_trainers.trainer_id": t.get("trainer_id")},
            {"$set": set_fields},
        )

    sent = sum(1 for r in results if r["status"] == "sent")
    failed = len(results) - sent
    success = sent > 0 and failed == 0
    return {
        "success": success,
        "sent": sent,
        "failed": failed,
        "total": len(results),
        "error": "" if success else (results[0].get("error_message") if results else "No emails were sent"),
        "results": results,
    }


async def _legacy_send_interview_link(
    payload: SendInterviewLinkRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Legacy implementation retained only for old data migration; it has no API route."""
    req = await db["requirements"].find_one({"requirement_id": payload.requirement_id}, {"_id": 0}) or {}
    shortlist = await db["shortlists"].find_one({"requirement_id": payload.requirement_id}, {"_id": 0}) or {}
    trainer = await db["trainers"].find_one({"trainer_id": payload.trainer_id}, {"_id": 0}) or {}
    shortlist_trainer = next(
        (t for t in shortlist.get("top_trainers") or [] if str(t.get("trainer_id") or "") == str(payload.trainer_id or "")),
        {},
    )
    email = _clean(payload.to_email or trainer.get("email") or shortlist_trainer.get("email") or shortlist_trainer.get("trainer_email"))
    name = _clean(payload.trainer_name or trainer.get("name") or shortlist_trainer.get("name") or shortlist_trainer.get("trainer_name")) or "Trainer"
    technology = _clean(
        payload.technology
        or req.get("technology_needed")
        or req.get("technology")
        or req.get("domain")
        or shortlist.get("technology_needed")
    ) or "training"
    interview_date = _clean(payload.interview_date or payload.date_time)
    platform = _clean(payload.platform) or "Google Meet"
    client_email = _clean(
        payload.client_email
        or req.get("client_email")
        or req.get("contact_email")
        or shortlist.get("client_email")
    )
    client_name = _clean(
        payload.client_name
        or req.get("client_name")
        or req.get("client_company")
        or shortlist.get("client_name")
    ) or "Client"
    link_mail_type = _clean(payload.mail_type) or "mail4"

    if not email:
        raise HTTPException(400, "Trainer email not found")
    if not client_email:
        raise HTTPException(400, "Client email not found; cannot send the meeting link to the client")
    if not _clean(payload.interview_link):
        now = datetime.utcnow()
        await db["shortlists"].update_one(
            {"requirement_id": payload.requirement_id, "top_trainers.trainer_id": payload.trainer_id},
            {"$set": {
                "top_trainers.$.pipeline_status": "calendar_failed_manual_review",
                "top_trainers.$.slot_status": "calendar_failed_no_mail_sent",
                "top_trainers.$.interview_link": "",
                "top_trainers.$.meet_link": "",
                "top_trainers.$.last_mail_type_attempted": link_mail_type,
                "top_trainers.$.last_mail_attempted_at": now,
                "top_trainers.$.last_mail_error": "Meeting link missing; interview schedule mail was not sent.",
                "top_trainers.$.updated_at": now,
                "updated_at": now,
            }},
        )
        raise HTTPException(400, "Meeting link missing; interview schedule mail was not sent. Please create/fix the Meet link and try again.")

    trainer_message = _trainer_interview_message(
        trainer_name=name,
        technology=technology,
        requirement_id=payload.requirement_id,
        interview_date=interview_date,
        platform=platform,
        interview_link=payload.interview_link,
    )
    trainer_calendar_invite = _interview_calendar_invite(
        attendee_name=name,
        attendee_email=email,
        technology=technology,
        interview_date=payload.date_time or payload.interview_date or "",
        interview_link=payload.interview_link,
    )
    client_message = _client_interview_message(
        client_name=client_name,
        trainer_name=name,
        technology=technology,
        requirement_id=payload.requirement_id,
        interview_date=interview_date,
        platform=platform,
        interview_link=payload.interview_link,
    )
    client_calendar_invite = _interview_calendar_invite(
        attendee_name=client_name,
        attendee_email=client_email,
        technology=technology,
        interview_date=payload.date_time or payload.interview_date or "",
        interview_link=payload.interview_link,
    )

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            trainer_response = await client.post(f"{EMAIL_SVC}/api/v1/email/send", json={
                "to": email,
                "subject": trainer_message["subject"],
                "body": trainer_message["body"],
                "mail_type": link_mail_type,
                "trainer_id": payload.trainer_id,
                "trainer_name": name,
                "requirement_id": payload.requirement_id,
                "smtp_config": payload.smtp_config,
                "calendar_invite": trainer_calendar_invite,
            })
            trainer_response.raise_for_status()
            trainer_sent = trainer_response.json()

            client_response = await client.post(f"{EMAIL_SVC}/api/v1/email/send", json={
                "to": client_email,
                "subject": client_message["subject"],
                "body": client_message["body"],
                "mail_type": "client_interview_schedule",
                "trainer_id": payload.trainer_id,
                "trainer_name": name,
                "requirement_id": payload.requirement_id,
                "smtp_config": payload.smtp_config,
                "calendar_invite": client_calendar_invite or None,
                # The email service checks the one global AI/template switch.
                # It can improve wording only; the fixed body is the fallback
                # and the link/date/calendar invite remain authoritative.
                "ai_generate": True,
                "ai_context": {
                    "workflow": "client_interview_confirmation",
                    "batch_type": "proposal" if _is_proposal_requirement(req) else "confirmed",
                    "requirement_id": payload.requirement_id,
                    "client_name": client_name,
                    "trainer_name": name,
                    "technology": technology,
                    "interview_date": interview_date,
                    "meeting_link": payload.interview_link,
                    "calendar_invite_attached": bool(client_calendar_invite),
                },
            })
            client_response.raise_for_status()
            client_sent = client_response.json()
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc

    now = datetime.utcnow()
    trainer_email_id = trainer_sent.get("email_id", "")
    client_email_id = client_sent.get("email_id", "")
    common_fields = {
        "requirement_id": payload.requirement_id,
        "trainer_id": payload.trainer_id,
        "trainer_name": name,
        "trainer_email": email,
        "client_email": client_email,
        "client_name": client_name,
        "technology": technology,
        "domain": technology,
        "interview_scheduled": True,
        "interview_date": interview_date,
        "date_time_text": interview_date,
        "interview_link": payload.interview_link,
        "meet_link": payload.interview_link,
        "platform": platform,
        "updated_at": now,
    }
    if trainer_email_id:
        await db["email_logs"].update_one(
            {"email_id": trainer_email_id},
            {"$set": {
                **common_fields,
                "to_email": email,
                "trainer_email_sent": True,
                "client_email_sent": True,
                "client_interview_email_id": client_email_id,
            }},
        )
    if client_email_id:
        await db["email_logs"].update_one(
            {"email_id": client_email_id},
            {"$set": {
                **common_fields,
                "to_email": client_email,
                "trainer_email_sent": True,
                "client_email_sent": True,
                "trainer_interview_email_id": trainer_email_id,
                "source_trainer_email_id": trainer_email_id,
            }},
        )

    await db["shortlists"].update_one(
        {"requirement_id": payload.requirement_id, "top_trainers.trainer_id": payload.trainer_id},
        {"$set": {
            "top_trainers.$.pipeline_status": "interview_scheduled",
            "top_trainers.$.slot_status": "interview_link_sent",
            "top_trainers.$.mail4_email_id": trainer_email_id,
            "top_trainers.$.client_mail4_email_id": client_email_id,
            "top_trainers.$.mail4_sent_at": now,
            "top_trainers.$.client_mail4_sent_at": now,
            "top_trainers.$.interview_scheduled_at": now,
            "top_trainers.$.interview_date": interview_date,
            "top_trainers.$.interview_link": payload.interview_link,
            "top_trainers.$.meet_link": payload.interview_link,
            "top_trainers.$.client_email_sent": True,
            "top_trainers.$.trainer_email_sent": True,
            "top_trainers.$.last_mail_type": link_mail_type,
            "top_trainers.$.last_mail_type_attempted": link_mail_type,
            "top_trainers.$.last_mail_attempted_at": now,
            "top_trainers.$.last_mailed_at": now,
            "top_trainers.$.last_mail_error": "",
            "top_trainers.$.updated_at": now,
            "updated_at": now,
        }},
    )

    return {
        "success": True,
        "trainer_sent_to": email,
        "client_sent_to": client_email,
        "trainer_email_id": trainer_email_id,
        "client_email_id": client_email_id,
        "interview_link": payload.interview_link,
    }


@router.post("/send-client-slots")
async def send_client_slots(
    payload: SendClientSlotsRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Forward trainer availability slots to the client via email."""
    req = await db["requirements"].find_one({"requirement_id": payload.requirement_id}, {"_id": 0}) or {}
    shortlist = await db["shortlists"].find_one({"requirement_id": payload.requirement_id}, {"_id": 0}) or {}
    trainer = next(
        (t for t in shortlist.get("top_trainers") or [] if str(t.get("trainer_id") or "") == str(payload.trainer_id or "")),
        {},
    )
    trainer_name = _clean(payload.trainer_name or trainer.get("name") or trainer.get("trainer_name")) or "Trainer"
    client_email = payload.client_email
    if not client_email:
        client_email = req.get("client_email", "")

    if not client_email:
        raise HTTPException(400, "client_email is required")

    slots_text = _clean(payload.slot_text)
    if not slots_text:
        slots_text = "\n".join(
            f"Slot {i+1}: {s.get('date_display', '')} {s.get('time_display', '')}".strip()
            for i, s in enumerate(payload.slots)
            if _clean(s.get("date_display") or s.get("date") or s.get("time_display") or s.get("time"))
        )
    slots_text = _clean(slots_text)
    if not slots_text:
        raise HTTPException(400, "Trainer slots are required before sending to client")
    slot_count = _dated_slot_option_count(slots_text, payload.slots)
    if slot_count != 3:
        raise HTTPException(400, "Exactly three dated trainer interview slots are required before sending to the client")

    # Client handoff is always idempotent. Extra request fields cannot bypass it.
    existing = await db["email_logs"].find_one(
        {
            "direction": "outbound",
            "status": "sent",
            "mail_type": "client_slots",
            "requirement_id": payload.requirement_id,
            "trainer_id": payload.trainer_id,
        },
        {"_id": 0, "email_id": 1, "recipient": 1, "to_email": 1, "sent_at": 1, "slot_text": 1, "body": 1},
        sort=[("created_at", -1)],
    )
    existing_slots = _clean(existing.get("slot_text") if existing else "")
    existing_body = _clean(existing.get("body") if existing else "")
    existing_is_placeholder = (
        not existing_slots
        and "availability slots will be shared shortly" in existing_body.lower()
    )
    if existing and not existing_is_placeholder:
        return {
            "success": True,
            "already_sent": True,
            "email_id": existing.get("email_id"),
            "sent_to": existing.get("to_email") or existing.get("recipient"),
            "slots_count": slot_count,
        }

    latest_detail_reply = await db["email_logs"].find_one(
        {
            "direction": {"$in": ["inbound", "received"]},
            "requirement_id": payload.requirement_id,
            "mail_type": {"$in": ["mail1", "mail2_followup", "trainer_auto_reply", "mail2"]},
            "$or": [
                {"trainer_id": payload.trainer_id},
                {"from_email": {"$regex": f"^{re.escape(_clean(trainer.get('email') or trainer.get('trainer_email')))}$", "$options": "i"}},
                {"sender": {"$regex": f"^{re.escape(_clean(trainer.get('email') or trainer.get('trainer_email')))}$", "$options": "i"}},
            ],
        },
        {"_id": 0, "body": 1, "body_snippet": 1, "reply_text": 1, "mail_type": 1, "created_at": 1, "sent_at": 1},
        sort=[("created_at", -1)],
    )
    if latest_detail_reply:
        reply_text = _clean(latest_detail_reply.get("body") or latest_detail_reply.get("reply_text") or latest_detail_reply.get("body_snippet"))
        if reply_text:
            trainer = {
                **trainer,
                "reply_text": trainer.get("reply_text") or reply_text,
                "last_reply_snippet": trainer.get("last_reply_snippet") or reply_text[:800],
                "details_reply_text": trainer.get("details_reply_text") or reply_text,
            }
    provided_details_text = _clean(payload.trainer_details_text)
    if provided_details_text:
        trainer = {
            **trainer,
            "reply_text": provided_details_text,
            "last_reply_snippet": provided_details_text[:800],
            "details_reply_text": provided_details_text,
            "trainer_details_text": provided_details_text,
        }

    technology = _clean(req.get("technology_needed") or req.get("technology") or req.get("domain")) or "training"
    client_name = _clean(payload.client_name or req.get("client_name") or req.get("client_company")) or "Client"
    attachments: List[Dict[str, str]] = []
    wants_profile, wants_toc, wants_lab_cost = _requested_client_attachments(req)
    client_toc_supplied = _has_client_supplied_toc(req)
    wants_profile = True
    profile_pdf = None
    if wants_profile:
        submitted_resume = await db["resume_uploads"].find_one(
            {
                "trainer_id": payload.trainer_id,
                "original_file": {"$exists": True},
                "$or": [
                    {"content_type": "application/pdf"},
                    {"filename": {"$regex": r"\.pdf$", "$options": "i"}},
                ],
            },
            {"_id": 0, "original_file": 1, "filename": 1, "extracted_text": 1, "parsed_text": 1, "resume_text": 1, "text": 1},
            sort=[("created_at", -1)],
        )
        if (
            submitted_resume
            and submitted_resume.get("original_file")
            and _submitted_resume_suits_requirement(submitted_resume, trainer, technology)
        ):
            profile_pdf = _edit_submitted_trainer_pdf(
                bytes(submitted_resume["original_file"]), trainer, technology
            )
        else:
            # A missing or poorly aligned uploaded resume must not prevent the client handoff.
            # Build a presentation copy solely from vetted trainer fields and
            # approved requirement-aligned bullets; the master profile is not changed.
            profile_pdf = await _generate_trainer_profile_pdf(trainer, technology)
            if not profile_pdf:
                logger.warning(
                    "Cannot create client profile copy for %s: no usable submitted PDF or vetted profile data",
                    payload.trainer_id,
                )
    if profile_pdf:
        attachments.append({
            "filename": f"{trainer_name} - Client Aligned Profile.pdf",
            "content_base64": base64.b64encode(profile_pdf).decode(),
            "subtype": "pdf",
        })

    # Client handoff always includes the training ToC together with the
    # trainer profile and exactly three slots.  Where the client supplied a
    # ToC, send that exact safe source document.  Otherwise attach the
    # approved system-generated ToC workbook.
    client_toc_topics = _client_supplied_toc_topics(req)
    client_toc_attachments = _client_toc_scope_attachments(req) if client_toc_supplied else []
    toc_data = await _build_toc(req, trainer, db)
    toc_attachment: Optional[bytes] = None
    if client_toc_attachments:
        attachments.extend(client_toc_attachments)
    elif toc_data:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                toc_response = await _post_with_local_fallback(
                    client,
                    f"{DOC_SVC}/api/v1/documents/excel/toc",
                    json={"toc": toc_data},
                )
            if toc_response.status_code == 200 and toc_response.content:
                toc_attachment = toc_response.content
            else:
                raise RuntimeError(
                    f"Client handoff ToC workbook generation failed: {toc_response.status_code} "
                    f"{toc_response.text[:300]}"
                )
        except Exception:
            logger.exception("Could not generate the required client-handoff ToC")
            raise HTTPException(502, "Could not generate the required ToC attachment for the client handoff")
    else:
        raise HTTPException(502, "Could not generate the required ToC for the client handoff")
    if toc_attachment:
        attachments.append({
            "filename": f"{technology} - Training ToC.xlsx",
            "content_base64": base64.b64encode(toc_attachment).decode(),
            "subtype": "vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        })

    lab_cost_attachment: Optional[bytes] = None
    # Automated client handoff sends the agreed lab-cost input summary only.
    # The same workbook is generated manually from the Lab Cost page after
    # commercial review, so AI automation never attaches a provisional file.
    if AUTO_ATTACH_LAB_COST_WORKBOOK and wants_lab_cost and toc_data and (not client_toc_supplied or client_toc_topics):
        try:
            participant_count = _safe_int(req.get("participant_count") or req.get("participants"), 1) or 1
            hours_per_day = _safe_float(req.get("hours_per_day") or req.get("lab_hours_per_day") or req.get("training_hours_per_day"), 3) or 3
            async with httpx.AsyncClient(timeout=60) as client:
                lab_response = await _post_with_local_fallback(
                    client,
                    f"{DOC_SVC}/api/v1/documents/excel/toc/lab-cost",
                    json={
                        "toc": toc_data,
                        "assumptions": {
                            "cloud_provider": _clean(req.get("cloud_provider") or "aws").lower(),
                            "hours_per_day": hours_per_day,
                            "participant_count": max(1, participant_count),
                            "include_default_hour_options": False,
                        },
                    },
                )
            if lab_response.status_code == 200 and lab_response.content:
                lab_cost_attachment = lab_response.content
            else:
                logger.error("Lab-cost workbook generation failed: %s", lab_response.text[:300])
        except Exception:
            logger.exception("Failed to generate lab-cost workbook for client handoff")
    if lab_cost_attachment:
        attachments.append({
            "filename": f"{technology} - Lab Cost Estimate.xlsx",
            "content_base64": base64.b64encode(lab_cost_attachment).decode(),
            "subtype": "vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        })

    trainer_details = _requested_trainer_details_for_client(
        req,
        trainer,
        profile_attached=bool(profile_pdf),
        toc_attached=bool(toc_attachment or client_toc_attachments),
        client_toc_supplied=client_toc_supplied,
    )
    trainer_details_section = f"Trainer details shared for your review:\n{trainer_details}\n\n" if trainer_details else ""
    training_summary = _client_training_summary(req)
    training_summary_section = f"Training details:\n{training_summary}\n\n" if training_summary else ""
    proposal_commercial_section = _proposal_client_commercial_section(req)
    lab_cost_note = ""
    toc_note = "The training ToC is attached for your review together with the trainer profile and interview slots.\n\n"
    if wants_lab_cost:
        lab_cost_note = (
            ("The lab-cost estimate is attached and is based on the ToC you provided. " if client_toc_supplied else "The lab-cost estimate is attached. ")
            + "We will update the final quote once the cloud region, participant count, and access timings are confirmed.\n\n"
            if lab_cost_attachment else
            "Lab-cost inputs have been recorded from the confirmed scope, participant count, duration, and lab-access timings. The final workbook will be shared separately after manual cost review.\n\n"
        )

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            subject = f"Interview Slots - {technology}"
            body = (
                f"{_client_time_greeting(client_name)},\n\n"
                f"We have received the requested trainer details for the shortlisted {technology} trainer.\n\n"
                f"{training_summary_section}"
                f"{trainer_details_section}"
                f"{proposal_commercial_section}"
                f"{toc_note}"
                "Available slots:\n"
                f"{slots_text}\n\n"
                f"{lab_cost_note}"
                "Kindly confirm the preferred slot, and we will proceed with the meeting coordination.\n\n"
                "Regards,\nClahan Technologies\nsujithaofficial585@gmail.com"
            )

            email_payload: Dict[str, Any] = {
                "to": client_email,
                "subject": subject,
                "body": body,
                "mail_type": "client_slots",
                "requirement_id": payload.requirement_id,
                "trainer_id": payload.trainer_id,
                "trainer_name": trainer_name,
                "smtp_config": payload.smtp_config,
                # Let email-service select AI or the approved template from
                # the single global setting.  Attachments, slots and all
                # commercial/lab-cost facts are still created by the system.
                "ai_generate": True,
                "ai_context": {
                    "workflow": "client_handoff",
                    "batch_type": "proposal" if _is_proposal_requirement(req) else "confirmed",
                    "requirement_id": payload.requirement_id,
                    "client_name": client_name,
                    "trainer_name": trainer_name,
                    "technology": technology,
                    "available_slots": slots_text,
                    "toc_attached": bool(toc_attachment or client_toc_attachments),
                    "lab_cost_attached": bool(lab_cost_attachment),
                    "attachment_names": [str(item.get("filename") or "") for item in attachments],
                },
            }
            # This is the final persistent duplicate guard for the client
            # handoff.  The inbox may process the same trainer reply more
            # than once after a retry or refresh; email-service stores this
            # key uniquely, so only one physical handoff email is delivered.
            handoff_key = (
                f"client-handoff:{payload.requirement_id}:"
                f"{payload.trainer_id or _email_address(trainer.get('email') or trainer.get('trainer_email'))}:"
                f"{_email_address(client_email)}"
            )
            email_payload["idempotency_key"] = handoff_key
            if attachments:
                email_payload["attachments"] = attachments
            response = await client.post(f"{EMAIL_SVC}/api/v1/email/send", json=email_payload)
            response.raise_for_status()
            sent_payload = response.json()
            if sent_payload.get("already_in_progress"):
                # The email service has atomically claimed this handoff.  Do
                # not mark the shortlist delivered until that worker confirms
                # the physical send. The inbox retry will re-check it.
                raise HTTPException(
                    409,
                    detail={
                        "message": "Client handoff delivery is already in progress",
                        "retry_after": (datetime.utcnow() + timedelta(minutes=1)).isoformat() + "Z",
                    },
                )
            if sent_payload.get("success") is not True or not _clean(sent_payload.get("email_id")):
                raise RuntimeError(
                    _clean(sent_payload.get("error") or sent_payload.get("detail"))
                    or "Email service did not confirm client handoff delivery"
                )
    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        response = exc.response
        try:
            upstream_detail: Any = response.json()
        except Exception:
            upstream_detail = response.text[:1000]
        logger.warning(
            "Client handoff email service failed requirement=%s trainer=%s status=%s detail=%s",
            payload.requirement_id,
            payload.trainer_id,
            response.status_code,
            upstream_detail,
        )
        if response.status_code == 429:
            raise HTTPException(
                429,
                detail={
                    "message": "Client handoff is waiting for the email provider retry window",
                    "upstream_detail": upstream_detail,
                },
            ) from exc
        raise HTTPException(
            502,
            detail={
                "message": "Client handoff email service failed",
                "upstream_status": response.status_code,
                "upstream_detail": upstream_detail,
            },
        ) from exc
    except Exception as exc:
        logger.exception(
            "Client handoff preparation failed requirement=%s trainer=%s",
            payload.requirement_id,
            payload.trainer_id,
        )
        raise HTTPException(502, str(exc)) from exc

    now = datetime.utcnow()
    await db["shortlists"].update_one(
        {"requirement_id": payload.requirement_id, "top_trainers.trainer_id": payload.trainer_id},
        {"$set": {
            "top_trainers.$.client_slots_sent": True,
            "top_trainers.$.client_slots_sent_at": now,
            "top_trainers.$.client_slots_email_id": sent_payload.get("email_id", ""),
            "top_trainers.$.slot_status": "sent_to_client",
            "top_trainers.$.slot_reply_text": slots_text,
            "top_trainers.$.client_slot_error": "",
            "top_trainers.$.client_handoff_error_detail": "",
            "top_trainers.$.client_handoff_retry_after": None,
            "top_trainers.$.last_mail_error": "",
            "top_trainers.$.updated_at": now,
            "pipeline_summary.status": "in_progress",
            "pipeline_summary.matching_status": "completed",
            "pipeline_summary.current_stage": "client_handoff_sent",
            "pipeline_summary.client_handoff_completed": True,
            "updated_at": now,
        }},
    )

    return {
        "success": True,
        "email_id": sent_payload.get("email_id"),
        "sent_to": client_email,
        "slots_count": slot_count,
        "slot_text": slots_text,
    }
