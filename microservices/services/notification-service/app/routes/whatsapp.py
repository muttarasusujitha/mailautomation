from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel
from typing import Any, Dict, Optional

from shared.database.service import get_db
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


@router.post("/groups/offline/{requirement_id}")
async def create_offline_training_group(
    requirement_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Create the requested offline training group through Meta Groups API."""
    from datetime import datetime
    import httpx
    from app.whatsapp import META_GRAPH_API_BASE
    from app.config import get_settings

    task = await db["offline_coordination_tasks"].find_one(
        {"requirement_id": requirement_id}, {"_id": 0}, sort=[("created_at", -1)],
    ) or {}
    if not task or not task.get("whatsapp_group_requested"):
        return {"success": False, "status": "not_requested"}
    if task.get("whatsapp_group_id"):
        return {
            "success": True,
            "status": task.get("whatsapp_group_status", "created"),
            "group_id": task["whatsapp_group_id"],
            "invite_link": task.get("whatsapp_group_invite_link", ""),
        }

    settings = get_settings()
    admin = await db["admin_settings"].find_one({"settings_id": "default"}, {"_id": 0, "twilioCfg": 1}) or {}
    cfg = admin.get("twilioCfg") or {}
    provider = str(cfg.get("provider") or settings.WHATSAPP_PROVIDER).lower()
    token = cfg.get("metaAccessToken") or settings.META_WHATSAPP_ACCESS_TOKEN
    phone_id = cfg.get("metaPhoneNumberId") or settings.META_WHATSAPP_PHONE_NUMBER_ID
    if provider != "meta" or not token or not phone_id:
        await db["offline_coordination_tasks"].update_one(
            {"_id": task.get("task_id")},
            {"$set": {"whatsapp_group_status": "staff_action_required", "whatsapp_group_error": "Meta Cloud API credentials are not configured", "updated_at": datetime.utcnow()}},
        )
        return {"success": False, "status": "staff_action_required", "reason": "Meta Cloud API credentials are not configured"}

    version = cfg.get("metaApiVersion") or settings.META_GRAPH_API_VERSION or "v23.0"
    subject = f"Offline training {requirement_id}"[:128]
    now = datetime.utcnow()
    claimed = await db["offline_coordination_tasks"].update_one(
        {"_id": task.get("task_id"), "whatsapp_group_status": {"$nin": ["creating", "created", "invite_link_ready"]}},
        {"$set": {"whatsapp_group_status": "creating", "whatsapp_group_subject": subject, "whatsapp_group_create_started_at": now, "updated_at": now}},
    )
    if not claimed.modified_count:
        latest = await db["offline_coordination_tasks"].find_one({"_id": task.get("task_id")}, {"_id": 0}) or task
        return {"success": bool(latest.get("whatsapp_group_id")), "status": latest.get("whatsapp_group_status", "creating"), "group_id": latest.get("whatsapp_group_id", ""), "invite_link": latest.get("whatsapp_group_invite_link", "")}

    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
    description = f"Offline training coordination for {requirement_id}. Selected trainer: {task.get('trainer_name') or 'Trainer'}."
    url = f"{META_GRAPH_API_BASE}/{version}/{phone_id}/groups"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                url,
                json={"messaging_product": "whatsapp", "subject": subject, "description": description, "join_approval_mode": "auto_approve"},
                headers={"Authorization": f"Bearer {token}"},
            )
        result = response.json() if response.content else {}
        if response.status_code >= 400:
            error = (result.get("error") or {}).get("message") or response.text
            await db["offline_coordination_tasks"].update_one({"_id": task.get("task_id")}, {"$set": {"whatsapp_group_status": "staff_action_required", "whatsapp_group_error": str(error)[:500], "updated_at": datetime.utcnow()}})
            return {"success": False, "status": "staff_action_required", "reason": str(error)[:500]}
        group_id = str(result.get("id") or result.get("group_id") or "")
        request_id = str(result.get("request_id") or "")
        await db["offline_coordination_tasks"].update_one({"_id": task.get("task_id")}, {"$set": {
            "whatsapp_group_id": group_id,
            "whatsapp_group_request_id": request_id,
            "whatsapp_group_status": "awaiting_invite_webhook",
            "whatsapp_group_created_at": datetime.utcnow(),
            "whatsapp_group_api_response": {key: value for key, value in result.items() if key not in {"access_token"}},
            "updated_at": datetime.utcnow(),
        }})
        await db["requirements"].update_one({"requirement_id": requirement_id}, {"$set": {"offline_logistics.whatsapp_group_status": "awaiting_invite_webhook", "updated_at": datetime.utcnow()}})
        return {"success": True, "status": "awaiting_invite_webhook", "group_id": group_id, "request_id": request_id}
    except Exception as exc:
        await db["offline_coordination_tasks"].update_one({"_id": task.get("task_id")}, {"$set": {"whatsapp_group_status": "staff_action_required", "whatsapp_group_error": str(exc)[:500], "updated_at": datetime.utcnow()}})
        return {"success": False, "status": "staff_action_required", "reason": str(exc)[:500]}
