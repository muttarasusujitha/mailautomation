import uuid
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import quote

import httpx

from config import get_settings


STAGE_META = {
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
        dt = datetime.utcnow()
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
) -> Dict[str, Any]:
    meta = STAGE_META.get(stage, {"title": "Pipeline Update", "stage": stage, "color": "Accent"})
    link = shortlist_url(requirement_id, request_base_url)

    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
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
                    {"title": "Trainer", "value": _text(trainer_name)},
                    {"title": "Technology", "value": _text(technology, "Training")},
                    {"title": "Current Stage", "value": _text(meta["stage"])},
                    {"title": "Timestamp", "value": _timestamp(timestamp)},
                ],
            },
        ],
    }
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
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
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
                {"$set": {"status": "failed", "error_message": error, "updated_at": datetime.utcnow()}},
            )
            return {"success": False, "status": "failed", "error": error, "teams_id": log_doc["teams_id"]}

        await db["teams_logs"].update_one(
            {"teams_id": log_doc["teams_id"]},
            {"$set": {
                "status": "sent",
                "sent_at": datetime.utcnow(),
                "response_status": response.status_code,
                "response_text": response.text[:500],
                "updated_at": datetime.utcnow(),
            }},
        )
        return {"success": True, "status": "sent", "teams_id": log_doc["teams_id"]}
    except Exception as exc:
        await db["teams_logs"].update_one(
            {"teams_id": log_doc["teams_id"]},
            {"$set": {"status": "failed", "error_message": str(exc), "updated_at": datetime.utcnow()}},
        )
        return {"success": False, "status": "failed", "error": str(exc), "teams_id": log_doc["teams_id"]}
