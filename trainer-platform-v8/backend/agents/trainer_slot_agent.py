"""Parse and process trainer availability-slot replies."""

import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Tuple

from utils.time_utils import utc_now


MONTH_NUMBERS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
SLOT_PATTERN = re.compile(
    r"(?:slot\s*\d+\s*[:\-]?\s*)?"
    r"(?P<day>\d{1,2})\s+"
    r"(?P<month>[A-Za-z]+)\s+"
    r"(?P<year>\d{4}),?\s+"
    r"(?P<start_hour>\d{1,2})(?::(?P<start_minute>\d{2}))?\s*"
    r"(?P<start_period>am|pm)\s*"
    r"(?:-|to|–|—)\s*"
    r"(?P<end_hour>\d{1,2})(?::(?P<end_minute>\d{2}))?\s*"
    r"(?P<end_period>am|pm)\b",
    re.IGNORECASE,
)


def _hour_24(hour_text: str, period: str) -> int:
    hour = int(hour_text)
    if not 1 <= hour <= 12:
        raise ValueError("Hour must be between 1 and 12")
    return hour % 12 + (12 if period.lower() == "pm" else 0)


def looks_like_trainer_slot_response(text: str) -> bool:
    """Return whether an email appears to contain trainer availability."""
    clean = str(text or "").lower().strip()
    if not clean:
        return False

    slot_indicators = (
        r"\bslot\s*[0-9]",
        r"\b(?:slot|availability|available|timing)\s*:\s*",
        r"\b\d{1,2}\s+[a-z]+\s+\d{4}\b",
        r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\s*(?:to|-|–|—)\s*"
        r"\d{1,2}(?::\d{2})?\s*(?:am|pm)\b",
        r"\b(?:available|availability|preferred|can do|can make)\b",
    )
    return sum(bool(re.search(pattern, clean)) for pattern in slot_indicators) >= 2


def extract_trainer_slots(text: str) -> List[Dict[str, Any]]:
    """Extract valid, same-day availability ranges from a trainer response."""
    slots = []
    for line in str(text or "").splitlines():
        match = SLOT_PATTERN.search(line)
        if not match:
            continue

        values = match.groupdict()
        month_num = MONTH_NUMBERS.get(values["month"].lower())
        if not month_num:
            continue

        try:
            start_minute = int(values["start_minute"] or 0)
            end_minute = int(values["end_minute"] or 0)
            if start_minute > 59 or end_minute > 59:
                raise ValueError("Minutes must be between 0 and 59")
            start_dt = datetime(
                int(values["year"]),
                month_num,
                int(values["day"]),
                _hour_24(values["start_hour"], values["start_period"]),
                start_minute,
            )
            end_dt = datetime(
                int(values["year"]),
                month_num,
                int(values["day"]),
                _hour_24(values["end_hour"], values["end_period"]),
                end_minute,
            )
        except ValueError:
            continue

        if end_dt <= start_dt:
            continue

        slots.append({
            "start_datetime": start_dt.isoformat(),
            "end_datetime": end_dt.isoformat(),
            "date_display": f"{start_dt.day} {start_dt.strftime('%B')} {start_dt.year}",
            "time_display": f"{start_dt.strftime('%I:%M %p')} - {end_dt.strftime('%I:%M %p')}",
            "raw_text": line.strip(),
            "confidence": 0.95,
        })
    return slots


def format_trainer_slots_for_email(slots: List[Dict[str, Any]]) -> str:
    """Format extracted slots for a plain-text email."""
    if not slots:
        return "No slots could be extracted."

    lines = ["Thank you for sharing your availability. Below are the slots we received:\n"]
    for index, slot in enumerate(slots, 1):
        lines.append(f"Slot {index}: {slot.get('date_display')} - {slot.get('time_display')}")
    return "\n".join(lines)


async def process_trainer_slot_response(
    db,
    email_log_id: str,
    trainer_id: str,
    trainer_email: str,
    trainer_name: str,
    requirement_id: str,
    clean_body: str,
    source: str = "incoming_email",
) -> Dict[str, Any]:
    """Extract a trainer's slots and persist them against the requirement."""
    slots = extract_trainer_slots(clean_body)
    if not slots:
        return {
            "success": False,
            "reason": "No valid slots found",
            "trainer_id": trainer_id,
            "requirement_id": requirement_id,
        }

    now = utc_now()
    slot_response_id = f"SLOT-{uuid.uuid4().hex[:8].upper()}"
    slot_doc = {
        "slot_response_id": slot_response_id,
        "trainer_id": trainer_id,
        "trainer_email": trainer_email,
        "trainer_name": trainer_name,
        "requirement_id": requirement_id,
        "email_log_id": email_log_id,
        "slots": slots,
        "slot_count": len(slots),
        "raw_response": clean_body[:2000],
        "source": source,
        "status": "received",
        "client_notified": False,
        "client_confirmation_pending": True,
        "received_at": now,
        "created_at": now,
    }
    await db["trainer_slot_responses"].insert_one(slot_doc)

    await db["requirements"].update_one(
        {"requirement_id": requirement_id},
        {"$set": {
            "trainer_slots_received": True,
            "trainer_slots_count": len(slots),
            "trainer_slots_response_id": slot_response_id,
            "trainer_slots_received_at": now,
            "status": "slots_awaiting_confirmation",
        }},
    )
    await db["email_logs"].update_one(
        {"email_id": email_log_id},
        {"$set": {
            "trainer_slots_parsed": True,
            "trainer_slots_count": len(slots),
            "trainer_slots_response_id": slot_response_id,
            "trainer_slots_details": slots,
        }},
    )

    return {
        "success": True,
        "slot_response_id": slot_response_id,
        "trainer_id": trainer_id,
        "requirement_id": requirement_id,
        "slots_count": len(slots),
        "slots": slots,
        "status": "stored",
    }


async def send_trainer_slot_confirmation(
    trainer_email: str,
    trainer_name: str,
    technology: str,
    slots: List[Dict[str, Any]],
) -> Tuple[bool, str]:
    """Confirm receipt of availability slots with the trainer."""
    from agents.email_agent import send_email_async

    subject = f"Availability Slots Confirmed - {technology} Training"
    slots_text = "\n".join(
        f"  Slot {index}: {slot.get('date_display')} - {slot.get('time_display')}"
        for index, slot in enumerate(slots, 1)
    )
    body = f"""Dear {trainer_name},

Thank you for confirming your availability for the {technology} training.

We have received and confirmed the following slots:

{slots_text}

We will now coordinate with the client to confirm one of these slots. You will receive the final confirmation shortly.

Thank you for your prompt response!

Best Regards,
TrainerSync Team
"""
    return await send_email_async(trainer_email, subject, body, {}, "")


async def notify_client_with_trainer_slots(
    db,
    requirement_id: str,
    trainer_name: str,
    slots: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Send a client the trainer's slot options for confirmation."""
    requirement = await db["requirements"].find_one(
        {"requirement_id": requirement_id},
        {"_id": 0},
    ) or {}
    client_email = requirement.get("client_email", "")
    if not client_email:
        return {"success": False, "reason": "Client email not found"}

    from agents.email_agent import send_email_async

    technology = requirement.get("technology_needed", "Training")
    client_name = requirement.get("client_name") or requirement.get("client_company") or "Client"
    slots_text = "\n".join(
        f"  Slot {index}: {slot.get('date_display')} - {slot.get('time_display')} IST"
        for index, slot in enumerate(slots, 1)
    )
    subject = f"Trainer Availability Confirmed - Please Select a Slot - {technology}"
    body = f"""Dear {client_name},

The {technology} trainer {trainer_name} has confirmed availability for the interview/discussion.

Please select one of the available slots below to schedule the meeting:

{slots_text}

Please reply with your preferred slot so we can send the final calendar invite.

Best Regards,
TrainerSync Team
"""
    success, error = await send_email_async(client_email, subject, body, {}, "")

    now = utc_now()
    update_fields = {
        "client_slot_options_last_attempt_at": now,
        "client_slot_options_last_error": error if not success else "",
    }
    if success:
        update_fields.update({
            "client_slot_options_sent": True,
            "client_slot_options_sent_at": now,
            "client_awaiting_slot_confirmation": True,
        })
    await db["requirements"].update_one(
        {"requirement_id": requirement_id},
        {"$set": update_fields},
    )

    return {
        "success": success,
        "to_email": client_email,
        "error": error if not success else "",
    }
