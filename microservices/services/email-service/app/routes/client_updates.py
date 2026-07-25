"""Client update scheduling — retry sending deferred client update emails."""
import logging
from datetime import datetime
from email.utils import parseaddr
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database import get_db
from app.gmail_client import send_email_async

router = APIRouter()
logger = logging.getLogger(__name__)


def _email_address(value: Any) -> str:
    return (parseaddr(str(value or ""))[1] or str(value or "")).strip().lower()


def _current_inbound_message_id(doc: Dict[str, Any]) -> str:
    return str(doc.get("latest_gmail_message_id") or doc.get("gmail_message_id") or "").strip()


async def _smtp_config(db: AsyncIOMotorDatabase) -> Dict[str, Any] | None:
    from app.routes.inbox import _load_admin_settings

    settings_doc = await _load_admin_settings(db)
    return settings_doc.get("emailCfg") or None


@router.get("")
async def list_client_updates(db: AsyncIOMotorDatabase = Depends(get_db)):
    """List pending client update emails that need to be sent."""
    cursor = db["client_emails"].find(
        {"reply_status": {"$in": ["pending_auto_send", "pending_review", "failed"]}},
        {"_id": 0, "raw_body": 0},
    ).sort("created_at", -1).limit(100)
    items = [d async for d in cursor]
    return {"success": True, "count": len(items), "updates": items}


@router.post("/{email_id}/retry-schedule")
async def retry_schedule_client_update(
    email_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Re-attempt sending a deferred client reply."""
    doc = await db["client_emails"].find_one({"email_id": email_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Client email not found")

    reply_body = doc.get("ai_reply") or doc.get("draft_reply") or ""
    to = _email_address(doc.get("from_email", ""))
    subject = doc.get("subject", "Re: Training Update")
    if subject and not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    if not to:
        raise HTTPException(400, "No recipient address available")
    if not reply_body:
        raise HTTPException(400, "No reply body available")

    success, error = await send_email_async(
        to=to,
        subject=subject,
        body=reply_body,
        smtp_config=await _smtp_config(db),
    )
    now = datetime.utcnow()
    await db["client_emails"].update_one(
        {"email_id": email_id},
        {"$set": {
            "reply_status": "sent" if success else "failed",
            "reply_sent": success,
            "reply_sent_at": now if success else None,
            "reply_sent_for_message_id": _current_inbound_message_id(doc) if success else doc.get("reply_sent_for_message_id"),
            "reply_error": error or "",
            "updated_at": now,
        }},
    )
    if not success:
        raise HTTPException(502, f"Send failed: {error}")
    return {"success": True, "email_id": email_id, "sent_to": to}
