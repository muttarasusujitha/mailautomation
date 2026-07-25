"""Email template composition endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.config import get_settings
from app.agents import reply_templates as rt

router = APIRouter()
settings = get_settings()


def _require_internal(x_internal_token: str = Header(None)) -> None:
    # If INTERNAL_SERVICE_TOKEN is configured, require matching header.
    token = settings.INTERNAL_SERVICE_TOKEN or ""
    if token:
        if not x_internal_token or x_internal_token != token:
            raise HTTPException(status_code=403, detail="Forbidden: invalid internal token")


def _from_name() -> str:
    return settings.FROM_NAME or "TrainerSync"


PLACEHOLDER_EMAILS = {
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
    if payload.duration:
        detail_lines.append(f"Duration: {payload.duration}")
    if payload.dates:
        detail_lines.append(f"Dates/Timings: {payload.dates}")
    if payload.mode:
        detail_lines.append(f"Mode: {payload.mode}")
    if payload.participants:
        detail_lines.append(f"Participants: {payload.participants}")
    detail_text = "\n".join(detail_lines)

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
Slot 1: 22 June 2026, 11:00 AM – 11:30 AM IST
Slot 2: 23 June 2026, 2:00 PM – 2:30 PM IST
Slot 3: 25 June 2026, 4:00 PM – 4:30 PM IST

This helps us process your availability automatically and move forward quickly.
"""
    missing_note = ""
    slot_guide = ""
    body = (
        f"Dear {payload.trainer_name or 'Trainer'},\n\n"
        f"We have received a training requirement for {domain} and are looking for a trainer with relevant experience.\n\n"
        f"Training Details:\n\n{detail_text}{missing_note}\n\n"
        "Please let us know if you are interested and available for this requirement. "
        "Kindly share your updated trainer profile along with relevant experience.\n\n"
        f"{slot_guide}"
        "Regards,\nTrainerSync Team"
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
        f"Thank you for your interest in the {payload.technology} training opportunity!\n\n"
        f"We are pleased to confirm your interview/discussion session.\n{date_line}\n"
        "Interview Details:\n"
        f"- Technology: {payload.technology}\n"
        f"- Reference ID: {payload.req_id}\n"
        "- Duration: 30 minutes\n"
        "- Mode: Google Meet\n"
        f"{link_line}\n"
        "Please confirm your availability by replying to this email.\n\n"
        "We look forward to speaking with you!\n\n"
        f"Warm regards,\n{_from_name()}\n{_from_email()}"
    )
    return {
        "subject": f"Interview Slot Booking – {payload.technology} | Ref: {payload.req_id}",
        "body": body,
    }


@router.post("/toc-request")
async def compose_toc_request(payload: TocRequestEmailRequest):
    trainer_name = payload.trainer_name or payload.name or "Trainer"
    body = (
        f"Dear {trainer_name},\n\n"
        "Congratulations on clearing the discussion round.\n\n"
        "Kindly share the Table of Contents (ToC) / Course Agenda for the training "
        "so we can proceed further with the client.\n\n"
        f"Regards,\n{_from_name()}\n{_from_email()}"
    )
    return {"subject": "ToC / Course Agenda Request", "body": body}


@router.post("/retry")
async def compose_retry(payload: RetryEmailRequest):
    body = (
        f"Dear {payload.trainer_name},\n\n"
        "I hope you're doing well!\n\n"
        f"I wanted to follow up on my earlier message regarding a {payload.technology} training opportunity.\n\n"
        "We remain very interested in your profile. Could you please let us know:\n"
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
        f"Dear {name},\n\n"
        f"Thank you for sharing your {tech} training requirement.\n\n"
        f"We have noted your requirement and will proceed with the initial trainer search for your {tech} requirement based on the information currently available.\n\n"
        "Our team will start identifying suitable trainers with relevant domain expertise, availability, and experience.\n\n"
        "To help us refine the shortlist and design the best-fit training content, kindly share only the following missing details:\n\n"
        "* {Only missing fields}\n\n"
        "These details will help us recommend better matched trainers and align the course content more accurately with your participants.\n\n"
        "We will share the most suitable profiles with commercials and availability for your review.\n\n"
        "Best Regards,\nRecruitment Team\nClahan Technologies"
    )
    return {"subject": f"Re: {tech} Trainer Requirement", "body": body}


@router.post("/client/full-details")
async def compose_client_full_details(payload: GenericSimpleRequest, x_internal_token: str = Header(None)):
    _require_internal(x_internal_token)
    tech = payload.technology or "training"
    body = (
        "Dear Client,\n\n"
        f"Thank you for sharing the required details for your {tech} training requirement.\n\n"
        "We will proceed with the trainer search and share suitable profiles with experience, skill set, availability, and commercials for your review shortly.\n\n"
        "Best Regards,\nRecruitment Team\nClahan Technologies"
    )
    return {"subject": f"Re: {tech} Trainer Requirement", "body": body}


@router.post("/client/clarification")
async def compose_client_clarification(payload: GenericSimpleRequest, x_internal_token: str = Header(None)):
    _require_internal(x_internal_token)
    body = (
        "Dear Client,\n\n"
        "Thank you for sharing the training requirement. To shortlist the right trainer profiles, please confirm the technology/topic, delivery mode, expected dates or duration, participant count, and commercials or budget range.\n\n"
        "Once we have these details, we will share suitable profiles for your review.\n\n"
        "Best Regards,\nRecruitment Team\nClahan Technologies"
    )
    return {"subject": "Re: Training Requirement Details", "body": body}


@router.post("/client-slots")
async def compose_client_slots(payload: BaseModel, x_internal_token: str = Header(None)):
    _require_internal(x_internal_token)
    # payload expected fields: client_name, trainer_name, technology, slots_text
    client_name = getattr(payload, "client_name", "Client") or "Client"
    trainer_name = getattr(payload, "trainer_name", "Trainer") or "Trainer"
    technology = getattr(payload, "technology", "training") or "training"
    slots_text = getattr(payload, "slots_text", "") or "The trainer's availability slots will be shared shortly."
    subject = f"Interview Slots — {technology} | {trainer_name}"
    body = (
        f"Dear {client_name},\n\n"
        f"Trainer {trainer_name} has shared the available interview slots for the {technology} requirement.\n\n"
        "Available slots:\n"
        f"{slots_text}\n\n"
        "Kindly confirm your preferred slot at the earliest.\n\n"
        "Best Regards,\nRecruitment Team\nClahan Technologies"
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
    body = (
        f"Dear {payload.name or 'Trainer'},\n\n"
        f"Following up on the {tech} requirement (Ref: {payload.requirement_id}). Could you please share the following details so we can shortlist appropriately:\n\n"
        "- Commercials/rate per day or per session\n- Current availability\n- Detailed experience/brief profile or credentials\n- Any sample course outlines or ToC\n\n"
        "Thanks and regards,\n" + _from_name()
    )
    return {"subject": subject, "body": body}


@router.post("/mail2-followup")
async def compose_mail2_followup(payload: GenericSimpleRequest):
    tech = payload.technology or "training"
    subject = f"Reminder: Details Request — {tech} Requirement"
    body = (
        f"Dear {payload.name or 'Trainer'},\n\n"
        "Just following up on my earlier request for details. Kindly share your commercials/rate, availability, and brief profile or credentials if you are interested.\n\n"
        "Regards,\n" + _from_name()
    )
    return {"subject": subject, "body": body}


@router.post("/trainer-ack")
async def compose_trainer_ack(payload: GenericSimpleRequest):
    subject = "Trainer Acknowledgement"
    body = (
        f"Dear {payload.name or 'Trainer'},\n\n"
        "Thank you for sharing your credentials, availability, and commercial details. We will review them for the requirement and update you with the next steps.\n\n"
        "Regards,\n" + _from_name()
    )
    return {"subject": subject, "body": body}


@router.post("/send-commercials")
async def compose_send_commercials(payload: GenericSimpleRequest):
    subject = f"Commercials for {payload.technology or 'training'} Requirement"
    body = (
        f"Dear {payload.client_name or 'Client'},\n\n"
        "Please find the trainer commercials attached/outlined below.\n\n"
        "Regards,\n" + _from_name()
    )
    return {"subject": subject, "body": body}


@router.post("/client-budget-reply")
async def compose_client_budget_reply(payload: GenericSimpleRequest, x_internal_token: str = Header(None)):
    _require_internal(x_internal_token)
    subject = "Budget Received — Thank you"
    body = (
        f"Dear {payload.client_name or 'Client'},\n\n"
        "Thank you for sharing the budget. We will align trainer options accordingly and revert shortly.\n\n"
        "Regards,\n" + _from_name()
    )
    return {"subject": subject, "body": body}


@router.post("/client-budget-ack")
async def compose_client_budget_ack(payload: GenericSimpleRequest, x_internal_token: str = Header(None)):
    _require_internal(x_internal_token)
    subject = "Budget Acknowledgement"
    body = (
        f"Dear {payload.client_name or 'Client'},\n\n"
        "Acknowledging receipt of the budget and next steps.\n\n"
        "Regards,\n" + _from_name()
    )
    return {"subject": subject, "body": body}


@router.post("/rate-gap-resolution")
async def compose_rate_gap_resolution(payload: GenericSimpleRequest):
    subject = "Rate Gap — Proposed Resolution"
    body = (
        f"Dear {payload.client_name or 'Client'},\n\n"
        "We have reviewed the rate expectations and propose the following resolution/options to bridge the gap.\n\n"
        "Regards,\n" + _from_name()
    )
    return {"subject": subject, "body": body}


@router.post("/client-proceed")
async def compose_client_proceed(payload: GenericSimpleRequest, x_internal_token: str = Header(None)):
    _require_internal(x_internal_token)
    # Keep wording aligned with shared templates
    tech = payload.technology or "training"
    reply = rt._reply("Proceed — Trainer Search Initiated", f"Dear {payload.client_name or 'Client'},\n\nWe will proceed with the initial trainer search and share shortlisted profiles shortly.\n\n{rt.SIGNATURE}", "client_proceed")
    return {"subject": reply.get("subject"), "body": reply.get("body")}


@router.post("/client-alternative")
async def compose_client_alternative(payload: GenericSimpleRequest, x_internal_token: str = Header(None)):
    _require_internal(x_internal_token)
    reply = rt._reply("Alternative Option — Trainer Recommendation", f"Dear {payload.client_name or 'Client'},\n\nThanks — as requested we will share alternative trainer options and details.\n\n{rt.SIGNATURE}", "client_alternative")
    return {"subject": reply.get("subject"), "body": reply.get("body")}


@router.post("/client-toc-request")
async def compose_client_toc_request(payload: GenericSimpleRequest, x_internal_token: str = Header(None)):
    _require_internal(x_internal_token)
    subject = "TOC / Course Agenda Request"
    body = (
        f"Dear {payload.client_name or 'Client'},\n\n"
        "Kindly share the Table of Contents (ToC) / Course Agenda so we can align the trainer profile and delivery.\n\n"
        "Regards,\n" + _from_name()
    )
    return {"subject": subject, "body": body}


@router.post("/trainer-rate-discussion")
async def compose_trainer_rate_discussion(payload: GenericSimpleRequest):
    subject = "Trainer Rate Discussion"
    body = (
        f"Dear {payload.name or 'Trainer'},\n\n"
        "Could you please confirm your expected rates and flexibility so we can proceed with client discussions?\n\n"
        "Regards,\n" + _from_name()
    )
    return {"subject": subject, "body": body}


@router.post("/mail3-slot-booking")
async def compose_mail3_slot_booking(payload: GenericSimpleRequest):
    technology = payload.technology or "Training"
    subject = f"Interview Slot Booking - {technology}"
    body = (
        f"Dear {payload.name or 'Trainer'},\n\n"
        "Thank you for sharing your details.\n\n"
        "We would like to book an interview slot with you. Based on your availability, please confirm one of the following slots:\n\n"
        "example\n"
        "• Monday, Jan 15, 2024 - 10:00 AM IST\n"
        "• Tuesday, Jan 16, 2024 - 2:00 PM IST\n"
        "• Wednesday, Jan 17, 2024 - 4:00 PM IST\n"
        "• [Slot 1]\n"
        "• [Slot 2]\n"
        "• [Slot 3]\n\n"
        "Kindly confirm your preferred slot at the earliest.\n\n"
        "Regards,\n"
        "TrainerSync Team"
    )
    return {"subject": subject, "body": body}


@router.post("/mail3-too-many")
async def compose_mail3_too_many(payload: GenericSimpleRequest):
    subject = "Re: Interview Slot Booking"
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
    body = (
        f"Hi {payload.name or 'Trainer'},\n\n"
        "Thank you for sharing the slot. Could you please provide the exact interview date and time, including whether it is AM or PM?\n\n"
        "Also, please share 3 available slots with the corresponding dates so that we can schedule the interview accordingly.\n\n"
        "Thanks."
    )
    return {"subject": subject, "body": body}


@router.post("/mail5-selection")
async def compose_mail5_selection(payload: GenericSimpleRequest):
    subject = "Selection — Trainer Confirmed"
    body = (
        f"Dear {payload.name or 'Trainer'},\n\n"
        "Congratulations — you have been selected for the assignment. We will share next steps and commercial terms shortly.\n\n"
        "Regards,\n" + _from_name()
    )
    return {"subject": subject, "body": body}


@router.post("/mail5-rejection")
async def compose_mail5_rejection(payload: GenericSimpleRequest):
    subject = "Update — Application Status"
    body = (
        f"Dear {payload.name or 'Trainer'},\n\n"
        "Thank you for your interest. Unfortunately, we will not be proceeding with your profile for this requirement. We will keep you in our pool for future opportunities.\n\n"
        "Regards,\n" + _from_name()
    )
    return {"subject": subject, "body": body}


@router.post("/mail6-toc-request")
async def compose_mail6_toc_request(payload: GenericSimpleRequest):
    subject = "ToC / Course Agenda Request"
    body = (
        f"Dear {payload.name or 'Trainer'},\n\n"
        "Please share the Table of Contents (ToC) / Course Agenda for the proposed training delivery.\n\n"
        "Regards,\n" + _from_name()
    )
    return {"subject": subject, "body": body}


@router.post("/mail7-training-confirmation")
async def compose_mail7_confirmation(payload: GenericSimpleRequest):
    subject = "Training Confirmation — Next Steps"
    body = (
        f"Dear {payload.client_name or payload.name or 'Client'},\n\n"
        "This confirms the training booking. We will share final logistics, invoices, and trainer details shortly.\n\n"
        "Regards,\n" + _from_name()
    )
    return {"subject": subject, "body": body}
