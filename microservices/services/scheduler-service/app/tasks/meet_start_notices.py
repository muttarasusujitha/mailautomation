"""Ten-minute Google Meet notices for scheduled interviews."""
import logging
from datetime import datetime, timedelta

import httpx

from app.celery_app import celery_app
from app.config import get_settings
from app.database import get_db, run_async

logger = logging.getLogger(__name__)
settings = get_settings()


def _clean(value) -> str:
    return str(value or "").strip()


def _notice_body(*, name: str, technology: str, interview_link: str, interview_date: str) -> str:
    greeting = f"Dear {name}," if name else "Hello,"
    return (
        f"{greeting}\n\n"
        f"Your {technology or 'training'} interview meeting starts in 10 minutes.\n\n"
        f"Meeting Time: {interview_date or 'As scheduled'}\n"
        f"Google Meet Link: {interview_link}\n\n"
        "Please open the link and join a few minutes before the scheduled start time.\n\n"
        "Regards,\n"
        "Clahan Technologies"
    )


def _notice_window(now: datetime) -> tuple[datetime, datetime]:
    """Return the tolerated interview-time window for a notice due now."""
    return now + timedelta(minutes=9), now + timedelta(minutes=11)


async def _send_start_notices():
    db = get_db()
    now = datetime.utcnow()
    # Beat runs every minute. Select meetings whose 10-minute notice is due,
    # with a small tolerance for scheduler/worker latency.
    window_start, window_end = _notice_window(now)
    query = {
        "interview_scheduled": True,
        "meet_start_notice_sent": {"$ne": True},
        "interview_at": {"$lte": window_end, "$gte": window_start},
        "$or": [
            {"interview_link": {"$exists": True, "$nin": ["", None]}},
            {"meet_link": {"$exists": True, "$nin": ["", None]}},
        ],
    }

    sent = failed = skipped = 0
    cursor = db["email_logs"].find(query).limit(100)
    async for log in cursor:
        email_id = _clean(log.get("email_id"))
        if not email_id:
            skipped += 1
            continue
        claimed = await db["email_logs"].find_one_and_update(
            {
                "email_id": email_id,
                "meet_start_notice_sent": {"$ne": True},
                "meet_start_notice_claimed": {"$ne": True},
            },
            {"$set": {"meet_start_notice_claimed": True, "meet_start_notice_claimed_at": now}},
        )
        if not claimed:
            skipped += 1
            continue

        requirement_id = _clean(log.get("requirement_id"))
        technology = _clean(log.get("technology")) or "Training"
        interview_link = _clean(log.get("interview_link") or log.get("meet_link"))
        interview_date = _clean(log.get("interview_date") or log.get("date_time_text") or log.get("interview_at"))
        recipients = [
            {
                "email": _clean(log.get("trainer_email") or log.get("to_email") or log.get("recipient")),
                "name": _clean(log.get("trainer_name")) or "Trainer",
                "role": "trainer",
            },
            {
                "email": _clean(log.get("client_email")),
                "name": _clean(log.get("client_name")) or "Client",
                "role": "client",
            },
        ]
        recipients = [item for item in recipients if item["email"]]
        if not recipients or not interview_link:
            await db["email_logs"].update_one(
                {"email_id": email_id},
                {
                    "$set": {
                        "meet_start_notice_sent": False,
                        "meet_start_notice_error": "Missing recipient or meeting link",
                        "updated_at": now,
                    },
                    "$unset": {"meet_start_notice_claimed": "", "meet_start_notice_claimed_at": ""},
                },
            )
            skipped += 1
            continue

        log_sent = 0
        log_failed = 0
        for recipient in recipients:
            try:
                response = httpx.post(
                    f"{settings.EMAIL_SERVICE_URL}/api/v1/email/send",
                    json={
                        "to": recipient["email"],
                        "subject": f"Interview Starts in 10 Minutes - {technology}",
                        "body": _notice_body(
                            name=recipient["name"],
                            technology=technology,
                            interview_link=interview_link,
                            interview_date=interview_date,
                        ),
                        "mail_type": "meet_start_notice",
                        "requirement_id": requirement_id,
                        "trainer_name": log.get("trainer_name") or "",
                        "idempotency_key": f"interview-10min:{email_id}:{recipient['role']}:{recipient['email']}",
                        "ai_generate": True,
                        "ai_context": {
                            "workflow": "interview_10_minute_reminder",
                            "recipient_role": recipient["role"],
                            "recipient_name": recipient["name"],
                            "technology": technology,
                            "meeting_time": interview_date,
                            "meeting_link": interview_link,
                            "required_message": "The interview starts in 10 minutes; join a few minutes early.",
                        },
                    },
                    timeout=30,
                )
                ok = response.status_code < 400 and response.json().get("success", False)
            except Exception as exc:
                logger.error("Meet start notice failed for %s: %s", recipient["email"], exc)
                ok = False
            if ok:
                log_sent += 1
            else:
                log_failed += 1

        success = log_sent > 0 and log_failed == 0
        await db["email_logs"].update_one(
            {"email_id": email_id},
            {
                "$set": {
                    "meet_start_notice_sent": success,
                    "meet_start_notice_sent_at": now if success else None,
                    "meet_start_notice_error": "" if success else f"{log_failed} notice(s) failed",
                    "updated_at": now,
                },
                "$unset": {"meet_start_notice_claimed": "", "meet_start_notice_claimed_at": ""},
            },
        )
        sent += log_sent
        failed += log_failed

    return {"sent": sent, "failed": failed, "skipped": skipped}


@celery_app.task(name="app.tasks.meet_start_notices.send_due_start_notices", bind=True, max_retries=2)
def send_due_start_notices(self):
    try:
        result = run_async(_send_start_notices())
        logger.info("Meet start notices: %s", result)
        return result
    except Exception as exc:
        logger.error("Meet start notice task failed: %s", exc)
        raise self.retry(exc=exc, countdown=60)
