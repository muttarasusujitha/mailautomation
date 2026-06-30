"""Email template composition endpoints."""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from app.config import get_settings

router = APIRouter()
settings = get_settings()


def _from_name() -> str:
    return settings.FROM_NAME or "TrainerSync"


def _from_email() -> str:
    return settings.FROM_EMAIL or settings.GMAIL_USER or ""


class ShortlistEmailRequest(BaseModel):
    trainer_name: str
    domain: str
    duration: Optional[str] = ""
    mode: Optional[str] = ""
    participants: Optional[str] = ""


class InterviewEmailRequest(BaseModel):
    trainer_name: str
    technology: str
    req_id: str
    interview_date: Optional[str] = ""
    interview_link: Optional[str] = ""


class TocRequestEmailRequest(BaseModel):
    trainer_name: str


class RetryEmailRequest(BaseModel):
    trainer_name: str
    technology: str
    req_id: str


@router.post("/shortlist-first")
async def compose_shortlist_first(payload: ShortlistEmailRequest):
    detail_lines = [f"* Domain/Technology: {payload.domain}"]
    if payload.duration:
        detail_lines.append(f"* Duration: {payload.duration}")
    if payload.mode:
        detail_lines.append(f"* Mode: {payload.mode}")
    if payload.participants:
        detail_lines.append(f"* Participants: {payload.participants}")
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
    body = (
        f"Dear {payload.trainer_name or 'Trainer'},\n\n"
        f"We have received a training requirement for {payload.domain} and are looking for a trainer with relevant experience.\n\n"
        f"Training Details:\n\n{detail_text}{missing_note}\n\n"
        "Please let us know if you are interested and available for this requirement. "
        "Kindly share your updated trainer profile along with relevant experience."
        f"{slot_guide}"
        f"Regards,\n{_from_name()}\n{_from_email()}"
    )
    return {
        "subject": f"Training Requirement - {payload.domain}",
        "body": body,
    }


@router.post("/interview")
async def compose_interview(payload: InterviewEmailRequest):
    link = payload.interview_link or f"https://calendly.com/trainersync/{payload.req_id}"
    date_line = f"\n\U0001F4C5 Scheduled: {payload.interview_date}\n" if payload.interview_date else ""
    body = (
        f"Dear {payload.trainer_name},\n\n"
        f"Thank you for your interest in the {payload.technology} training opportunity!\n\n"
        f"We are pleased to confirm your interview/discussion session.\n{date_line}\n"
        "Interview Details:\n"
        f"- Technology: {payload.technology}\n"
        f"- Reference ID: {payload.req_id}\n"
        "- Duration: 30 minutes\n"
        "- Mode: Video Call (Google Meet / Zoom)\n"
        f"- Book/Join: {link}\n\n"
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
    body = (
        f"Dear {payload.trainer_name or 'Trainer'},\n\n"
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
        f"Book a slot: https://calendly.com/trainersync/{payload.req_id}\n\n"
        f"Warm regards,\n{_from_name()}\n{_from_email()}"
    )
    return {
        "subject": f"Follow-Up: {payload.technology} Training Requirement",
        "body": body,
    }
