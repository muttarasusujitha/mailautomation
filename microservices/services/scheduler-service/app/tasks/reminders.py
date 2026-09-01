"""General reminder tasks — follow-ups and log cleanup."""
import logging
from datetime import datetime, timedelta

import httpx

from app.celery_app import celery_app
from app.config import get_settings
from app.database import get_db, run_async

logger = logging.getLogger(__name__)
settings = get_settings()

FIRST_FOLLOWUP_AFTER_HOURS = 6
SECOND_FOLLOWUP_AFTER_FIRST_HOURS = 24
GMAIL_QUOTA_COOLDOWN_HOURS = 6


def _coerce_bool(value, default=True):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off", "disabled"}


async def _followup_automation_enabled(db) -> bool:
    doc = await db["admin_settings"].find_one(
        {"settings_id": "default"},
        {"_id": 0, "pipeline": 1, "schedulerCfg": 1},
    ) or {}
    pipeline = doc.get("pipeline") or {}
    scheduler_cfg = doc.get("schedulerCfg") or {}
    switches = (
        pipeline.get("autoRetry"),
        scheduler_cfg.get("auto_retry_enabled"),
        scheduler_cfg.get("autoRetryEnabled"),
        scheduler_cfg.get("followupEnabled"),
    )
    return all(_coerce_bool(value, True) for value in switches)


async def _gmail_quota_cooldown_active(db) -> dict:
    now = datetime.utcnow()
    cooldown = await db["mail_send_cooldowns"].find_one(
        {"_id": "gmail_send_quota", "retry_after": {"$gt": now}},
        {"_id": 0, "retry_after": 1, "error_message": 1},
    )
    if cooldown:
        return {"active": True, "retry_after": cooldown.get("retry_after"), "source": "mail_send_cooldowns"}
    recent_quota = await db["email_logs"].find_one(
        {
            "status": "failed",
            "error_message": {"$regex": "Gmail sending quota exceeded|Daily user sending limit exceeded|User-rate limit exceeded", "$options": "i"},
            "created_at": {"$gte": now - timedelta(hours=GMAIL_QUOTA_COOLDOWN_HOURS)},
        },
        {"_id": 0, "created_at": 1, "error_message": 1},
        sort=[("created_at", -1)],
    )
    if recent_quota:
        retry_after = recent_quota.get("created_at") + timedelta(hours=GMAIL_QUOTA_COOLDOWN_HOURS)
        return {"active": True, "retry_after": retry_after, "source": "recent_quota_failure"}
    return {"active": False}


async def _do_followup_reminders():
    """
    First trainer follow-up only: send once when Mail 1 is unanswered for 6 hours.
    """
    db = get_db()
    if not await _followup_automation_enabled(db):
        return {"sent": 0, "failed": 0, "skipped": True, "reason": "followup_automation_disabled"}
    cooldown = await _gmail_quota_cooldown_active(db)
    if cooldown.get("active"):
        return {"sent": 0, "failed": 0, "skipped": True, "reason": "gmail_quota_cooldown", **cooldown}

    cutoff = datetime.utcnow() - timedelta(hours=FIRST_FOLLOWUP_AFTER_HOURS)
    query = {
        "mail_type": "mail1",
        "direction": "outbound",
        "status": "sent",
        "replied": {"$ne": True},
        "reminder_sent": {"$ne": True},
        "sent_at": {"$lte": cutoff},
    }
    sent = failed = 0

    # Iterate candidates but atomically claim each log before sending to avoid duplicate sends
    cursor = db["email_logs"].find(query).limit(200)
    async for candidate in cursor:
        email_id = candidate.get("email_id")
        recipient = candidate.get("recipient") or candidate.get("trainer_email") or ""
        trainer_name = candidate.get("trainer_name") or "Trainer"
        technology = candidate.get("technology") or "Training"
        req_id = candidate.get("requirement_id") or ""

        if not recipient or not email_id:
            continue

        # Try to atomically claim this log for processing. If another worker claimed it, skip.
        now = datetime.utcnow()
        claimed = await db["email_logs"].find_one_and_update(
            {"email_id": email_id, "reminder_sent": {"$ne": True}, "reminder_claimed": {"$ne": True}},
            {"$set": {"reminder_claimed": True, "reminder_claimed_at": now}},
        )
        if not claimed:
            continue

        try:
            # Compose reminder via email-service template
            tmpl_resp = httpx.post(
                f"{settings.EMAIL_SERVICE_URL}/api/v1/email/templates/retry",
                json={"trainer_name": trainer_name, "technology": technology, "req_id": req_id},
                headers={"X-INTERNAL-TOKEN": settings.INTERNAL_SERVICE_TOKEN},
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
            if send_resp.status_code == 429 or "quota" in send_resp.text.lower():
                await db["mail_send_cooldowns"].update_one(
                    {"_id": "gmail_send_quota"},
                    {
                        "$set": {
                            "retry_after": datetime.utcnow() + timedelta(hours=GMAIL_QUOTA_COOLDOWN_HOURS),
                            "error_message": send_resp.text[:1000],
                            "updated_at": datetime.utcnow(),
                        },
                        "$setOnInsert": {"created_at": datetime.utcnow()},
                    },
                    upsert=True,
                )
        except Exception as exc:
            logger.error("Follow-up send failed for %s: %s", recipient, exc)
            success = False

        now2 = datetime.utcnow()
        # Update the log: mark reminder_sent and clear claim marker
        await db["email_logs"].update_one(
            {"email_id": email_id},
            {"$set": {"reminder_sent": True if success else False, "reminder_sent_at": now2 if success else None, "updated_at": now2}, "$unset": {"reminder_claimed": "", "reminder_claimed_at": ""}},
        )
        if success:
            sent += 1
        else:
            failed += 1

    return {"sent": sent, "failed": failed}


async def _do_followup2_reminders():
    """
    Second and final trainer follow-up only.

    It is based on the first follow-up timestamp. The second follow-up waits a
    full 24 hours after the first follow-up, then the chain stops.
    """
    db = get_db()
    if not await _followup_automation_enabled(db):
        return {"sent": 0, "failed": 0, "skipped": True, "reason": "followup_automation_disabled"}
    cooldown = await _gmail_quota_cooldown_active(db)
    if cooldown.get("active"):
        return {"sent": 0, "failed": 0, "skipped": True, "reason": "gmail_quota_cooldown", **cooldown}

    cutoff = datetime.utcnow() - timedelta(hours=SECOND_FOLLOWUP_AFTER_FIRST_HOURS)
    query = {
        "mail_type": "mail1_reminder",
        "direction": "outbound",
        "status": "sent",
        "followup2_sent": {"$ne": True},
        "followup2_claimed": {"$ne": True},
        "sent_at": {"$lte": cutoff},
    }
    sent = failed = 0

    cursor = db["email_logs"].find(query).limit(200)
    async for candidate in cursor:
        email_id = candidate.get("email_id")
        recipient = candidate.get("recipient") or candidate.get("trainer_email") or ""
        trainer_name = candidate.get("trainer_name") or "Trainer"
        technology = candidate.get("technology") or "Training"
        req_id = candidate.get("requirement_id") or ""

        if not recipient or not email_id:
            continue

        now = datetime.utcnow()
        claimed = await db["email_logs"].find_one_and_update(
            {"email_id": email_id, "followup2_sent": {"$ne": True}, "followup2_claimed": {"$ne": True}},
            {"$set": {"followup2_claimed": True, "followup2_claimed_at": now}},
        )
        if not claimed:
            continue

        try:
            tmpl_resp = httpx.post(
                f"{settings.EMAIL_SERVICE_URL}/api/v1/email/templates/retry",
                json={"trainer_name": trainer_name, "technology": technology, "req_id": req_id},
                headers={"X-INTERNAL-TOKEN": settings.INTERNAL_SERVICE_TOKEN},
                timeout=10,
            )
            tmpl = tmpl_resp.json()

            send_resp = httpx.post(
                f"{settings.EMAIL_SERVICE_URL}/api/v1/email/send",
                json={
                    "to": recipient,
                    "subject": tmpl.get("subject", f"Follow-Up: {technology}"),
                    "body": tmpl.get("body", ""),
                    "mail_type": "mail2_reminder",
                    "requirement_id": req_id,
                },
                timeout=30,
            )
            success = send_resp.status_code < 400
            if send_resp.status_code == 429 or "quota" in send_resp.text.lower():
                await db["mail_send_cooldowns"].update_one(
                    {"_id": "gmail_send_quota"},
                    {
                        "$set": {
                            "retry_after": datetime.utcnow() + timedelta(hours=GMAIL_QUOTA_COOLDOWN_HOURS),
                            "error_message": send_resp.text[:1000],
                            "updated_at": datetime.utcnow(),
                        },
                        "$setOnInsert": {"created_at": datetime.utcnow()},
                    },
                    upsert=True,
                )
        except Exception as exc:
            logger.error("Followup2 send failed for %s: %s", recipient, exc)
            success = False

        now2 = datetime.utcnow()
        await db["email_logs"].update_one(
            {"email_id": email_id},
            {"$set": {"followup2_sent": True if success else False, "followup2_sent_at": now2 if success else None, "updated_at": now2}, "$unset": {"followup2_claimed": "", "followup2_claimed_at": ""}},
        )
        if success:
            sent += 1
        else:
            failed += 1

    return {"sent": sent, "failed": failed}


async def _do_followup3_reminders():
    """
    Disabled by policy: trainer outreach is capped at two follow-ups.

    Kept as a no-op for backwards compatibility with old manual endpoints or
    stale worker messages; it must never send another trainer email.
    """
    return {"sent": 0, "failed": 0, "skipped": True, "reason": "followup3_disabled_two_followup_limit"}


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


@celery_app.task(name="app.tasks.reminders.send_followup2_reminders", bind=True, max_retries=2)
def send_followup2_reminders(self):
    try:
        result = run_async(_do_followup2_reminders())
        logger.info("Follow-up2 reminders: %s", result)
        return result
    except Exception as exc:
        logger.error("Follow-up2 reminder task failed: %s", exc)
        raise self.retry(exc=exc, countdown=300)


@celery_app.task(name="app.tasks.reminders.send_followup3_reminders", bind=True, max_retries=2)
def send_followup3_reminders(self):
    try:
        result = run_async(_do_followup3_reminders())
        logger.info("Follow-up3 reminders: %s", result)
        return result
    except Exception as exc:
        logger.error("Follow-up3 reminder task failed: %s", exc)
        raise self.retry(exc=exc, countdown=300)
