"""Client inbox management — approve, reject, regenerate-reply."""
import logging
import uuid
from datetime import datetime, time
from email.utils import parseaddr
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.database import get_db
from app.gmail_client import send_email_async

router = APIRouter()
logger = logging.getLogger(__name__)

PENDING_STATUSES = ["pending_approval", "pending_review", "needs_manual_review"]
HIDDEN_DEFAULT_STATUSES = ["spam", "ignored"]
HIDDEN_DEFAULT_SENDER_REGEX = (
    r"noreply|no-reply|donotreply|postmaster|newsletter|updates-noreply|"
    r"recommendationnc|onlinecourses|@linkedin\.com$|@naukri\.com$|"
    r"@alison\.com$|@reliancedigital\.in$|@nptel\.iitm\.ac\.in$"
)


def _status_filter(status: Optional[str]) -> Dict[str, Any]:
    if not status or status == "all":
        return {
            "$and": [
                {"status": {"$nin": HIDDEN_DEFAULT_STATUSES}},
                {"reply_status": {"$nin": HIDDEN_DEFAULT_STATUSES}},
                {"$nor": [{"from_email": {"$regex": HIDDEN_DEFAULT_SENDER_REGEX, "$options": "i"}}]},
            ],
        }
    statuses = PENDING_STATUSES if status == "pending_approval" else [status]
    return {
        "$or": [
            {"status": {"$in": statuses}},
            {"reply_status": {"$in": statuses}},
        ],
    }


def _count_status_query(statuses: List[str]) -> Dict[str, Any]:
    return {
        "$or": [
            {"status": {"$in": statuses}},
            {"reply_status": {"$in": statuses}},
        ],
    }


def _normalise_item_status(doc: Dict[str, Any]) -> Dict[str, Any]:
    raw_status = doc.get("status") or ""
    effective = doc.get("reply_status") or raw_status or "pending_approval"
    if effective in ("pending_review", "needs_manual_review"):
        effective = "pending_approval"
    if raw_status and raw_status != effective:
        doc["raw_status"] = raw_status
    doc["status"] = effective
    return doc


def _email_address(value: Any) -> str:
    return (parseaddr(str(value or ""))[1] or str(value or "")).strip().lower()


def _current_inbound_message_id(doc: Dict[str, Any]) -> str:
    return str(doc.get("latest_gmail_message_id") or doc.get("gmail_message_id") or "").strip()


async def _smtp_config(db: AsyncIOMotorDatabase) -> Optional[Dict[str, Any]]:
    from app.routes.inbox import _load_admin_settings

    settings_doc = await _load_admin_settings(db)
    return settings_doc.get("emailCfg") or None


class ApproveRequest(BaseModel):
    send_now: bool = True
    override_body: Optional[str] = None
    body: Optional[str] = None
    subject: Optional[str] = None


class RegenerateRequest(BaseModel):
    hint: Optional[str] = ""
    instruction: Optional[str] = ""


class ProcessPendingRequest(BaseModel):
    limit: int = 100


@router.get("")
async def list_inbox_emails(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    page: int = Query(1, ge=1),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    query = _status_filter(status)

    total = await db["client_emails"].count_documents(query)
    skip = (page - 1) * limit
    cursor = (
        db["client_emails"]
        .find(query, {"_id": 0, "raw_body": 0})
        .sort("created_at", -1)
        .skip(skip)
        .limit(limit)
    )
    items = [_normalise_item_status(d) async for d in cursor]
    today_start = datetime.combine(datetime.utcnow().date(), time.min)
    status_count = db["client_emails"].count_documents
    return {
        "success": True,
        "total": total,
        "page": page,
        "page_size": limit,
        "pages": max(1, (total + limit - 1) // limit),
        "emails": items,
        "stats": {
            "today": await status_count({"created_at": {"$gte": today_start}}),
            "pending_approval": await status_count(_count_status_query(PENDING_STATUSES)),
            "auto_sent": await status_count(_count_status_query(["auto_sent"])),
            "sent": await status_count(_count_status_query(["sent"])),
            "approved": await status_count(_count_status_query(["approved"])),
            "rejected": await status_count(_count_status_query(["rejected"])),
            "spam": await status_count(_count_status_query(["spam"])),
            "office_replies": await status_count(_count_status_query(["office_reply", "routed_to_trainer_reply"])),
            "requirements_created": await status_count({"requirement_id": {"$exists": True, "$nin": ["", None]}}),
            "total": await status_count({}),
        },
    }


@router.post("/process-pending")
async def process_pending_inbox_emails(
    payload: ProcessPendingRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Re-run requirement extraction and trainer automation for stored client emails."""
    from app.routes.inbox import _process_pending_client_emails

    return {"success": True, **await _process_pending_client_emails(db, payload.limit)}


@router.post("/{email_id}/create-requirement")
async def create_requirement_from_inbox_email(
    email_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Create a requirement and shortlist from a single inbox email."""
    from app.routes.inbox import _process_client_requirement_email

    doc = await db["client_emails"].find_one({"email_id": email_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Inbox email not found")
    return {"success": True, **await _process_client_requirement_email(db, doc, force_new_requirement=True)}


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

    reply_body = payload.override_body or payload.body or doc.get("ai_reply") or doc.get("draft_reply") or ""
    if not reply_body:
        raise HTTPException(400, "No reply body available to approve")

    now = datetime.utcnow()
    update: Dict[str, Any] = {
        "approved": True,
        "approved_at": now,
        "reply_status": "approved",
        "status": "approved",
        "updated_at": now,
    }

    if payload.send_now:
        to = _email_address(doc.get("from_email", ""))
        if not to:
            raise HTTPException(400, "No recipient address available")
        subject = payload.subject or doc.get("subject", "Re: Training Requirement")
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        source_gmail_message_id = _current_inbound_message_id(doc)
        duplicate_markers = [{"source_email_id": email_id}]
        if source_gmail_message_id:
            duplicate_markers.append({"source_gmail_message_id": source_gmail_message_id})
        existing_sent_log = await db["email_logs"].find_one(
            {
                "mail_type": "client_reply",
                "status": "sent",
                "$and": [
                    {"$or": [{"recipient": to}, {"to_email": to}]},
                    {"$or": [*duplicate_markers, {"subject": subject}]},
                ],
            },
            {"_id": 0, "sent_at": 1, "created_at": 1},
            sort=[("created_at", -1)],
        )
        if existing_sent_log:
            success, error = True, ""
            sent_at = existing_sent_log.get("sent_at") or existing_sent_log.get("created_at") or now
        else:
            success, error = await send_email_async(
                to=to,
                subject=subject,
                body=reply_body,
                smtp_config=await _smtp_config(db),
            )
            sent_at = now
        if success:
            update["reply_sent"] = True
            update["reply_sent_at"] = sent_at
            update["reply_sent_for_message_id"] = source_gmail_message_id
            update["reply_status"] = "sent"
            update["status"] = "sent"
            # Log outbound reply
            if not existing_sent_log:
                await db["email_logs"].insert_one({
                    "email_id": f"RPL-{uuid.uuid4().hex[:10].upper()}",
                    "direction": "outbound",
                    "recipient": to,
                    "to_email": to,
                    "subject": subject,
                    "body": reply_body,
                    "body_snippet": reply_body[:300],
                    "status": "sent",
                    "mail_type": "client_reply",
                    "requirement_id": doc.get("requirement_id"),
                    "source_email_id": email_id,
                    "source_gmail_message_id": source_gmail_message_id,
                    "sent_at": now,
                    "created_at": now,
                    "updated_at": now,
                })
            if doc.get("pending_trainer_automation") or doc.get("client_authorized_trainer_search"):
                try:
                    from app.routes.inbox import _start_trainer_search_after_client_reply

                    automation_update = await _start_trainer_search_after_client_reply(db, doc)
                    update.update(automation_update)
                except Exception as exc:
                    logger.exception("Trainer automation failed after client reply for %s", email_id)
                    update.update({
                        "status": "trainer_email_failed",
                        "trainer_automation_status": "failed",
                        "trainer_automation_error": str(exc),
                        "trainer_automation_failed_at": now,
                    })
        else:
            update["reply_status"] = "send_failed"
            update["status"] = "send_failed"
            update["reply_sent"] = False
            update["reply_error"] = error

    await db["client_emails"].update_one({"email_id": email_id}, {"$set": update})
    return {
        "success": True,
        "email_id": email_id,
        "status": update["status"],
        "reply_status": update["reply_status"],
        "trainer_automation_status": update.get("trainer_automation_status"),
        "mail_automation": update.get("mail_automation"),
    }


@router.post("/{email_id}/reject")
async def reject_inbox_reply(
    email_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Reject a pending auto-generated reply (marks it as discarded)."""
    result = await db["client_emails"].update_one(
        {"email_id": email_id},
        {"$set": {"status": "rejected", "reply_status": "rejected", "approved": False, "updated_at": datetime.utcnow()}},
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
    hint = payload.hint or payload.instruction or ""

    new_reply = await _ai_draft_reply(subject=subject, body=body, hint=hint)

    now = datetime.utcnow()
    generated_reply = {
        "subject": f"Re: {subject}" if subject and not subject.lower().startswith("re:") else subject,
        "body": new_reply,
    }
    await db["client_emails"].update_one(
        {"email_id": email_id},
        {"$set": {
            "ai_reply": new_reply,
            "draft_reply": new_reply,
            "generated_reply": generated_reply,
            "status": "pending_approval",
            "reply_status": "pending_review",
            "regenerated_at": now,
            "updated_at": now,
        }},
    )
    return {"success": True, "email_id": email_id, "reply": new_reply, "generated_reply": generated_reply}


def _client_auto_reply_template() -> str:
    return (
        "Dear Client,\n\n"
        "Thank you for sharing your training requirement.\n\n"
        "To help us identify and recommend the most suitable trainers, kindly provide the following details:\n\n"
        "* Training duration\n"
        "* Preferred training dates\n"
        "* Daily training timings\n"
        "* Audience level (Beginner / Intermediate / Advanced)\n"
        "* Training mode (Online / Offline / Hybrid)\n"
        "* Budget or expected commercial charges per day/session\n\n"
        "Meanwhile, we will begin an initial trainer search based on the information currently available. "
        "Once we receive the above details, we will refine the shortlist and share the most relevant trainer profiles for your review.\n\n"
        "We look forward to your response.\n\n"
        "Best Regards,\n"
        "Recruitment Team\n"
        "Clahan Technologies"
    )


async def _ai_draft_reply(subject: str, body: str, hint: str = "") -> str:
    """Generate a client reply using Anthropic Claude (fallback: template)."""
    from app.config import get_settings
    cfg = get_settings()
    key = cfg.ANTHROPIC_API_KEY.strip() if hasattr(cfg, "ANTHROPIC_API_KEY") else ""
    if key:
        try:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=key)
            template = _client_auto_reply_template()
            prompt = (
                f"You are a professional training coordinator at {settings.FROM_NAME or 'TrainerSync'}. "
                f"Draft a helpful, concise reply to this client email using the exact template below whenever the client request is for training or a trainer requirement. "
                f"Preserve the wording exactly, except you may personalize the greeting if the client name is available.\n\n"
                f"Template:\n{template}\n\n"
                f"Subject: {subject}\nBody: {body[:2000]}"
                + (f"\n\nHint: {hint}" if hint else "")
                + "\n\nReturn only the reply body, no subject line."
            )
            model_name = getattr(cfg, "ANTHROPIC_MODEL", "claude-haiku-4-20250514") or "claude-haiku-4-20250514"
            msg = await client.messages.create(
                model=model_name,
                max_tokens=600,
                temperature=0.4,
                messages=[{"role": "user", "content": prompt}],
            )
            return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
        except Exception as exc:
            logger.warning("AI reply generation failed: %s", exc)

    # Fallback template
    return _client_auto_reply_template()
