"""Scheduler configuration — read and write polling/automation schedule."""
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.database import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


class SchedulerConfigUpdate(BaseModel):
    inbox_poll_interval_minutes: Optional[int] = None
    auto_send_enabled: Optional[bool] = None
    auto_send_confidence_threshold: Optional[float] = None
    followup_days: Optional[int] = None
    interview_reminder_hours_before: Optional[int] = None
    daily_followup_time_utc: Optional[str] = None


@router.get("/config")
async def get_scheduler_config(db: AsyncIOMotorDatabase = Depends(get_db)):
    doc = await db["admin_settings"].find_one(
        {"settings_id": "default"}, {"_id": 0, "schedulerCfg": 1}
    ) or {}
    cfg = doc.get("schedulerCfg") or {}
    return {
        "success": True,
        "config": {
            "inbox_poll_interval_minutes": cfg.get("inboxPollIntervalMinutes", 5),
            "auto_send_enabled": True,
            "auto_send_confidence_threshold": cfg.get("autoSendConfidenceThreshold", 0.7),
            "followup_days": cfg.get("followupDays", 3),
            "interview_reminder_hours_before": cfg.get("interviewReminderHoursBefore", 1),
            "daily_followup_time_utc": cfg.get("dailyFollowupTimeUtc", "09:00"),
        },
    }


@router.post("/config")
async def save_scheduler_config(
    payload: SchedulerConfigUpdate,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    now = datetime.utcnow()
    mapping = {
        "inbox_poll_interval_minutes": "schedulerCfg.inboxPollIntervalMinutes",
        "auto_send_enabled": "schedulerCfg.autoSendEnabled",
        "auto_send_confidence_threshold": "schedulerCfg.autoSendConfidenceThreshold",
        "followup_days": "schedulerCfg.followupDays",
        "interview_reminder_hours_before": "schedulerCfg.interviewReminderHoursBefore",
        "daily_followup_time_utc": "schedulerCfg.dailyFollowupTimeUtc",
    }
    update: Dict[str, Any] = {"updated_at": now}
    for field, mongo_key in mapping.items():
        val = getattr(payload, field)
        if val is not None:
            if field == "auto_send_enabled":
                val = True
            update[mongo_key] = val

    await db["admin_settings"].update_one(
        {"settings_id": "default"},
        {"$set": update, "$setOnInsert": {"settings_id": "default", "created_at": now}},
        upsert=True,
    )
    return {"success": True, "message": "Scheduler config saved."}
