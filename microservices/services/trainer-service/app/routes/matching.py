"""Trainer matching against a requirement."""
import re
import math
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from shared.database.service import get_db

router = APIRouter()

STOP_WORDS = {"and", "or", "the", "a", "an", "in", "with", "for", "to", "of", "on", "at", "by"}


def _score_trainer(trainer: Dict[str, Any], skills: List[str], domain: str, location: str) -> float:
    from shared.toc_quality import topic_is_covered
    score = 0.0
    t_text = " ".join([
        str(trainer.get("technology_category") or ""),
        " ".join(trainer.get("skills") or []),
        " ".join(trainer.get("secondary_categories") or []),
        str(trainer.get("summary") or ""),
        str(trainer.get("technologies") or ""),
    ]).lower()

    matched_skills = [skill for skill in skills if topic_is_covered(skill, t_text)]
    domain_match = bool(domain and topic_is_covered(domain, t_text))
    if (skills and not matched_skills) or (not skills and not domain_match):
        return 0.0
    for skill in matched_skills:
        if skill:
            score += 10.0

    if domain_match:
        score += 15.0

    def number(value, maximum):
        try:
            value = float(value or 0)
            return max(0, min(maximum, value)) if math.isfinite(value) else 0
        except (TypeError, ValueError):
            return 0
    exp = number(trainer.get("experience_years"), 60)
    score += min(exp * 1.5, 15.0)

    if location and location.lower() in str(trainer.get("location") or "").lower():
        score += 5.0

    rank = number(trainer.get("resume_rank_score"), 100)
    score += rank * 0.2

    return round(min(score, 100), 2)


class MatchRequest(BaseModel):
    requirement_id: Optional[str] = None
    skills: List[str] = []
    domain: Optional[str] = ""
    location: Optional[str] = ""
    # `budget` remains a backwards-compatible per-day ceiling. New callers
    # should say explicitly whether their ceiling is daily or for the course.
    budget: Optional[float] = Field(None, ge=0)
    budget_per_day: Optional[float] = Field(None, ge=0)
    budget_total: Optional[float] = Field(None, ge=0)
    top_n: int = 1


def _budget_per_day(payload: MatchRequest, requirement: Dict[str, Any]) -> tuple[Optional[float], str]:
    """Resolve a comparable daily trainer-rate ceiling without guessing units."""
    def amount(value: Any) -> Optional[float]:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) and number >= 0 else None

    from shared.requirement_duration import training_duration
    requirement_days = training_duration(requirement).get("duration_days")

    if payload.budget_per_day is not None:
        return payload.budget_per_day, "request_per_day"
    if payload.budget_total is not None:
        total = payload.budget_total
        days = float(requirement_days or 0)
        if not math.isfinite(days):
            days = 0
        return (total / days, "request_total") if days > 0 else (None, "total_missing_duration")
    if payload.budget is not None:
        return payload.budget, "legacy_request_per_day"

    per_day = next((requirement.get(key) for key in ("budget_per_day", "client_budget_per_day")
                    if requirement.get(key) is not None), None)
    if per_day is not None:
        parsed = amount(per_day)
        if parsed is None:
            return None, "invalid_budget"
        return parsed, "requirement_per_day"

    total = next((requirement.get(key) for key in
                  ("budget_total", "client_budget", "approved_client_budget", "budget")
                  if requirement.get(key) is not None), None)
    if total is None:
        return None, "not_provided"
    parsed_total = amount(total)
    if parsed_total is None:
        return None, "invalid_budget"
    days = float(requirement_days or 0)
    if not math.isfinite(days):
        days = 0
    return (parsed_total / days, "requirement_total") if days > 0 else (None, "total_missing_duration")


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
    budget_limit, budget_basis = _budget_per_day(payload, req)
    budget_basis_unresolved = budget_basis in {"total_missing_duration", "invalid_budget"}

    # AI-extracted profiles stay out of matching until a reviewer confirms them.
    query: Dict[str, Any] = {"status": {"$ne": "rejected"}, "needs_review": {"$ne": True}}

    cursor = db.trainers.find(query, {"resume": 0, "combined_text": 0})
    trainers = [d async for d in cursor]

    scored = []
    unpriced = []
    for t in trainers:
        s = _score_trainer(t, skills, domain, location)
        if s > 0:
            try:
                day_rate = float(t.get("day_rate")) if t.get("day_rate") is not None else None
            except (TypeError, ValueError):
                day_rate = None
            if day_rate is not None and (not math.isfinite(day_rate) or day_rate < 0):
                day_rate = None
            if budget_limit is not None and day_rate is not None and day_rate > budget_limit:
                continue
            t["_id"] = str(t["_id"])
            if budget_basis_unresolved or (budget_limit is not None and day_rate is None):
                unpriced.append({**t, "_match_score": s, "budget_status": "unknown"})
                continue
            budget_status = (
                "not_checked" if budget_limit is None else
                "unknown" if day_rate is None else "within_budget"
            )
            scored.append({**t, "_match_score": s, "budget_status": budget_status})

    scored.sort(key=lambda x: (x["budget_status"] == "unknown", -x["_match_score"]))
    # This endpoint is also used by ad-hoc matching screens; enforce the
    # system policy here instead of relying on each caller's payload.
    top = scored[:1]

    return {
        "matched": len(top),
        "total_evaluated": len(trainers),
        "budget_per_day_limit": budget_limit,
        "budget_basis": budget_basis,
        "unpriced_candidates": unpriced,
        "requirement_id": payload.requirement_id,
        "trainers": top,
    }


@router.get("/shortlist/{requirement_id}")
async def get_shortlist(requirement_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Return trainers already shortlisted for a requirement."""
    cursor = db.shortlists.find({"requirement_id": requirement_id}, {"_id": 0})
    items = [d async for d in cursor]
    return {"requirement_id": requirement_id, "shortlisted": items, "count": len(items)}
