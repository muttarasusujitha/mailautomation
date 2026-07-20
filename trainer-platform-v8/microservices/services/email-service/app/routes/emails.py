"""Outbound email log management — list, retry, send-one, check-replies, schedule interview, send-client-slots."""
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.database import get_db
from app.gmail_client import send_email_async

router = APIRouter()
logger = logging.getLogger(__name__)


class SendOneRequest(BaseModel):
    to: str
    subject: str
    body: str
    mail_type: Optional[str] = None
    trainer_id: Optional[str] = None
    requirement_id: Optional[str] = None
    smtp_config: Optional[Dict[str, Any]] = None


class ScheduleInterviewRequest(BaseModel):
    trainer_name: str
    trainer_email: str
    technology: str
    requirement_id: Optional[str] = None
    interview_date: Optional[str] = ""
    interview_link: Optional[str] = ""
    slot_start: Optional[str] = ""
    slot_end: Optional[str] = ""
    smtp_config: Optional[Dict[str, Any]] = None


class SendClientSlotsRequest(BaseModel):
    requirement_id: str
    trainer_slots: List[Dict[str, Any]] = []
    client_email: Optional[str] = ""
    client_name: Optional[str] = ""
    smtp_config: Optional[Dict[str, Any]] = None


class CheckRepliesRequest(BaseModel):
    since_days: int = 7
    max_messages: int = 50
    from_emails: Optional[List[str]] = None


# ─── GET /emails ──────────────────────────────────────────────────────────────

@router.get("")
async def list_emails(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    direction: Optional[str] = None,
    mail_type: Optional[str] = None,
    trainer_id: Optional[str] = None,
    requirement_id: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    query: Dict[str, Any] = {}
    if direction:
        query["direction"] = direction
    if mail_type:
        query["mail_type"] = mail_type
    if trainer_id:
        query["trainer_id"] = trainer_id
    if requirement_id:
        query["requirement_id"] = requirement_id
    if status:
        query["status"] = status

    total = await db["email_logs"].count_documents(query)
    skip = (page - 1) * page_size
    cursor = (
        db["email_logs"]
        .find(query, {"_id": 0})
        .sort("created_at", -1)
        .skip(skip)
        .limit(page_size)
    )
    items = [d async for d in cursor]
    return {
        "success": True,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
        "emails": items,
    }


# ─── POST /emails/{email_id}/send-one ─────────────────────────────────────────

@router.post("/{email_id}/send-one")
async def send_one_email(
    email_id: str,
    payload: SendOneRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Send a single targeted email and log it."""
    success, error = await send_email_async(
        to=payload.to,
        subject=payload.subject,
        body=payload.body,
        smtp_config=payload.smtp_config,
    )
    now = datetime.utcnow()
    log = {
        "email_id": email_id,
        "direction": "outbound",
        "recipient": payload.to,
        "subject": payload.subject,
        "body_snippet": payload.body[:300],
        "status": "sent" if success else "failed",
        "mail_type": payload.mail_type,
        "trainer_id": payload.trainer_id,
        "requirement_id": payload.requirement_id,
        "sent_at": now if success else None,
        "error_message": error or "",
        "created_at": now,
        "updated_at": now,
    }
    await db["email_logs"].update_one(
        {"email_id": email_id},
        {"$set": log},
        upsert=True,
    )
    if not success:
        raise HTTPException(502, detail={"message": "Email delivery failed", "error": error})
    return {"success": True, "email_id": email_id, "sent_at": now.isoformat()}


# ─── POST /emails/{email_id}/retry ────────────────────────────────────────────

@router.post("/{email_id}/retry")
async def retry_email(
    email_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Re-send a previously failed outbound email."""
    doc = await db["email_logs"].find_one({"email_id": email_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Email log not found")
    if doc.get("status") == "sent":
        return {"success": True, "message": "Already sent", "email_id": email_id}

    success, error = await send_email_async(
        to=doc.get("recipient", ""),
        subject=doc.get("subject", ""),
        body=doc.get("body_snippet", ""),
    )
    now = datetime.utcnow()
    await db["email_logs"].update_one(
        {"email_id": email_id},
        {"$set": {
            "status": "sent" if success else "failed",
            "sent_at": now if success else None,
            "error_message": error or "",
            "retry_count": (doc.get("retry_count") or 0) + 1,
            "updated_at": now,
        }},
    )
    if not success:
        raise HTTPException(502, detail={"message": "Retry failed", "error": error})
    return {"success": True, "email_id": email_id, "sent_at": now.isoformat()}


# ─── POST /emails/check-replies ───────────────────────────────────────────────

@router.post("/check-replies")
async def check_email_replies(
    payload: CheckRepliesRequest,
    background_tasks: BackgroundTasks,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Poll Gmail inbox for replies, then process trainer/client automation."""
    from app.routes.inbox import _poll_and_store, _process_pending_client_emails

    async def _poll_then_process() -> None:
        await _poll_and_store(
            db,
            since_days=payload.since_days,
            max_messages=payload.max_messages,
            from_emails=payload.from_emails,
        )
        await _process_pending_client_emails(db, limit=payload.max_messages)

    background_tasks.add_task(_poll_then_process)
    return {"success": True, "message": "Reply check and automation processing triggered in background."}


# ─── POST /emails/{email_id}/schedule-interview ───────────────────────────────

@router.post("/{email_id}/schedule-interview")
async def schedule_interview(
    email_id: str,
    payload: ScheduleInterviewRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Send interview scheduling email to a trainer and update email log."""
    subject = f"Interview Slot Booking – {payload.technology}"
    link = payload.interview_link or ""
    date_line = f"\nScheduled: {payload.interview_date}" if payload.interview_date else ""
    body = (
        f"Dear {payload.trainer_name},\n\n"
        f"We are pleased to schedule your interview for the {payload.technology} training requirement.\n"
        f"{date_line}\n\n"
        f"Interview Details:\n"
        f"- Technology: {payload.technology}\n"
        f"- Duration: 30 minutes\n"
        + (f"- Join: {link}\n" if link else "")
        + "\nPlease confirm your availability.\n\nRegards,\nTrainerSync Team"
    )

    success, error = await send_email_async(
        to=payload.trainer_email,
        subject=subject,
        body=body,
        smtp_config=payload.smtp_config,
    )
    now = datetime.utcnow()
    update: Dict[str, Any] = {
        "interview_scheduled": True,
        "interview_mail_sent": success,
        "interview_date": payload.interview_date,
        "interview_link": link,
        "interview_slot_start": payload.slot_start,
        "interview_slot_end": payload.slot_end,
        "updated_at": now,
    }
    await db["email_logs"].update_one({"email_id": email_id}, {"$set": update})
    if not success:
        raise HTTPException(502, detail={"error": error})
    return {"success": True, "email_id": email_id, "interview_scheduled": True}


# ─── POST /emails/{email_id}/send-client-slots ────────────────────────────────

@router.post("/{email_id}/send-client-slots")
async def send_client_slots(
    email_id: str,
    payload: SendClientSlotsRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Email trainer availability slots to the client."""
    doc = await db["email_logs"].find_one({"email_id": email_id}, {"_id": 0})
    client_email = payload.client_email
    client_name = payload.client_name or "Client"
    if not client_email and payload.requirement_id:
        req = await db["requirements"].find_one({"requirement_id": payload.requirement_id}, {"_id": 0}) or {}
        client_email = req.get("client_email", "")
        client_name = req.get("client_name") or req.get("client_company") or client_name

    if not client_email:
        raise HTTPException(400, "client_email is required")

    slots_text = "\n".join(
        f"Slot {i+1}: {s.get('date_display', '')} {s.get('time_display', '')}"
        for i, s in enumerate(payload.trainer_slots)
    ) or "Trainer availability slots will be shared shortly."

    subject = f"Trainer Availability Slots – {payload.requirement_id or 'Training'}"
    body = (
        f"Dear {client_name},\n\n"
        "Please find below the trainer's available slots for your review:\n\n"
        f"{slots_text}\n\n"
        "Kindly confirm your preferred slot.\n\nRegards,\nTrainerSync Team"
    )
    success, error = await send_email_async(to=client_email, subject=subject, body=body)
    now = datetime.utcnow()
    await db["email_logs"].update_one(
        {"email_id": email_id},
        {"$set": {"client_slots_sent": success, "client_slots_sent_at": now, "updated_at": now}},
    )
    if not success:
        raise HTTPException(502, detail={"error": error})
    return {"success": True, "email_id": email_id, "client_email": client_email}
