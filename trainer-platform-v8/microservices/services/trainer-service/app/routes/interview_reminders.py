"""Interview reminder scheduling — create, list, cancel, reschedule."""
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.database import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


class ScheduleReminderRequest(BaseModel):
    email_id: str
    trainer_id: Optional[str] = ""
    trainer_name: Optional[str] = ""
    trainer_phone: Optional[str] = ""
    trainer_email: Optional[str] = ""
    requirement_id: Optional[str] = ""
    technology: Optional[str] = ""
    interview_at: str  # ISO datetime string
    platform: Optional[str] = "Online"
    interview_link: Optional[str] = ""
    reminder_hours_before: int = 1


class RescheduleRequest(BaseModel):
    new_interview_at: str
    interview_link: Optional[str] = ""


@router.get("")
async def list_reminders(
    status: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    query: Dict[str, Any] = {}
    if status:
        query["status"] = status
    cursor = db["interview_reminders"].find(query, {"_id": 0}).sort("interview_at", 1).limit(200)
    items = [d async for d in cursor]
    return {"success": True, "count": len(items), "reminders": items}


@router.get("/interview-schedules")
async def list_interview_schedules(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Return email_logs where an interview is scheduled."""
    cursor = (
        db["email_logs"]
        .find({"interview_scheduled": True}, {"_id": 0})
        .sort("interview_at", 1)
        .limit(200)
    )
    items = [d async for d in cursor]
    return {"success": True, "count": len(items), "schedules": items}


@router.post("")
async def schedule_reminder(
    payload: ScheduleReminderRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    now = datetime.utcnow()
    try:
        interview_at = datetime.fromisoformat(payload.interview_at.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError as exc:
        raise HTTPException(400, f"Invalid interview_at: {exc}") from exc

    remind_at = interview_at - timedelta(hours=max(0, payload.reminder_hours_before))

    reminder_id = f"REM-{uuid.uuid4().hex[:10].upper()}"
    doc = {
        "reminder_id": reminder_id,
        "email_id": payload.email_id,
        "trainer_id": payload.trainer_id,
        "trainer_name": payload.trainer_name,
        "trainer_phone": payload.trainer_phone,
        "trainer_email": payload.trainer_email,
        "requirement_id": payload.requirement_id,
        "technology": payload.technology,
        "interview_at": interview_at,
        "remind_at": remind_at,
        "platform": payload.platform,
        "interview_link": payload.interview_link,
        "status": "scheduled",
        "whatsapp_reminder_status": "pending",
        "created_at": now,
        "updated_at": now,
    }
    await db["interview_reminders"].insert_one(doc)

    # Also mark the email_log with interview details
    await db["email_logs"].update_one(
        {"email_id": payload.email_id},
        {"$set": {
            "interview_scheduled": True,
            "interview_at": interview_at,
            "interview_link": payload.interview_link,
            "reminder_id": reminder_id,
            "whatsapp_reminder_status": "pending",
            "updated_at": now,
        }},
    )
    doc.pop("_id", None)
    doc["interview_at"] = interview_at.isoformat()
    doc["remind_at"] = remind_at.isoformat()
    return {"success": True, "reminder_id": reminder_id, "remind_at": remind_at.isoformat()}


@router.post("/{reminder_id}/cancel")
async def cancel_reminder(reminder_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    result = await db["interview_reminders"].update_one(
        {"reminder_id": reminder_id},
        {"$set": {"status": "cancelled", "cancelled_at": datetime.utcnow(), "updated_at": datetime.utcnow()}},
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Reminder not found")
    return {"success": True, "reminder_id": reminder_id, "status": "cancelled"}


@router.post("/{reminder_id}/reschedule")
async def reschedule_reminder(
    reminder_id: str,
    payload: RescheduleRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    doc = await db["interview_reminders"].find_one({"reminder_id": reminder_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Reminder not found")

    try:
        new_at = datetime.fromisoformat(payload.new_interview_at.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    hours_before = doc.get("reminder_hours_before", 1)
    new_remind_at = new_at - timedelta(hours=hours_before)
    now = datetime.utcnow()

    update: Dict[str, Any] = {
        "interview_at": new_at,
        "remind_at": new_remind_at,
        "status": "rescheduled",
        "rescheduled_at": now,
        "updated_at": now,
    }
    if payload.interview_link:
        update["interview_link"] = payload.interview_link

    await db["interview_reminders"].update_one({"reminder_id": reminder_id}, {"$set": update})
    return {"success": True, "reminder_id": reminder_id, "new_interview_at": new_at.isoformat()}
