import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx

from database import get_db


TWILIO_API_BASE = "https://api.twilio.com/2010-04-01"

STAGE_LABELS = {
    "mail1": "Stage 1 - First outreach",
    "mail1_reminder": "Stage 1 - Follow-up reminder",
    "first": "Stage 1 - First outreach",
    "mail2": "Stage 2 - Details requested",
    "mail3": "Stage 3 - Interview slot booking",
    "mail4": "Stage 4 - Interview scheduled",
    "mail5_ok": "Stage 5 - Trainer selected",
    "mail5_no": "Stage 5 - Trainer rejected",
    "mail6_toc": "Stage 6 - ToC requested",
    "mail7_confirm": "Stage 7 - Training confirmed",
    "reply": "Trainer reply",
}


async def get_twilio_config(db) -> Dict[str, Any]:
    settings_doc = await db["admin_settings"].find_one(
        {"settings_id": "default"},
        {"_id": 0, "twilioCfg": 1},
    )
    cfg = (settings_doc or {}).get("twilioCfg") or {}
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "accountSid": (cfg.get("accountSid") or os.getenv("TWILIO_ACCOUNT_SID", "")).strip(),
        "authToken": (cfg.get("authToken") or os.getenv("TWILIO_AUTH_TOKEN", "")).strip(),
        "fromWhatsAppNumber": (cfg.get("fromWhatsAppNumber") or os.getenv("TWILIO_WHATSAPP_FROM", "")).strip(),
        "vendorWhatsAppNumber": (cfg.get("vendorWhatsAppNumber") or os.getenv("VENDOR_WHATSAPP_NUMBER", "")).strip(),
        "defaultCountryCode": (cfg.get("defaultCountryCode") or "+91").strip(),
        "statusCallbackUrl": (cfg.get("statusCallbackUrl") or "").strip(),
    }


def stage_label(mail_type: str = "") -> str:
    return STAGE_LABELS.get(mail_type or "", mail_type or "Pipeline update")


def _clip(text: Any, limit: int = 900) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    return cleaned if len(cleaned) <= limit else f"{cleaned[:limit - 3]}..."


def _format_whatsapp_number(number: Any, default_country_code: str = "+91") -> str:
    raw = str(number or "").strip()
    if not raw:
        return ""
    if raw.lower().startswith("whatsapp:"):
        return raw

    raw = raw.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if raw.startswith("00"):
        raw = f"+{raw[2:]}"
    if not raw.startswith("+"):
        digits = re.sub(r"\D", "", raw)
        country = default_country_code if default_country_code.startswith("+") else f"+{default_country_code}"
        raw = f"{country}{digits}"
    return f"whatsapp:{raw}"


def _callback_url(config: Dict[str, Any], request_base_url: str = "") -> str:
    if config.get("statusCallbackUrl"):
        return config["statusCallbackUrl"]
    if request_base_url:
        return f"{request_base_url.rstrip('/')}/api/whatsapp/status-callback"
    return ""


async def _insert_whatsapp_log(db, log_doc: Dict[str, Any]) -> Dict[str, Any]:
    doc = {
        "whatsapp_id": f"WA-{uuid.uuid4().hex[:10].upper()}",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        **log_doc,
    }
    await db["whatsapp_logs"].insert_one(doc)
    return doc


async def send_whatsapp_message(
    db,
    to_number: str,
    body: str,
    *,
    event_type: str,
    recipient_type: str,
    context: Optional[Dict[str, Any]] = None,
    request_base_url: str = "",
    media_url: str = "",
) -> Dict[str, Any]:
    config = await get_twilio_config(db)
    context = context or {}
    to_whatsapp = _format_whatsapp_number(to_number, config.get("defaultCountryCode", "+91"))
    from_whatsapp = _format_whatsapp_number(config.get("fromWhatsAppNumber"), config.get("defaultCountryCode", "+91"))

    log_doc = await _insert_whatsapp_log(db, {
        "direction": "outbound",
        "event_type": event_type,
        "recipient_type": recipient_type,
        "to_number": to_whatsapp,
        "from_number": from_whatsapp,
        "body": body,
        "media_url": media_url,
        "status": "queued",
        "context": context,
    })

    missing = []
    if not config.get("enabled"):
        missing.append("Twilio WhatsApp is disabled")
    if not config.get("accountSid"):
        missing.append("Twilio Account SID")
    if not config.get("authToken"):
        missing.append("Twilio Auth Token")
    if not from_whatsapp:
        missing.append("Twilio WhatsApp sender number")
    if not to_whatsapp:
        missing.append("recipient WhatsApp number")

    if missing:
        error = ", ".join(missing)
        await db["whatsapp_logs"].update_one(
            {"whatsapp_id": log_doc["whatsapp_id"]},
            {"$set": {"status": "skipped", "error_message": error, "updated_at": datetime.utcnow()}},
        )
        return {"success": False, "status": "skipped", "error": error, "whatsapp_id": log_doc["whatsapp_id"]}

    url = f"{TWILIO_API_BASE}/Accounts/{config['accountSid']}/Messages.json"
    data = {
        "From": from_whatsapp,
        "To": to_whatsapp,
        "Body": body,
    }
    if media_url:
        data["MediaUrl"] = media_url
    callback = _callback_url(config, request_base_url)
    if callback:
        data["StatusCallback"] = callback

    try:
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.post(
                url,
                data=data,
                auth=(config["accountSid"], config["authToken"]),
            )
        payload = response.json()
        if response.status_code >= 400:
            error = payload.get("message") or response.text
            await db["whatsapp_logs"].update_one(
                {"whatsapp_id": log_doc["whatsapp_id"]},
                {"$set": {
                    "status": "failed",
                    "error_message": error,
                    "twilio_response": payload,
                    "updated_at": datetime.utcnow(),
                }},
            )
            return {"success": False, "status": "failed", "error": error, "whatsapp_id": log_doc["whatsapp_id"]}

        await db["whatsapp_logs"].update_one(
            {"whatsapp_id": log_doc["whatsapp_id"]},
            {"$set": {
                "status": payload.get("status", "sent"),
                "twilio_sid": payload.get("sid"),
                "twilio_response": payload,
                "sent_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }},
        )
        return {
            "success": True,
            "status": payload.get("status", "sent"),
            "twilio_sid": payload.get("sid"),
            "whatsapp_id": log_doc["whatsapp_id"],
        }
    except Exception as exc:
        await db["whatsapp_logs"].update_one(
            {"whatsapp_id": log_doc["whatsapp_id"]},
            {"$set": {"status": "failed", "error_message": str(exc), "updated_at": datetime.utcnow()}},
        )
        return {"success": False, "status": "failed", "error": str(exc), "whatsapp_id": log_doc["whatsapp_id"]}


def email_summary_message(
    trainer_name: str,
    subject: str,
    body: str,
    mail_type: str,
    requirement_id: str,
) -> str:
    return (
        "TrainerSync update\n"
        f"Stage: {stage_label(mail_type)}\n"
        f"Trainer: {trainer_name or 'Trainer'}\n"
        f"Requirement: {requirement_id or '-'}\n"
        f"Subject: {_clip(subject, 160)}\n\n"
        f"{_clip(body, 850)}"
    )


async def send_shortlist_whatsapp(
    db,
    *,
    trainer_phone: str,
    trainer_name: str,
    subject: str,
    body: str,
    mail_type: str,
    requirement_id: str,
    email_id: str,
    request_base_url: str = "",
) -> Dict[str, Any]:
    message = email_summary_message(trainer_name, subject, body, mail_type, requirement_id)
    return await send_whatsapp_message(
        db,
        trainer_phone,
        message,
        event_type="email_summary",
        recipient_type="trainer",
        request_base_url=request_base_url,
        context={
            "trainer_name": trainer_name,
            "requirement_id": requirement_id,
            "email_id": email_id,
            "mail_type": mail_type,
            "stage": stage_label(mail_type),
        },
    )


async def send_vendor_reply_notification(
    db,
    *,
    trainer_name: str,
    trainer_id: str,
    requirement_id: str,
    mail_type: str,
    reply_subject: str,
    reply_body: str,
    sentiment: str = "",
    request_base_url: str = "",
) -> Dict[str, Any]:
    config = await get_twilio_config(db)
    message = (
        "TrainerSync reply alert\n"
        f"Trainer: {trainer_name or trainer_id or 'Trainer'}\n"
        f"Requirement: {requirement_id or '-'}\n"
        f"Stage: {stage_label(mail_type)}\n"
        f"Sentiment: {sentiment or 'pending review'}\n"
        f"Subject: {_clip(reply_subject, 160)}\n\n"
        f"Reply: {_clip(reply_body, 700)}"
    )
    return await send_whatsapp_message(
        db,
        config.get("vendorWhatsAppNumber", ""),
        message,
        event_type="trainer_email_reply",
        recipient_type="vendor",
        request_base_url=request_base_url,
        context={
            "trainer_id": trainer_id,
            "trainer_name": trainer_name,
            "requirement_id": requirement_id,
            "mail_type": mail_type,
            "stage": stage_label(mail_type),
            "sentiment": sentiment,
        },
    )


async def send_interview_whatsapp(
    db,
    *,
    trainer_phone: str,
    trainer_name: str,
    requirement_id: str,
    technology: str,
    date_time: str,
    platform: str,
    interview_link: str,
    email_id: str,
    request_base_url: str = "",
    reminder: bool = False,
) -> Dict[str, Any]:
    title = "TrainerSync interview reminder" if reminder else "TrainerSync interview scheduled"
    message = (
        f"{title}\n"
        f"Trainer: {trainer_name or 'Trainer'}\n"
        f"Technology: {technology or 'Training'}\n"
        f"Requirement: {requirement_id or '-'}\n"
        f"Date/Time: {date_time or '[Date & Time]'}\n"
        f"Platform: {platform or 'Online'}\n"
        f"Meeting Link: {interview_link or '[Meeting Link]'}"
    )
    return await send_whatsapp_message(
        db,
        trainer_phone,
        message,
        event_type="interview_reminder" if reminder else "interview_scheduled",
        recipient_type="trainer",
        request_base_url=request_base_url,
        context={
            "trainer_name": trainer_name,
            "requirement_id": requirement_id,
            "email_id": email_id,
            "mail_type": "mail4",
            "stage": stage_label("mail4"),
            "date_time": date_time,
            "platform": platform,
            "interview_link": interview_link,
        },
    )


def parse_interview_datetime(value: str) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None

    candidates = [raw]
    if raw.endswith("Z"):
        candidates.append(raw[:-1] + "+00:00")
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            break
        except ValueError:
            parsed = None
    if not parsed:
        for fmt in ("%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
    if not parsed:
        return None

    if parsed.tzinfo is None:
        local_tz = datetime.now().astimezone().tzinfo
        parsed = parsed.replace(tzinfo=local_tz)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def interview_reminder_fields(date_time: str) -> Dict[str, Any]:
    interview_at = parse_interview_datetime(date_time)
    if not interview_at:
        return {}
    return {
        "interview_at": interview_at,
        "whatsapp_reminder_due_at": interview_at - timedelta(hours=1),
        "whatsapp_reminder_status": "pending",
    }


async def send_due_interview_reminders():
    db = get_db()
    now = datetime.utcnow()
    logs = await db["email_logs"].find({
        "interview_scheduled": True,
        "whatsapp_reminder_due_at": {"$lte": now},
        "whatsapp_reminder_status": "pending",
    }).to_list(100)

    for log in logs:
        trainer = await db["trainers"].find_one(
            {"trainer_id": log.get("trainer_id")},
            {"_id": 0, "phone": 1, "name": 1},
        ) or {}
        req = await db["requirements"].find_one(
            {"requirement_id": log.get("requirement_id")},
            {"_id": 0, "technology_needed": 1},
        ) or {}

        result = await send_interview_whatsapp(
            db,
            trainer_phone=log.get("trainer_phone") or trainer.get("phone", ""),
            trainer_name=log.get("trainer_name") or trainer.get("name", ""),
            requirement_id=log.get("requirement_id", ""),
            technology=req.get("technology_needed", "Training"),
            date_time=log.get("interview_date", ""),
            platform=log.get("platform", "Online"),
            interview_link=log.get("interview_link", ""),
            email_id=log.get("email_id", ""),
            reminder=True,
        )
        await db["email_logs"].update_one(
            {"email_id": log.get("email_id")},
            {"$set": {
                "whatsapp_reminder_status": "sent" if result.get("success") else result.get("status", "failed"),
                "whatsapp_reminder_sent_at": datetime.utcnow() if result.get("success") else None,
                "whatsapp_reminder_error": result.get("error", ""),
            }},
        )


async def update_whatsapp_status(db, payload: Dict[str, Any]) -> Dict[str, Any]:
    sid = payload.get("MessageSid") or payload.get("SmsSid") or payload.get("SmsMessageSid")
    status = payload.get("MessageStatus") or payload.get("SmsStatus")
    if not sid:
        return {"updated": False, "reason": "Missing MessageSid"}

    set_fields = {
        "status": status or "status_callback",
        "status_callback": payload,
        "updated_at": datetime.utcnow(),
    }
    if status == "delivered":
        set_fields["delivered_at"] = datetime.utcnow()
    if payload.get("ErrorCode"):
        set_fields["error_code"] = payload.get("ErrorCode")
        set_fields["error_message"] = payload.get("ErrorMessage", "")

    result = await db["whatsapp_logs"].update_one(
        {"twilio_sid": sid},
        {"$set": set_fields},
    )
    return {"updated": result.modified_count > 0, "twilio_sid": sid, "status": status}
