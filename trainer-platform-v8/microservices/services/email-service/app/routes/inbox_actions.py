"""Client inbox management — approve, reject, regenerate-reply."""
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.database import get_db
from app.gmail_client import send_email_async

router = APIRouter()
logger = logging.getLogger(__name__)


class ApproveRequest(BaseModel):
    send_now: bool = True
    override_body: Optional[str] = None


class RegenerateRequest(BaseModel):
    hint: Optional[str] = ""


@router.post("/{email_id}/approve")
async def approve_inbox_reply(
    email_id: str,
    payload: ApproveRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Approve a pending auto-generated client reply and optionally send it."""
    doc = await db["client_emails"].find_one({"email_id": email_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Inbox email not found")

    reply_body = payload.override_body or doc.get("ai_reply") or doc.get("draft_reply") or ""
    if not reply_body:
        raise HTTPException(400, "No reply body available to approve")

    now = datetime.utcnow()
    update: Dict[str, Any] = {
        "approved": True,
        "approved_at": now,
        "reply_status": "approved",
        "updated_at": now,
    }

    if payload.send_now:
        to = doc.get("from_email", "")
        subject = doc.get("subject", "Re: Training Requirement")
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        success, error = await send_email_async(to=to, subject=subject, body=reply_body)
        if success:
            update["reply_sent"] = True
            update["reply_sent_at"] = now
            update["reply_status"] = "sent"
            # Log outbound reply
            await db["email_logs"].insert_one({
                "email_id": f"RPL-{uuid.uuid4().hex[:10].upper()}",
                "direction": "outbound",
                "recipient": to,
                "subject": subject,
                "body_snippet": reply_body[:300],
                "status": "sent",
                "mail_type": "client_reply",
                "sent_at": now,
                "created_at": now,
                "updated_at": now,
            })
        else:
            update["reply_status"] = "send_failed"
            update["reply_error"] = error

    await db["client_emails"].update_one({"email_id": email_id}, {"$set": update})
    return {"success": True, "email_id": email_id, "reply_status": update["reply_status"]}


@router.post("/{email_id}/reject")
async def reject_inbox_reply(
    email_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Reject a pending auto-generated reply (marks it as discarded)."""
    result = await db["client_emails"].update_one(
        {"email_id": email_id},
        {"$set": {"reply_status": "rejected", "approved": False, "updated_at": datetime.utcnow()}},
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Inbox email not found")
    return {"success": True, "email_id": email_id, "reply_status": "rejected"}


@router.post("/{email_id}/regenerate-reply")
async def regenerate_reply(
    email_id: str,
    payload: RegenerateRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Re-generate an AI reply for a client email using Anthropic/Gemini."""
    doc = await db["client_emails"].find_one({"email_id": email_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Inbox email not found")

    body = doc.get("body") or doc.get("raw_body") or ""
    subject = doc.get("subject", "")
    hint = payload.hint or ""

    new_reply = await _ai_draft_reply(subject=subject, body=body, hint=hint)

    now = datetime.utcnow()
    await db["client_emails"].update_one(
        {"email_id": email_id},
        {"$set": {
            "ai_reply": new_reply,
            "draft_reply": new_reply,
            "reply_status": "pending_review",
            "regenerated_at": now,
            "updated_at": now,
        }},
    )
    return {"success": True, "email_id": email_id, "reply": new_reply}


async def _ai_draft_reply(subject: str, body: str, hint: str = "") -> str:
    """Generate a client reply using Anthropic Claude (fallback: template)."""
    from app.config import get_settings
    cfg = get_settings()
    key = cfg.ANTHROPIC_API_KEY.strip() if hasattr(cfg, "ANTHROPIC_API_KEY") else ""
    if key:
        try:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=key)
            prompt = (
                f"You are a professional training coordinator at TrainerSync. "
                f"Draft a helpful, concise reply to this client email.\n\n"
                f"Subject: {subject}\nBody: {body[:2000]}"
                + (f"\n\nHint: {hint}" if hint else "")
                + "\n\nReturn only the reply body, no subject line."
            )
            msg = await client.messages.create(
                model="claude-haiku-4-20250514",
                max_tokens=600,
                temperature=0.4,
                messages=[{"role": "user", "content": prompt}],
            )
            return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
        except Exception as exc:
            logger.warning("AI reply generation failed: %s", exc)

    # Fallback template
    return (
        "Dear Client,\n\n"
        "Thank you for your email. We have noted your requirement and will revert shortly "
        "with suitable trainer profiles and next steps.\n\n"
        "Regards,\nTrainerSync Team"
    )
