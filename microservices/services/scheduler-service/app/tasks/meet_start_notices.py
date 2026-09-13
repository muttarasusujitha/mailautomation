"""Five-minute Google Meet notices for scheduled interviews."""
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.celery_app import celery_app
from app.config import get_settings
from app.database import get_db, run_async

logger = logging.getLogger(__name__)
settings = get_settings()

MEET_START_NOTICE_RETRY_WINDOW_MINUTES = 30
MEET_START_NOTICE_MAX_RETRIES = 3


def _clean(value) -> str:
    return str(value or "").strip()


def _canonical_interview_time(value: Any) -> str:
    """Return one stable value for equivalent datetime objects/ISO strings."""
    parsed = value
    if not isinstance(parsed, datetime):
        raw = _clean(value)
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return raw.lower()
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed.isoformat(timespec="seconds")


def _notice_idempotency_key(log: dict, recipient_email: str) -> str:
    """Identify a meeting occurrence independently of duplicate invitation logs."""
    meeting_identity = "|".join(
        [
            _clean(log.get("requirement_id")).lower(),
            (_clean(log.get("trainer_id")) or _clean(log.get("trainer_name"))).lower(),
            _canonical_interview_time(log.get("interview_at")),
            _clean(recipient_email).lower(),
        ]
    )
    digest = hashlib.sha256(meeting_identity.encode("utf-8")).hexdigest()
    return f"interview-5min:v1:{digest}"


def _notice_recipients(log: dict) -> list[dict[str, str]]:
    """Build distinct recipients without treating a client invite as a trainer invite."""
    mail_type = _clean(log.get("mail_type")).lower()
    trainer_email = _clean(log.get("trainer_email"))
    if not trainer_email and mail_type != "client_interview_schedule":
        trainer_email = _clean(log.get("to_email") or log.get("recipient"))

    candidates = [
        {
            "email": trainer_email,
            "name": _clean(log.get("trainer_name")) or "Trainer",
            "role": "trainer",
        },
        {
            "email": _clean(log.get("client_email")),
            "name": _clean(log.get("client_name")) or "Client",
            "role": "client",
        },
        {
            "email": _clean(
                log.get("clahan_email")
                or log.get("office_email")
                or log.get("coordinator_email")
                or settings.CLAHAN_NOTIFICATION_EMAIL
            ),
            "name": "Clahan Technologies",
            "role": "clahan",
        },
    ]
    recipients: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in candidates:
        normalized_email = item["email"].lower()
        if not normalized_email or normalized_email in seen:
            continue
        seen.add(normalized_email)
        item["email"] = normalized_email
        recipients.append(item)
    return recipients


def _notice_body(*, name: str, technology: str, interview_link: str, interview_date: str) -> str:
    greeting = f"Dear {name}," if name else "Hello,"
    return (
        f"{greeting}\n\n"
        f"Your {technology or 'training'} interview meeting starts in 5 minutes.\n\n"
        f"Meeting Time: {interview_date or 'As scheduled'}\n"
        f"Google Meet Link: {interview_link}\n\n"
        "ACTION REQUIRED: Please open the meeting link now and join a few minutes before the scheduled start time.\n"
        "Check your microphone, speakers, and internet connection before joining.\n"
        "If you are delayed or cannot attend, reply to the interview invitation immediately "
        "so the Clahan coordinator can assist.\n\n"
        "Regards,\n"
        "Clahan Technologies"
    )


def _notice_window(now: datetime) -> tuple[datetime, datetime]:
    """Return the tolerated interview-time window for a notice due now."""
    return now + timedelta(minutes=4), now + timedelta(minutes=6)


def _due_notice_query(now: datetime) -> dict:
    """Find a newly due notice or a bounded retry after a transient failure."""
    window_start, window_end = _notice_window(now)
    has_link = {
        "$or": [
            {"interview_link": {"$exists": True, "$nin": ["", None]}},
            {"meet_link": {"$exists": True, "$nin": ["", None]}},
        ],
    }
    return {
        "interview_scheduled": True,
        "meet_start_notice_sent": {"$ne": True},
        "$and": [
            has_link,
            {"$or": [
                {"meet_start_notice_retry_count": {"$exists": False}},
                {"meet_start_notice_retry_count": {"$lt": MEET_START_NOTICE_MAX_RETRIES}},
            ]},
            {"$or": [
                {"meet_start_notice_retry_after": {"$exists": False}},
                {"meet_start_notice_retry_after": None},
                {"meet_start_notice_retry_after": {"$lte": now}},
            ]},
            {
                "$or": [
                    # The normal five-minute-before-meeting alarm.
                    {"interview_at": {"$lte": window_end, "$gte": window_start}},
                    # SMTP/DNS failures are often transient. Retry only for a
                    # short period and cap attempts so a bad address cannot
                    # keep the scheduler busy indefinitely.
                    {
                        "interview_at": {
                            "$gte": now - timedelta(minutes=MEET_START_NOTICE_RETRY_WINDOW_MINUTES),
                            "$lt": window_start,
                        },
                        "$or": [
                            {"meet_start_notice_retry_after": {"$exists": False}},
                            {"meet_start_notice_retry_after": None},
                            {"meet_start_notice_retry_after": {"$lte": now}},
                        ],
                    },
                ],
            },
        ],
    }


async def _send_start_notices():
    db = get_db()
    now = datetime.utcnow()
    # Beat runs every minute. Select five-minute notices and bounded retries.
    query = _due_notice_query(now)

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
        recipients = _notice_recipients(log)
        if not recipients or not interview_link:
            await db["email_logs"].update_one(
                {"email_id": email_id},
                {
                    "$set": {
                        "meet_start_notice_sent": False,
                        "meet_start_notice_error": "Missing recipient or meeting link",
                        "meet_start_notice_retry_count": MEET_START_NOTICE_MAX_RETRIES,
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
                        "subject": f"Interview Meeting Reminder - {technology}",
                        "body": _notice_body(
                            name=recipient["name"],
                            technology=technology,
                            interview_link=interview_link,
                            interview_date=interview_date,
                        ).replace("starts in 5 minutes", "is scheduled for the time below"),
                        "mail_type": "meet_start_notice",
                        "requirement_id": requirement_id,
                        "trainer_id": _clean(log.get("trainer_id")),
                        "trainer_name": log.get("trainer_name") or "",
                        "idempotency_key": _notice_idempotency_key(log, recipient["email"]),
                        # The reminder already contains the confirmed meeting
                        # details. Model generation adds latency and an unrelated
                        # failure dependency to this time-sensitive send.
                        "ai_generate": False,
                        "ai_context": {
                            "workflow": "interview_5_minute_reminder",
                            "recipient_role": recipient["role"],
                            "recipient_name": recipient["name"],
                            "technology": technology,
                            "meeting_time": interview_date,
                            "meeting_link": interview_link,
                            "required_message": "Meeting reminder: check the scheduled time below and join using the meeting link.",
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
        retry_count = int(log.get("meet_start_notice_retry_count") or 0)
        retry_after = None
        if not success:
            retry_count += 1
            # One-minute spacing keeps the alarm useful while allowing a
            # temporary DNS/SMTP outage to recover before the meeting.
            retry_after = now + timedelta(minutes=1)
        await db["email_logs"].update_one(
            {"email_id": email_id},
            {
                "$set": {
                    "meet_start_notice_sent": success,
                    "meet_start_notice_sent_at": now if success else None,
                    "meet_start_notice_error": "" if success else f"{log_failed} notice(s) failed",
                    "meet_start_notice_retry_count": retry_count,
                    "meet_start_notice_retry_after": None if success else retry_after,
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
