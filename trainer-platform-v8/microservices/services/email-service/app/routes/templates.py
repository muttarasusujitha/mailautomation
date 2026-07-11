"""Email template composition endpoints."""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from app.config import get_settings

router = APIRouter()
settings = get_settings()


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
    trainer_name: Optional[str] = ""
    name: Optional[str] = ""


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
            "\n\nAt this stage, we are checking your interest, commercials, and availability first. "
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
        "Please share the following details if you are interested in this requirement:\n\n"
        "* Commercials/rate per day or per session\n"
        "* Current availability and preferred slots\n"
        "* Updated trainer profile/credentials\n"
        "* Relevant training experience\n"
        "* LinkedIn profile, if available"
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
        f"Book a slot: https://calendly.com/trainersync/{payload.req_id}\n\n"
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
async def compose_client_mail2(payload: ClientMail2Request):
    name = payload.client_name or "Client"
    tech = payload.technology or "Devops"
    subject = payload.subject or f"Re: {tech} Trainer Requirement"
    body = (
        f"Dear {name},\n\n"
        f"Thank you for sharing your {tech} training requirement.\n\n"
        "To help us identify and recommend the most suitable trainers, kindly provide the following details:\n\n"
        "* Training duration\n"
        "* Preferred training dates\n"
        "* Daily training timings\n"
        "* Audience level (Beginner / Intermediate / Advanced)\n"
        "* Training mode (Online / Offline / Hybrid)\n"
        "* Budget or expected commercial charges per day/session\n\n"
        "Meanwhile, we will begin an initial trainer search based on the Devops domain and the information currently available. "
        "Once we receive the above details, we will refine the shortlist and share the most relevant trainer profiles for your review.\n\n"
        "We look forward to your response.\n\n"
        f"Regards,\n{_from_name()}\n{_from_email()}"
    )
    return {"subject": subject, "body": body}


@router.post("/client/proceed-ack")
async def compose_client_proceed_ack(payload: ClientProceedRequest):
    name = payload.client_name or "Client"
    tech = payload.technology or "training"
    subject = f"Re: {tech} Trainer Requirement"
    body = (
        f"Dear {name},\n\n"
        "Thank you for sharing your training requirement.\n\n"
        f"We have noted your requirement and will proceed with the initial trainer search for your {tech} requirement based on the information currently available.\n\n"
        "Our team will start identifying suitable trainers with relevant domain expertise, availability, and experience. "
        "Once you share any remaining details, we will refine the shortlist further and share the most suitable profiles with commercials and availability for your review.\n\n"
        f"Regards,\n{_from_name()}\n{_from_email()}"
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
async def compose_client_budget_reply(payload: GenericSimpleRequest):
    subject = "Budget Received — Thank you"
    body = (
        f"Dear {payload.client_name or 'Client'},\n\n"
        "Thank you for sharing the budget. We will align trainer options accordingly and revert shortly.\n\n"
        "Regards,\n" + _from_name()
    )
    return {"subject": subject, "body": body}


@router.post("/client-budget-ack")
async def compose_client_budget_ack(payload: GenericSimpleRequest):
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
async def compose_client_proceed(payload: GenericSimpleRequest):
    subject = "Proceed — Trainer Search Initiated"
    body = (
        f"Dear {payload.client_name or 'Client'},\n\n"
        "We will proceed with the initial trainer search and share shortlisted profiles shortly.\n\n"
        "Regards,\n" + _from_name()
    )
    return {"subject": subject, "body": body}


@router.post("/client-alternative")
async def compose_client_alternative(payload: GenericSimpleRequest):
    subject = "Alternative Option — Trainer Recommendation"
    body = (
        f"Dear {payload.client_name or 'Client'},\n\n"
        "Thanks — as requested we will share alternative trainer options and details.\n\n"
        "Regards,\n" + _from_name()
    )
    return {"subject": subject, "body": body}


@router.post("/client-toc-request")
async def compose_client_toc_request(payload: GenericSimpleRequest):
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
    subject = "Slot Booking — Interview Availability"
    body = (
        f"Dear {payload.name or 'Trainer'},\n\n"
        "Please share 3 convenient slots for the interview/short discussion. Use the format: Slot 1: Date, Time.\n\n"
        "Regards,\n" + _from_name()
    )
    return {"subject": subject, "body": body}


@router.post("/mail3-too-many")
async def compose_mail3_too_many(payload: GenericSimpleRequest):
    subject = "Please Narrow Down to 3 Slots"
    body = (
        f"Dear {payload.name or 'Trainer'},\n\n"
        "Thanks — please provide 3 preferred slots (instead of multiple options) so we can finalise scheduling.\n\n"
        "Regards,\n" + _from_name()
    )
    return {"subject": subject, "body": body}


@router.post("/mail3-too-few")
async def compose_mail3_too_few(payload: GenericSimpleRequest):
    subject = "Need 3 Slots — Please Share 3 Options"
    body = (
        f"Dear {payload.name or 'Trainer'},\n\n"
        "Kindly share 3 suitable slots so scheduling can proceed.\n\n"
        "Regards,\n" + _from_name()
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
