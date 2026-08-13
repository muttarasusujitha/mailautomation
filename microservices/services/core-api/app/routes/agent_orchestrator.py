import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

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


def _requires_human(action: str, confidence: float, explicit: bool = False) -> bool:
    return bool(explicit or confidence < 0.7 or action not in SAFE_AUTO_ACTIONS)


async def _log_decision(db: AsyncIOMotorDatabase, payload: AgentDecisionCreate) -> Dict[str, Any]:
    if payload.agent_role not in AGENT_ROLES:
        raise HTTPException(400, f"Unknown agent_role: {payload.agent_role}")
    now = _now()
    doc = payload.model_dump()
    doc.update(
        {
            "decision_id": f"AGD-{uuid.uuid4().hex[:10].upper()}",
            "requires_human": _requires_human(payload.action, payload.confidence, payload.requires_human),
            "created_at": now,
            "updated_at": now,
        }
    )
    await db["agent_decisions"].insert_one(doc)
    doc.pop("_id", None)
    return doc


def _client_decision(email: Dict[str, Any]) -> Optional[AgentDecisionCreate]:
    extracted = email.get("extracted") or {}
    email_id = _clean(email.get("email_id"))
    if not email_id:
        return None
    missing = []
    if not _clean(extracted.get("technology_needed") or extracted.get("domain")):
        missing.append("technology")
    if not _clean(extracted.get("duration_days") or extracted.get("duration_hours")):
        missing.append("duration")
    if not _clean(extracted.get("budget_total") or extracted.get("budget_per_day") or email.get("budget")):
        missing.append("budget")
    confidence = float(email.get("auto_send_confidence") or email.get("confidence") or extracted.get("confidence") or 0.65)
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
        confidence=max(confidence, 0.8),
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
    client_emails = await db["client_emails"].find(
        {"deleted": {"$ne": True}},
        {"_id": 0},
    ).sort("updated_at", -1).limit(limit).to_list(limit)
    requirements = await db["requirements"].find({}, {"_id": 0}).sort("updated_at", -1).limit(limit).to_list(limit)
    interviews = await db["email_logs"].find(
        {"interview_scheduled": True},
        {"_id": 0},
    ).sort("interview_at", -1).limit(limit).to_list(limit)

    candidates: List[Optional[AgentDecisionCreate]] = []
    candidates.extend(_client_decision(item) for item in client_emails)
    candidates.extend(_commercial_decision(item) for item in requirements)
    candidates.extend(_interview_decision(item) for item in interviews)

    for candidate in candidates:
        if not candidate:
            continue
        existing = await db["agent_decisions"].find_one(
            {
                "agent_role": candidate.agent_role,
                "entity_type": candidate.entity_type,
                "entity_id": candidate.entity_id,
                "decision": candidate.decision,
            },
            {"_id": 0},
        )
        if existing:
            continue
        decisions.append(await _log_decision(db, candidate))

    return {"success": True, "created": len(decisions), "decisions": decisions}


@router.get("/summary")
async def agent_summary(db: AsyncIOMotorDatabase = Depends(get_db)):
    total = await db["agent_decisions"].count_documents({})
    needs_review = await db["agent_decisions"].count_documents({"requires_human": True})
    by_role = []
    pipeline = [
        {"$group": {"_id": "$agent_role", "count": {"$sum": 1}, "review": {"$sum": {"$cond": ["$requires_human", 1, 0]}}}},
        {"$sort": {"count": -1}},
    ]
    async for row in db["agent_decisions"].aggregate(pipeline):
        by_role.append({"agent_role": row["_id"], "count": row["count"], "requires_human": row["review"]})
    recent = await db["agent_decisions"].find({}, {"_id": 0}).sort("created_at", -1).limit(10).to_list(10)
    return {"success": True, "total": total, "requires_human": needs_review, "by_role": by_role, "recent": recent}
