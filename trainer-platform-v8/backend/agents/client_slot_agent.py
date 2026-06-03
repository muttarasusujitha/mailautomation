from datetime import datetime
from utils.time_utils import utc_now
import hashlib
import re
import uuid
from typing import Callable, Optional

from agents.email_agent import send_email_async
from agents.teams_agent import send_teams_stage_notification
from agents.whatsapp_agent import send_whatsapp_message


class ClientSlotError(Exception):
    pass


def strip_quoted_reply_text(text: str) -> str:
    value = str(text or "")
    value = re.split(r"\nOn .+wrote:\s*", value, maxsplit=1, flags=re.IGNORECASE)[0]
    value = re.split(r"\n-{2,}\s*Original Message\s*-{2,}", value, maxsplit=1, flags=re.IGNORECASE)[0]
    lines = [line for line in value.splitlines() if not line.strip().startswith(">")]
    return "\n".join(lines).strip()


def looks_like_trainer_slots(text: str) -> bool:
    value = re.sub(r"\s+", " ", strip_quoted_reply_text(text).lower()).strip()
    if not value:
        return False

    client_confirmation_phrases = [
        "works for our team",
        "client team",
        "please proceed with scheduling",
        "share the meeting details",
        "share meeting details",
        "schedule the discussion",
        "thank you for sharing the trainer",
    ]
    if any(phrase in value for phrase in client_confirmation_phrases):
        return False

    has_time = bool(re.search(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", value))
    has_range = bool(re.search(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s*(?:to|-|–|—)\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", value))
    has_date_or_day = bool(re.search(
        r"\b(?:today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
        r"\d{1,2}\s*[/-]\s*\d{1,2}(?:\s*[/-]\s*\d{2,4})?|"
        r"\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{2,4})\b",
        value,
    ))
    has_slot_language = bool(re.search(r"\b(?:slot|available|availability|timing|schedule|interview|discussion)\b", value))
    return (has_time or has_range) and (has_date_or_day or has_slot_language)


async def get_admin_email_config(db):
    settings_doc = await db["admin_settings"].find_one(
        {"settings_id": "default"},
        {"_id": 0, "emailCfg": 1},
    )
    email_cfg = (settings_doc or {}).get("emailCfg") or {}
    return {k: v for k, v in email_cfg.items() if v not in (None, "")}


async def client_contact_for_requirement(db, requirement_id: str, payload: dict) -> tuple:
    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}

    email = (payload.get("client_email") or requirement.get("client_email") or "").strip()
    name = (
        payload.get("client_name")
        or requirement.get("client_name")
        or requirement.get("client_company")
        or "Client"
    )

    if not email:
        inbox_docs = await db["client_emails"].find(
            {"requirement_id": requirement_id},
            {"_id": 0},
        ).sort("created_at", -1).limit(1).to_list(1)
        inbox_doc = inbox_docs[0] if inbox_docs else {}
        extracted = inbox_doc.get("extracted") or {}
        email = (inbox_doc.get("from_email") or extracted.get("client_email") or "").strip()
        name = inbox_doc.get("from_name") or extracted.get("client_name") or name

    return requirement, email, name


def requirement_locked_for_other_trainer(requirement: dict, trainer_id: str) -> tuple[bool, str, str]:
    selected_trainer_id = str((requirement or {}).get("selected_trainer_id") or "").strip()
    selection_status = str((requirement or {}).get("selection_status") or (requirement or {}).get("status") or "").strip().lower()
    locked_statuses = {
        "selected",
        "trainer_selected_auto_sent",
        "toc_requested",
        "training_confirmed",
        "closed",
        "fulfilled",
    }
    locked = bool(selected_trainer_id) or selection_status in locked_statuses
    if not locked:
        return False, "", ""
    if selected_trainer_id and str(trainer_id or "").strip() == selected_trainer_id:
        return False, selected_trainer_id, str((requirement or {}).get("selected_trainer_name") or "").strip()
    return True, selected_trainer_id, str((requirement or {}).get("selected_trainer_name") or "").strip()


async def send_client_slot_options_email(
    db,
    payload: dict,
    *,
    tracking_url_builder: Optional[Callable[[str], str]] = None,
    source: str = "manual",
    request_base_url: str = "",
) -> dict:
    trainer_id = payload.get("trainer_id", "")
    trainer_name = payload.get("trainer_name") or "the trainer"
    requirement_id = payload.get("requirement_id", "")
    force = bool(payload.get("force", False))

    if not requirement_id and not str(payload.get("client_email") or "").strip():
        raise ClientSlotError("requirement_id is required")

    requirement, client_email, client_name = await client_contact_for_requirement(db, requirement_id, payload)
    client_phone = (
        str(payload.get("client_phone") or "").strip()
        or str(payload.get("client_whatsapp") or "").strip()
        or str(requirement.get("client_phone") or "").strip()
        or str(requirement.get("client_whatsapp") or "").strip()
    )
    blocked, selected_trainer_id, selected_trainer_name = requirement_locked_for_other_trainer(requirement, trainer_id)
    if blocked:
        return {
            "success": True,
            "skipped": True,
            "already_sent": True,
            "status": "requirement_already_selected",
            "reason": f"{selected_trainer_name or selected_trainer_id or 'Another trainer'} is already selected for this requirement. Client slot mails to remaining trainers are stopped.",
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
            "selected_trainer_id": selected_trainer_id,
            "selected_trainer_name": selected_trainer_name,
        }
    if not client_email:
        raise ClientSlotError("Client email not found for this requirement")

    technology = requirement.get("technology_needed") or payload.get("technology") or "training"
    slot_text = strip_quoted_reply_text(
        payload.get("slot_text") or payload.get("slots") or payload.get("trainer_reply") or ""
    )
    if not slot_text:
        if not force:
            raise ClientSlotError("Trainer slot availability not found for client scheduling")
        slot_text = "The trainer has confirmed availability. Please reply with a convenient slot or share alternate timings."
    elif not force and not looks_like_trainer_slots(slot_text):
        raise ClientSlotError("Trainer reply does not contain concrete interview slot availability")

    normalised_slots = re.sub(r"\s+", " ", slot_text.lower()).strip()
    slot_hash = hashlib.sha256(f"{requirement_id}|{trainer_id}|{normalised_slots}".encode("utf-8")).hexdigest()

    active_statuses = [
        "sent",
        "confirmed_scheduled",
        "calendar_failed",
        "trainer_email_failed",
        "client_email_failed",
        "needs_manual_review",
    ]

    if not force:
        existing = await db["client_slot_emails"].find_one({
            "requirement_id": requirement_id,
            "status": {"$in": active_statuses},
        }, {"_id": 0}, sort=[("created_at", -1)])
        if existing:
            return {
                "success": True,
                "already_sent": True,
                "email_id": existing.get("email_id"),
                "to_email": existing.get("to_email"),
                "slot_ref": existing.get("slot_ref"),
                "status": existing.get("status"),
                "blocked_by_requirement": True,
            }

    slot_ref = payload.get("slot_ref") or f"SLOT-{uuid.uuid4().hex[:8].upper()}"
    subject = payload.get("subject") or f"Interview Slot Options - {technology} | {requirement_id} | {slot_ref}"
    body = payload.get("body") or (
        f"Hi {client_name or 'Team'},\n\n"
        f"Our training coordination team has received availability for the {technology} discussion/interview.\n\n"
        f"Reference: {requirement_id} / {slot_ref}\n\n"
        f"Available slot(s):\n{slot_text}\n\n"
        "Please confirm which slot works for your team, or share alternate timings if these are not convenient.\n"
        "Once you confirm, Calhan Technologies will schedule the meeting and share the final link separately.\n\n"
        "Regards,\nRecruitment Team,\nCalhan Technologies"
    )
    if slot_ref not in subject:
        subject = f"{subject} | {slot_ref}"
    if slot_ref not in body:
        body = f"{body.rstrip()}\n\nReference: {requirement_id} / {slot_ref}"

    email_id = f"CLIENT-SLOT-{uuid.uuid4().hex[:8].upper()}"
    tracking_url = tracking_url_builder(email_id) if tracking_url_builder else ""
    smtp_config = await get_admin_email_config(db)
    success, error = await send_email_async(client_email, subject, body, smtp_config, tracking_url)
    whatsapp_result = {"status": "skipped", "error": "Client phone not found"}
    if success and client_phone:
        whatsapp_result = await send_whatsapp_message(
            db,
            client_phone,
            body,
            event_type="client_slot_options",
            recipient_type="client",
            request_base_url=request_base_url,
            context={
                "source": source,
                "email_id": email_id,
                "mail_type": "client_slot_options",
                "recipient_name": client_name,
                "client_name": client_name,
                "client_email": client_email,
                "trainer_name": trainer_name,
                "trainer_id": trainer_id,
                "requirement_id": requirement_id,
                "subject": subject,
            },
        )

    now = utc_now()
    doc = {
        "email_id": email_id,
        "requirement_id": requirement_id,
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "to_email": client_email,
        "client_phone": client_phone,
        "client_name": client_name,
        "subject": subject,
        "body": body,
        "slot_text": slot_text,
        "slot_ref": slot_ref,
        "slot_hash": slot_hash,
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "sent_at": now if success else None,
        "created_at": now,
        "force": force,
        "source": source,
        "source_email_id": payload.get("source_email_id") or "",
        "source_message_id": payload.get("source_message_id") or "",
        "whatsapp_summary": whatsapp_result,
    }
    await db["client_slot_emails"].insert_one(doc)

    await db["email_logs"].insert_one({
        "email_id": email_id,
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "requirement_id": requirement_id,
        "to_email": client_email,
        "subject": subject,
        "body": body,
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "sent_at": now if success else None,
        "reply_received": False,
        "opened": False,
        "open_count": 0,
        "tracking_url": tracking_url,
        "retry_count": 0,
        "mail_type": "client_slot_options",
        "created_at": now,
        "source": source,
        "client_phone": client_phone,
        "whatsapp_summary": whatsapp_result,
    })

    teams_result = {"status": "not_sent", "error": "email_failed"}
    if success:
        teams_result = await send_teams_stage_notification(
            db,
            stage="client_message_sent",
            trainer_name=client_name,
            requirement=requirement or {"requirement_id": requirement_id, "technology_needed": technology},
            request_base_url=request_base_url,
            context={
                "source": source,
                "email_id": email_id,
                "mail_type": "client_slot_options",
                "trainer_id": trainer_id,
                "trainer_name": trainer_name,
                "recipient_type": "client",
                "client_email": client_email,
                "client_phone": client_phone,
                "subject": subject,
                "body": body,
                "email_status": "sent",
                "whatsapp_status": whatsapp_result.get("status", ""),
            },
        )
        await db["client_slot_emails"].update_one(
            {"email_id": email_id},
            {"$set": {"teams_summary": teams_result}},
        )
        await db["email_logs"].update_one(
            {"email_id": email_id},
            {"$set": {"teams_summary": teams_result}},
        )

    return {
        "success": success,
        "error": error,
        "email_id": email_id,
        "to_email": client_email,
        "slot_ref": slot_ref,
        "already_sent": False,
        "whatsapp": whatsapp_result,
        "teams": teams_result,
    }


async def send_client_slots_for_email_log(
    db,
    email_id: str,
    *,
    force: bool = False,
    overrides: Optional[dict] = None,
    tracking_url_builder: Optional[Callable[[str], str]] = None,
    source: str = "email_log_manual",
    request_base_url: str = "",
) -> dict:
    log = await db["email_logs"].find_one({"email_id": email_id}, {"_id": 0})
    if not log:
        raise ClientSlotError("Email log not found")
    if log.get("mail_type") != "mail3":
        raise ClientSlotError("Client slot sending is available only for interview slot booking replies")

    slot_text = log.get("reply_text") or ""
    if not slot_text:
        latest_reply = await db["conversations"].find_one(
            {
                "trainer_id": log.get("trainer_id"),
                "requirement_id": log.get("requirement_id"),
                "direction": "received",
            },
            {"_id": 0},
            sort=[("sent_at", -1), ("created_at", -1)],
        )
        slot_text = (latest_reply or {}).get("body") or ""
    if not slot_text:
        raise ClientSlotError("Trainer slot reply not found for this email")

    overrides = overrides or {}
    client_email = str(overrides.get("client_email") or "").strip()
    client_name = str(overrides.get("client_name") or "").strip()
    if client_email and log.get("requirement_id"):
        update_fields = {"client_email": client_email}
        if client_name:
            update_fields["client_name"] = client_name
        await db["requirements"].update_one(
            {"requirement_id": log.get("requirement_id")},
            {"$set": update_fields},
        )

    result = await send_client_slot_options_email(
        db,
        {
            "trainer_id": log.get("trainer_id") or "",
            "trainer_name": log.get("trainer_name") or "the trainer",
            "requirement_id": log.get("requirement_id") or "",
            "slot_text": slot_text,
            "force": force,
            "client_email": client_email,
            "client_name": client_name,
            "source_email_id": email_id,
            "source_message_id": log.get("reply_message_id") or "",
        },
        tracking_url_builder=tracking_url_builder,
        source=source,
        request_base_url=request_base_url,
    )
    await db["email_logs"].update_one(
        {"email_id": email_id},
        {"$set": {
            "client_slot_auto_result": result,
            "client_slot_auto_checked_at": utc_now(),
        }},
    )
    return result


async def send_pending_client_slot_replies(
    db,
    *,
    limit: int = 50,
    requirement_id: str = "",
    tracking_url_builder: Optional[Callable[[str], str]] = None,
    source: str = "pending_reply_scan",
    request_base_url: str = "",
) -> dict:
    query = {
        "mail_type": {"$in": ["mail3", "mail3_slot_followup"]},
        "status": "sent",
        "reply_received": True,
        "reply_text": {"$nin": [None, ""]},
        "$or": [
            {"client_slot_auto_result": {"$exists": False}},
            {"client_slot_auto_result.success": {"$ne": True}},
        ],
    }
    if requirement_id:
        query["requirement_id"] = requirement_id

    logs = await db["email_logs"].find(
        query,
        {"_id": 0},
    ).sort("replied_at", -1).limit(limit).to_list(limit)

    results = []
    sent = 0
    failed = 0
    for log in logs:
        try:
            result = await send_client_slots_for_email_log(
                db,
                log.get("email_id", ""),
                force=False,
                tracking_url_builder=tracking_url_builder,
                source=source,
                request_base_url=request_base_url,
            )
        except ClientSlotError as exc:
            result = {"success": False, "error": str(exc), "already_sent": False}
            await db["email_logs"].update_one(
                {"email_id": log.get("email_id")},
                {"$set": {
                    "client_slot_auto_result": result,
                    "client_slot_auto_checked_at": utc_now(),
                }},
            )
        except Exception as exc:
            result = {"success": False, "error": str(exc), "already_sent": False}
            await db["email_logs"].update_one(
                {"email_id": log.get("email_id")},
                {"$set": {
                    "client_slot_auto_result": result,
                    "client_slot_auto_checked_at": utc_now(),
                }},
            )
        results.append(result)
        if result.get("success"):
            sent += 1
        else:
            failed += 1

    return {"checked": len(logs), "sent": sent, "failed": failed, "results": results}
