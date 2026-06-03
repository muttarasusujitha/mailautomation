import asyncio
from utils.time_utils import utc_now
from typing import Any, Dict

import httpx
from motor.motor_asyncio import AsyncIOMotorClient

from celery_app import celery_app
from config import get_settings
from agents.email_agent import send_email_async
from agents.whatsapp_agent import (
    get_twilio_config,
    send_interview_whatsapp,
    send_whatsapp_message,
)


async def _admin_email_config(db) -> Dict[str, Any]:
    settings_doc = await db["admin_settings"].find_one(
        {"settings_id": "default"},
        {"_id": 0, "emailCfg": 1},
    )
    email_cfg = (settings_doc or {}).get("emailCfg") or {}
    return {k: v for k, v in email_cfg.items() if v not in (None, "")}


async def _teams_webhook_url(db) -> str:
    settings = get_settings()
    settings_doc = await db["admin_settings"].find_one(
        {"settings_id": "default"},
        {"_id": 0, "teamsCfg": 1},
    )
    cfg = (settings_doc or {}).get("teamsCfg") or {}
    return (cfg.get("webhookUrl") or settings.teams_webhook_url or "").strip()


def _reminder_subject(reminder: Dict[str, Any]) -> str:
    return f"Interview Reminder - {reminder.get('technology') or 'Training'}"


def _reminder_body(reminder: Dict[str, Any]) -> str:
    return (
        f"Dear {reminder.get('trainer_name') or 'Trainer'},\n\n"
        "This is a reminder that your trainer interview/discussion is scheduled in 1 hour.\n\n"
        f"Technology: {reminder.get('technology') or 'Training'}\n"
        f"Date & Time: {reminder.get('interview_date') or '[Date & Time]'}\n"
        f"Platform: {reminder.get('platform') or 'Online'}\n"
        f"Meeting Link: {reminder.get('interview_link') or '[Meeting Link]'}\n\n"
        "Please join on time and keep your profile, availability, commercials, and course outline handy.\n\n"
        "Regards,\n"
        "TrainerSync Team"
    )


def _requirement_locked_for_other_trainer(requirement: Dict[str, Any], trainer_id: str) -> bool:
    requirement = requirement or {}
    selected_trainer_id = str(requirement.get("selected_trainer_id") or "").strip()
    selection_status = str(requirement.get("selection_status") or requirement.get("status") or "").strip().lower()
    locked_statuses = {
        "selected",
        "trainer_selected_auto_sent",
        "toc_requested",
        "training_confirmed",
        "closed",
        "fulfilled",
    }
    locked = bool(selected_trainer_id) or selection_status in locked_statuses
    return locked and (not selected_trainer_id or str(trainer_id or "").strip() != selected_trainer_id)


async def _send_teams_card(db, reminder: Dict[str, Any]) -> Dict[str, Any]:
    webhook_url = await _teams_webhook_url(db)
    if not webhook_url:
        return {"success": False, "status": "skipped", "error": "Teams webhook URL not configured"}

    card = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": "Trainer interview reminder",
        "themeColor": "2563EB",
        "title": "Trainer interview reminder",
        "sections": [{
            "activityTitle": reminder.get("trainer_name") or "Trainer",
            "activitySubtitle": reminder.get("technology") or "Training",
            "facts": [
                {"name": "Requirement", "value": reminder.get("requirement_id") or "-"},
                {"name": "Date/Time", "value": reminder.get("interview_date") or "-"},
                {"name": "Platform", "value": reminder.get("platform") or "Online"},
                {"name": "Trainer Email", "value": reminder.get("trainer_email") or "-"},
            ],
            "markdown": True,
        }],
        "potentialAction": [{
            "@type": "OpenUri",
            "name": "Open Meeting",
            "targets": [{"os": "default", "uri": reminder.get("interview_link") or ""}],
        }] if reminder.get("interview_link") else [],
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(webhook_url, json=card)
        if response.status_code >= 400:
            return {"success": False, "status": "failed", "error": response.text[:500]}
        return {"success": True, "status": "sent"}
    except Exception as exc:
        return {"success": False, "status": "failed", "error": str(exc)}


async def _send_interview_reminder(reminder_id: str, celery_task_id: str = "") -> Dict[str, Any]:
    settings = get_settings()
    client = AsyncIOMotorClient(settings.mongodb_uri)
    db = client[settings.mongodb_db]
    now = utc_now()

    try:
        reminder = await db["interview_reminders"].find_one({"reminder_id": reminder_id}, {"_id": 0})
        if not reminder:
            return {"success": False, "status": "missing", "reminder_id": reminder_id}
        if reminder.get("status") == "cancelled":
            return {"success": True, "status": "cancelled", "reminder_id": reminder_id}

        requirement = await db["requirements"].find_one(
            {"requirement_id": reminder.get("requirement_id")},
            {"_id": 0},
        )
        if _requirement_locked_for_other_trainer(requirement, reminder.get("trainer_id", "")):
            await db["interview_reminders"].update_one(
                {"reminder_id": reminder_id},
                {"$set": {
                    "status": "skipped_requirement_selected",
                    "updated_at": now,
                    "skipped_at": now,
                }},
            )
            await db["email_logs"].update_one(
                {"email_id": reminder.get("email_id")},
                {"$set": {
                    "interview_reminder_status": "skipped_requirement_selected",
                    "interview_reminder_skipped_at": now,
                }},
            )
            return {"success": True, "status": "skipped_requirement_selected", "reminder_id": reminder_id}

        await db["interview_reminders"].update_one(
            {"reminder_id": reminder_id, "status": {"$ne": "cancelled"}},
            {"$set": {"status": "sending", "started_at": now, "updated_at": now}},
        )

        subject = _reminder_subject(reminder)
        body = _reminder_body(reminder)
        smtp_config = await _admin_email_config(db)
        email_success, email_error = await send_email_async(
            reminder.get("trainer_email", ""),
            subject,
            body,
            smtp_config,
        )

        trainer_whatsapp = await send_interview_whatsapp(
            db,
            trainer_phone=reminder.get("trainer_phone", ""),
            trainer_name=reminder.get("trainer_name", ""),
            requirement_id=reminder.get("requirement_id", ""),
            technology=reminder.get("technology", ""),
            date_time=reminder.get("interview_date", ""),
            platform=reminder.get("platform", "Online"),
            interview_link=reminder.get("interview_link", ""),
            email_id=reminder.get("email_id", ""),
            request_base_url=reminder.get("request_base_url", ""),
            reminder=True,
        )

        twilio_cfg = await get_twilio_config(db)
        vendor_body = (
            "TrainerSync interview reminder sent\n"
            f"Trainer: {reminder.get('trainer_name') or 'Trainer'}\n"
            f"Technology: {reminder.get('technology') or 'Training'}\n"
            f"Requirement: {reminder.get('requirement_id') or '-'}\n"
            f"Date/Time: {reminder.get('interview_date') or '-'}\n"
            f"Platform: {reminder.get('platform') or 'Online'}"
        )
        vendor_whatsapp = await send_whatsapp_message(
            db,
            twilio_cfg.get("vendorWhatsAppNumber", ""),
            vendor_body,
            event_type="interview_reminder_vendor",
            recipient_type="vendor",
            request_base_url=reminder.get("request_base_url", ""),
            context={
                "reminder_id": reminder_id,
                "trainer_id": reminder.get("trainer_id"),
                "trainer_name": reminder.get("trainer_name"),
                "requirement_id": reminder.get("requirement_id"),
                "email_id": reminder.get("email_id"),
            },
        )

        teams_result = await _send_teams_card(db, reminder)
        channel_status = {
            "email": "sent" if email_success else "failed",
            "trainer_whatsapp": "sent" if trainer_whatsapp.get("success") else trainer_whatsapp.get("status", "failed"),
            "vendor_whatsapp": "sent" if vendor_whatsapp.get("success") else vendor_whatsapp.get("status", "failed"),
            "teams": "sent" if teams_result.get("success") else teams_result.get("status", "failed"),
        }
        status = "sent"
        sent_at = utc_now()

        await db["interview_reminders"].update_one(
            {"reminder_id": reminder_id},
            {"$set": {
                "status": status,
                "sent_at": sent_at,
                "updated_at": sent_at,
                "celery_task_id": celery_task_id,
                "channels": channel_status,
                "email_error": email_error,
                "trainer_whatsapp": trainer_whatsapp,
                "vendor_whatsapp": vendor_whatsapp,
                "teams": teams_result,
            }},
        )
        await db["email_logs"].update_one(
            {"email_id": reminder.get("email_id")},
            {"$set": {
                "interview_reminder_status": status,
                "interview_reminder_sent_at": sent_at,
                "whatsapp_reminder_status": channel_status["trainer_whatsapp"],
                "whatsapp_reminder_sent_at": sent_at if trainer_whatsapp.get("success") else None,
                "whatsapp_reminder_error": trainer_whatsapp.get("error", ""),
            }},
        )
        await db["conversations"].insert_one({
            "trainer_id": reminder.get("trainer_id"),
            "trainer_name": reminder.get("trainer_name"),
            "to_email": reminder.get("trainer_email"),
            "requirement_id": reminder.get("requirement_id"),
            "subject": subject,
            "body": body,
            "mail_type": "interview_reminder",
            "direction": "sent",
            "status": "sent" if email_success else "failed",
            "error": email_error if not email_success else "",
            "sent_at": sent_at,
            "reminder_id": reminder_id,
        })
        return {"success": True, "status": status, "reminder_id": reminder_id, "channels": channel_status}
    except Exception as exc:
        failed_at = utc_now()
        await db["interview_reminders"].update_one(
            {"reminder_id": reminder_id},
            {"$set": {
                "status": "failed",
                "error": str(exc),
                "failed_at": failed_at,
                "updated_at": failed_at,
            }},
        )
        return {"success": False, "status": "failed", "error": str(exc), "reminder_id": reminder_id}
    finally:
        client.close()


@celery_app.task(bind=True, name="trainersync.send_interview_reminder")
def send_interview_reminder_task(self, reminder_id: str) -> Dict[str, Any]:
    return asyncio.run(_send_interview_reminder(reminder_id, self.request.id))
