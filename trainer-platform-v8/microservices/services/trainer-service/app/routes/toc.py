"""Training Table of Contents (TOC) generation endpoint."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.database import get_db

router = APIRouter()


class TocRequest(BaseModel):
    domain: str
    duration_days: int = 5
    level: str = "intermediate"
    mode: str = "Online"
    notes: Optional[str] = ""
    requirement_id: Optional[str] = None
    trainer_id: Optional[str] = None


@router.post("/generate")
async def generate_toc(payload: TocRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """
    Generate a structured TOC for a training programme.
    Uses the service-local TOC generator.
    """
    toc = _minimal_toc(payload.domain, payload.duration_days)

    if payload.requirement_id:
        from datetime import datetime
        await db.toc_generations.insert_one({
            "requirement_id": payload.requirement_id,
            "trainer_id": payload.trainer_id,
            "domain": payload.domain,
            "duration_days": payload.duration_days,
            "toc": toc,
            "created_at": datetime.utcnow(),
        })

    return {"success": True, "toc": toc}


def _minimal_toc(domain: str, days: int) -> dict:
    return {
        "title": f"{domain} Training",
        "subtitle": f"{days}-Day Programme",
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
            for i in range(days)
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
