"""WhatsApp inbound/status webhooks — Twilio, Meta Cloud API, AiSensy."""
import hashlib
import hmac
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database import get_db
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
    auth_token = cfg.get("authToken", "")
    if not auth_token:
        return True  # skip verification if not configured
    try:
        from twilio.request_validator import RequestValidator
        v = RequestValidator(auth_token)
        return v.validate(request_url, params, signature)
    except Exception:
        return True


# ── Twilio inbound callback ───────────────────────────────────────────────────

@router.post("/inbound-callback")
async def twilio_inbound(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Receive inbound WhatsApp message from Twilio."""
    try:
        form = await request.form()
        data = dict(form)
    except Exception:
        data = await request.json()

    cfg = await _get_cfg(db)
    sig = request.headers.get("X-Twilio-Signature", "")
    if sig and not _verify_twilio_signature(cfg, str(request.url), data, sig):
        logger.warning("Twilio signature mismatch for inbound webhook")

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
    if mode == "subscribe" and (not expected or token == expected):
        return Response(content=challenge, media_type="text/plain")
    raise HTTPException(403, "Webhook verification failed")


@router.post("/meta/webhook")
async def meta_webhook_receive(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Receive inbound messages and status updates from Meta Cloud API."""
    try:
        body = await request.json()
    except Exception:
        return Response(status_code=200)

    try:
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
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
