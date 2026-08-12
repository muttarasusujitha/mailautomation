"""Trainer automation pipeline — tick, send single mail, status."""
import logging
from datetime import datetime
from typing import Any, Dict, Optional

import httpx
import re
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.config import get_settings
from shared.database.service import get_db

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()

EMAIL_SVC = settings.EMAIL_SERVICE_URL.rstrip("/")
NOTIF_SVC = settings.NOTIFICATION_SERVICE_URL.rstrip("/")

PIPELINE_STAGES = ["mail1", "mail1_reminder", "mail2", "mail3", "mail4", "mail5_ok", "mail5_no", "mail6_toc", "mail7_confirm"]


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _trainer_lookup(identifier: str) -> Dict[str, Any]:
    clauses = [{"trainer_id": identifier}]
    if ObjectId.is_valid(identifier):
        clauses.append({"_id": ObjectId(identifier)})
    return {"$or": clauses}


def _public_trainer_id(trainer: Dict[str, Any], fallback: str) -> str:
    return _clean_text(trainer.get("trainer_id")) or _clean_text(trainer.get("_id")) or fallback


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _clean_duration_text(value: Any) -> str:
    text = _clean_text(value)
    text = re.sub(r"(?i)^to\s+be\s*:?\s*(?=\d)", "", text).strip()
    return text


def _trainer_mail1_commercial_text(requirement: Dict[str, Any]) -> str:
    amount = None
    if requirement.get("budget_total") not in (None, "", []) and requirement.get("commercial_working_days") not in (None, "", [], 0):
        try:
            amount = (float(requirement.get("budget_total")) / float(requirement.get("commercial_working_days"))) * 0.70
        except (TypeError, ValueError, ZeroDivisionError):
            amount = None
    if amount in (None, "", []):
        amount = requirement.get("trainer_visible_budget_per_session") or requirement.get("trainer_requested_budget_per_session")
    if amount in (None, "", []):
        client_amount = (
            requirement.get("client_budget_per_day")
            or requirement.get("budget_per_day")
            or requirement.get("budget")
        )
        if client_amount in (None, "", []) and requirement.get("budget_total") not in (None, "", []):
            days = _safe_int(requirement.get("commercial_working_days"), 0)
            try:
                client_amount = float(requirement.get("budget_total")) / days if days else requirement.get("budget_total")
            except (TypeError, ValueError):
                client_amount = requirement.get("budget_total")
        try:
            amount = _safe_float(client_amount) * 0.70
        except (TypeError, ValueError):
            amount = None
    try:
        numeric = float(amount)
    except (TypeError, ValueError):
        return ""
    if numeric <= 0:
        return ""
    return f"INR {int(round(numeric)):,} per day/session, inclusive of TDS"


def _client_requirement_text(requirement: Dict[str, Any]) -> str:
    metadata = requirement.get("metadata") or {}
    return _clean_text(
        requirement.get("client_requirement_text")
        or metadata.get("original_body")
        or requirement.get("original_body")
        or requirement.get("requirement_text")
        or requirement.get("description")
    )


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
    trainer = await db["trainers"].find_one(_trainer_lookup(trainer_id)) or {}
    public_trainer_id = _public_trainer_id(trainer, trainer_id)
    email = payload.trainer_email or trainer.get("email", "")
    name = payload.trainer_name or trainer.get("name", "Trainer")

    if not email:
        raise HTTPException(400, "No email address found for trainer")

    requirement: Dict[str, Any] = {}
    if payload.requirement_id:
        requirement = await db["requirements"].find_one({"requirement_id": payload.requirement_id}, {"_id": 0}) or {}

    # Compose body via email-service templates if no explicit body
    body = payload.body
    subject = payload.subject
    technology = (
        payload.technology
        or payload.domain
        or requirement.get("technology_needed")
        or requirement.get("domain")
        or "Training"
    )
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
                    duration = _clean_duration_text(
                        payload.duration
                        or requirement.get("duration_text")
                        or (f"{requirement.get('duration_days')} days" if requirement.get("duration_days") else "")
                        or (f"{requirement.get('duration_hours')} hours" if requirement.get("duration_hours") else "")
                    )
                    dates = _clean_text(
                        requirement.get("training_dates")
                        or requirement.get("preferred_dates")
                        or requirement.get("dates")
                        or requirement.get("date_time_text")
                    )
                    mode = _clean_text(payload.mode or requirement.get("mode") or requirement.get("delivery_mode"))
                    participants = _clean_text(payload.participants or requirement.get("participant_count"))
                    r = await client.post(
                        f"{EMAIL_SVC}/api/v1/email/templates/shortlist-first",
                        json={
                            "trainer_name": name,
                            "domain": technology,
                            "duration": duration,
                            "dates": dates,
                            "mode": mode,
                            "location": _clean_text(requirement.get("preferred_location") or requirement.get("location")),
                            "participants": participants,
                            "budget": _trainer_mail1_commercial_text(requirement),
                            "client_request": _client_requirement_text(requirement),
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
        from_name = getattr(settings, "FROM_NAME", None) or "Clahan Technologies"
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
            send_payload = {
                "to": email, "subject": subject, "body": body,
                "mail_type": payload.mail_type, "trainer_id": public_trainer_id,
                "trainer_name": name,
                "requirement_id": payload.requirement_id,
                "smtp_config": payload.smtp_config,
            }
            if payload.mail_type in ("mail1", "first") and payload.requirement_id:
                send_payload["idempotency_key"] = f"trainer-mail1:{payload.requirement_id}:{public_trainer_id or email.lower()}"
            r = await client.post(f"{EMAIL_SVC}/api/v1/email/send", json=send_payload)
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
            {"requirement_id": payload.requirement_id, "top_trainers.trainer_id": public_trainer_id},
            {"$set": {
                "top_trainers.$.pipeline_status": payload.mail_type,
                "top_trainers.$.last_mail_type": payload.mail_type,
                "top_trainers.$.last_mailed_at": now,
            }},
        )

    return {"success": True, "trainer_id": public_trainer_id, "mail_type": payload.mail_type, "sent_to": email}


@router.post("/{trainer_id}/automation-pipeline/tick")
async def automation_pipeline_tick(
    trainer_id: str,
    payload: PipelineTickRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Advance a trainer to the next pipeline stage."""
    trainer = await db["trainers"].find_one(_trainer_lookup(trainer_id)) or {}
    if not trainer:
        raise HTTPException(404, "Trainer not found")
    public_trainer_id = _public_trainer_id(trainer, trainer_id)

    # Find current stage from email logs
    latest_log = await db["email_logs"].find_one(
        {"trainer_id": public_trainer_id, "requirement_id": payload.requirement_id or {"$exists": True}},
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
        "trainer_id": public_trainer_id,
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
    trainer = await db["trainers"].find_one(_trainer_lookup(trainer_id)) or {}
    public_trainer_id = _public_trainer_id(trainer, trainer_id)
    email = trainer.get("email", "")
    name = trainer.get("name", "Trainer")

    if not email:
        raise HTTPException(400, "Trainer email not found")

    body = (
        f"Dear {name},\n\n"
        "We came across your profile and would like to consider you for a training assignment.\n\n"
        "Could you please share your updated trainer profile/resume at your earliest convenience?\n\n"
        "Regards,\nClahan Technologies\nsujithaofficial585@gmail.com"
    )
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(f"{EMAIL_SVC}/api/v1/email/send", json={
                "to": email, "subject": "Profile / Resume Request - Clahan Technologies",
                "body": body, "mail_type": "resume_request",
                "trainer_id": public_trainer_id, "requirement_id": requirement_id or "",
            })
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc

    return {"success": True, "trainer_id": public_trainer_id, "sent_to": email}
