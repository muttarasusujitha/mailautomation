"""Trainer availability slot parsing and management."""
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.database import get_db

router = APIRouter()

MONTH_NUMBERS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

SLOT_PATTERN = re.compile(
    r"(?:slot\s*\d+\s*[:\-]?\s*)?"
    r"(?P<day>\d{1,2})\s+(?P<month>[A-Za-z]+)\s+(?P<year>\d{4}),?\s+"
    r"(?P<sh>\d{1,2})(?::(?P<sm>\d{2}))?\s*(?P<sp>am|pm)\s*(?:-|to|–|—)\s*"
    r"(?P<eh>\d{1,2})(?::(?P<em>\d{2}))?\s*(?P<ep>am|pm)\b",
    re.IGNORECASE,
)


def _h24(h: str, period: str) -> int:
    hour = int(h)
    return hour % 12 + (12 if period.lower() == "pm" else 0)


def extract_slots(text: str) -> List[Dict[str, Any]]:
    slots = []
    for line in str(text or "").splitlines():
        m = SLOT_PATTERN.search(line)
        if not m:
            continue
        v = m.groupdict()
        mon = MONTH_NUMBERS.get(v["month"].lower())
        if not mon:
            continue
        try:
            s_min = int(v["sm"] or 0)
            e_min = int(v["em"] or 0)
            start = datetime(int(v["year"]), mon, int(v["day"]), _h24(v["sh"], v["sp"]), s_min)
            end = datetime(int(v["year"]), mon, int(v["day"]), _h24(v["eh"], v["ep"]), e_min)
        except ValueError:
            continue
        if end <= start:
            continue
        slots.append({
            "start_datetime": start.isoformat(),
            "end_datetime": end.isoformat(),
            "date_display": f"{start.day} {start.strftime('%B')} {start.year}",
            "time_display": f"{start.strftime('%I:%M %p')} - {end.strftime('%I:%M %p')}",
            "raw_text": line.strip(),
            "confidence": 0.95,
        })
    return slots


def looks_like_slot_reply(text: str) -> bool:
    clean = str(text or "").lower()
    indicators = [
        r"\bslot\s*[0-9]", r"\b(?:slot|availability|available|timing)\s*:\s*",
        r"\b\d{1,2}\s+[a-z]+\s+\d{4}\b", r"\b(?:monday|tuesday|wednesday|thursday|friday)\b",
        r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\s*(?:to|-|–|—)\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)\b",
        r"\b(?:available|availability|preferred|can do)\b",
    ]
    return sum(bool(re.search(p, clean)) for p in indicators) >= 2


class SlotParseRequest(BaseModel):
    text: str
    trainer_id: Optional[str] = None
    trainer_email: Optional[str] = None
    trainer_name: Optional[str] = None
    requirement_id: Optional[str] = None
    email_log_id: Optional[str] = None


class SlotBookRequest(BaseModel):
    requirement_id: str
    trainer_id: str
    slot_start: str
    slot_end: str
    title: Optional[str] = None
    meeting_link: Optional[str] = None


@router.post("/parse")
async def parse_slots(payload: SlotParseRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Parse availability slots from a trainer's reply text and optionally persist them."""
    slots = extract_slots(payload.text)
    if not slots:
        return {"success": False, "reason": "No valid slots found", "slots": []}

    if payload.requirement_id and payload.trainer_id:
        now = datetime.utcnow()
        slot_id = f"SLOT-{uuid.uuid4().hex[:8].upper()}"
        await db.trainer_slot_responses.insert_one({
            "slot_response_id": slot_id,
            "trainer_id": payload.trainer_id,
            "trainer_email": payload.trainer_email,
            "trainer_name": payload.trainer_name,
            "requirement_id": payload.requirement_id,
            "email_log_id": payload.email_log_id,
            "slots": slots,
            "slot_count": len(slots),
            "raw_response": payload.text[:2000],
            "status": "received",
            "client_notified": False,
            "received_at": now,
            "created_at": now,
        })
        await db.requirements.update_one(
            {"requirement_id": payload.requirement_id},
            {"$set": {"trainer_slots_received": True, "trainer_slots_count": len(slots), "status": "slots_awaiting_confirmation"}},
        )
        return {"success": True, "slot_response_id": slot_id, "slots_count": len(slots), "slots": slots}

    return {"success": True, "slots_count": len(slots), "slots": slots}


@router.get("/responses/{requirement_id}")
async def get_slot_responses(requirement_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    cursor = db.trainer_slot_responses.find({"requirement_id": requirement_id}, {"_id": 0})
    items = [d async for d in cursor]
    return {"requirement_id": requirement_id, "responses": items, "count": len(items)}


@router.post("/book")
async def book_slot(payload: SlotBookRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    now = datetime.utcnow()
    slot_doc = {
        "slot_id": f"SL-{uuid.uuid4().hex[:8].upper()}",
        "requirement_id": payload.requirement_id,
        "trainer_id": payload.trainer_id,
        "slot_type": "interview",
        "start_time": payload.slot_start,
        "end_time": payload.slot_end,
        "title": payload.title or "Interview",
        "meeting_link": payload.meeting_link,
        "status": "booked",
        "created_at": now,
        "updated_at": now,
    }
    await db.slots.insert_one(slot_doc)
    slot_doc.pop("_id", None)
    return {"success": True, "slot": slot_doc}
