"""Client update scheduling — retry sending deferred client update emails."""
import logging
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database import get_db
from app.gmail_client import send_email_async

router = APIRouter()
logger = logging.getLogger(__name__)


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
    to = doc.get("from_email", "")
    subject = doc.get("subject", "Re: Training Update")
    if not to:
        raise HTTPException(400, "No recipient address available")

    success, error = await send_email_async(to=to, subject=subject, body=reply_body)
    now = datetime.utcnow()
    await db["client_emails"].update_one(
        {"email_id": email_id},
        {"$set": {
            "reply_status": "sent" if success else "failed",
            "reply_sent": success,
            "reply_sent_at": now if success else None,
            "reply_error": error or "",
            "updated_at": now,
        }},
    )
    if not success:
        raise HTTPException(502, f"Send failed: {error}")
    return {"success": True, "email_id": email_id, "sent_to": to}
