"""General reminder tasks — follow-ups and log cleanup."""
import logging
from datetime import datetime, timedelta

import httpx

from app.celery_app import celery_app
from app.config import get_settings
from app.database import get_db, run_async

logger = logging.getLogger(__name__)
settings = get_settings()


async def _do_followup_reminders():
    """
    Find trainers who received mail1 but haven't replied in 3 days.
    Send them a reminder via email-service.
    """
    db = get_db()
    cutoff = datetime.utcnow() - timedelta(days=3)
    query = {
        "mail_type": "mail1",
        "direction": "outbound",
        "status": "sent",
        "replied": {"$ne": True},
        "reminder_sent": {"$ne": True},
        "sent_at": {"$lte": cutoff},
    }
    logs = await db["email_logs"].find(query).to_list(50)
    sent = failed = 0

    for log in logs:
        recipient = log.get("recipient") or log.get("trainer_email") or ""
        trainer_name = log.get("trainer_name") or "Trainer"
        technology = log.get("technology") or "Training"
        req_id = log.get("requirement_id") or ""

        if not recipient:
            continue

        try:
            # Compose reminder via email-service template
            tmpl_resp = httpx.post(
                f"{settings.EMAIL_SERVICE_URL}/api/v1/email/templates/retry",
                json={"trainer_name": trainer_name, "technology": technology, "req_id": req_id},
                timeout=10,
            )
            tmpl = tmpl_resp.json()

            send_resp = httpx.post(
                f"{settings.EMAIL_SERVICE_URL}/api/v1/email/send",
                json={
                    "to": recipient,
                    "subject": tmpl.get("subject", f"Follow-Up: {technology}"),
                    "body": tmpl.get("body", ""),
                    "mail_type": "mail1_reminder",
                    "requirement_id": req_id,
                },
                timeout=30,
            )
            success = send_resp.status_code < 400
        except Exception as exc:
            logger.error("Follow-up send failed for %s: %s", recipient, exc)
            success = False

        now = datetime.utcnow()
        await db["email_logs"].update_one(
            {"email_id": log.get("email_id")},
            {"$set": {"reminder_sent": True, "reminder_sent_at": now if success else None, "updated_at": now}},
        )
        if success:
            sent += 1
        else:
            failed += 1

    return {"sent": sent, "failed": failed}


async def _do_cleanup_old_logs(days_old: int = 90):
    db = get_db()
    cutoff = datetime.utcnow() - timedelta(days=days_old)
    result = await db["email_logs"].delete_many({
        "direction": "inbound",
        "processed": True,
        "created_at": {"$lte": cutoff},
    })
    return {"deleted": result.deleted_count}


@celery_app.task(name="app.tasks.reminders.send_followup_reminders", bind=True, max_retries=2)
def send_followup_reminders(self):
    try:
        result = run_async(_do_followup_reminders())
        logger.info("Follow-up reminders: %s", result)
        return result
    except Exception as exc:
        logger.error("Follow-up reminder task failed: %s", exc)
        raise self.retry(exc=exc, countdown=300)


@celery_app.task(name="app.tasks.reminders.cleanup_old_logs", bind=True, max_retries=1)
def cleanup_old_logs(self):
    try:
        result = run_async(_do_cleanup_old_logs())
        logger.info("Log cleanup: %s", result)
        return result
    except Exception as exc:
        logger.error("Log cleanup failed: %s", exc)
        raise self.retry(exc=exc, countdown=600)
