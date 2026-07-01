"""Gmail inbox polling and inbound email processing."""
import asyncio
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, BackgroundTasks
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.database import get_db
from app.gmail_client import check_imap_replies

router = APIRouter()


class PollRequest(BaseModel):
    since_days: int = 7
    max_messages: int = 50
    from_emails: Optional[list] = None


async def _process_and_store_replies(db, replies: list) -> int:
    """Persist inbound replies to email_logs collection, avoid duplicates."""
    stored = 0
    for reply in replies:
        msg_id_hdr = reply.get("message_id_header", "")
        if msg_id_hdr:
            existing = await db.email_logs.find_one({"gmail_message_id": msg_id_hdr})
            if existing:
                continue

        now = datetime.utcnow()
        doc = {
            "email_id": f"INB-{uuid.uuid4().hex[:10].upper()}",
            "direction": "inbound",
            "sender": reply.get("from_email"),
            "subject": reply.get("subject"),
            "body_snippet": (reply.get("body") or "")[:500],
            "gmail_message_id": msg_id_hdr,
            "in_reply_to": reply.get("in_reply_to"),
            "sentiment": reply.get("sentiment"),
            "action": reply.get("action"),
            "status": "received",
            "processed": False,
            "received_at": reply.get("received_at"),
            "created_at": now,
            "updated_at": now,
        }
        await db.email_logs.insert_one(doc)
        stored += 1
    return stored


async def _poll_and_store(db, since_days: int = 7, max_messages: int = 50, from_emails: Optional[list] = None) -> int:
    """Helper used by gmail routes to poll IMAP and persist replies.

    This function is imported and scheduled by `gmail.py` (background task)
    so it must be available at module import time.
    """
    loop = asyncio.get_event_loop()
    replies = await loop.run_in_executor(
        None,
        lambda: check_imap_replies(since_days=since_days, max_messages=max_messages, from_emails=from_emails),
    )
    stored = await _process_and_store_replies(db, replies)
    return stored


@router.post("/poll")
async def poll_inbox(
    payload: PollRequest,
    background_tasks: BackgroundTasks,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Trigger a Gmail IMAP poll. Processing runs in background."""
    async def _run():
        loop = asyncio.get_event_loop()
        replies = await loop.run_in_executor(
            None,
            lambda: check_imap_replies(
                since_days=payload.since_days,
                max_messages=payload.max_messages,
                from_emails=payload.from_emails,
            ),
        )
        await _process_and_store_replies(db, replies)

    background_tasks.add_task(_run)
    return {"message": "Inbox poll triggered", "since_days": payload.since_days}


@router.post("/poll/sync")
async def poll_inbox_sync(
    payload: PollRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Synchronous poll — waits for completion and returns counts."""
    loop = asyncio.get_event_loop()
    replies = await loop.run_in_executor(
        None,
        lambda: check_imap_replies(
            since_days=payload.since_days,
            max_messages=payload.max_messages,
            from_emails=payload.from_emails,
        ),
    )
    stored = await _process_and_store_replies(db, replies)
    return {"fetched": len(replies), "stored": stored}


@router.get("/unprocessed")
async def get_unprocessed(
    limit: int = 50,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Return inbound emails not yet processed by the pipeline."""
    cursor = db.email_logs.find(
        {"direction": "inbound", "processed": False},
        {"_id": 0},
    ).limit(limit).sort("created_at", 1)
    items = [d async for d in cursor]
    return {"items": items, "count": len(items)}


@router.patch("/{email_id}/mark-processed")
async def mark_processed(
    email_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    await db.email_logs.update_one(
        {"email_id": email_id},
        {"$set": {"processed": True, "processed_at": datetime.utcnow(), "updated_at": datetime.utcnow()}},
    )
    return {"message": "Marked as processed", "email_id": email_id}
