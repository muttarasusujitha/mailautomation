from datetime import datetime, timedelta, timezone
import uuid
from typing import Any, Dict, Optional

from celery_app import celery_app
from agents.reminder_tasks import send_interview_reminder_task
from agents.whatsapp_agent import parse_interview_datetime


REMINDER_LEAD_TIME = timedelta(hours=1)


def _public_reminder(doc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not doc:
        return {}
    public = {k: v for k, v in doc.items() if k != "_id"}
    for key, value in list(public.items()):
        if isinstance(value, datetime):
            public[key] = value.isoformat()
    return public


async def cancel_interview_reminder(
    db,
    *,
    reminder_id: str = "",
    email_id: str = "",
    trainer_id: str = "",
    requirement_id: str = "",
    reason: str = "cancelled",
) -> Dict[str, Any]:
    query: Dict[str, Any] = {"status": {"$in": ["pending", "scheduled"]}}
    if reminder_id:
        query["reminder_id"] = reminder_id
    elif email_id:
        query["email_id"] = email_id
    elif trainer_id and requirement_id:
        query["trainer_id"] = trainer_id
        query["requirement_id"] = requirement_id
    else:
        return {"cancelled": False, "reason": "No reminder identifier provided"}

    reminders = await db["interview_reminders"].find(query, {"_id": 0}).to_list(20)
    cancelled = []
    for reminder in reminders:
        task_id = reminder.get("task_id")
        if task_id:
            try:
                celery_app.control.revoke(task_id, terminate=False)
            except Exception as exc:
                await db["interview_reminders"].update_one(
                    {"reminder_id": reminder.get("reminder_id")},
                    {"$set": {"revoke_error": str(exc), "updated_at": datetime.utcnow()}},
                )
        await db["interview_reminders"].update_one(
            {"reminder_id": reminder.get("reminder_id")},
            {"$set": {
                "status": "cancelled",
                "cancel_reason": reason,
                "cancelled_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }},
        )
        if reminder.get("email_id"):
            await db["email_logs"].update_one(
                {"email_id": reminder.get("email_id")},
                {"$set": {
                    "interview_reminder_status": "cancelled",
                    "whatsapp_reminder_status": "cancelled",
                    "interview_reminder_cancelled_at": datetime.utcnow(),
                }},
            )
        cancelled.append(reminder.get("reminder_id"))

    return {"cancelled": bool(cancelled), "reminder_ids": cancelled}


async def schedule_interview_reminder(
    db,
    *,
    email_log: Dict[str, Any],
    request_base_url: str = "",
    replace_existing: bool = True,
) -> Dict[str, Any]:
    interview_at = parse_interview_datetime(email_log.get("interview_date", ""))
    if not interview_at:
        return {"scheduled": False, "status": "invalid_datetime", "error": "Interview datetime is missing or invalid"}

    if replace_existing:
        await cancel_interview_reminder(
            db,
            trainer_id=email_log.get("trainer_id", ""),
            requirement_id=email_log.get("requirement_id", ""),
            reason="rescheduled",
        )

    reminder_at = interview_at - REMINDER_LEAD_TIME
    now = datetime.utcnow()
    eta = reminder_at if reminder_at > now else now
    reminder_id = f"REM-{uuid.uuid4().hex[:10].upper()}"
    task_id = f"interview-reminder-{reminder_id}"
    reminder_doc = {
        "reminder_id": reminder_id,
        "task_id": task_id,
        "email_id": email_log.get("email_id"),
        "trainer_id": email_log.get("trainer_id"),
        "trainer_name": email_log.get("trainer_name"),
        "trainer_email": email_log.get("to_email"),
        "trainer_phone": email_log.get("trainer_phone", ""),
        "requirement_id": email_log.get("requirement_id"),
        "technology": email_log.get("technology", ""),
        "interview_date": email_log.get("interview_date"),
        "interview_at": interview_at,
        "reminder_at": reminder_at,
        "scheduled_eta": eta,
        "platform": email_log.get("platform", "Online"),
        "interview_link": email_log.get("interview_link", ""),
        "status": "pending",
        "channels": {
            "email": "pending",
            "trainer_whatsapp": "pending",
            "vendor_whatsapp": "pending",
            "teams": "pending",
        },
        "request_base_url": request_base_url,
        "created_at": now,
        "updated_at": now,
    }
    await db["interview_reminders"].insert_one(reminder_doc)

    try:
        eta_for_celery = eta.replace(tzinfo=timezone.utc) if eta.tzinfo is None else eta
        send_interview_reminder_task.apply_async(args=[reminder_id], eta=eta_for_celery, task_id=task_id)
        await db["interview_reminders"].update_one(
            {"reminder_id": reminder_id},
            {"$set": {"status": "pending", "celery_registered_at": datetime.utcnow()}},
        )
        await db["email_logs"].update_one(
            {"email_id": email_log.get("email_id")},
            {"$set": {
                "interview_reminder_id": reminder_id,
                "interview_reminder_task_id": task_id,
                "interview_reminder_at": reminder_at,
                "interview_reminder_status": "pending",
                "whatsapp_reminder_status": "celery_pending",
            }},
        )
        return {"scheduled": True, "reminder": _public_reminder({**reminder_doc, "status": "pending"})}
    except Exception as exc:
        await db["interview_reminders"].update_one(
            {"reminder_id": reminder_id},
            {"$set": {
                "status": "schedule_failed",
                "schedule_error": str(exc),
                "updated_at": datetime.utcnow(),
            }},
        )
        await db["email_logs"].update_one(
            {"email_id": email_log.get("email_id")},
            {"$set": {
                "interview_reminder_id": reminder_id,
                "interview_reminder_task_id": task_id,
                "interview_reminder_status": "schedule_failed",
                "interview_reminder_error": str(exc),
            }},
        )
        return {"scheduled": False, "status": "schedule_failed", "error": str(exc), "reminder_id": reminder_id}
