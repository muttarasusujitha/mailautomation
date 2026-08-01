"""Interview reminder task — finds due reminders and fires WhatsApp notifications."""
import logging
from datetime import datetime, timedelta

import httpx

from app.celery_app import celery_app
from app.config import get_settings
from app.database import get_db, run_async

logger = logging.getLogger(__name__)
settings = get_settings()


async def _fetch_and_send_reminders():
    db = get_db()
    now = datetime.utcnow()
    window_end = now + timedelta(hours=settings.INTERVIEW_REMINDER_HOURS_BEFORE)

    # Find email_logs where an interview is scheduled, reminder not yet sent,
    # and the interview is within the reminder window
    query = {
        "interview_scheduled": True,
        "whatsapp_reminder_status": "pending",
        "interview_at": {"$lte": window_end, "$gte": now},
    }
    logs = await db["email_logs"].find(query).to_list(100)
    sent = failed = 0

    for log in logs:
        trainer_phone = log.get("trainer_phone") or ""
        trainer_name = log.get("trainer_name") or "Trainer"
        technology = log.get("technology") or "Training"
        interview_date = str(log.get("interview_date") or log.get("interview_at") or "")
        platform = log.get("platform") or "Online"
        interview_link = log.get("interview_link") or ""
        requirement_id = log.get("requirement_id") or ""
        email_id = log.get("email_id") or ""

        if not trainer_phone:
            logger.warning("No phone for email_id=%s, skipping reminder", email_id)
            continue

        try:
            resp = httpx.post(
                f"{settings.NOTIFICATION_SERVICE_URL}/api/v1/notifications/whatsapp/interview-reminder",
                json={
                    "trainer_phone": trainer_phone,
                    "trainer_name": trainer_name,
                    "requirement_id": requirement_id,
                    "technology": technology,
                    "date_time": interview_date,
                    "platform": platform,
                    "interview_link": interview_link,
                    "email_id": email_id,
                    "reminder": True,
                },
                timeout=30,
            )
            success = resp.status_code < 400 and resp.json().get("success", False)
        except Exception as exc:
            logger.error("Reminder HTTP call failed for %s: %s", email_id, exc)
            success = False

        status = "sent" if success else "failed"
        await db["email_logs"].update_one(
            {"email_id": email_id},
            {"$set": {
                "whatsapp_reminder_status": status,
                "whatsapp_reminder_sent_at": now if success else None,
                "updated_at": now,
            }},
        )
        if success:
            sent += 1
        else:
            failed += 1

    return {"sent": sent, "failed": failed}


@celery_app.task(name="app.tasks.interview_reminders.send_due_reminders", bind=True, max_retries=2)
def send_due_reminders(self):
    try:
        result = run_async(_fetch_and_send_reminders())
        logger.info("Interview reminders: %s", result)
        return result
    except Exception as exc:
        logger.error("Interview reminder task failed: %s", exc)
        raise self.retry(exc=exc, countdown=120)
