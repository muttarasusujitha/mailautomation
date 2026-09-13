"""Safe post-start interview no-show notices.

This task never guesses attendance.  It uses only role-level observations
written by the authenticated Meet bot after it has opened the People panel.
If Meet cannot expose a reliable identity, the interview is marked
unverifiable and no notice is sent.
"""
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


def _notice_body(*, name: str, technology: str, interview_link: str, interview_date: str,
                 role: str = "participant", missing_roles: list[str] | None = None,
                 recipient_joined: bool = False) -> str:
    if role == "clahan" or recipient_joined:
        missing_text = ", ".join(missing_roles or []) or "a participant"
        opening = f"The {technology or 'training'} interview started 10 minutes ago, and we could not confirm that {missing_text} joined the Google Meet."
    else:
        opening = f"The {technology or 'training'} interview started 10 minutes ago and we could not confirm that you joined the Google Meet."
    return (
        f"Dear {name or 'Team'},\n\n"
        f"{opening}\n\n"
        f"Meeting Time: {interview_date or 'As scheduled'}\n"
        f"Google Meet Link: {interview_link}\n\n"
        "Please join now if you are available. If you need to reschedule, reply with your preferred date and time zone.\n\n"
        "Regards,\nClahan Technologies"
    )


async def _send_due_no_show_notices():
    db = get_db()
    now = datetime.utcnow()
    due_before = now - timedelta(minutes=max(1, settings.INTERVIEW_NO_SHOW_MINUTES_AFTER))
    query = {
        "direction": "outbound",
        "mail_type": "mail4",
        "status": "sent",
        "interview_scheduled": True,
        "reschedule_requested": {"$ne": True},
        "no_show_check_completed": {"$ne": True},
        "interview_at": {"$lte": due_before},
        "meet_bot_status": {"$in": ["joined", "completed"]},
        "meet_attendance_source": "meet_bot_visible_participants",
        "meet_participant_view_available": True,
        "meet_attendance_observed_at": {"$exists": True},
    }
    sent = failed = skipped = unverifiable = 0
    async for log in db["email_logs"].find(query).limit(100):
        email_id = _clean(log.get("email_id"))
        if not email_id:
            skipped += 1
            continue
        claimed = await db["email_logs"].find_one_and_update(
            {
                "email_id": email_id,
                "no_show_check_completed": {"$ne": True},
                "no_show_check_claimed": {"$ne": True},
            },
            {"$set": {"no_show_check_claimed": True, "no_show_check_claimed_at": now}},
        )
        if not claimed:
            skipped += 1
            continue

        participants = [
            {
                "role": "trainer",
                "email": _clean(log.get("trainer_email") or log.get("to_email") or log.get("recipient")),
                "name": _clean(log.get("trainer_name")) or "Trainer",
                "identity_available": bool(log.get("trainer_attendance_identity_available")),
                "joined": bool(log.get("trainer_joined")),
            },
            {
                "role": "client",
                "email": _clean(log.get("client_email")),
                "name": _clean(log.get("client_name")) or "Client",
                "identity_available": bool(log.get("client_attendance_identity_available")),
                "joined": bool(log.get("client_joined")),
            },
        ]
        missing = [item for item in participants if item["identity_available"] and not item["joined"] and item["email"]]
        unverifiable_roles = [item["role"] for item in participants if not item["identity_available"]]
        if not missing:
            await db["email_logs"].update_one(
                {"email_id": email_id},
                {
                    "$set": {
                        "no_show_check_completed": True,
                        "no_show_check_completed_at": now,
                        "no_show_check_result": "attendance_unverifiable" if unverifiable_roles else "both_joined",
                        "no_show_unverifiable_roles": unverifiable_roles,
                        "updated_at": now,
                    },
                    "$unset": {"no_show_check_claimed": "", "no_show_check_claimed_at": ""},
                },
            )
            if unverifiable_roles:
                unverifiable += 1
            else:
                skipped += 1
            continue

        # Everyone involved receives an awareness notice whenever either party
        # is missing; the missing participant is asked to join or reschedule.
        clahan_email = _clean(log.get("clahan_email") or log.get("office_email")
                              or log.get("coordinator_email") or settings.CLAHAN_NOTIFICATION_EMAIL)
        missing_roles = [item["role"] for item in missing]
        notice_recipients = [item for item in participants if item["email"]]
        if clahan_email and clahan_email.lower() not in {item["email"].lower() for item in notice_recipients}:
            notice_recipients.append({"role": "clahan", "email": clahan_email, "name": "Clahan Technologies",
                                      "identity_available": True, "joined": False})
        technology = _clean(log.get("technology") or log.get("domain")) or "training"
        interview_link = _clean(log.get("interview_link") or log.get("meet_link"))
        interview_date = _clean(log.get("interview_date") or log.get("date_time_text") or log.get("interview_at"))
        log_sent = log_failed = 0
        for participant in notice_recipients:
            try:
                response = httpx.post(
                    f"{settings.EMAIL_SERVICE_URL}/api/v1/email/send",
                    json={
                        "to": participant["email"],
                        "subject": f"Interview Join Check - {technology}",
                        "body": _notice_body(
                            name=participant["name"],
                            technology=technology,
                            interview_link=interview_link,
                            interview_date=interview_date,
                            role=participant["role"],
                            missing_roles=missing_roles,
                            recipient_joined=participant.get("joined", False),
                        ),
                        "mail_type": "meet_no_show_notice",
                        "requirement_id": _clean(log.get("requirement_id")),
                        "trainer_id": _clean(log.get("trainer_id")),
                        "trainer_name": _clean(log.get("trainer_name")),
                        "idempotency_key": f"interview-no-show:{email_id}:{participant['role']}:{participant['email']}",
                        "ai_generate": True,
                        "ai_context": {
                            "workflow": "interview_no_show_notice",
                            "recipient_role": participant["role"],
                            "recipient_name": participant["name"],
                            "technology": technology,
                            "meeting_time": interview_date,
                            "meeting_link": interview_link,
                            "required_message": "The meeting began 10 minutes ago; we could not confirm your attendance. Join now or reply if you need to reschedule.",
                            "no_auto_reschedule": True,
                        },
                    },
                    timeout=30,
                )
                ok = response.status_code < 400 and response.json().get("success", False)
            except Exception as exc:
                logger.error("No-show notice failed for %s: %s", participant["email"], exc)
                ok = False
            if ok:
                log_sent += 1
            else:
                log_failed += 1

        complete = log_failed == 0
        await db["email_logs"].update_one(
            {"email_id": email_id},
            {
                "$set": {
                    "no_show_check_completed": complete,
                    "no_show_check_completed_at": now if complete else None,
                    "no_show_check_result": "notice_sent" if complete else "notice_send_failed",
                    "no_show_notice_roles": [item["role"] for item in missing] if complete else [],
                    "no_show_unverifiable_roles": unverifiable_roles,
                    "followup_suppressed": True,
                    "followup_suppressed_at": now,
                    "updated_at": now,
                },
                "$unset": {"no_show_check_claimed": "", "no_show_check_claimed_at": ""},
            },
        )
        # The meeting reply has already completed trainer outreach. Prevent
        # any stale Mail 1/Mail 2 reminder chain from firing after attendance
        # failure is handled.
        requirement_key = _clean(log.get("requirement_id"))
        trainer_key = _clean(log.get("trainer_id"))
        if requirement_key and trainer_key:
            await db["email_logs"].update_many(
                {"requirement_id": requirement_key, "trainer_id": trainer_key,
                 "mail_type": {"$in": ["mail1", "mail1_reminder", "mail2_reminder"]}},
                {"$set": {"followup_suppressed": True, "followup_suppressed_at": now}},
            )
        if complete and _clean(log.get("requirement_id")) and _clean(log.get("trainer_id")):
            await db["shortlists"].update_one(
                {"requirement_id": log["requirement_id"], "top_trainers.trainer_id": log["trainer_id"]},
                {"$set": {
                    "top_trainers.$.slot_status": "interview_no_show_awaiting_reply",
                    "top_trainers.$.no_show_notice_sent_at": now,
                    "top_trainers.$.updated_at": now,
                    "updated_at": now,
                }},
            )
        sent += log_sent
        failed += log_failed

    return {"sent": sent, "failed": failed, "skipped": skipped, "unverifiable": unverifiable}


@celery_app.task(name="app.tasks.no_show_notices.send_due_no_show_notices", bind=True, max_retries=2)
def send_due_no_show_notices(self):
    try:
        result = run_async(_send_due_no_show_notices())
        logger.info("Interview no-show notices: %s", result)
        return result
    except Exception as exc:
        logger.error("Interview no-show notice task failed: %s", exc)
        raise self.retry(exc=exc, countdown=60)
