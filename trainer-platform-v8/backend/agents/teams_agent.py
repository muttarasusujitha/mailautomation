import uuid
from datetime import datetime
from utils.time_utils import utc_now
from typing import Any, Dict, Optional
from urllib.parse import quote

import httpx

from config import get_settings


STAGE_META = {
    "pipeline_message_sent": {
        "title": "Pipeline Message Sent",
        "stage": "Trainer Pipeline",
        "color": "Accent",
    },
    "client_message_sent": {
        "title": "Client Message Sent",
        "stage": "Client Communication",
        "color": "Accent",
    },
    "new_requirement_created": {
        "title": "New Requirement Created",
        "stage": "New Requirement",
        "color": "Accent",
    },
    "trainer_contacted": {
        "title": "Trainer Contacted",
        "stage": "Trainer Contacted",
        "color": "Accent",
    },
    "trainer_replied": {
        "title": "Trainer Replied",
        "stage": "Trainer Replied",
        "color": "Good",
    },
    "interview_scheduled": {
        "title": "Interview Scheduled",
        "stage": "Interview Scheduled",
        "color": "Warning",
    },
    "trainer_selected": {
        "title": "Trainer Selected",
        "stage": "Trainer Selected",
        "color": "Good",
    },
    "po_generated": {
        "title": "Purchase Order Generated",
        "stage": "PO Generated",
        "color": "Accent",
    },
}

MAIL_TYPE_LABELS = {
    "first": "Mail 1 - First Contact",
    "mail1": "Mail 1 - First Contact",
    "mail1_reminder": "Mail 1 Reminder",
    "mail2": "Mail 2 - Details Request",
    "mail2_followup": "Mail 2 Follow-up",
    "mail3": "Mail 3 - Slot Booking",
    "mail4": "Mail 4 - Interview Schedule",
    "mail5_ok": "Mail 5 - Selection",
    "mail5_no": "Mail 5 - Rejection",
    "mail6_toc": "Mail 6 - ToC / Agenda",
    "mail7_confirm": "Mail 7 - Training Confirmation",
    "client_slot_options": "Client Slot Options",
    "client_interview_schedule": "Client Interview Schedule",
}


async def get_teams_webhook_url(db) -> str:
    settings = get_settings()
    settings_doc = await db["admin_settings"].find_one(
        {"settings_id": "default"},
        {"_id": 0, "teamsCfg": 1},
    )
    cfg = (settings_doc or {}).get("teamsCfg") or {}
    return (cfg.get("webhookUrl") or settings.teams_webhook_url or "").strip()


def _text(value: Any, fallback: str = "-") -> str:
    cleaned = str(value or "").strip()
    return cleaned if cleaned else fallback


def _timestamp(value: Optional[Any] = None) -> str:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = utc_now()
    return f"{dt.replace(microsecond=0).isoformat()}Z"


def _requirement_id(requirement: Dict[str, Any], explicit: str = "") -> str:
    return _text(explicit or requirement.get("requirement_id"), "")


def _technology(requirement: Dict[str, Any], explicit: str = "") -> str:
    return _text(
        explicit
        or requirement.get("technology_needed")
        or requirement.get("technology")
        or requirement.get("job_title"),
        "Training",
    )


def _trainer_name(trainer: Dict[str, Any], explicit: str = "") -> str:
    return _text(
        explicit
        or trainer.get("trainer_name")
        or trainer.get("name")
        or trainer.get("full_name"),
        "Not assigned yet",
    )


def _clip(value: Any, limit: int = 900) -> str:
    cleaned = " ".join(str(value or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[:limit - 3].rstrip()}..."


def _card_message_body(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) <= 4500:
        return text
    return f"{text[:4497].rstrip()}..."


def shortlist_url(requirement_id: str = "", request_base_url: str = "") -> str:
    settings = get_settings()
    base_url = (settings.frontend_url or request_base_url or "").strip().rstrip("/")
    if not base_url:
        return ""
    url = f"{base_url}/shortlist"
    if requirement_id:
        url = f"{url}?requirement_id={quote(str(requirement_id))}"
    return url


def build_adaptive_card(
    *,
    stage: str,
    trainer_name: str,
    technology: str,
    requirement_id: str,
    timestamp: Optional[Any] = None,
    request_base_url: str = "",
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    meta = STAGE_META.get(stage, {"title": "Pipeline Update", "stage": stage, "color": "Accent"})
    link = shortlist_url(requirement_id, request_base_url)
    context = context or {}
    mail_type = str(context.get("mail_type") or "").strip()
    subject = str(context.get("subject") or "").strip()
    body = str(context.get("body") or context.get("message") or "").strip()
    to_email = str(context.get("to_email") or context.get("client_email") or "").strip()
    to_phone = str(context.get("to_phone") or context.get("trainer_phone") or context.get("client_phone") or "").strip()
    recipient_type = str(context.get("recipient_type") or "").strip()
    whatsapp_status = str(context.get("whatsapp_status") or "").strip()
    email_status = str(context.get("email_status") or "").strip()

    card = {
        "$schema": "https://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": meta["title"],
                "weight": "Bolder",
                "size": "Medium",
                "color": meta["color"],
                "wrap": True,
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Client" if recipient_type.lower() == "client" else "Trainer", "value": _text(trainer_name)},
                    {"title": "Technology", "value": _text(technology, "Training")},
                    {"title": "Current Stage", "value": _text(meta["stage"])},
                    {"title": "Timestamp", "value": _timestamp(timestamp)},
                ],
            },
        ],
    }
    facts = card["body"][1]["facts"]
    if mail_type:
        facts.insert(2, {"title": "Message Type", "value": MAIL_TYPE_LABELS.get(mail_type, mail_type)})
    if recipient_type:
        facts.append({"title": "Recipient Type", "value": recipient_type.title()})
    if to_email:
        facts.append({"title": "Email", "value": to_email})
    if to_phone:
        facts.append({"title": "WhatsApp / Phone", "value": to_phone})
    if email_status:
        facts.append({"title": "Email Status", "value": email_status})
    if whatsapp_status:
        facts.append({"title": "WhatsApp Status", "value": whatsapp_status})
    if subject:
        card["body"].append({
            "type": "TextBlock",
            "text": f"Subject: {_clip(subject, 180)}",
            "weight": "Bolder",
            "wrap": True,
            "spacing": "Medium",
        })
    if body:
        card["body"].append({
            "type": "TextBlock",
            "text": _card_message_body(body),
            "wrap": True,
            "spacing": "Small",
        })
    if link:
        card["actions"] = [{"type": "Action.OpenUrl", "title": "Open Shortlist", "url": link}]
    if requirement_id:
        card["body"][1]["facts"].insert(1, {"title": "Requirement", "value": requirement_id})
    return card


def build_teams_payload(card: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": card,
            }
        ],
    }


async def _insert_teams_log(db, doc: Dict[str, Any]) -> Dict[str, Any]:
    log_doc = {
        "teams_id": f"TEAMS-{uuid.uuid4().hex[:10].upper()}",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        **doc,
    }
    await db["teams_logs"].insert_one(log_doc)
    return log_doc


async def send_teams_stage_notification(
    db,
    *,
    stage: str,
    trainer_name: str = "",
    requirement_id: str = "",
    technology: str = "",
    trainer: Optional[Dict[str, Any]] = None,
    requirement: Optional[Dict[str, Any]] = None,
    request_base_url: str = "",
    timestamp: Optional[Any] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    webhook_url = await get_teams_webhook_url(db)
    if not webhook_url:
        return {"success": True, "status": "skipped"}

    trainer = trainer or {}
    requirement = requirement or {}
    context = context or {}
    req_id = _requirement_id(requirement, requirement_id)
    tech = _technology(requirement, technology)
    name = _trainer_name(trainer, trainer_name)

    card = build_adaptive_card(
        stage=stage,
        trainer_name=name,
        requirement_id=req_id,
        technology=tech,
        timestamp=timestamp,
        request_base_url=request_base_url,
        context=context,
    )
    payload = build_teams_payload(card)
    log_doc = await _insert_teams_log(db, {
        "event_type": stage,
        "status": "queued",
        "trainer_name": name,
        "requirement_id": req_id,
        "technology": tech,
        "shortlist_url": shortlist_url(req_id, request_base_url),
        "payload": payload,
        "context": context,
    })

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(webhook_url, json=payload)
        if response.status_code >= 400:
            error = response.text[:500]
            await db["teams_logs"].update_one(
                {"teams_id": log_doc["teams_id"]},
                {"$set": {"status": "failed", "error_message": error, "updated_at": utc_now()}},
            )
            return {"success": False, "status": "failed", "error": error, "teams_id": log_doc["teams_id"]}

        await db["teams_logs"].update_one(
            {"teams_id": log_doc["teams_id"]},
            {"$set": {
                "status": "sent",
                "sent_at": utc_now(),
                "response_status": response.status_code,
                "response_text": response.text[:500],
                "updated_at": utc_now(),
            }},
        )
        return {"success": True, "status": "sent", "teams_id": log_doc["teams_id"]}
    except Exception as exc:
        await db["teams_logs"].update_one(
            {"teams_id": log_doc["teams_id"]},
            {"$set": {"status": "failed", "error_message": str(exc), "updated_at": utc_now()}},
        )
        return {"success": False, "status": "failed", "error": str(exc), "teams_id": log_doc["teams_id"]}
