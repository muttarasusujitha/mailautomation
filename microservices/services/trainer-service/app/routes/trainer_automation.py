"""Trainer automation pipeline — tick, send single mail, status."""
import logging
import math
from datetime import datetime
from typing import Any, Dict, List, Optional

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
MIN_TRAINER_DAY_RATE_VISIBLE = 10000
DEFAULT_TRAINER_SHARE = 0.70


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _is_proposal_requirement(requirement: Dict[str, Any]) -> bool:
    flow_value = _clean_text(
        requirement.get("batch_flow")
        or requirement.get("batch_type")
        or requirement.get("requirement_type")
    ).lower()
    if "proposal" in flow_value:
        return True
    source = "\n".join(_clean_text(requirement.get(key)) for key in (
        "client_requirement_text", "requirement_text", "description", "original_body",
    )).lower()
    return any(marker in source for marker in (
        "mode: to be confirmed",
        "duration: to be confirmed",
        "location: to be confirmed",
        "upcoming corporate training",
        "immediate requirement",
    ))


def _trainer_scope_attachments(requirement: Dict[str, Any]) -> List[Dict[str, str]]:
    allowed = {
        ".pdf": "pdf", ".doc": "msword", ".docx": "vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xls": "vnd.ms-excel", ".xlsx": "vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".csv": "csv", ".txt": "plain",
    }
    forwarded: List[Dict[str, str]] = []
    total_bytes = 0
    for item in requirement.get("source_attachments") or []:
        if not isinstance(item, dict) or not item.get("safe_client_scope"):
            continue
        filename = re.sub(r"[\r\n\\/]+", "_", _clean_text(item.get("filename")))[:160]
        extension = next((ext for ext in allowed if filename.lower().endswith(ext)), "")
        content_base64 = _clean_text(item.get("content_base64"))
        size_bytes = int(item.get("size_bytes") or 0)
        if not filename or not extension or not content_base64 or size_bytes <= 0 or size_bytes > 4 * 1024 * 1024:
            continue
        if total_bytes + size_bytes > 6 * 1024 * 1024:
            break
        forwarded.append({"filename": filename, "content_base64": content_base64, "subtype": allowed[extension]})
        total_bytes += size_bytes
    return forwarded


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


def _round_commercial_amount(value: Any) -> int:
    numeric = _safe_float(value, 0)
    if numeric <= 0:
        return 0
    return int(round(numeric))


def _clean_duration_text(value: Any) -> str:
    text = _clean_text(value)
    text = re.sub(r"(?i)^to\s+be\s*:?\s*(?=\d)", "", text).strip()
    return text


def _trainer_mail1_commercial_text(requirement: Dict[str, Any]) -> str:
    daily_client_amount = 0.0
    total_client_amount = 0.0
    days = _safe_int(requirement.get("duration_days"), 0) or _safe_int(requirement.get("commercial_working_days"), 0)
    if requirement.get("budget_total") not in (None, "", []):
        total_client_amount = _safe_float(requirement.get("budget_total"))
        daily_client_amount = total_client_amount / days if days else 0.0
    if not daily_client_amount:
        daily_client_amount = _safe_float(requirement.get("client_budget_per_day") or requirement.get("budget_per_day"))
        total_client_amount = daily_client_amount * days if daily_client_amount and days else total_client_amount
    if not daily_client_amount and not total_client_amount:
        return ""
    if daily_client_amount and daily_client_amount < MIN_TRAINER_DAY_RATE_VISIBLE and total_client_amount:
        return f"INR {_round_commercial_amount(total_client_amount * DEFAULT_TRAINER_SHARE):,} total commercial, inclusive of applicable TDS"
    if daily_client_amount:
        return f"INR {_round_commercial_amount(daily_client_amount * DEFAULT_TRAINER_SHARE):,} per day/session, inclusive of applicable TDS"
    return f"INR {_round_commercial_amount(total_client_amount * DEFAULT_TRAINER_SHARE):,} total commercial, inclusive of applicable TDS"


def _replace_trainer_mail1_commercial(body: str, requirement: Dict[str, Any]) -> str:
    commercial_text = _trainer_mail1_commercial_text(requirement)
    if not commercial_text:
        return body
    line = f"Offered trainer commercial: {commercial_text}"
    if re.search(r"(?im)^(?:Commercials/Budget|Offered trainer commercial):\s*.*$", body or ""):
        return re.sub(r"(?im)^(?:Commercials/Budget|Offered trainer commercial):\s*.*$", line, body or "")
    return body


def _has_raw_client_mail_leak(body: str) -> bool:
    text = _clean_text(body).lower()
    return any(marker in text for marker in (
        "requirement snapshot",
        "client requirement details",
        "appears aligned with your profile",
        "dear team,\nwe have",
    ))


def _mail1_requested_items(requirement: Dict[str, Any]) -> List[str]:
    source = _client_requirement_text(requirement).lower()
    technology = _clean_text(requirement.get("domain") or requirement.get("technology") or "technology")
    toc_label = (
        "Detailed day-wise ToC/course agenda"
        if any(term in source for term in ("day-wise", "day wise", "detailed", "topics and subtopics"))
        else "ToC/course agenda"
    )
    commercial_label = (
        "Commercials for the complete training engagement"
        if re.search(r"commercials?.{0,40}(?:complete|entire|total)|(?:complete|entire|total).{0,40}commercials?", source)
        else "Commercial expectation per hour/day"
    )
    checks = [
        ("Updated trainer profile/CV", ("cv", "resume", "profile")),
        ("LinkedIn profile", ("linkedin",)),
        (f"Relevant {technology} corporate training experience", ("training experience", "relevant experience", "corporate training experience")),
        ("Availability for the specified dates and timings", ("availability", "available", "slots")),
        (toc_label, ("toc", "table of contents", "agenda", "course outline", "proposal")),
        ("Day-wise hands-on lab plan", ("lab plan", "hands-on lab", "hands on lab")),
        (commercial_label, ("commercial", "budget", "rate", "charges", "cost")),
        ("Relevant certifications", ("certification", "certifications", "certified")),
    ]
    items = [label for label, needles in checks if any(needle in source for needle in needles)]
    toc_action = _clean_text(requirement.get("toc_action") or (requirement.get("extracted") or {}).get("toc_action")).lower()
    scope_attached = bool(requirement.get("scope_attached") or (requirement.get("extracted") or {}).get("scope_attached"))
    if toc_action == "generate_by_clahan" and not scope_attached:
        items = [
            item for item in items
            if not any(term in item.lower() for term in ("toc", "course agenda", "day-wise"))
        ]
    return items or ["Updated trainer profile/CV", "LinkedIn profile", "Availability"]


def _mail1_source_value(requirement: Dict[str, Any], label_pattern: str) -> str:
    source = _client_requirement_text(requirement)
    match = re.search(rf"(?im)^\s*(?:{label_pattern})\s*:\s*([^\r\n]+)", source)
    return _clean_text(match.group(1)).strip("* ") if match else ""


def _clean_confirmed_mail1_body(trainer_name: str, requirement: Dict[str, Any], technology: str) -> str:
    if technology.lower() == "devops":
        technology = "DevOps"
    dates = _clean_text(
        requirement.get("training_dates")
        or requirement.get("preferred_dates")
        or requirement.get("dates")
        or requirement.get("date_time_text")
        or requirement.get("timeline")
        or requirement.get("schedule")
        or requirement.get("training_schedule")
        or requirement.get("timing")
        or requirement.get("session_timing")
    )
    duration = _clean_text(
        requirement.get("duration_text")
        or requirement.get("duration")
        or (f"{requirement.get('duration_days')} Days" if requirement.get("duration_days") else "")
        or (f"{requirement.get('duration_hours')} Hours" if requirement.get("duration_hours") else "")
    )
    mode = _clean_text(requirement.get("mode") or requirement.get("training_mode") or requirement.get("delivery_mode"))
    participants = _clean_text(requirement.get("participant_count") or requirement.get("participants") or requirement.get("audience_level"))
    training_time = _clean_text(requirement.get("training_time") or requirement.get("session_timing") or _mail1_source_value(requirement, r"training\s+time|timings?"))
    hands_on_lab = _clean_text(requirement.get("hands_on_lab") or _mail1_source_value(requirement, r"hands[-\s]?on\s+lab|lab\s+duration"))
    commercial = _trainer_mail1_commercial_text(requirement)
    details = [f"Domain/Technology: {technology}"]
    if dates:
        details.append(f"Training dates: {dates}")
    if duration:
        details.append(f"Duration: {duration}")
    if training_time:
        details.append(f"Training time: {training_time}")
    if hands_on_lab:
        details.append(f"Hands-on lab: {hands_on_lab}")
    if mode:
        details.append(f"Mode: {mode}")
    if participants:
        details.append(f"Participants: {participants}")
    if commercial:
        details.append(f"Offered trainer commercial: {commercial}")
    requested_items = _mail1_requested_items(requirement)
    selected = []
    for label, needle in [
        ("availability", "availability"),
        ("updated profile", "profile"),
        ("commercials", "commercial"),
        (f"relevant {technology} experience", "experience"),
        ("day-wise TOC", "toc"),
    ]:
        if any(needle in item.lower() for item in requested_items):
            selected.append(label)
    if not selected:
        selected = ["availability", "updated profile", "commercials", f"relevant {technology} experience"]
    ask = ", ".join(dict.fromkeys(selected))
    return (
        f"Hi {trainer_name or 'Trainer'},\n\n"
        "Hope you are doing well.\n\n"
        f"We have a corporate training requirement for {technology} and are checking trainer availability.\n\n"
        "Training Details:\n"
        f"{chr(10).join(details)}\n\n"
        f"Please confirm your availability for the above requirement. Also share your {ask}.\n\n"
        "Regards,\n"
        "Clahan Technologies"
    )


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

    # This legacy Trainer page must never fetch email-service/template.py.
    # The live automatic workflow belongs to Shortlist / Shortlist1, where
    # requirement facts, ToC attachment, exact three slots and one-only
    # missing-detail follow-up are all enforced together.  This endpoint may
    # deliver an explicitly reviewed manual message only.
    body = _clean_text(payload.body)
    subject = payload.subject
    technology = (
        payload.technology
        or payload.domain
        or requirement.get("technology_needed")
        or requirement.get("domain")
        or "Training"
    )
    if not body:
        raise HTTPException(
            409,
            "Automatic mail drafting from template.py is retired. Use Shortlist/Shortlist1 for the current AI workflow, or provide a reviewed manual email body.",
        )
    if payload.mail_type not in ("mail1", "first") and payload.message and payload.message.strip():
        body = f"{payload.message.strip()}\n\n{body}"
    if not subject:
        subject = f"Training Requirement - {technology or payload.requirement_id or 'Opportunity'}"
    if payload.mail_type in ("mail1", "first") and "proposal" not in _clean_text(
        requirement.get("batch_flow") or requirement.get("batch_type") or requirement.get("requirement_type")
    ).lower():
        if _has_raw_client_mail_leak(body):
            body = _clean_confirmed_mail1_body(name, requirement, technology)
        body = _replace_trainer_mail1_commercial(body, requirement)

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            send_payload = {
                "to": email, "subject": subject, "body": body,
                "mail_type": payload.mail_type, "trainer_id": public_trainer_id,
                "trainer_name": name,
                "requirement_id": payload.requirement_id,
                "smtp_config": payload.smtp_config,
            }
            if payload.mail_type in ("mail1", "first"):
                scope_attachments = _trainer_scope_attachments(requirement)
                if scope_attachments:
                    send_payload["attachments"] = scope_attachments
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
