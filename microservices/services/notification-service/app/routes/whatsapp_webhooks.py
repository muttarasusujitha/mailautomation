"""WhatsApp inbound/status webhooks — Twilio, Meta Cloud API, AiSensy."""
import hashlib
import hmac
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from motor.motor_asyncio import AsyncIOMotorDatabase

from shared.database.service import get_db
from app.config import get_settings

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()


# ── helpers ───────────────────────────────────────────────────────────────────

async def _get_cfg(db) -> Dict[str, Any]:
    doc = await db["admin_settings"].find_one({"settings_id": "default"}, {"_id": 0, "twilioCfg": 1}) or {}
    return doc.get("twilioCfg") or {}


async def _log_inbound(db, payload: Dict[str, Any]) -> None:
    now = datetime.utcnow()
    payload.update({"direction": "inbound", "created_at": now, "updated_at": now})
    await db["whatsapp_logs"].insert_one(payload)


def _verify_twilio_signature(cfg: Dict[str, Any], request_url: str, params: dict, signature: str) -> bool:
    auth_token = cfg.get("authToken") or settings.TWILIO_AUTH_TOKEN
    if not auth_token or not signature:
        return False
    try:
        from twilio.request_validator import RequestValidator
        v = RequestValidator(auth_token)
        return v.validate(request_url, params, signature)
    except Exception:
        return False


async def _require_twilio(request, db, data):
    cfg = await _get_cfg(db)
    base = settings.TWILIO_WEBHOOK_BASE_URL.rstrip("/")
    url = base + request.url.path if base else str(request.url)
    if base and request.url.query:
        url += "?" + request.url.query
    if not _verify_twilio_signature(cfg, url, data, request.headers.get("X-Twilio-Signature", "")):
        raise HTTPException(403, "Invalid webhook signature")


# ── Twilio inbound callback ───────────────────────────────────────────────────

@router.post("/inbound-callback")
async def twilio_inbound(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Receive inbound WhatsApp message from Twilio."""
    try:
        form = await request.form()
        data = dict(form)
    except Exception:
        data = await request.json()

    await _require_twilio(request, db, data)

    await _log_inbound(db, {
        "provider": "twilio",
        "event_type": "inbound",
        "from_number": data.get("From", ""),
        "to_number": data.get("To", ""),
        "body": data.get("Body", ""),
        "twilio_message_sid": data.get("MessageSid", ""),
        "num_media": int(data.get("NumMedia", 0)),
        "raw_payload": data,
    })
    # Return TwiML empty response
    return Response(
        content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
        media_type="text/xml",
    )


# ── Twilio status callback ────────────────────────────────────────────────────

@router.post("/status-callback")
async def twilio_status(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Receive delivery status update from Twilio."""
    try:
        form = await request.form()
        data = dict(form)
    except Exception:
        data = await request.json()

    await _require_twilio(request, db, data)
    sid = data.get("MessageSid", "")
    status = data.get("MessageStatus", "")
    now = datetime.utcnow()
    if sid:
        await db["whatsapp_logs"].update_one(
            {"twilio_sid": sid},
            {"$set": {"status": status, "delivery_updated_at": now, "updated_at": now}},
        )
    return Response(content="OK", media_type="text/plain")


# ── Meta Cloud API webhook ────────────────────────────────────────────────────

@router.get("/meta/webhook")
async def meta_webhook_verify(request: Request):
    """Respond to Meta webhook verification challenge."""
    params = dict(request.query_params)
    mode = params.get("hub.mode", "")
    token = params.get("hub.verify_token", "")
    challenge = params.get("hub.challenge", "")
    expected = settings.META_WEBHOOK_VERIFY_TOKEN if hasattr(settings, "META_WEBHOOK_VERIFY_TOKEN") else ""
    if mode == "subscribe" and expected and hmac.compare_digest(token, expected):
        return Response(content=challenge, media_type="text/plain")
    raise HTTPException(403, "Webhook verification failed")


@router.post("/meta/webhook")
async def meta_webhook_receive(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Receive inbound messages and status updates from Meta Cloud API."""
    raw_body = await request.body()
    secret = settings.META_APP_SECRET
    signature = request.headers.get("X-Hub-Signature-256", "")
    expected = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    if not secret or not hmac.compare_digest(signature, expected):
        raise HTTPException(403, "Invalid webhook signature")
    try:
        body = await request.json()
    except Exception:
        return Response(status_code=200)

    try:
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                # Group creation is asynchronous; Meta returns the invite link
                # in a group_lifecycle_update webhook rather than in the
                # create request response.
                if change.get("field") == "group_lifecycle_update":
                    for group in value.get("groups", []):
                        group_id = str(group.get("group_id") or "")
                        request_id = str(group.get("request_id") or "")
                        subject = str(group.get("subject") or "")
                        query = {"whatsapp_group_requested": True}
                        correlate = []
                        if group_id:
                            correlate.append({"whatsapp_group_id": group_id})
                        if request_id:
                            correlate.append({"whatsapp_group_request_id": request_id})
                        if subject:
                            correlate.append({"whatsapp_group_subject": subject})
                        if correlate:
                            query["$or"] = correlate
                            task = await db["offline_coordination_tasks"].find_one(query, {"_id": 0})
                            if task:
                                invite_link = str(group.get("invite_link") or "")
                                created = group.get("type") == "group_create" and bool(invite_link)
                                update = {
                                    "whatsapp_group_id": group_id or task.get("whatsapp_group_id", ""),
                                    "whatsapp_group_status": "invite_link_ready" if created else "staff_action_required",
                                    "whatsapp_group_webhook_at": datetime.utcnow(),
                                    "updated_at": datetime.utcnow(),
                                }
                                if invite_link:
                                    update["whatsapp_group_invite_link"] = invite_link
                                if group.get("errors"):
                                    update["whatsapp_group_error"] = str(group["errors"])[:500]
                                await db["offline_coordination_tasks"].update_one({"_id": task.get("task_id")}, {"$set": update})
                                if invite_link:
                                    await db["requirements"].update_one(
                                        {"requirement_id": task.get("requirement_id")},
                                        {"$set": {"offline_logistics.whatsapp_group_invite_link": invite_link, "offline_logistics.whatsapp_group_status": "invite_link_ready", "updated_at": datetime.utcnow()}},
                                    )
                # Inbound messages
                for msg in value.get("messages", []):
                    await _log_inbound(db, {
                        "provider": "meta",
                        "event_type": "inbound",
                        "from_number": msg.get("from", ""),
                        "body": (msg.get("text") or {}).get("body", ""),
                        "meta_message_id": msg.get("id", ""),
                        "meta_type": msg.get("type", ""),
                        "raw_payload": msg,
                    })
                # Status updates
                for status in value.get("statuses", []):
                    mid = status.get("id", "")
                    st = status.get("status", "")
                    if mid:
                        await db["whatsapp_logs"].update_one(
                            {"meta_message_id": mid},
                            {"$set": {"status": st, "updated_at": datetime.utcnow()}},
                        )
    except Exception as exc:
        logger.error("Meta webhook processing error: %s", exc)

    return Response(status_code=200)
