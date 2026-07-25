"""Trainer automation pipeline — tick, send single mail, status."""
import logging
from datetime import datetime
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.config import get_settings
from app.database import get_db

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()

EMAIL_SVC = settings.EMAIL_SERVICE_URL.rstrip("/")
NOTIF_SVC = settings.NOTIFICATION_SERVICE_URL.rstrip("/")

PIPELINE_STAGES = ["mail1", "mail1_reminder", "mail2", "mail3", "mail4", "mail5_ok", "mail5_no", "mail6_toc", "mail7_confirm"]


class SendAutomationMailRequest(BaseModel):
    trainer_email: Optional[str] = ""
    trainer_name: Optional[str] = ""
    mail_type: str
    subject: Optional[str] = ""
    body: Optional[str] = ""
    requirement_id: Optional[str] = ""
    technology: Optional[str] = ""
    domain: Optional[str] = ""
    duration: Optional[str] = ""
    mode: Optional[str] = ""
    participants: Optional[str] = ""
    client_name: Optional[str] = ""
    slots: Optional[str] = ""
    date_time: Optional[str] = ""
    platform: Optional[str] = ""
    interview_link: Optional[str] = ""
    training_date: Optional[str] = ""
    venue: Optional[str] = ""
    contact_name: Optional[str] = ""
    contact_phone: Optional[str] = ""
    contact_email: Optional[str] = ""
    message: Optional[str] = ""
    smtp_config: Optional[Dict[str, Any]] = None


class PipelineTickRequest(BaseModel):
    requirement_id: Optional[str] = ""
    force_stage: Optional[str] = None


@router.get("/{trainer_id}/automation-status")
async def get_automation_status(trainer_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Return the current pipeline stage for a trainer across all requirements."""
    logs = await (
        db["email_logs"]
        .find({"trainer_id": trainer_id}, {"_id": 0, "mail_type": 1, "requirement_id": 1, "status": 1, "sent_at": 1})
        .sort("created_at", -1)
        .to_list(50)
    )
    by_req: Dict[str, Any] = {}
    for log in logs:
        req_id = log.get("requirement_id", "general")
        if req_id not in by_req:
            by_req[req_id] = {"latest_stage": log.get("mail_type"), "emails": []}
        by_req[req_id]["emails"].append(log)

    return {"success": True, "trainer_id": trainer_id, "pipeline": by_req}


@router.get("/{trainer_id}/conversation-thread")
async def get_conversation_thread(trainer_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Return full email thread for a trainer."""
    cursor = (
        db["email_logs"]
        .find({"trainer_id": trainer_id}, {"_id": 0})
        .sort("created_at", 1)
        .limit(200)
    )
    items = [d async for d in cursor]
    return {"success": True, "trainer_id": trainer_id, "thread": items, "count": len(items)}


@router.post("/{trainer_id}/send-automation-mail")
async def send_automation_mail(
    trainer_id: str,
    payload: SendAutomationMailRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Send a specific pipeline stage email to a trainer."""
    trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0}) or {}
    email = payload.trainer_email or trainer.get("email", "")
    name = payload.trainer_name or trainer.get("name", "Trainer")

    if not email:
        raise HTTPException(400, "No email address found for trainer")

    # Compose body via email-service templates if no explicit body
    body = payload.body
    subject = payload.subject
    technology = payload.technology or payload.domain or "Training"
    if not body:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = None
                base_template_payload = {
                    "name": name,
                    "technology": technology,
                    "requirement_id": payload.requirement_id or "",
                    "client_name": payload.client_name or "",
                }
                if payload.mail_type in ("mail1", "first"):
                    r = await client.post(
                        f"{EMAIL_SVC}/api/v1/email/templates/shortlist-first",
                        json={
                            "trainer_name": name,
                            "domain": technology,
                            "duration": payload.duration or "",
                            "mode": payload.mode or "",
                            "participants": payload.participants or "",
                        },
                        headers={"X-INTERNAL-TOKEN": settings.INTERNAL_SERVICE_TOKEN},
                    )
                elif payload.mail_type in ("mail2", "mail2_followup"):
                    tmpl_name = "mail2" if payload.mail_type == "mail2" else "mail2-followup"
                    r = await client.post(
                        f"{EMAIL_SVC}/api/v1/email/templates/{tmpl_name}",
                        json=base_template_payload,
                        headers={"X-INTERNAL-TOKEN": settings.INTERNAL_SERVICE_TOKEN},
                    )
                elif payload.mail_type in ("mail3", "mail3_slot_booking"):
                    r = await client.post(
                        f"{EMAIL_SVC}/api/v1/email/templates/mail3-slot-booking",
                        json=base_template_payload,
                        headers={"X-INTERNAL-TOKEN": settings.INTERNAL_SERVICE_TOKEN},
                    )
                elif payload.mail_type in ("mail3_slot_followup", "mail3_too_few", "mail3_too_few_slots"):
                    r = await client.post(
                        f"{EMAIL_SVC}/api/v1/email/templates/mail3-too-few",
                        json=base_template_payload,
                        headers={"X-INTERNAL-TOKEN": settings.INTERNAL_SERVICE_TOKEN},
                    )
                elif payload.mail_type in ("mail3_too_many", "mail3_too_many_slots"):
                    r = await client.post(
                        f"{EMAIL_SVC}/api/v1/email/templates/mail3-too-many",
                        json=base_template_payload,
                        headers={"X-INTERNAL-TOKEN": settings.INTERNAL_SERVICE_TOKEN},
                    )
                elif payload.mail_type == "mail4":
                    r = await client.post(
                        f"{EMAIL_SVC}/api/v1/email/templates/interview",
                        json={
                            "trainer_name": name,
                            "technology": technology,
                            "req_id": payload.requirement_id or "",
                            "interview_date": payload.date_time or "",
                            "interview_link": payload.interview_link or "",
                        },
                        headers={"X-INTERNAL-TOKEN": settings.INTERNAL_SERVICE_TOKEN},
                    )
                elif payload.mail_type in ("mail5", "mail5_ok", "mail5_selection"):
                    r = await client.post(
                        f"{EMAIL_SVC}/api/v1/email/templates/mail5-selection",
                        json=base_template_payload,
                        headers={"X-INTERNAL-TOKEN": settings.INTERNAL_SERVICE_TOKEN},
                    )
                elif payload.mail_type in ("mail5_no", "mail5_rejection"):
                    r = await client.post(
                        f"{EMAIL_SVC}/api/v1/email/templates/mail5-rejection",
                        json=base_template_payload,
                        headers={"X-INTERNAL-TOKEN": settings.INTERNAL_SERVICE_TOKEN},
                    )
                elif payload.mail_type in ("mail6", "mail6_toc", "toc-request"):
                    r = await client.post(
                        f"{EMAIL_SVC}/api/v1/email/templates/mail6-toc-request",
                        json=base_template_payload,
                        headers={"X-INTERNAL-TOKEN": settings.INTERNAL_SERVICE_TOKEN},
                    )
                elif payload.mail_type in ("mail7", "mail7_confirm", "training_confirmation"):
                    r = await client.post(
                        f"{EMAIL_SVC}/api/v1/email/templates/mail7-training-confirmation",
                        json=base_template_payload,
                        headers={"X-INTERNAL-TOKEN": settings.INTERNAL_SERVICE_TOKEN},
                    )
                elif payload.mail_type in ("mail1_reminder",):
                    r = await client.post(
                        f"{EMAIL_SVC}/api/v1/email/templates/retry",
                        json={"trainer_name": name, "technology": technology, "req_id": payload.requirement_id or ""},
                        headers={"X-INTERNAL-TOKEN": settings.INTERNAL_SERVICE_TOKEN},
                    )
            if r and r.status_code < 400:
                tmpl = r.json()
                body = tmpl.get("body", "")
                subject = subject or tmpl.get("subject", "")
        except Exception as exc:
            logger.warning("Template fetch failed, using fallback: %s", exc)

    if not body:
        from_name = getattr(settings, "FROM_NAME", None) or "TrainerSync Team"
        from_email = getattr(settings, "FROM_EMAIL", None) or "sujithaofficial585@gmail.com"
        body = (
            f"Dear {name},\n\n"
            "We have a training requirement matching your profile. Please revert if interested.\n\n"
            f"Regards,\n{from_name}\n{from_email}"
        )
    if payload.message and payload.message.strip():
        body = f"{payload.message.strip()}\n\n{body}"
    if not subject:
        subject = f"Training Requirement - {technology or payload.requirement_id or 'Opportunity'}"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{EMAIL_SVC}/api/v1/email/send", json={
                "to": email, "subject": subject, "body": body,
                "mail_type": payload.mail_type, "trainer_id": trainer_id,
                "trainer_name": name,
                "requirement_id": payload.requirement_id,
                "smtp_config": payload.smtp_config,
            })
        success = r.status_code < 400
        result = r.json() if r.content else {}
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc

    if not success:
        raise HTTPException(502, "Email delivery failed")

    # Update shortlist stage
    if payload.requirement_id:
        now = datetime.utcnow()
        await db["shortlists"].update_one(
            {"requirement_id": payload.requirement_id, "top_trainers.trainer_id": trainer_id},
            {"$set": {
                "top_trainers.$.pipeline_status": payload.mail_type,
                "top_trainers.$.last_mail_type": payload.mail_type,
                "top_trainers.$.last_mailed_at": now,
            }},
        )

    return {"success": True, "trainer_id": trainer_id, "mail_type": payload.mail_type, "sent_to": email}


@router.post("/{trainer_id}/automation-pipeline/tick")
async def automation_pipeline_tick(
    trainer_id: str,
    payload: PipelineTickRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Advance a trainer to the next pipeline stage."""
    trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0}) or {}
    if not trainer:
        raise HTTPException(404, "Trainer not found")

    # Find current stage from email logs
    latest_log = await db["email_logs"].find_one(
        {"trainer_id": trainer_id, "requirement_id": payload.requirement_id or {"$exists": True}},
        {"_id": 0, "mail_type": 1},
        sort=[("created_at", -1)],
    )
    current_stage = (latest_log or {}).get("mail_type") or "none"
    if payload.force_stage:
        next_stage = payload.force_stage
    else:
        try:
            idx = PIPELINE_STAGES.index(current_stage)
            next_stage = PIPELINE_STAGES[idx + 1] if idx + 1 < len(PIPELINE_STAGES) else current_stage
        except ValueError:
            next_stage = PIPELINE_STAGES[0]

    return {
        "success": True,
        "trainer_id": trainer_id,
        "current_stage": current_stage,
        "next_stage": next_stage,
        "message": f"Ready to send {next_stage}. Call /send-automation-mail with mail_type={next_stage}",
    }


@router.post("/{trainer_id}/request-resume")
async def request_resume(
    trainer_id: str,
    requirement_id: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Send a resume request email to a trainer."""
    trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0}) or {}
    email = trainer.get("email", "")
    name = trainer.get("name", "Trainer")

    if not email:
        raise HTTPException(400, "Trainer email not found")

    body = (
        f"Dear {name},\n\n"
        "We came across your profile and would like to consider you for a training assignment.\n\n"
        "Could you please share your updated trainer profile/resume at your earliest convenience?\n\n"
        "Regards,\nTrainerSync Team"
    )
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(f"{EMAIL_SVC}/api/v1/email/send", json={
                "to": email, "subject": "Profile / Resume Request — TrainerSync",
                "body": body, "mail_type": "resume_request",
                "trainer_id": trainer_id, "requirement_id": requirement_id or "",
            })
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc

    return {"success": True, "trainer_id": trainer_id, "sent_to": email}
