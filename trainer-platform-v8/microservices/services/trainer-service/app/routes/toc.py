"""Training Table of Contents (TOC) generation endpoint."""
import uuid
from datetime import datetime
from math import ceil
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, root_validator

from app.database import get_db
from app.toc_generation_agent import generate_toc_from_dataset, validate_toc

router = APIRouter()


class TocRequest(BaseModel):
    domain: Optional[str] = None
    technology: Optional[str] = None
    duration_days: float = 5.0
    level: str = "intermediate"
    mode: str = "Online"
    notes: Optional[str] = ""
    requirement_id: Optional[str] = None
    trainer_id: Optional[str] = None
    trainer_name: Optional[str] = None
    trainer_email: Optional[str] = None
    audience_level: Optional[str] = None
    training_dates: Optional[str] = None
    timing: Optional[str] = None
    toc_type: Optional[str] = "standard"
    custom_topics: Optional[str] = ""
    client_notes: Optional[str] = ""
    toc_id: Optional[str] = None

    @root_validator(skip_on_failure=True)
    def require_domain_or_technology(cls, values):
        domain = values.get("domain") or values.get("technology")
        if not domain:
            raise ValueError("domain or technology is required")
        values["domain"] = domain
        return values

    @root_validator(skip_on_failure=True)
    def validate_duration_days(cls, values):
        duration_days = values.get("duration_days")
        if duration_days is None or duration_days <= 0:
            raise ValueError("duration_days must be a positive number")
        return values


@router.post("/generate")
async def generate_toc(payload: TocRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """
    Generate a structured TOC for a training programme.
    Uses the richer TOC generator with curriculum dataset support.
    """
    try:
        # Use the richer curriculum-aware TOC generator
        toc = generate_toc_from_dataset(
            domain_name=payload.domain,
            duration_days=int(payload.duration_days),
            level=payload.level,
            mode=payload.mode,
            notes=payload.notes or "",
        )
        # Validate and ensure all day entries are complete
        toc = validate_toc(toc, int(payload.duration_days))
    except Exception as e:
        # Fallback to minimal if generator fails
        toc = _minimal_toc(payload.domain, payload.duration_days)

    toc.update({
        "domain": payload.domain,
        "duration_days": int(payload.duration_days),
        "level": payload.level,
        "mode": payload.mode,
    })
    if payload.trainer_name:
        toc["trainer_name"] = payload.trainer_name

    toc_id = payload.toc_id or f"TOC-{uuid.uuid4().hex[:10].upper()}"

    await db.toc_generations.insert_one({
        "toc_id": toc_id,
        "requirement_id": payload.requirement_id,
        "trainer_id": payload.trainer_id,
        "trainer_name": payload.trainer_name,
        "trainer_email": payload.trainer_email,
        "domain": payload.domain,
        "duration_days": payload.duration_days,
        "audience_level": payload.audience_level,
        "training_dates": payload.training_dates,
        "timing": payload.timing,
        "toc_type": payload.toc_type,
        "custom_topics": payload.custom_topics,
        "client_notes": payload.client_notes,
        "toc": toc,
        "created_at": datetime.utcnow(),
    })

    return {"success": True, "toc_id": toc_id, "toc_data": toc}


def _minimal_toc(domain: str, days: float) -> dict:
    rounded_days = max(1, ceil(days))
    return {
        "title": f"{domain} Training",
        "subtitle": f"{rounded_days}-Day Programme",
        "domain": domain,
        "duration_days": rounded_days,
        "overview": f"A {days}-day {domain} training programme.",
        "days": [
            {
                "day": i + 1,
                "title": f"Day {i + 1}: {domain} Module {i + 1}",
                "focus_area": f"{domain} concepts and labs",
                "tools": domain,
                "morning_session": {"time": "9:00 AM - 1:00 PM", "title": "Concepts", "topics": []},
                "afternoon_session": {"time": "1:00 PM - 5:00 PM", "title": "Hands-on", "topics": []},
                "learning_objectives": [f"Understand {domain} Day {i + 1} topics"],
                "jira_practice": ["Update sprint board"],
            }
            for i in range(rounded_days)
        ],
        "tools_software": [domain],
        "certification_roadmap": [f"{domain} certification roadmap"],
    }


@router.get("/knowledge-base")
async def list_knowledge_base(db: AsyncIOMotorDatabase = Depends(get_db)):
    """List available TOC knowledge-base entries."""
    cursor = db.toc_knowledge.find({}, {"_id": 0, "domain": 1, "created_at": 1}).sort("domain", 1)
    items = [d async for d in cursor]
    return {"domains": items, "count": len(items)}
