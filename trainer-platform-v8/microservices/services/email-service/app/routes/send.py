"""Send email endpoints."""
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, EmailStr

from app.database import get_db
from app.gmail_client import is_send_quota_error, send_email_async

router = APIRouter()


class SendEmailRequest(BaseModel):
    to: EmailStr
    subject: str
    body: str
    smtp_config: Optional[Dict[str, Any]] = None
    tracking_url: Optional[str] = ""
    customer_id: Optional[str] = None
    requirement_id: Optional[str] = None
    mail_type: Optional[str] = None
    trainer_id: Optional[str] = None
    trainer_name: Optional[str] = None


class BulkEmailRequest(BaseModel):
    payloads: List[SendEmailRequest]
    smtp_config: Optional[Dict[str, Any]] = None


@router.post("/send")
async def send_single_email(
    payload: SendEmailRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    success, error = await send_email_async(
        to=payload.to,
        subject=payload.subject,
        body=payload.body,
        smtp_config=payload.smtp_config,
        tracking_url=payload.tracking_url or "",
    )
    now = datetime.utcnow()
    log = {
        "email_id": f"EML-{uuid.uuid4().hex[:10].upper()}",
        "direction": "outbound",
        "recipient": payload.to,
        "subject": payload.subject,
        "body_snippet": payload.body[:300],
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "customer_id": payload.customer_id,
        "requirement_id": payload.requirement_id,
        "mail_type": payload.mail_type,
        "trainer_id": payload.trainer_id,
        "trainer_name": payload.trainer_name,
        "sent_at": now if success else None,
        "created_at": now,
        "updated_at": now,
    }
    await db.email_logs.insert_one(log)
    log.pop("_id", None)

    if not success:
        raise HTTPException(502, detail={"message": "Email delivery failed", "error": error})
    return {"success": True, "email_id": log["email_id"], "sent_at": now}


@router.post("/send/bulk")
async def send_bulk_emails(
    payload: BulkEmailRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    import asyncio
    results = []
    for item in payload.payloads:
        cfg = item.smtp_config or payload.smtp_config
        success, error = await send_email_async(
            to=item.to,
            subject=item.subject,
            body=item.body,
            smtp_config=cfg,
            tracking_url=item.tracking_url or "",
        )
        now = datetime.utcnow()
        log = {
            "email_id": f"EML-{uuid.uuid4().hex[:10].upper()}",
            "direction": "outbound",
            "recipient": item.to,
            "subject": item.subject,
            "body_snippet": item.body[:300],
            "status": "sent" if success else "failed",
            "error_message": error if not success else "",
            "customer_id": item.customer_id,
            "requirement_id": item.requirement_id,
            "mail_type": item.mail_type,
            "trainer_id": item.trainer_id,
            "trainer_name": item.trainer_name,
            "sent_at": now if success else None,
            "created_at": now,
            "updated_at": now,
        }
        await db.email_logs.insert_one(log)
        log.pop("_id", None)
        quota_blocked = is_send_quota_error(error)
        results.append({
            "email_id": log["email_id"],
            "to": item.to,
            "success": success,
            "error": error,
            "quota_blocked": quota_blocked,
        })
        if quota_blocked:
            break
        if success:
            await asyncio.sleep(1.5)

    sent = sum(1 for r in results if r["success"])
    return {"total": len(results), "sent": sent, "failed": len(results) - sent, "results": results}
