"""Email template composition endpoints."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.config import get_settings
from app.agents import reply_templates as rt

router = APIRouter()
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
    client_name: Optional[str] = ""
    audience_level: Optional[str] = ""
    location: Optional[str] = ""
    budget: Optional[str] = ""
    topics: Optional[str] = ""
    client_request: Optional[str] = ""


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


class InterviewEmailRequest(BaseModel):
    trainer_name: str
    technology: str
    req_id: str
    interview_date: Optional[str] = ""
    interview_link: Optional[str] = ""


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
    detail_lines = [f"Domain/Technology: {domain}"]
    if payload.dates:
        detail_lines.append(f"Dates/Timings: {payload.dates}")
    if payload.mode:
        detail_lines.append(f"Mode: {payload.mode}")
    if payload.duration:
        detail_lines.append(f"Duration: {payload.duration}")
    if payload.participants:
        detail_lines.append(f"Participants: {payload.participants}")
    if payload.budget:
        detail_lines.append(f"Commercials: {payload.budget}")
    detail_text = "\n".join(detail_lines)
    client_request = _clean_client_request_for_trainer(payload.client_request or "")
    if client_request:
        detail_text = f"Client Requirement Details:\n{client_request}"
        if payload.budget:
            detail_text += f"\n\nCommercials: {payload.budget}"

    missing_note = ""
    if not payload.duration or not payload.participants:
        missing_note = (
            "\n\nAt this stage, we are checking your interest and availability first. "
            "Once you confirm, we will share the confirmed duration, schedule, participants, "
            "and other requirement details as they are finalised."
        )

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
    body = (
        f"Dear {payload.trainer_name or 'Trainer'},\n\n"
        f"We have a {domain} training opportunity that appears aligned with your profile.\n\n"
        f"Requirement Snapshot:\n\n{detail_text}{missing_note}\n\n"
        "Please confirm if you are interested and available for this requirement. Kindly share your updated trainer profile along with relevant experience for client review.\n\n"
        f"{slot_guide}"
        f"Regards,\nClahan Technologies\n{_from_email()}"
    )
    return {
        "subject": f"Training Requirement - {domain}",
        "body": body,
    }


@router.post("/interview")
async def compose_interview(payload: InterviewEmailRequest):
    link = (payload.interview_link or "").strip()
    date_line = f"\n\U0001F4C5 Scheduled: {payload.interview_date}\n" if payload.interview_date else ""
    link_line = f"- Google Meet: {link}\n" if link else "- Google Meet: To be shared shortly\n"
    body = (
        f"Dear {payload.trainer_name},\n\n"
        f"Thank you for your interest in the {payload.technology} opportunity.\n\n"
        f"The client discussion has been scheduled. Please find the details below:\n{date_line}\n"
        "Interview Details:\n"
        f"- Technology: {payload.technology}\n"
        f"- Reference ID: {payload.req_id}\n"
        "- Duration: 30 minutes\n"
        "- Mode: Google Meet\n"
        f"{link_line}\n"
        "Please join on time and let us know if any change is required.\n\n"
        f"Regards,\nClahan Technologies\n{_from_email()}"
    )
    return {
        "subject": f"Interview Slot Booking â€“ {payload.technology} | Ref: {payload.req_id}",
        "body": body,
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
    body = (
        f"{_client_time_greeting(name)},\n\n"
        f"Thank you for sharing the {tech} requirement. We have noted the available details.\n\n"
        "To help us shortlist the best-fit trainer, kindly share only the missing details below:\n\n"
        "* {Only missing fields}\n\n"
        "Once received, we will share suitable trainer options with commercials and availability.\n\n"
        "Regards,\nClahan Technologies"
    )
    return {"subject": f"Re: {tech} Trainer Requirement", "body": body}


@router.post("/client/full-details")
async def compose_client_full_details(payload: GenericSimpleRequest, x_internal_token: str = Header(None)):
    _require_internal(x_internal_token)
    tech = payload.technology or "training"
    body = (
        f"{_client_time_greeting(payload.client_name or 'Client')},\n\n"
        f"Thank you for sharing the required details for your {tech} training requirement.\n\n"
        "We will share the best-fit trainer options with commercials and availability shortly.\n\n"
        "Regards,\nClahan Technologies"
    )
    return {"subject": f"Re: {tech} Trainer Requirement", "body": body}


@router.post("/client/clarification")
async def compose_client_clarification(payload: GenericSimpleRequest, x_internal_token: str = Header(None)):
    _require_internal(x_internal_token)
    body = (
        f"{_client_time_greeting(payload.client_name or 'Client')},\n\n"
        "Thank you for reaching out. Please share the technology/topic, delivery mode, dates or duration, participant count, and budget range.\n\n"
        "Once received, we will share suitable trainer options for your review.\n\n"
        "Regards,\nClahan Technologies"
    )
    return {"subject": "Re: Training Requirement Details", "body": body}


@router.post("/client-slots")
async def compose_client_slots(payload: BaseModel, x_internal_token: str = Header(None)):
    _require_internal(x_internal_token)
    # payload expected fields: client_name, trainer_name, technology, slots_text
    client_name = getattr(payload, "client_name", "Client") or "Client"
    technology = getattr(payload, "technology", "training") or "training"
    slots_text = getattr(payload, "slots_text", "") or "The trainer's availability slots will be shared shortly."
    subject = f"Interview Slots - {technology}"
    body = (
        f"{_client_time_greeting(client_name)},\n\n"
        f"We have coordinated suitable interview/discussion slots for the shortlisted {technology} trainer.\n\n"
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


@router.post("/mail2")
async def compose_mail2(payload: GenericSimpleRequest):
    tech = payload.technology or "training"
    subject = f"Details Request: {tech} Trainer Requirement"
    ref_text = f" (Ref: {payload.requirement_id})" if payload.requirement_id else ""
    polished_body = (
        f"Dear {payload.name or 'Trainer'},\n\n"
        f"Thank you for your interest in the {tech} requirement{ref_text}.\n\n"
        "To move ahead with the client coordination, please share the following details:\n\n"
        "- Updated trainer profile/resume, if any newer version is available\n"
        "- Expected commercial charges per day/session\n"
        "- Table of Contents (ToC) / Course Agenda, if available\n\n"
        "Regards,\nClahan Technologies"
    )
    return {"subject": subject, "body": polished_body}


@router.post("/mail2-followup")
async def compose_mail2_followup(payload: GenericSimpleRequest):
    tech = payload.technology or "training"
    subject = f"Reminder: Details Request - {tech} Requirement"
    body = (
        f"Dear {payload.name or 'Trainer'},\n\n"
        f"Following up on the details requested for the {tech} requirement.\n\n"
        "Please share your commercial expectation and updated profile so we can proceed with the client coordination.\n\n"
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
        "Thank you for sharing the budget. We will align trainer options accordingly and revert shortly.\n\n"
        "Regards,\n" + _from_name()
    )
    return {"subject": subject, "body": body}


@router.post("/client-budget-ack")
async def compose_client_budget_ack(payload: GenericSimpleRequest, x_internal_token: str = Header(None)):
    _require_internal(x_internal_token)
    subject = "Budget Acknowledgement"
    body = (
        f"{_client_time_greeting(payload.client_name or 'Client')},\n\n"
        "Acknowledging receipt of the budget and next steps.\n\n"
        "Regards,\n" + _from_name()
    )
    return {"subject": subject, "body": body}


@router.post("/rate-gap-resolution")
async def compose_rate_gap_resolution(payload: GenericSimpleRequest):
    subject = "Rate Gap â€” Proposed Resolution"
    body = (
        f"{_client_time_greeting(payload.client_name or 'Client')},\n\n"
        "We have reviewed the rate expectations and propose the following resolution/options to bridge the gap.\n\n"
        "Regards,\n" + _from_name()
    )
    return {"subject": subject, "body": body}


@router.post("/client-proceed")
async def compose_client_proceed(payload: GenericSimpleRequest, x_internal_token: str = Header(None)):
    _require_internal(x_internal_token)
    # Keep wording aligned with shared templates
    tech = payload.technology or "training"
    reply = rt._reply("Proceed â€” Trainer Search Initiated", f"{_client_time_greeting(payload.client_name or 'Client')},\n\nWe will proceed with the initial trainer search and share shortlisted profiles shortly.\n\n{rt.SIGNATURE}", "client_proceed")
    return {"subject": reply.get("subject"), "body": reply.get("body")}


@router.post("/client-alternative")
async def compose_client_alternative(payload: GenericSimpleRequest, x_internal_token: str = Header(None)):
    _require_internal(x_internal_token)
    reply = rt._reply("Alternative Option â€” Trainer Recommendation", f"{_client_time_greeting(payload.client_name or 'Client')},\n\nThanks â€” as requested we will share alternative trainer options and details.\n\n{rt.SIGNATURE}", "client_alternative")
    return {"subject": reply.get("subject"), "body": reply.get("body")}


@router.post("/client-toc-request")
async def compose_client_toc_request(payload: GenericSimpleRequest, x_internal_token: str = Header(None)):
    _require_internal(x_internal_token)
    subject = "TOC / Course Agenda Request"
    body = (
        f"{_client_time_greeting(payload.client_name or 'Client')},\n\n"
        "Kindly share the Table of Contents (ToC) / Course Agenda so we can align the trainer profile and delivery.\n\n"
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
        "Thank you for sharing the required details.\n\n"
        "Please share three convenient interview/discussion slots with date, time, and time zone so we can coordinate with the client.\n\n"
        "Preferred format:\n"
        "- 15 January 2026, 10:00 AM - 10:30 AM IST\n"
        "- 16 January 2026, 02:00 PM - 02:30 PM IST\n"
        "- 17 January 2026, 04:00 PM - 04:30 PM IST\n\n"
        "Regards,\n"
        "Clahan Technologies"
    )
    return {"subject": subject, "body": polished_body}


@router.post("/mail3-too-many")
async def compose_mail3_too_many(payload: GenericSimpleRequest):
    subject = "Re: Interview Slot Booking"
    polished_body = (
        f"Dear {payload.name or 'Trainer'},\n\n"
        "Thank you for sharing your availability. To coordinate smoothly with the client, please share your top 3 preferred slots with date, time, and time zone.\n\n"
        "Regards,\nClahan Technologies"
    )
    return {"subject": subject, "body": polished_body}
    body = (
        f"Hi {payload.name or 'Trainer'},\n\n"
        "Thank you for your availability. For our scheduling process, we typically work with 3 slots as it helps us coordinate efficiently.\n\n"
        "Could you please share your top 3 preferred slots with dates and times?\n\n"
        "Thank you."
    )
    return {"subject": subject, "body": body}


@router.post("/mail3-too-few")
async def compose_mail3_too_few(payload: GenericSimpleRequest):
    subject = "Interview Slot Details Required"
    polished_body = (
        f"Dear {payload.name or 'Trainer'},\n\n"
        "Thank you for sharing the slot. Please share the exact date and time, including AM/PM and time zone. If possible, share 2-3 options so we can close the schedule faster.\n\n"
        "Regards,\nClahan Technologies"
    )
    return {"subject": subject, "body": polished_body}
    body = (
        f"Hi {payload.name or 'Trainer'},\n\n"
        "Thank you for sharing the slot. Could you please provide the exact interview date and time, including whether it is AM or PM?\n\n"
        "Also, please share 3 available slots with the corresponding dates so that we can schedule the interview accordingly.\n\n"
        "Thanks."
    )
    return {"subject": subject, "body": body}


@router.post("/mail5-selection")
async def compose_mail5_selection(payload: GenericSimpleRequest):
    raise HTTPException(
        status_code=410,
        detail="Trainer selection/onboarding email template has been removed.",
    )


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
        "This confirms the training engagement. We will share the final logistics and coordination details shortly.\n\n"
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
