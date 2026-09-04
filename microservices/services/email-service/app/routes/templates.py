"""Email template composition endpoints."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from app.config import get_settings
from app.agents import reply_templates as rt

router = APIRouter()
# Proposal enquiries use this internal shortlist range in the trainer mail.
# It is not a request for the trainer to quote a commercial.
PROPOSAL_COMMERCIAL_RANGE = "INR 12,000-15,000 per day/session"
settings = get_settings()
LOCAL_TZ = timezone(timedelta(hours=5, minutes=30))


def _require_internal(x_internal_token: str = Header(None)) -> None:
    # If INTERNAL_SERVICE_TOKEN is configured, require matching header.
    token = settings.INTERNAL_SERVICE_TOKEN or ""
    if token:
        if not x_internal_token or x_internal_token != token:
            raise HTTPException(status_code=403, detail="Forbidden: invalid internal token")


def _from_name() -> str:
    return settings.FROM_NAME or "Clahan Technologies"


def _client_time_greeting(name: str) -> str:
    clean_name = str(name or "Client").strip() or "Client"
    hour = datetime.now(LOCAL_TZ).hour
    if hour < 12:
        greeting = "Good morning"
    elif hour < 17:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"
    return f"{greeting} {clean_name}"


PLACEHOLDER_EMAILS = {
    "your-gmail@gmail.com",
    "your-gmail-address@gmail.com",
    "your-email@gmail.com",
    "yourname@example.com",
    "your-email@example.com",
    "email@example.com",
    "test@example.com",
    "your@email.com",
}


def _normalize_email_address(email: str) -> str:
    raw = str(email or "").strip()
    if raw.lower().startswith("mailto:"):
        raw = raw[7:]
    raw = raw.split("?", 1)[0].strip()
    if raw.lower() in PLACEHOLDER_EMAILS:
        return ""
    return raw


def _from_email() -> str:
    # Prefer explicit FROM_EMAIL, then GMAIL_USER; if that is a placeholder or blank,
    # fall back to the requested persistent sender address so templates never show
    # the placeholder email in outgoing messages.
    email = _normalize_email_address(settings.FROM_EMAIL or settings.GMAIL_USER or "")
    return email or "sujithaofficial585@gmail.com"


class ShortlistEmailRequest(BaseModel):
    trainer_name: str
    domain: Optional[str] = None
    duration: Optional[str] = ""
    mode: Optional[str] = ""
    participants: Optional[str] = ""
    dates: Optional[str] = ""
    training_time: Optional[str] = ""
    hands_on_lab: Optional[str] = ""
    client_name: Optional[str] = ""
    audience_level: Optional[str] = ""
    location: Optional[str] = ""
    budget: Optional[str] = ""
    topics: Optional[str] = ""
    client_request: Optional[str] = ""
    toc_action: Optional[str] = ""
    scope_attached: Optional[bool] = False
    requirement_kind: Optional[str] = ""
    resume_verified_experience: Optional[bool] = False
    profile_available: Optional[bool] = False
    linkedin_available: Optional[bool] = False
    certifications_available: Optional[bool] = False
    location_available: Optional[bool] = False
    request_interview_slots: Optional[bool] = False


def _clean_client_request_for_trainer(value: str) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.lower().startswith(("from:", "sent:", "to:", "cc:", "bcc:", "subject:")):
            continue
        if re.match(r"(?i)^on .+ wrote:$", line):
            break
        lines.append(raw_line.rstrip())
    text = "\n".join(lines).strip()
    return text[:1800].strip()


def _has_value(value: str) -> bool:
    text = str(value or "").strip().lower()
    return bool(text) and text not in {"to be confirmed", "tbc", "tbd", "na", "n/a", "not confirmed", "not finalized", "not finalised"}


def _requirement_kind(payload: ShortlistEmailRequest, client_request: str) -> str:
    explicit_kind = str(payload.requirement_kind or "").strip().lower()
    if "proposal" in explicit_kind:
        return "proposal_requirement"
    if "confirmed" in explicit_kind:
        return "confirmed_batch"
    training_text = f"{payload.domain or ''}\n{payload.duration or ''}\n{payload.mode or ''}\n{payload.dates or ''}\n{payload.location or ''}".lower()
    client_text = str(client_request or "").lower()
    fixed_count = sum(
        1
        for value in (payload.duration, payload.mode, payload.dates, payload.location)
        if _has_value(value)
    )
    pending_training_labels = (
        "duration: to be confirmed",
        "duration - to be confirmed",
        "training duration: to be confirmed",
        "mode: to be confirmed",
        "mode - to be confirmed",
        "location: to be confirmed",
        "location - to be confirmed",
        "dates: to be confirmed",
        "dates - to be confirmed",
        "timing: to be confirmed",
        "timings: to be confirmed",
        "schedule: to be confirmed",
        "sessions: to be confirmed",
    )
    proposal_signals = (
        "mode to be confirmed",
        "duration to be confirmed",
        "location to be confirmed",
        "dates to be confirmed",
        "timing to be confirmed",
        "schedule to be confirmed",
        "share the following details",
        "suitable trainer",
        "upcoming corporate training",
        "immediate requirement",
    )
    if fixed_count >= 3 and not any(signal in training_text for signal in ("to be confirmed", "tbc", "tbd")):
        return "confirmed_batch"
    if any(signal in client_text for signal in pending_training_labels):
        return "proposal_requirement"
    if any(signal in client_text for signal in proposal_signals):
        return "proposal_requirement"
    return "confirmed_batch"


def _trainer_detail_requests(client_request: str, has_budget: bool) -> list[str]:
    text = client_request.lower()
    requests = []
    checks = [
        (("trainer profile", "consultant profile", "updated profile"), "Updated CV / Trainer Profile"),
        (("resume", "cv"), "Updated CV / Trainer Profile"),
        (("linkedin", "linked in"), "LinkedIn Profile"),
        (("implementation experience", "training experience", "hands-on implementation", "relevant experience"), "Relevant corporate training and implementation experience"),
        (("current location", "location"), "Current Location"),
        (("availability",), "Availability for the specified dates and timings"),
        (("available dates for training", "training dates"), "Available dates for training"),
        (("available time slots", "technical call", "interview slots"), "Available time slots for technical call"),
        (("commercial", "commercials", "per hour", "per day", "rate", "cost"), "Commercials for the requested training engagement"),
        (("certification cost",), "Certification cost, if applicable"),
        (("lab plan", "hands-on lab", "hands on lab"), "Day-wise hands-on lab plan"),
        (("system requirement", "hardware"), "System requirements / hardware"),
        (("software required", "required software"), "Software required for training"),
        (("availability of required software",), "Availability of required software from trainer side"),
        (("certification", "certifications"), "Relevant certifications"),
        (("toc", "table of content", "table of contents", "course agenda", "agenda", "curriculum"), "Detailed day-wise ToC/course agenda"),
        (("day wise content", "day-wise content", "scope of the delivery"), "Day-wise ToC / course content"),
        (("batches delivered", "similar technology"), "Number of similar batches delivered"),
        (("client names", "similar trainings were delivered"), "Client names where similar trainings were delivered"),
    ]
    for keys, label in checks:
        if any(key in text for key in keys) and label not in requests:
            requests.append(label)
    if not requests:
        requests.extend(["Updated CV / Trainer Profile", "LinkedIn Profile"])
    if not has_budget and not any("Commercial" in item for item in requests):
        requests.append("Commercials (per hour/day)")
    return requests


def _requirement_snapshot(payload: ShortlistEmailRequest) -> str:
    rows = [
        ("Domain/Technology", payload.domain or "Training"),
        ("Training dates", payload.dates),
        ("Duration", payload.duration),
        ("Training time", payload.training_time),
        ("Hands-on lab", payload.hands_on_lab),
        ("Mode", payload.mode),
        ("Location", payload.location),
        ("Audience/Participants", payload.audience_level or payload.participants),
        ("Commercials/Budget", payload.budget),
        ("Topics", payload.topics),
    ]
    return "\n".join(f"- {label}: {str(value).strip()}" for label, value in rows if _has_value(str(value or "")))


def _proposal_requirement_snapshot(payload: ShortlistEmailRequest) -> str:
    participants = payload.participants or payload.audience_level or "Corporate professionals"
    rows = [
        ("Technology", payload.domain or "Training"),
        ("Experience Required", getattr(payload, "experience_required", "") or ""),
        ("Training Dates", payload.dates or ""),
        ("Participants", participants),
        ("Mode", payload.mode or "To be confirmed"),
        ("Duration", payload.duration or "To be confirmed"),
        ("Location", payload.location or "To be confirmed"),
    ]
    return "\n".join(f"* {label}: {str(value).strip()}" for label, value in rows if str(value or "").strip())


def _clean_trainer_detail_label(item: str) -> str:
    text = str(item or "").strip()
    replacements = {
        "Updated CV / Trainer Profile": "updated profile",
        "Commercials (per hour/day)": "commercials",
        "Commercials for the requested training engagement": "commercials",
        "Detailed day-wise ToC/course agenda": "day-wise TOC",
        "Day-wise ToC / course content": "day-wise TOC",
        "ToC/course agenda": "TOC",
    }
    return replacements.get(text, text)


def _simple_trainer_mail1_body(payload: ShortlistEmailRequest, domain: str, requested_items: list[str]) -> str:
    details = [
        ("Technology", domain),
        ("Duration", payload.duration),
        ("Dates", payload.dates),
        ("Time", payload.training_time),
        ("Mode", payload.mode),
        ("Participants", payload.participants or payload.audience_level),
        ("Location", payload.location),
    ]
    detail_text = "\n".join(f"- {label}: {str(value).strip()}" for label, value in details if _has_value(str(value or "")))
    proposal_flow = _requirement_kind(payload, payload.client_request or "") == "proposal_requirement"
    cleaned_items = [_clean_trainer_detail_label(item) for item in requested_items]
    selected = list(dict.fromkeys(item for item in cleaned_items if item))
    if proposal_flow:
        # Proposal scope is intentionally incomplete. Show every core field
        # explicitly so the trainer knows these items are confirmed later by
        # the client rather than being missing from the email.
        proposal_details = [
            ("Technology", domain),
            ("Mode", payload.mode or "To be confirmed (Online/Offline)"),
            ("Duration", payload.duration or "To be confirmed"),
            ("Location", payload.location or "To be confirmed"),
            ("Participants", payload.participants or payload.audience_level or "Corporate professionals"),
            ("Commercials", PROPOSAL_COMMERCIAL_RANGE),
        ]
        detail_text = "\n".join(f"- {label}: {value}" for label, value in proposal_details)
        managed_terms = ("commercial", "toc", "course agenda", "day-wise", "lab")
        selected = [item for item in selected if not any(term in item.lower() for term in managed_terms)]
        # Every proposal shortlist needs trainer availability and three slots
        # for the client handoff, even when availability was not extracted
        # from the inbound client email as a separate requested field.
        if not any("availability" in item.lower() for item in selected):
            selected.append("availability")
    if not selected:
        selected = ["availability"] if proposal_flow else ["updated profile", "LinkedIn profile", "availability"]
    ask = ", ".join(dict.fromkeys(item for item in selected if "availability" not in item.lower()))
    request_line = (
        "Please let us know whether you are available for this requirement"
        if not ask
        else f"Please let us know whether you are available for this requirement and share your {ask}"
    )
    needs_slots = bool(payload.request_interview_slots) or proposal_flow or any("availability" in item.lower() for item in selected)
    slot_request = (
        "\n\nPlease also share three convenient interview/discussion slots with the date, time, and time zone.\n"
        "Example:\n"
        "- 04 September 2026, 10:00 AM IST\n"
        "- 04 September 2026, 2:00 PM IST\n"
        "- 04 September 2026, 4:00 PM IST\n"
        if needs_slots else ""
    )
    if not proposal_flow:
        request_text = "\n".join(f"- {item}" for item in requested_items)
        return (
            f"Hi {payload.trainer_name or 'Trainer'},\n\n"
            "Hope you are doing well.\n\n"
            f"We have received a training requirement for {domain}.\n\n"
            "Training Details:\n"
            f"{_requirement_snapshot(payload)}\n\n"
            "Kindly share the details below:\n"
            f"{request_text}{slot_request}\n\n"
            "Once a slot is finalized, we will share the confirmed meeting invitation with you.\n\n"
            "Regards,\n"
            "Clahan Technologies"
        )
    return (
        f"Hi {payload.trainer_name or 'Trainer'},\n\n"
        "Hope you are doing well.\n\n"
        "We are reaching out regarding the following corporate training requirement.\n\n"
        "Requirement details noted:\n\n"
        f"{detail_text}\n\n"
        f"{request_line}.{slot_request}\n\n"
        "Once a slot is finalized, we will share the confirmed meeting invitation with you.\n\n"
        "Regards,\n"
        "Clahan Technologies"
    )


class InterviewEmailRequest(BaseModel):
    trainer_name: str
    technology: str
    req_id: str
    interview_date: Optional[str] = ""
    interview_link: Optional[str] = ""
    slot_start: Optional[str] = ""
    slot_end: Optional[str] = ""
    client_name: Optional[str] = ""
    organizer_name: Optional[str] = "Clahan Technologies"
    organizer_email: Optional[str] = ""


def _parse_calendar_datetime(value: str) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo:
            return parsed.astimezone(LOCAL_TZ).replace(tzinfo=None)
        return parsed
    except Exception:
        pass
    clean = re.sub(r"(?i)\b(?:IST|Asia/Kolkata|Asia/Calcutta)\b", "", raw).strip(" ,")
    formats = (
        "%d %B %Y, %I:%M %p",
        "%d %b %Y, %I:%M %p",
        "%d %B %Y %I:%M %p",
        "%d %b %Y %I:%M %p",
        "%d-%m-%Y %I:%M %p",
        "%Y-%m-%d %I:%M %p",
        "%Y-%m-%d %H:%M",
    )
    for fmt in formats:
        try:
            return datetime.strptime(clean, fmt)
        except ValueError:
            continue
    return None


def _calendar_event_from_interview(payload: InterviewEmailRequest, subject: str) -> Optional[dict]:
    start = _parse_calendar_datetime(payload.slot_start or "")
    end = _parse_calendar_datetime(payload.slot_end or "")
    if not start and payload.interview_date:
        match = re.search(
            r"(.+?\b\d{4})[,\s]+(\d{1,2}:\d{2}\s*[AP]M)\s*(?:-|to|–|—)\s*(\d{1,2}:\d{2}\s*[AP]M)",
            payload.interview_date,
            flags=re.IGNORECASE,
        )
        if match:
            start = _parse_calendar_datetime(f"{match.group(1)}, {match.group(2)}")
            end = _parse_calendar_datetime(f"{match.group(1)}, {match.group(3)}")
    if start and not end:
        end = start + timedelta(minutes=30)
    if not start or not end:
        return None
    link = (payload.interview_link or "").strip()
    return {
        "summary": subject,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "timezone": "Asia/Kolkata",
        "location": "Google Meet" if link else "Online Meeting",
        "description": (
            f"Trainer evaluation for {payload.technology}."
            + (f"\nJoin meeting: {link}" if link else "")
            + (f"\nReference ID: {payload.req_id}" if payload.req_id else "")
        ),
        "organizer_name": payload.organizer_name or "Clahan Technologies",
        "organizer_email": payload.organizer_email or _from_email(),
        "attendee_name": payload.trainer_name,
        "meeting_url": link,
    }


class TocRequestEmailRequest(BaseModel):
    trainer_name: Optional[str] = ""
    name: Optional[str] = ""


class RetryEmailRequest(BaseModel):
    trainer_name: str
    technology: str
    req_id: str


@router.post("/shortlist-first")
async def compose_shortlist_first(payload: ShortlistEmailRequest):
    domain = payload.domain or "Training"
    if domain.strip().lower() == "devops":
        domain = "DevOps"
        payload.domain = domain
    client_request = _clean_client_request_for_trainer(payload.client_request or "")
    requirement_kind = _requirement_kind(payload, client_request)
    detail_text = _requirement_snapshot(payload)

    slot_guide = """

Format for Sharing Availability Slots:
=====================================
Slot 1: 22 June 2026, 11:00 AM â€“ 11:30 AM IST
Slot 2: 23 June 2026, 2:00 PM â€“ 2:30 PM IST
Slot 3: 25 June 2026, 4:00 PM â€“ 4:30 PM IST

This helps us process your availability automatically and move forward quickly.
"""
    missing_note = ""
    slot_guide = ""
    if requirement_kind == "confirmed_batch":
        intro = (
            f"We are coordinating a {domain} corporate training requirement and your profile appears relevant "
            "for this engagement."
        )
        action_line = (
            "Please confirm your availability and share the details below so we can proceed with the client shortlist:"
        )
    else:
        intro = (
            f"We have an upcoming corporate training requirement for an experienced {domain} Trainer."
        )
        action_line = (
            "If you are interested and available for this requirement, kindly share the below details:"
        )
        detail_text = _proposal_requirement_snapshot(payload)
    requested_items = _trainer_detail_requests(client_request, bool(payload.budget))
    if payload.resume_verified_experience:
        requested_items = [
            item for item in requested_items
            if "implementation experience" not in item.lower()
            and "training experience" not in item.lower()
            and "relevant experience" not in item.lower()
        ]
    if requirement_kind == "confirmed_batch":
        experience_item = f"Relevant {domain} corporate training and implementation experience"
        toc_item = (
            "Review the attached client scope, confirm full/partial module coverage and share an aligned day-wise TOC"
            if payload.scope_attached or payload.toc_action == "trainer_validate_scope"
            else "Detailed day-wise ToC/course agenda"
        )
        confirmed_order = [
            "Updated CV / Trainer Profile", "LinkedIn Profile", experience_item,
            "Relevant certifications", "Current Location", "Availability",
            "Availability for the specified dates and timings", "Available dates for training", "Available time slots for technical call",
            toc_item, "Day-wise hands-on lab plan", "Commercials for the requested training engagement", "Certification cost, if applicable",
            "Number of similar batches delivered", "Client names where similar trainings were delivered",
            "System requirements / hardware", "Software required for training",
            "Availability of required software from trainer side",
        ]
        requested_set = set(requested_items)
        if "Relevant corporate training and implementation experience" in requested_set:
            requested_set.remove("Relevant corporate training and implementation experience")
            requested_set.add(experience_item)
        if payload.toc_action == "generate_by_clahan" and not payload.scope_attached:
            requested_set = {
                item for item in requested_set
                if not any(term in item.lower() for term in ("toc", "course agenda", "day-wise"))
            }
        if "Detailed day-wise ToC/course agenda" in requested_set and toc_item != "Detailed day-wise ToC/course agenda":
            requested_set.remove("Detailed day-wise ToC/course agenda")
            requested_set.add(toc_item)
        if "Day-wise ToC / course content" in requested_set:
            requested_set.remove("Day-wise ToC / course content")
            requested_set.add(toc_item)
        requested_items = [item for item in confirmed_order if item in requested_set]
        if not requested_items:
            requested_items = [
                "Updated CV / Trainer Profile",
                "LinkedIn Profile",
                "Availability",
            ]
    if requirement_kind != "confirmed_batch":
        # ToC and lab cost are Clahan-managed in a proposal workflow. The
        # trainer is not asked to quote a commercial or prepare a ToC/lab-cost
        # document.
        managed_terms = ("commercial", "toc", "course agenda", "day-wise", "lab plan", "lab support", "lab cost")
        requested_items = [item for item in requested_items if not any(term in item.lower() for term in managed_terms)]
        # Experience and current location are read from the trainer resume
        # already held by the platform; do not ask the trainer to repeat them.
        requested_items = [
            item for item in requested_items
            if "experience" not in item.lower() and "current location" not in item.lower()
        ]
        # Apply the same record cross-check used by Shortlist 1. Proposal Mail
        # 1 asks only for information that is absent from the trainer record.
        def is_already_available(item: str) -> bool:
            label = item.lower()
            return (
                (payload.profile_available and any(term in label for term in ("profile", "cv", "resume")))
                or (payload.linkedin_available and "linkedin" in label)
                or (payload.certifications_available and "certification" in label)
                or (payload.location_available and "location" in label)
            )
        requested_items = [item for item in requested_items if not is_already_available(item)]
        ordered_items = [
            "Updated CV / Trainer Profile",
            "LinkedIn Profile",
            "Relevant certifications",
            "Availability",
            "Availability for the specified dates and timings",
            "Available dates for training",
            "Available time slots for technical call",
            "Certification cost, if applicable",
            "Number of similar batches delivered",
            "Client names where similar trainings were delivered",
            "System requirements / hardware",
            "Software required for training",
            "Availability of required software from trainer side",
        ]
        requested_set = set(requested_items)
        requested_items = [item for item in ordered_items if item in requested_set]
        if not requested_items:
            requested_items = ["Availability"]
    request_bullet = "*" if requirement_kind != "confirmed_batch" else "-"
    request_text = "\n".join(f"{request_bullet} {item}" for item in requested_items)
    signature = "Clahan Team" if requirement_kind != "confirmed_batch" else "Clahan Technologies"
    urgent_line = (
        "Please share the details at the earliest as this is an urgent requirement.\n\n"
        if requirement_kind != "confirmed_batch"
        else ""
    )
    body = _simple_trainer_mail1_body(payload, domain, requested_items)
    return {
        "subject": f"Training Requirement - {domain}",
        "body": body,
    }


@router.post("/interview")
async def compose_interview(payload: InterviewEmailRequest):
    link = (payload.interview_link or "").strip()
    date_line = f"\nScheduled: {payload.interview_date}\n" if payload.interview_date else ""
    link_line = f"- Join Link: {link}\n" if link else "- Join Link: To be shared shortly\n"
    subject = f"Interview Slot Booking - {payload.technology} | Ref: {payload.req_id}"
    body = (
        f"Dear {payload.trainer_name},\n\n"
        f"Thank you for your interest in the {payload.technology} opportunity.\n\n"
        f"Your trainer evaluation / client discussion has been scheduled. Please find the calendar invite details below:\n{date_line}\n"
        "Calendar Invite Details:\n"
        f"- Technology: {payload.technology}\n"
        f"- Reference ID: {payload.req_id}\n"
        "- Duration: 30 minutes\n"
        "- Mode: Google Meet\n"
        f"{link_line}\n"
        "Please accept the calendar invite and join on time. Let us know if any change is required.\n\n"
        f"Regards,\nClahan Technologies\n{_from_email()}"
    )
    calendar_invite = _calendar_event_from_interview(payload, subject)
    return {
        "subject": subject,
        "body": body,
        "calendar_invite": calendar_invite,
    }


@router.post("/toc-request")
async def compose_toc_request(payload: TocRequestEmailRequest):
    trainer_name = payload.trainer_name or payload.name or "Trainer"
    body = (
        f"Dear {trainer_name},\n\n"
        "Thank you for the discussion. To proceed further, please share the Table of Contents (ToC) / Course Agenda for the proposed training.\n\n"
        f"Regards,\nClahan Technologies\n{_from_email()}"
    )
    return {"subject": "ToC / Course Agenda Request", "body": body}


@router.post("/retry")
async def compose_retry(payload: RetryEmailRequest):
    body = (
        f"Dear {payload.trainer_name},\n\n"
        f"Following up on the {payload.technology} training opportunity shared earlier.\n\n"
        "Please let us know your interest and availability so we can update the client accordingly.\n"
        "\u2705 Are you available for a quick call this week?\n"
        "\u2705 What is your availability for training engagements?\n\n"
        "Please reply with your available slots, and we will share a Google Meet link once the discussion slot is confirmed.\n\n"
        f"Warm regards,\n{_from_name()}\n{_from_email()}"
    )
    return {
        "subject": f"Follow-Up: {payload.technology} Training Requirement",
        "body": body,
    }


class ClientMail2Request(BaseModel):
    client_name: Optional[str] = "Client"
    technology: Optional[str] = "training"
    subject: Optional[str] = ""


class ClientProceedRequest(BaseModel):
    client_name: Optional[str] = "Client"
    technology: Optional[str] = "training"


@router.post("/client/mail2")
async def compose_client_mail2(payload: ClientMail2Request, x_internal_token: str = Header(None)):
    _require_internal(x_internal_token)
    name = payload.client_name or "Client"
    tech = payload.technology or "training"
    missing_lines = (
        "* Training duration\n"
        "* Preferred training dates\n"
        "* Daily training timings\n"
        "* Audience level (Beginner / Intermediate / Advanced)\n"
        "* Training mode (Online / Offline / Hybrid)\n"
        "* Budget or expected commercial charges per day/session"
    )
    reply = rt._client_missing_details_reply(name, tech, missing_lines)
    return {"subject": reply.get("subject"), "body": reply.get("body")}


@router.post("/client/proceed-ack")
async def compose_client_proceed_ack(payload: ClientProceedRequest, x_internal_token: str = Header(None)):
    _require_internal(x_internal_token)
    name = payload.client_name or "Client"
    tech = payload.technology or "training"
    reply = rt._client_short_requirement_ack(name, tech, template_key="client_proceed_ack")
    return {"subject": reply.get("subject"), "body": reply.get("body")}


@router.post("/client/full-details")
async def compose_client_full_details(payload: GenericSimpleRequest, x_internal_token: str = Header(None)):
    _require_internal(x_internal_token)
    tech = payload.technology or "training"
    reply = rt._client_short_requirement_ack(payload.client_name or "Client", tech, template_key="client_full_details_received")
    return {"subject": reply.get("subject"), "body": reply.get("body")}


@router.post("/client/clarification")
async def compose_client_clarification(payload: GenericSimpleRequest, x_internal_token: str = Header(None)):
    _require_internal(x_internal_token)
    tech = payload.technology or "training"
    reply = rt._client_short_requirement_ack(payload.client_name or "Client", tech, template_key="client_clarification")
    return {"subject": reply.get("subject"), "body": reply.get("body")}


@router.post("/client-slots")
async def compose_client_slots(payload: BaseModel, x_internal_token: str = Header(None)):
    _require_internal(x_internal_token)
    # payload expected fields: client_name, trainer_name, technology, slots_text
    client_name = getattr(payload, "client_name", "Client") or "Client"
    technology = getattr(payload, "technology", "training") or "training"
    slots_text = getattr(payload, "slots_text", "") or "The trainer's availability slots will be shared shortly."
    trainer_details = getattr(payload, "trainer_details", "") or ""
    trainer_details_section = (
        f"Trainer details shared for your review:\n{trainer_details}\n\n"
        if trainer_details
        else ""
    )
    subject = f"Interview Slots - {technology}"
    body = (
        f"{_client_time_greeting(client_name)},\n\n"
        f"Thank you for sharing the requirement details for the {technology} training.\n\n"
        f"We have coordinated suitable interview/discussion slots for the shortlisted {technology} trainer.\n\n"
        f"{trainer_details_section}"
        "Available slots:\n"
        f"{slots_text}\n\n"
        "Kindly confirm the preferred slot, and we will proceed with the meeting coordination.\n\n"
        "Regards,\nClahan Technologies"
    )
    return {"subject": subject, "body": body}


class GenericSimpleRequest(BaseModel):
    name: Optional[str] = ""
    technology: Optional[str] = ""
    requirement_id: Optional[str] = ""
    client_name: Optional[str] = "Client"
    requested_details: List[str] = []


@router.post("/mail2")
async def compose_mail2(payload: GenericSimpleRequest):
    tech = payload.technology or "training"
    subject = f"Details Request: {tech} Trainer Requirement"
    ref_text = f" (Ref: {payload.requirement_id})" if payload.requirement_id else ""
    requested_details = payload.requested_details or ["Updated trainer profile/CV"]
    requested_lines = "\n".join(f"- {item}" for item in requested_details)
    polished_body = (
        f"Dear {payload.name or 'Trainer'},\n\n"
        f"Thank you for confirming your interest in the {tech} requirement{ref_text}.\n\n"
        "To proceed further, kindly share the below details:\n\n"
        f"- Technology: {tech}\n\n"
        f"{requested_lines}\n\n"
        "Regards,\nClahan Technologies"
    )
    return {"subject": subject, "body": polished_body}


@router.post("/mail2-followup")
async def compose_mail2_followup(payload: GenericSimpleRequest):
    tech = payload.technology or "training"
    subject = f"Reminder: Details Request - {tech} Requirement"
    body = (
        f"Dear {payload.name or 'Trainer'},\n\n"
        "Thank you for confirming your interest.\n\n"
        f"To proceed further for the {tech} requirement, kindly share the above requested details.\n\n"
        "Regards,\nClahan Technologies"
    )
    return {"subject": subject, "body": body}

@router.post("/trainer-ack")
async def compose_trainer_ack(payload: GenericSimpleRequest):
    subject = "Trainer Acknowledgement"
    body = (
        f"Dear {payload.name or 'Trainer'},\n\n"
        "Thank you for sharing your details. We have noted your profile, availability, and commercials for the requirement.\n\n"
        "We will review and update you with the next coordination step shortly.\n\n"
        "Regards,\nClahan Technologies"
    )
    return {"subject": subject, "body": body}


@router.post("/send-commercials")
async def compose_send_commercials(payload: GenericSimpleRequest):
    subject = f"Commercials for {payload.technology or 'training'} Requirement"
    body = (
        f"{_client_time_greeting(payload.client_name or 'Client')},\n\n"
        "Please find the trainer commercials attached/outlined below.\n\n"
        "Regards,\n" + _from_name()
    )
    return {"subject": subject, "body": body}


@router.post("/client-budget-reply")
async def compose_client_budget_reply(payload: GenericSimpleRequest, x_internal_token: str = Header(None)):
    _require_internal(x_internal_token)
    subject = "Budget Received â€” Thank you"
    body = (
        f"{_client_time_greeting(payload.client_name or 'Client')},\n\n"
        "Thank you for sharing the budget/commercial feedback.\n\n"
        "We will review the commercials and revert with the feasible option shortly.\n\n"
        "Regards,\n" + _from_name()
    )
    return {"subject": subject, "body": body}


@router.post("/client-budget-ack")
async def compose_client_budget_ack(payload: GenericSimpleRequest, x_internal_token: str = Header(None)):
    _require_internal(x_internal_token)
    subject = "Budget Acknowledgement"
    body = (
        f"{_client_time_greeting(payload.client_name or 'Client')},\n\n"
        "Thank you for confirming the budget.\n\n"
        "We will align the trainer option accordingly and proceed with the next coordination step.\n\n"
        "Regards,\n" + _from_name()
    )
    return {"subject": subject, "body": body}


@router.post("/rate-gap-resolution")
async def compose_rate_gap_resolution(payload: GenericSimpleRequest):
    subject = "Rate Gap â€” Proposed Resolution"
    body = (
        f"{_client_time_greeting(payload.client_name or 'Client')},\n\n"
        "We have reviewed the rate expectation for this requirement.\n\n"
        "We will share the feasible commercial option for your review shortly.\n\n"
        "Regards,\n" + _from_name()
    )
    return {"subject": subject, "body": body}


@router.post("/client-proceed")
async def compose_client_proceed(payload: GenericSimpleRequest, x_internal_token: str = Header(None)):
    _require_internal(x_internal_token)
    # Keep wording aligned with shared templates
    tech = payload.technology or "training"
    reply = rt._client_short_requirement_ack(payload.client_name or "Client", tech, template_key="client_proceed")
    return {"subject": reply.get("subject"), "body": reply.get("body")}


@router.post("/client-alternative")
async def compose_client_alternative(payload: GenericSimpleRequest, x_internal_token: str = Header(None)):
    _require_internal(x_internal_token)
    tech = payload.technology or "training"
    reply = rt._client_short_requirement_ack(payload.client_name or "Client", tech, template_key="client_alternative")
    return {"subject": reply.get("subject"), "body": reply.get("body")}


@router.post("/client-toc-request")
async def compose_client_toc_request(payload: GenericSimpleRequest, x_internal_token: str = Header(None)):
    _require_internal(x_internal_token)
    subject = "TOC / Course Agenda Request"
    body = (
        f"{_client_time_greeting(payload.client_name or 'Client')},\n\n"
        "We have requested the trainer to share the Table of Contents (ToC) / Course Agenda.\n\n"
        "We will share it with you once received.\n\n"
        "Regards,\n" + _from_name()
    )
    return {"subject": subject, "body": body}


@router.post("/trainer-rate-discussion")
async def compose_trainer_rate_discussion(payload: GenericSimpleRequest):
    subject = "Commercial Discussion"
    body = (
        f"Dear {payload.name or 'Trainer'},\n\n"
        "Thank you for sharing your commercial expectation.\n\n"
        "Please confirm your best workable commercial for this requirement so we can proceed with the client coordination.\n\n"
        "Regards,\nClahan Technologies"
    )
    return {"subject": subject, "body": body}


@router.post("/mail3-slot-booking")
async def compose_mail3_slot_booking(payload: GenericSimpleRequest):
    technology = payload.technology or "Training"
    subject = f"Interview Slot Booking - {technology}"
    polished_body = (
        f"Dear {payload.name or 'Trainer'},\n\n"
        "Please share three convenient interview/discussion slots with date, time, and time zone so we can coordinate with the client.\n\n"
        "Preferred format:\n"
        "- Date: 1 September 2026, Time: 10:00 AM - 10:30 AM IST\n"
        "- Date: 2 September 2026, Time: 2:00 PM - 2:30 PM IST\n"
        "- Date: 3 September 2026, Time: 4:00 PM - 4:30 PM IST\n\n"
        "Regards,\n"
        "Clahan Technologies"
    )
    return {"subject": subject, "body": polished_body}


@router.post("/mail3-too-many")
async def compose_mail3_too_many(payload: GenericSimpleRequest):
    raise HTTPException(
        status_code=410,
        detail=(
            "Retired workflow: slots are requested in Mail 1. "
            "An incomplete response may receive one Mail 2 follow-up for exactly three dated slots."
        ),
    )


@router.post("/mail3-too-few")
async def compose_mail3_too_few(payload: GenericSimpleRequest):
    raise HTTPException(
        status_code=410,
        detail=(
            "Retired workflow: slots are requested in Mail 1. "
            "An incomplete response may receive one Mail 2 follow-up for exactly three dated slots."
        ),
    )


@router.post("/mail5-selection")
async def compose_mail5_selection(payload: GenericSimpleRequest):
    tech = payload.technology or "training"
    subject = f"Selection Update - {tech} Requirement"
    body = (
        f"Dear {payload.name or 'Trainer'},\n\n"
        f"Congratulations. The client has selected your profile for the {tech} requirement.\n\n"
        "We will share the next steps and coordination details shortly.\n\n"
        f"Regards,\nClahan Technologies\n{_from_email()}"
    )
    return {"subject": subject, "body": body}


@router.post("/mail5-rejection")
async def compose_mail5_rejection(payload: GenericSimpleRequest):
    polished_subject = "Update - Application Status"
    polished_body = (
        f"Dear {payload.name or 'Trainer'},\n\n"
        "Thank you for your time and interest. The client has decided to proceed with another profile for this requirement.\n\n"
        "We will keep your profile in consideration for suitable future opportunities.\n\n"
        "Regards,\nClahan Technologies"
    )
    return {"subject": polished_subject, "body": polished_body}
    subject = "Update â€” Application Status"
    body = (
        f"Dear {payload.name or 'Trainer'},\n\n"
        "Thank you for your interest. Unfortunately, we will not be proceeding with your profile for this requirement. We will keep you in our pool for future opportunities.\n\n"
        "Regards,\n" + _from_name()
    )
    return {"subject": subject, "body": body}


@router.post("/mail6-toc-request")
async def compose_mail6_toc_request(payload: GenericSimpleRequest):
    polished_subject = "ToC / Course Agenda Request"
    polished_body = (
        f"Dear {payload.name or 'Trainer'},\n\n"
        "Please share the Table of Contents (ToC) / Course Agenda for the proposed training delivery so we can align it with the client requirement.\n\n"
        "Regards,\nClahan Technologies"
    )
    return {"subject": polished_subject, "body": polished_body}
    subject = "ToC / Course Agenda Request"
    body = (
        f"Dear {payload.name or 'Trainer'},\n\n"
        "Please share the Table of Contents (ToC) / Course Agenda for the proposed training delivery.\n\n"
        "Regards,\n" + _from_name()
    )
    return {"subject": subject, "body": body}


@router.post("/mail7-training-confirmation")
async def compose_mail7_confirmation(payload: GenericSimpleRequest):
    polished_subject = "Training Confirmation - Next Steps"
    polished_body = (
        f"Dear {payload.name or 'Trainer'},\n\n"
        f"We are pleased to confirm your engagement for the {payload.technology or 'training'} requirement.\n\n"
        "We will share the final logistics and coordination details shortly.\n\n"
        "Regards,\nClahan Technologies"
    )
    return {"subject": polished_subject, "body": polished_body}
    subject = "Training Confirmation â€” Next Steps"
    body = (
        f"{_client_time_greeting(payload.client_name or payload.name or 'Client')},\n\n"
        "This confirms the training booking. We will share final logistics, invoices, and trainer details shortly.\n\n"
        "Regards,\n" + _from_name()
    )
    return {"subject": subject, "body": body}
