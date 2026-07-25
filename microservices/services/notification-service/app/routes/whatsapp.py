from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel
from typing import Any, Dict, Optional

from app.database import get_db
from app.whatsapp import send_whatsapp, stage_label

router = APIRouter()


class SendWhatsAppRequest(BaseModel):
    to_number: str
    body: str
    event_type: str = "notification"
    recipient_type: str = "trainer"
    context: Optional[Dict[str, Any]] = None
    media_url: Optional[str] = ""


class PipelineWhatsAppRequest(BaseModel):
    trainer_phone: str
    trainer_name: str
    subject: str = ""
    body: str
    mail_type: str
    requirement_id: str = ""
    email_id: str = ""
    technology: str = ""


class InterviewReminderRequest(BaseModel):
    trainer_phone: str
    trainer_name: str
    requirement_id: str = ""
    technology: str = ""
    date_time: str = ""
    platform: str = "Online"
    interview_link: str = ""
    email_id: str = ""
    reminder: bool = False


@router.post("/send")
async def send_whatsapp_message(
    payload: SendWhatsAppRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    return await send_whatsapp(
        db,
        payload.to_number,
        payload.body,
        event_type=payload.event_type,
        recipient_type=payload.recipient_type,
        context=payload.context,
        media_url=payload.media_url or "",
    )


@router.post("/pipeline")
async def send_pipeline_message(
    payload: PipelineWhatsAppRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Send a stage-specific pipeline WhatsApp to a trainer."""
    from app.whatsapp import _plain_phone
    context = {
        "trainer_name": payload.trainer_name,
        "requirement_id": payload.requirement_id,
        "email_id": payload.email_id,
        "mail_type": payload.mail_type,
        "stage": stage_label(payload.mail_type),
        "subject": payload.subject,
        "technology": payload.technology,
        "template_source": "pipeline_whatsapp",
    }
    return await send_whatsapp(
        db,
        payload.trainer_phone,
        payload.body,
        event_type="trainer_pipeline_message",
        recipient_type="trainer",
        context=context,
    )


@router.post("/interview-reminder")
async def send_interview_reminder(
    payload: InterviewReminderRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    if payload.reminder:
        body = (
            f"Dear {payload.trainer_name or 'Trainer'},\n\n"
            f"This is a reminder for your {payload.technology or 'Training'} interview.\n\n"
            f"Date & Time: {payload.date_time or '[Date & Time]'}\n"
            f"Platform: {payload.platform or 'Online'}\n"
            f"Meeting Link: {payload.interview_link or '[Meeting Link]'}\n\n"
            "Please join on time.\n\nRegards,\nTrainerSync Team"
        )
    else:
        body = (
            f"Dear {payload.trainer_name or 'Trainer'},\n\n"
            f"Your interview has been scheduled.\n\n"
            f"Date & Time: {payload.date_time or '[Date & Time]'}\n"
            f"Platform: {payload.platform or 'Online'}\n"
            f"Meeting Link: {payload.interview_link or '[Meeting Link]'}\n\n"
            "Please join on time.\n\nRegards,\nTrainerSync Team"
        )
    return await send_whatsapp(
        db,
        payload.trainer_phone,
        body,
        event_type="interview_reminder" if payload.reminder else "interview_scheduled",
        recipient_type="trainer",
        context={
            "trainer_name": payload.trainer_name,
            "requirement_id": payload.requirement_id,
            "mail_type": "mail4",
            "date_time": payload.date_time,
            "platform": payload.platform,
            "interview_link": payload.interview_link,
        },
    )


@router.get("/logs")
async def get_whatsapp_logs(
    limit: int = 50,
    status: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    query: Dict[str, Any] = {}
    if status:
        query["status"] = status
    cursor = db["whatsapp_logs"].find(query, {"_id": 0}).limit(limit).sort("created_at", -1)
    items = [d async for d in cursor]
    return {"items": items, "count": len(items)}
