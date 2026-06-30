"""Microsoft Teams Adaptive Card notifications."""
import uuid
import logging
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import quote

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

STAGE_META = {
    "pipeline_message_sent": {"title": "Pipeline Message Sent", "stage": "Trainer Pipeline", "color": "Accent"},
    "client_message_sent": {"title": "Client Message Sent", "stage": "Client Communication", "color": "Accent"},
    "new_requirement_created": {"title": "New Requirement Created", "stage": "New Requirement", "color": "Accent"},
    "trainer_contacted": {"title": "Trainer Contacted", "stage": "Trainer Contacted", "color": "Accent"},
    "trainer_replied": {"title": "Trainer Replied", "stage": "Trainer Replied", "color": "Good"},
    "interview_scheduled": {"title": "Interview Scheduled", "stage": "Interview Scheduled", "color": "Warning"},
    "trainer_selected": {"title": "Trainer Selected", "stage": "Trainer Selected", "color": "Good"},
    "po_generated": {"title": "Purchase Order Generated", "stage": "PO Generated", "color": "Accent"},
}

MAIL_TYPE_LABELS = {
    "first": "Mail 1 - First Contact",
    "mail1": "Mail 1 - First Contact",
    "mail1_reminder": "Mail 1 Reminder",
    "mail2": "Mail 2 - Details Request",
    "mail3": "Mail 3 - Slot Booking",
    "mail4": "Mail 4 - Interview Schedule",
    "mail5_ok": "Mail 5 - Selection",
    "mail5_no": "Mail 5 - Rejection",
    "mail6_toc": "Mail 6 - ToC / Agenda",
    "mail7_confirm": "Mail 7 - Training Confirmation",
}


def _t(v: Any, fb: str = "-") -> str:
    s = str(v or "").strip()
    return s if s else fb


def _ts(v=None) -> str:
    dt = v if isinstance(v, datetime) else datetime.utcnow()
    return f"{dt.replace(microsecond=0).isoformat()}Z"


def _clip(v: Any, n: int = 900) -> str:
    s = " ".join(str(v or "").split())
    return s if len(s) <= n else f"{s[:n-3]}..."


def _shortlist_url(req_id: str = "") -> str:
    base = settings.FRONTEND_URL.rstrip("/")
    if not base:
        return ""
    url = f"{base}/shortlist"
    return f"{url}?requirement_id={quote(req_id)}" if req_id else url


async def _get_webhook(db) -> str:
    doc = await db["admin_settings"].find_one({"settings_id": "default"}, {"_id": 0, "teamsCfg": 1}) or {}
    return (doc.get("teamsCfg") or {}).get("webhookUrl") or settings.TEAMS_WEBHOOK_URL or ""


def build_card(
    stage: str,
    trainer_name: str,
    technology: str,
    requirement_id: str,
    timestamp=None,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    meta = STAGE_META.get(stage, {"title": "Pipeline Update", "stage": stage, "color": "Accent"})
    context = context or {}
    link = _shortlist_url(requirement_id)
    mail_type = str(context.get("mail_type") or "")
    subject = str(context.get("subject") or "")
    body = str(context.get("body") or context.get("message") or "")
    recipient_type = str(context.get("recipient_type") or "")

    facts = [
        {"title": "Client" if recipient_type.lower() == "client" else "Trainer", "value": _t(trainer_name)},
        {"title": "Technology", "value": _t(technology, "Training")},
        {"title": "Requirement", "value": _t(requirement_id)},
        {"title": "Current Stage", "value": _t(meta["stage"])},
        {"title": "Timestamp", "value": _ts(timestamp)},
    ]
    if mail_type:
        facts.insert(3, {"title": "Message Type", "value": MAIL_TYPE_LABELS.get(mail_type, mail_type)})
    if context.get("to_email"):
        facts.append({"title": "Email", "value": context["to_email"]})
    if context.get("to_phone"):
        facts.append({"title": "WhatsApp / Phone", "value": context["to_phone"]})

    card_body = [
        {"type": "TextBlock", "text": meta["title"], "weight": "Bolder", "size": "Medium", "color": meta["color"], "wrap": True},
        {"type": "FactSet", "facts": facts},
    ]
    if subject:
        card_body.append({"type": "TextBlock", "text": f"Subject: {_clip(subject, 180)}", "weight": "Bolder", "wrap": True, "spacing": "Medium"})
    if body:
        card_body.append({"type": "TextBlock", "text": _clip(body, 4500), "wrap": True, "spacing": "Small"})

    card: Dict[str, Any] = {
        "$schema": "https://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": card_body,
    }
    if link:
        card["actions"] = [{"type": "Action.OpenUrl", "title": "Open Shortlist", "url": link}]
    return card


async def send_teams_notification(
    db,
    *,
    stage: str,
    trainer_name: str = "",
    requirement_id: str = "",
    technology: str = "",
    timestamp=None,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    webhook = await _get_webhook(db)
    if not webhook:
        return {"success": True, "status": "skipped", "reason": "No webhook configured"}

    card = build_card(stage, trainer_name, technology, requirement_id, timestamp, context)
    payload = {
        "type": "message",
        "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None, "content": card}],
    }
    now = datetime.utcnow()
    log_doc = {
        "teams_id": f"TEAMS-{uuid.uuid4().hex[:10].upper()}",
        "event_type": stage,
        "status": "queued",
        "trainer_name": trainer_name,
        "requirement_id": requirement_id,
        "technology": technology,
        "payload": payload,
        "context": context or {},
        "created_at": now,
        "updated_at": now,
    }
    await db["teams_logs"].insert_one(log_doc)

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(webhook, json=payload)
        if resp.status_code >= 400:
            err = resp.text[:500]
            await db["teams_logs"].update_one(
                {"teams_id": log_doc["teams_id"]},
                {"$set": {"status": "failed", "error_message": err, "updated_at": datetime.utcnow()}},
            )
            return {"success": False, "status": "failed", "error": err, "teams_id": log_doc["teams_id"]}
        await db["teams_logs"].update_one(
            {"teams_id": log_doc["teams_id"]},
            {"$set": {"status": "sent", "sent_at": datetime.utcnow(), "response_status": resp.status_code, "updated_at": datetime.utcnow()}},
        )
        return {"success": True, "status": "sent", "teams_id": log_doc["teams_id"]}
    except Exception as exc:
        await db["teams_logs"].update_one(
            {"teams_id": log_doc["teams_id"]},
            {"$set": {"status": "failed", "error_message": str(exc), "updated_at": datetime.utcnow()}},
        )
        return {"success": False, "status": "failed", "error": str(exc), "teams_id": log_doc["teams_id"]}
