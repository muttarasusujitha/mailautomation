import asyncio
import hashlib
import json
import logging
import math
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
import httpx
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from shared.database.service import get_db
from app.config import get_settings

router = APIRouter()
settings = get_settings()
logger = logging.getLogger(__name__)

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

AGENTIC_LLM_ROLES = set(AGENT_ROLES)


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
        find_one = getattr(db["agent_decisions"], "find_one", None)
        existing = await find_one({"_id": doc["_id"]}, {"_id": 0}) if find_one else None
        # A failed dispatch remains retryable; a queued/completed decision is
        # never enqueued twice by repeated orchestrator runs.
        if existing and existing.get("status") == "execution_failed":
            return existing
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
    raw_interview_at = log.get("interview_at")
    if not link or not raw_interview_at:
        return None
    parsed_link = urlparse(link)
    if parsed_link.scheme != "https" or parsed_link.hostname != "meet.google.com":
        return None
    try:
        interview_at = raw_interview_at if isinstance(raw_interview_at, datetime) else datetime.fromisoformat(str(raw_interview_at).replace("Z", "+00:00"))
        if interview_at.tzinfo is None:
            interview_at = interview_at.replace(tzinfo=timezone.utc)
        if interview_at <= datetime.now(timezone.utc):
            return None
    except (TypeError, ValueError):
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
            "interview_at": interview_at.isoformat(),
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
    dry_run: bool = Query(False),
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
        if dry_run:
            decision = candidate.model_dump()
            decision["requires_human"] = _requires_human(candidate.action, candidate.confidence, candidate.requires_human)
            decision["status"] = "planned"
            if candidate.action == "send_reminder" and not decision["requires_human"]:
                decision["action_execution"] = {"success": True, "dry_run": True, "status": "would_queue"}
            decisions.append(decision)
            continue
        decision = await _log_decision(db, candidate, deduplicate=True)
        if decision:
            if candidate.action == "send_reminder" and not decision.get("requires_human"):
                decision["action_execution"] = await _queue_interview_notice(candidate)
                decision["status"] = "queued" if decision["action_execution"].get("success") else "execution_failed"
                decision["updated_at"] = _now()
                await db["agent_decisions"].update_one(
                    {"decision_id": decision["decision_id"]},
                    {"$set": {
                        "status": decision["status"],
                        "action_execution": decision["action_execution"],
                        "updated_at": decision["updated_at"],
                    }},
                )
            decisions.append(decision)

    await _attach_agentic_wording(db, decisions, dry_run)

    return {
        "success": True,
        "dry_run": dry_run,
        "generation_mode": await _generation_mode(db),
        "created": len(decisions) if not dry_run else 0,
        "previewed": len(decisions) if dry_run else 0,
        "would_queue": sum(
            decision.get("action_execution", {}).get("status") == "would_queue"
            for decision in decisions
        ) if dry_run else 0,
        "decisions": decisions,
    }


async def _generation_mode(db: AsyncIOMotorDatabase) -> str:
    try:
        setting = await db["automation_settings"].find_one({"key": "generation_mode"}, {"_id": 0}) or {}
    except Exception:
        return "template"
    mode = _clean(setting.get("value")).lower()
    return mode if mode in {"ai", "template"} else "template"


async def _pending_llm_decisions(db: AsyncIOMotorDatabase) -> List[Dict[str, Any]]:
    try:
        cursor = db["agent_decisions"].find(
            {"agent_role": {"$in": list(AGENTIC_LLM_ROLES)}, "metadata.llm": {"$exists": False}},
            {"_id": 0},
        ).sort("created_at", -1).limit(8)
        return await cursor.to_list(8)
    except Exception:
        logger.warning("Could not load agent decisions that still need AI wording")
        return []


async def _fetch_agentic_wording(decisions: List[Dict[str, Any]]) -> Dict[tuple, Dict[str, str]]:
    """Ask the application LLM for client, shortlist, and TOC notes."""
    compact = []
    for item in decisions[:8]:
        compact.append({
            "agent_role": item.get("agent_role"),
            "entity_id": item.get("entity_id"),
            "observation": item.get("observation"),
            "decision": item.get("decision"),
            "reason": item.get("reason"),
            "metadata": item.get("metadata") or {},
        })
    prompt = (
        "For each decision, write short operational notes from the supplied facts only. "
        "This covers every application agent: client requirements, trainer matching, outreach, "
        "commercials, interview scheduling, and exception review. "
        "Return a JSON array. Each item must include agent_role, entity_id, client_text, "
        "shortlist_note, and toc_note. client_text is one client-facing sentence. "
        "shortlist_note explains the trainer shortlist or the operational next step. "
        "toc_note says whether a table of contents should be drafted from the known scope. "
        "Repeat only prices, dates, slots, and names that are already in the decision. "
        "Do not invent prices, dates, trainer names, selections, or attachments. "
        "Use an empty string when a note does not apply.\n"
        + json.dumps(compact, default=str)
    )
    url = settings.INTELLIGENCE_SERVICE_URL.rstrip("/") + "/api/v1/assistant/chat"
    try:
        async with httpx.AsyncClient(timeout=40) as client:
            response = await client.post(url, json={
                "messages": [{"role": "user", "content": prompt}],
                "system_prompt": "You draft grounded training-workflow notes. Return JSON only.",
                "max_tokens": 900,
                "temperature": 0.2,
            })
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        logger.warning("Agentic AI wording unavailable: %s", exc)
        return {}
    if not payload.get("success"):
        return {}
    reply = str(payload.get("reply") or "")
    match = re.search(r"\[[\s\S]*\]", reply)
    if not match:
        return {}
    try:
        rows = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    mapped: Dict[tuple, Dict[str, str]] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        mapped[(_clean(row.get("agent_role")), _clean(row.get("entity_id")))] = {
            "client_text": _clean(row.get("client_text"))[:1200],
            "shortlist_note": _clean(row.get("shortlist_note"))[:1200],
            "toc_note": _clean(row.get("toc_note"))[:1200],
            "provider": "llm",
        }
    return mapped


async def _attach_agentic_wording(db: AsyncIOMotorDatabase, decisions: List[Dict[str, Any]], dry_run: bool) -> None:
    """Use the LLM for client, shortlist, and TOC notes only when AI generation is on."""
    if await _generation_mode(db) != "ai":
        return
    targets = [item for item in decisions if item.get("agent_role") in AGENTIC_LLM_ROLES and not (item.get("metadata") or {}).get("llm")]
    if not dry_run:
        seen = {(item.get("agent_role"), item.get("entity_id"), item.get("decision_id")) for item in targets}
        for item in await _pending_llm_decisions(db):
            key = (item.get("agent_role"), item.get("entity_id"), item.get("decision_id"))
            if key not in seen and not (item.get("metadata") or {}).get("llm"):
                targets.append(item)
                seen.add(key)
    targets = targets[:8]
    if not targets:
        return
    wording = await _fetch_agentic_wording(targets)
    for item in targets:
        note = wording.get((_clean(item.get("agent_role")), _clean(item.get("entity_id"))))
        metadata = dict(item.get("metadata") or {})
        if note:
            metadata["llm"] = note
            item["metadata"] = metadata
            if not dry_run and item.get("decision_id"):
                await db["agent_decisions"].update_one(
                    {"decision_id": item["decision_id"]},
                    {"$set": {"metadata": metadata, "updated_at": _now()}},
                )
        else:
            metadata["llm_status"] = "unavailable"
            item["metadata"] = metadata


async def _queue_interview_notice(candidate: AgentDecisionCreate) -> Dict[str, Any]:
    """Queue the existing due-only, idempotent scheduler task for safe reminders."""
    if not settings.INTERNAL_SERVICE_TOKEN:
        return {"success": False, "error": "internal_service_token_not_configured"}
    url = settings.SCHEDULER_SERVICE_URL.rstrip("/") + "/api/v1/scheduler/tasks/agent-interview-notices"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, headers={"X-Internal-Service-Token": settings.INTERNAL_SERVICE_TOKEN})
            response.raise_for_status()
            data = response.json()
        return {"success": True, "task_id": data.get("task_id"), "task_name": data.get("task_name")}
    except Exception as exc:
        logger.warning("Could not queue interview notice: %s", exc)
        return {"success": False, "error": "scheduler_unavailable"}


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
