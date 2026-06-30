"""Shortlist management — send mail, send interview link, send client slots."""
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.database import get_db
from app.config import get_settings

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()

EMAIL_SVC = "http://email-service:8002"
NOTIF_SVC = "http://notification-service:8003"


class SendMailRequest(BaseModel):
    requirement_id: str
    trainer_ids: Optional[List[str]] = None
    mail_type: str = "mail1"
    subject: Optional[str] = ""
    body: Optional[str] = ""
    smtp_config: Optional[Dict[str, Any]] = None


class SendInterviewLinkRequest(BaseModel):
    requirement_id: str
    trainer_id: str
    interview_link: str
    interview_date: Optional[str] = ""
    technology: Optional[str] = ""
    smtp_config: Optional[Dict[str, Any]] = None


class SendClientSlotsRequest(BaseModel):
    requirement_id: str
    trainer_id: str
    slots: List[Dict[str, Any]] = []
    client_email: Optional[str] = ""
    client_name: Optional[str] = ""
    smtp_config: Optional[Dict[str, Any]] = None


@router.get("/{requirement_id}")
async def get_shortlist(requirement_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    doc = await db["shortlists"].find_one({"requirement_id": requirement_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Shortlist not found")
    return {"success": True, "shortlist": doc}


@router.get("/thread")
async def get_shortlist_thread(
    requirement_id: str = Query(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    logs = await (
        db["email_logs"]
        .find({"requirement_id": requirement_id}, {"_id": 0})
        .sort("created_at", -1)
        .to_list(200)
    )
    return {"success": True, "requirement_id": requirement_id, "thread": logs}


@router.get("/thread-states")
async def get_thread_states(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Return pipeline stage counts across all active shortlists."""
    pipeline = [
        {"$unwind": "$top_trainers"},
        {"$group": {"_id": "$top_trainers.pipeline_status", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    stages = {r["_id"]: r["count"] async for r in db["shortlists"].aggregate(pipeline) if r["_id"]}
    return {"success": True, "stage_counts": stages}


@router.post("/send-mail")
async def send_shortlist_mail(
    payload: SendMailRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Send the configured mail_type email to one or all trainers on a shortlist."""
    shortlist = await db["shortlists"].find_one({"requirement_id": payload.requirement_id}, {"_id": 0}) or {}
    top_trainers: List[Dict[str, Any]] = shortlist.get("top_trainers") or []

    if payload.trainer_ids:
        targets = [t for t in top_trainers if t.get("trainer_id") in payload.trainer_ids]
    else:
        targets = [t for t in top_trainers if t.get("pipeline_status") not in ("stopped_selected", "declined")]

    if not targets:
        return {"success": True, "sent": 0, "message": "No eligible trainers found"}

    results = []
    for t in targets:
        trainer_email = t.get("email") or t.get("trainer_email") or ""
        trainer_name = t.get("name") or t.get("trainer_name") or "Trainer"
        if not trainer_email:
            results.append({"trainer_id": t.get("trainer_id"), "status": "skipped_no_email"})
            continue

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(f"{EMAIL_SVC}/api/v1/email/send", json={
                    "to": trainer_email,
                    "subject": payload.subject or f"Training Opportunity — {payload.requirement_id}",
                    "body": payload.body or f"Dear {trainer_name},\n\nWe have a training requirement matching your profile. Please revert if interested.\n\nRegards,\nTrainerSync Team",
                    "mail_type": payload.mail_type,
                    "trainer_id": t.get("trainer_id"),
                    "requirement_id": payload.requirement_id,
                    "smtp_config": payload.smtp_config,
                })
            ok = r.status_code < 400
        except Exception as exc:
            logger.error("Email send failed for %s: %s", trainer_email, exc)
            ok = False

        results.append({"trainer_id": t.get("trainer_id"), "email": trainer_email, "status": "sent" if ok else "failed"})

        now = datetime.utcnow()
        await db["shortlists"].update_one(
            {"requirement_id": payload.requirement_id, "top_trainers.trainer_id": t.get("trainer_id")},
            {"$set": {
                f"top_trainers.$.pipeline_status": payload.mail_type,
                f"top_trainers.$.last_mail_type": payload.mail_type,
                f"top_trainers.$.last_mailed_at": now,
            }},
        )

    sent = sum(1 for r in results if r["status"] == "sent")
    return {"success": True, "sent": sent, "total": len(results), "results": results}


@router.post("/send-interview-link")
async def send_interview_link(
    payload: SendInterviewLinkRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Email an interview link to a specific trainer."""
    trainer = await db["trainers"].find_one({"trainer_id": payload.trainer_id}, {"_id": 0}) or {}
    email = trainer.get("email", "")
    name = trainer.get("name", "Trainer")
    technology = payload.technology or ""

    if not email:
        raise HTTPException(400, "Trainer email not found")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{EMAIL_SVC}/api/v1/email/templates/interview", json={
                "trainer_name": name,
                "technology": technology,
                "req_id": payload.requirement_id,
                "interview_date": payload.interview_date,
                "interview_link": payload.interview_link,
            })
            tmpl = r.json()
            await client.post(f"{EMAIL_SVC}/api/v1/email/send", json={
                "to": email,
                "subject": tmpl.get("subject", f"Interview – {technology}"),
                "body": tmpl.get("body", ""),
                "mail_type": "mail4",
                "trainer_id": payload.trainer_id,
                "requirement_id": payload.requirement_id,
                "smtp_config": payload.smtp_config,
            })
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc

    return {"success": True, "sent_to": email, "interview_link": payload.interview_link}


@router.post("/send-client-slots")
async def send_client_slots(
    payload: SendClientSlotsRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Forward trainer availability slots to the client via email."""
    client_email = payload.client_email
    if not client_email:
        req = await db["requirements"].find_one({"requirement_id": payload.requirement_id}, {"_id": 0}) or {}
        client_email = req.get("client_email", "")

    if not client_email:
        raise HTTPException(400, "client_email is required")

    slots_text = "\n".join(
        f"Slot {i+1}: {s.get('date_display', '')} {s.get('time_display', '')}".strip()
        for i, s in enumerate(payload.slots)
    ) or "The trainer's availability slots will be shared shortly."

    body = (
        f"Dear {payload.client_name or 'Client'},\n\n"
        "Please find below the trainer's available interview slots:\n\n"
        f"{slots_text}\n\n"
        "Kindly confirm your preferred slot at the earliest.\n\n"
        "Regards,\nTrainerSync Team"
    )

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(f"{EMAIL_SVC}/api/v1/email/send", json={
                "to": client_email,
                "subject": f"Trainer Slots — {payload.requirement_id}",
                "body": body,
                "mail_type": "client_slots",
                "requirement_id": payload.requirement_id,
            })
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc

    return {"success": True, "sent_to": client_email, "slots_count": len(payload.slots)}
