import asyncio
import hashlib
import json
import math
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from shared.database.service import get_db

router = APIRouter()

AGENT_ROLES = {
    "client_requirement_agent": "Understands client emails and requirement completeness.",
    "trainer_matching_agent": "Finds and ranks matching trainers.",
    "outreach_agent": "Plans trainer/client emails and follow-ups.",
    "commercial_agent": "Compares one-time, per-day, and commercial risk.",
    "interview_scheduling_agent": "Plans interview slots, Meet links, and start notices.",
    "exception_review_agent": "Escalates low-confidence or failed automation.",
}

SAFE_AUTO_ACTIONS = {
    "observe",
    "classify",
    "recommend",
    "log_decision",
    "send_reminder",
    "sync_inbox",
}


class AgentDecisionCreate(BaseModel):
    agent_role: str
    entity_type: str
    entity_id: str
    observation: str = ""
    decision: str
    action: str
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    reason: str = ""
    status: str = "planned"
    requires_human: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _now() -> datetime:
    return datetime.utcnow()


def _confidence(*values: Any) -> float:
    """Preserve explicit zero; treat malformed/out-of-range scores as uncertain."""
    for value in values:
        if value is None or value == "":
            continue
        try:
            score = float(value)
        except (TypeError, ValueError):
            return 0.0
        return score if math.isfinite(score) and 0.0 <= score <= 1.0 else 0.0
    return 0.65


def _requires_human(action: str, confidence: float, explicit: bool = False) -> bool:
    return bool(explicit or confidence < 0.7 or action not in SAFE_AUTO_ACTIONS)


async def _log_decision(db: AsyncIOMotorDatabase, payload: AgentDecisionCreate, deduplicate: bool = False) -> Optional[Dict[str, Any]]:
    if payload.agent_role not in AGENT_ROLES:
        raise HTTPException(400, f"Unknown agent_role: {payload.agent_role}")
    now = _now()
    doc = payload.model_dump()
    if deduplicate:
        # MongoDB's built-in unique _id index arbitrates concurrent runs.
        # Include evidence so changed confidence or metadata creates a new decision.
        fingerprint = json.dumps(doc, sort_keys=True, default=str, separators=(",", ":"))
        doc["_id"] = "agent:" + hashlib.sha256(fingerprint.encode()).hexdigest()
    doc.update(
        {
            "decision_id": f"AGD-{uuid.uuid4().hex[:10].upper()}",
            "requires_human": _requires_human(payload.action, payload.confidence, payload.requires_human),
            "created_at": now,
            "updated_at": now,
        }
    )
    try:
        await db["agent_decisions"].insert_one(doc)
    except DuplicateKeyError:
        if not deduplicate:
            raise
        return None
    doc.pop("_id", None)
    return doc


def _matching_decision(requirement: Dict[str, Any], shortlist: Dict[str, Any]) -> Optional[AgentDecisionCreate]:
    req_id = _clean(requirement.get("requirement_id"))
    if not req_id:
        return None
    trainers = shortlist.get("top_trainers") or []
    ranked = []
    for trainer in trainers:
        if not isinstance(trainer, dict) or not trainer.get("trainer_id"):
            continue
        if _clean(trainer.get("pipeline_status") or trainer.get("status")).lower() in {"declined", "rejected", "unavailable"}:
            continue
        try:
            score = float(trainer.get("match_score") or 0)
        except (TypeError, ValueError):
            score = 0
        score = score if math.isfinite(score) and 0 <= score <= 100 else 0
        ranked.append({"trainer_id": str(trainer["trainer_id"]), "match_score": score})
    ranked.sort(key=lambda row: (-row["match_score"], row["trainer_id"]))
    confidence = ranked[0]["match_score"] / 100 if ranked else 0
    return AgentDecisionCreate(
        agent_role="trainer_matching_agent", entity_type="requirement", entity_id=req_id,
        observation=f"Found {len(ranked)} eligible trainers in the existing shortlist.",
        decision="Review ranked shortlist before outreach." if ranked else "Generate or refresh trainer matches for this requirement.",
        action="recommend", confidence=confidence, requires_human=confidence < 0.7,
        reason="Uses existing matching scores; availability and commercial approval still need verification.",
        metadata={"ranked_trainers": ranked},
    )


def _outreach_decision(email: Dict[str, Any]) -> Optional[AgentDecisionCreate]:
    requirement = _client_decision(email)
    if not requirement:
        return None
    missing = requirement.metadata.get("missing_fields", [])
    return AgentDecisionCreate(
        agent_role="outreach_agent", entity_type="client_email", entity_id=requirement.entity_id,
        observation=requirement.observation,
        decision="Prepare a clarification request for missing fields." if missing else "Review trainer shortlist and outreach eligibility before preparing emails.",
        action="recommend", confidence=requirement.confidence,
        requires_human=True, reason="Outreach plans require review of recipients and prior correspondence.",
        metadata={"missing_fields": missing, "requirement_id": email.get("requirement_id")},
    )


def _exception_decision(candidate: AgentDecisionCreate) -> Optional[AgentDecisionCreate]:
    if not _requires_human(candidate.action, candidate.confidence, candidate.requires_human):
        return None
    return AgentDecisionCreate(
        agent_role="exception_review_agent", entity_type=candidate.entity_type, entity_id=candidate.entity_id,
        observation=candidate.observation, decision="Review the source decision before automation proceeds.",
        action="recommend", confidence=candidate.confidence, requires_human=True,
        reason=candidate.reason, metadata={"source_role": candidate.agent_role, "source_decision": candidate.decision},
    )


def _client_decision(email: Dict[str, Any]) -> Optional[AgentDecisionCreate]:
    extracted = email.get("extracted") or {}
    if not isinstance(extracted, dict):
        extracted = {}
    email_id = _clean(email.get("email_id"))
    if not email_id:
        return None
    missing = []
    if not _clean(extracted.get("technology_needed") or extracted.get("domain")):
        missing.append("technology")
    from shared.requirement_duration import training_duration
    duration = training_duration(email)
    if not (duration.get("duration_days") or duration.get("duration_hours")):
        missing.append("duration")
    if not _clean(extracted.get("budget_total") or extracted.get("budget_per_day") or email.get("budget")):
        missing.append("budget")
    confidence = _confidence(email.get("auto_send_confidence"), email.get("confidence"), extracted.get("confidence"))
    if missing:
        return AgentDecisionCreate(
            agent_role="client_requirement_agent",
            entity_type="client_email",
            entity_id=email_id,
            observation=f"Client request is missing: {', '.join(missing)}.",
            decision="Ask client for missing requirement details before trainer outreach.",
            action="recommend",
            confidence=min(confidence, 0.75),
            reason="Requirement is incomplete.",
            requires_human=confidence < 0.7,
            metadata={"missing_fields": missing, "subject": email.get("subject")},
        )
    return AgentDecisionCreate(
        agent_role="client_requirement_agent",
        entity_type="client_email",
        entity_id=email_id,
        observation="Client request has core requirement fields.",
        decision="Proceed with trainer matching and commercial analysis.",
        action="recommend",
        confidence=confidence,
        requires_human=confidence < 0.7,
        reason="Technology, duration, and budget are present.",
        metadata={"subject": email.get("subject"), "requirement_id": email.get("requirement_id")},
    )


def _commercial_decision(requirement: Dict[str, Any]) -> Optional[AgentDecisionCreate]:
    req_id = _clean(requirement.get("requirement_id"))
    if not req_id:
        return None
    budget = requirement.get("budget") or requirement.get("client_budget") or requirement.get("budget_total")
    dates = requirement.get("training_dates") or requirement.get("preferred_dates")
    if budget and dates:
        return AgentDecisionCreate(
            agent_role="commercial_agent",
            entity_type="requirement",
            entity_id=req_id,
            observation=f"Requirement has budget {budget} and date range {dates}.",
            decision="Compare one-time and day-wise commercial models with TDS shown separately.",
            action="recommend",
            confidence=0.86,
            reason="Budget and dates are enough for deterministic 30/70/TDS calculation.",
            metadata={"budget": budget, "dates": dates},
        )
    return AgentDecisionCreate(
        agent_role="commercial_agent",
        entity_type="requirement",
        entity_id=req_id,
        observation="Commercial inputs are incomplete.",
        decision="Request missing budget/date/rate details before final commercial recommendation.",
        action="recommend",
        confidence=0.62,
        reason="Commercial calculation needs budget and duration/date basis.",
        requires_human=True,
        metadata={"budget": budget, "dates": dates},
    )


def _interview_decision(log: Dict[str, Any]) -> Optional[AgentDecisionCreate]:
    email_id = _clean(log.get("email_id"))
    if not email_id:
        return None
    link = _clean(log.get("interview_link") or log.get("meet_link"))
    if not link:
        return None
    return AgentDecisionCreate(
        agent_role="interview_scheduling_agent",
        entity_type="email_log",
        entity_id=email_id,
        observation="Interview is scheduled with a Google Meet link.",
        decision="Send exact start-time notice to trainer and client during the meeting window.",
        action="send_reminder",
        confidence=0.9,
        reason="Scheduled interview has start time and meeting link.",
        metadata={
            "requirement_id": log.get("requirement_id"),
            "interview_at": str(log.get("interview_at") or ""),
            "client_email": log.get("client_email"),
            "trainer_email": log.get("trainer_email") or log.get("to_email") or log.get("recipient"),
        },
    )


@router.get("/roles")
async def list_agent_roles():
    return {"success": True, "roles": [{"role": key, "description": value} for key, value in AGENT_ROLES.items()]}


@router.post("/decisions")
async def create_agent_decision(payload: AgentDecisionCreate, db: AsyncIOMotorDatabase = Depends(get_db)):
    return {"success": True, "decision": await _log_decision(db, payload)}


@router.get("/decisions")
async def list_agent_decisions(
    entity_type: Optional[str] = Query(None),
    entity_id: Optional[str] = Query(None),
    agent_role: Optional[str] = Query(None),
    requires_human: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    query: Dict[str, Any] = {}
    if entity_type:
        query["entity_type"] = entity_type
    if entity_id:
        query["entity_id"] = entity_id
    if agent_role:
        query["agent_role"] = agent_role
    if requires_human is not None:
        query["requires_human"] = requires_human
    items = await db["agent_decisions"].find(query, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    return {"success": True, "decisions": items, "count": len(items)}


@router.post("/run")
async def run_agent_orchestrator(
    limit: int = Query(25, ge=1, le=100),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    decisions: List[Dict[str, Any]] = []
    client_emails_query = db["client_emails"].find(
        {"deleted": {"$ne": True}},
        {"_id": 0},
    ).sort("updated_at", -1).limit(limit).to_list(limit)
    requirements_query = db["requirements"].find({}, {"_id": 0}).sort("updated_at", -1).limit(limit).to_list(limit)
    interviews_query = db["email_logs"].find(
        {"interview_scheduled": True},
        {"_id": 0},
    ).sort("interview_at", -1).limit(limit).to_list(limit)
    client_emails, requirements, interviews = await asyncio.gather(
        client_emails_query, requirements_query, interviews_query,
    )
    requirement_ids = [item["requirement_id"] for item in requirements if item.get("requirement_id")]
    shortlists = await db["shortlists"].find(
        {"requirement_id": {"$in": requirement_ids}},
        {"_id": 0, "requirement_id": 1, "top_trainers": 1},
    ).to_list(None) if requirement_ids else []
    by_requirement = {item["requirement_id"]: item for item in shortlists}

    candidates: List[Optional[AgentDecisionCreate]] = []
    candidates.extend(_client_decision(item) for item in client_emails)
    candidates.extend(_commercial_decision(item) for item in requirements)
    candidates.extend(_interview_decision(item) for item in interviews)
    candidates.extend(_matching_decision(item, by_requirement.get(item.get("requirement_id"), {})) for item in requirements)
    candidates.extend(_outreach_decision(item) for item in client_emails)
    candidates.extend([_exception_decision(item) for item in candidates if item])

    for candidate in candidates:
        if not candidate:
            continue
        decision = await _log_decision(db, candidate, deduplicate=True)
        if decision:
            decisions.append(decision)

    return {"success": True, "created": len(decisions), "decisions": decisions}


@router.get("/summary")
async def agent_summary(db: AsyncIOMotorDatabase = Depends(get_db)):
    by_role = []
    pipeline = [
        {"$group": {"_id": "$agent_role", "count": {"$sum": 1}, "review": {"$sum": {"$cond": ["$requires_human", 1, 0]}}}},
        {"$sort": {"count": -1}},
    ]
    async for row in db["agent_decisions"].aggregate(pipeline):
        by_role.append({"agent_role": row["_id"], "count": row["count"], "requires_human": row["review"]})
    total = sum(row["count"] for row in by_role)
    needs_review = sum(row["requires_human"] for row in by_role)
    recent = await db["agent_decisions"].find({}, {"_id": 0}).sort("created_at", -1).limit(10).to_list(10)
    return {"success": True, "total": total, "requires_human": needs_review, "by_role": by_role, "recent": recent}
