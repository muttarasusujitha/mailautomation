"""Trainer matching against a requirement."""
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.database import get_db

router = APIRouter()

STOP_WORDS = {"and", "or", "the", "a", "an", "in", "with", "for", "to", "of", "on", "at", "by"}


def _score_trainer(trainer: Dict[str, Any], skills: List[str], domain: str, location: str) -> float:
    score = 0.0
    t_text = " ".join([
        str(trainer.get("technology_category") or ""),
        " ".join(trainer.get("skills") or []),
        " ".join(trainer.get("secondary_categories") or []),
        str(trainer.get("summary") or ""),
        str(trainer.get("technologies") or ""),
    ]).lower()

    for skill in skills:
        if skill.lower() in t_text:
            score += 10.0

    if domain and re.search(re.escape(domain.lower()), t_text):
        score += 15.0

    exp = float(trainer.get("experience_years") or 0)
    score += min(exp * 1.5, 15.0)

    if location and location.lower() in str(trainer.get("location") or "").lower():
        score += 5.0

    rank = float(trainer.get("resume_rank_score") or 0)
    score += rank * 0.2

    return round(score, 2)


class MatchRequest(BaseModel):
    requirement_id: Optional[str] = None
    skills: List[str] = []
    domain: Optional[str] = ""
    location: Optional[str] = ""
    budget: Optional[float] = None
    top_n: int = 10


@router.post("/match")
async def match_trainers(
    payload: MatchRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Score and rank trainers against a requirement."""
    req: Dict[str, Any] = {}
    if payload.requirement_id:
        req = await db.requirements.find_one({"requirement_id": payload.requirement_id}, {"_id": 0}) or {}

    skills = payload.skills or [s for s in re.split(r"[,\s]+", str(req.get("skills") or "")) if s and s not in STOP_WORDS]
    domain = payload.domain or str(req.get("technology_needed") or req.get("domain") or "")
    location = payload.location or str(req.get("location") or "")
    budget = payload.budget or req.get("budget")

    query: Dict[str, Any] = {"status": {"$ne": "rejected"}}
    if budget:
        query["$or"] = [{"day_rate": {"$lte": budget}}, {"day_rate": None}, {"day_rate": {"$exists": False}}]

    cursor = db.trainers.find(query, {"resume": 0, "combined_text": 0})
    trainers = [d async for d in cursor]

    scored = []
    for t in trainers:
        s = _score_trainer(t, skills, domain, location)
        if s > 0:
            t["_id"] = str(t["_id"])
            scored.append({**t, "_match_score": s})

    scored.sort(key=lambda x: x["_match_score"], reverse=True)
    top = scored[: payload.top_n]

    return {
        "matched": len(top),
        "total_evaluated": len(trainers),
        "requirement_id": payload.requirement_id,
        "trainers": top,
    }


@router.get("/shortlist/{requirement_id}")
async def get_shortlist(requirement_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Return trainers already shortlisted for a requirement."""
    cursor = db.shortlists.find({"requirement_id": requirement_id}, {"_id": 0})
    items = [d async for d in cursor]
    return {"requirement_id": requirement_id, "shortlisted": items, "count": len(items)}
