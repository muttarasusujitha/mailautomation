"""Requirement-aligned trainer profile enhancement with explicit fact approval."""
import json
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from app.config import get_settings
from shared.database.service import get_db

router = APIRouter()


class AnalyzeProfileRequest(BaseModel):
    requirement_id: str
    trainer_id: str


class ApproveProfileRequest(BaseModel):
    approved_suggestion_ids: List[str] = Field(default_factory=list)
    edited_bullets: Dict[str, str] = Field(default_factory=dict)
    confirmed_by: str = "internal_review"


class ConfirmProfileRequest(BaseModel):
    confirmed_bullets: Dict[str, str] = Field(default_factory=dict)
    confirmed_by: str
    confirmation_source: str = "trainer_email_or_call"


def _text(source: Dict[str, Any], *keys: str) -> str:
    values = []
    for key in keys:
        value = source.get(key)
        if isinstance(value, list):
            values.extend(str(item) for item in value if item)
        elif value:
            values.append(str(value))
    return "\n".join(values)


def _requirement_text(requirement: Dict[str, Any]) -> str:
    return _text(
        requirement,
        "technology_needed", "technology", "domain", "job_title", "description",
        "client_request_text", "original_client_request", "required_skills", "skills",
        "topics", "requested_details", "audience_level", "mode",
    )


def _resume_text(trainer: Dict[str, Any]) -> str:
    return _text(
        trainer,
        "resume", "combined_text", "raw_text", "summary", "bio", "skills",
        "technologies", "experience", "projects", "certifications",
    )


def _keywords(value: str) -> List[str]:
    stop = {
        "and", "the", "for", "with", "from", "this", "that", "training", "trainer",
        "requirement", "experience", "years", "client", "skills", "knowledge", "using",
        "preferred", "needed", "workshop", "course", "team", "days", "online", "offline",
    }
    tokens = re.findall(r"[a-z][a-z0-9+#.-]{2,}", value.lower())
    return list(dict.fromkeys(token for token in tokens if token not in stop))[:80]


def _fallback_analysis(requirement: Dict[str, Any], trainer: Dict[str, Any]) -> Dict[str, Any]:
    required = _keywords(_requirement_text(requirement))
    resume_lower = _resume_text(trainer).lower()
    confirmed = [skill for skill in required if skill in resume_lower]
    missing = [skill for skill in required if skill not in resume_lower]
    suggestions = []
    for skill in confirmed[:12]:
        suggestions.append({
            "id": f"S-{len(suggestions)+1}",
            "skill": skill,
            "evidence_status": "confirmed",
            "resume_evidence": f"The original profile contains '{skill}'.",
            "source_section": "Original trainer profile",
            "match_strength": "strong",
            "experience_depth": "keyword evidence; reviewer should verify practical depth",
            "suggested_bullet": f"Applied {skill} in relevant delivery, implementation, or training assignments.",
            "requires_trainer_confirmation": False,
        })
    for skill in missing[:12]:
        suggestions.append({
            "id": f"S-{len(suggestions)+1}",
            "skill": skill,
            "evidence_status": "missing",
            "resume_evidence": "No supporting statement was found in the original profile.",
            "source_section": "Not found",
            "match_strength": "not_available",
            "experience_depth": "no evidence available",
            "suggested_bullet": "",
            "requires_trainer_confirmation": True,
        })
    return {"confirmed_skills": confirmed, "missing_skills": missing, "suggestions": suggestions}


async def _ai_analysis(requirement: Dict[str, Any], trainer: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    settings = get_settings()
    api_key = str(getattr(settings, "OPENAI_API_KEY", "") or "").strip()
    if not api_key:
        return None
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key)
        response = await client.responses.create(
            model=str(getattr(settings, "OPENAI_MODEL", "gpt-5.5") or "gpt-5.5"),
            reasoning={"effort": "low"},
            text={
                "format": {
                    "type": "json_schema",
                    "name": "profile_gap_analysis",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "confirmed_skills": {"type": "array", "items": {"type": "string"}},
                            "missing_skills": {"type": "array", "items": {"type": "string"}},
                            "suggestions": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "string"},
                                        "skill": {"type": "string"},
                                        "evidence_status": {"type": "string", "enum": ["confirmed", "related", "missing"]},
                                        "resume_evidence": {"type": "string"},
                                        "source_section": {"type": "string"},
                                        "match_strength": {"type": "string", "enum": ["strong", "partial", "confirmation_required", "not_available"]},
                                        "experience_depth": {"type": "string"},
                                        "suggested_bullet": {"type": "string"},
                                        "requires_trainer_confirmation": {"type": "boolean"},
                                    },
                                    "required": ["id", "skill", "evidence_status", "resume_evidence", "source_section", "match_strength", "experience_depth", "suggested_bullet", "requires_trainer_confirmation"],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": ["confirmed_skills", "missing_skills", "suggestions"],
                        "additionalProperties": False,
                    },
                },
                "verbosity": "low",
            },
            instructions=(
                "Compare a trainer's original resume with a client requirement. Suggest concise resume bullets "
                "only when supported by quoted or clearly related resume evidence. Never invent employers, dates, "
                "clients, certifications, projects, metrics, or hands-on/training experience. Mark unsupported "
                "requirements as missing and requiring trainer confirmation; leave their suggested_bullet empty. "
                "For related evidence, use cautious wording and require confirmation."
                " For every item identify the resume section or project containing the evidence, classify match "
                "strength, and describe whether evidence shows only a keyword or practical project/training depth."
            ),
            input=(
                "CLIENT REQUIREMENT:\n" + _requirement_text(requirement)[:12000]
                + "\n\nORIGINAL TRAINER PROFILE:\n" + _resume_text(trainer)[:30000]
            ),
            max_output_tokens=3000,
        )
        return json.loads(response.output_text)
    except Exception:
        return None


async def _records(db: AsyncIOMotorDatabase, requirement_id: str, trainer_id: str):
    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
    trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0}) or {}
    if not requirement:
        raise HTTPException(404, "Requirement not found")
    if not trainer or not _resume_text(trainer).strip():
        shortlist = await db["shortlists"].find_one(
            {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
            {"_id": 0, "top_trainers": 1},
        ) or {}
        shortlist_trainer = next(
            (item for item in shortlist.get("top_trainers") or [] if item.get("trainer_id") == trainer_id),
            {},
        )
        if shortlist_trainer:
            trainer = {**trainer, **shortlist_trainer}
    if not trainer:
        raise HTTPException(404, "Trainer profile not found")
    if not _resume_text(trainer).strip():
        raise HTTPException(400, "Trainer's original resume/profile text is not available yet")
    return requirement, trainer


@router.post("/analyze")
async def analyze_profile(payload: AnalyzeProfileRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    requirement, trainer = await _records(db, payload.requirement_id, payload.trainer_id)
    analysis = await _ai_analysis(requirement, trainer) or _fallback_analysis(requirement, trainer)
    now = datetime.utcnow()
    enhancement_id = f"PE-{uuid.uuid4().hex[:10].upper()}"
    doc = {
        "enhancement_id": enhancement_id,
        "requirement_id": payload.requirement_id,
        "trainer_id": payload.trainer_id,
        "trainer_name": trainer.get("name") or trainer.get("trainer_name") or "Trainer",
        "status": "pending_confirmation",
        "original_profile_preserved": True,
        "analysis": analysis,
        "created_at": now,
        "updated_at": now,
    }
    await db["profile_enhancements"].update_one(
        {"requirement_id": payload.requirement_id, "trainer_id": payload.trainer_id},
        {"$set": doc},
        upsert=True,
    )
    return {"success": True, "enhancement": doc}


@router.post("/{requirement_id}/{trainer_id}/confirm")
async def confirm_profile_evidence(
    requirement_id: str,
    trainer_id: str,
    payload: ConfirmProfileRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Record new claims supplied by the trainer; never infer confirmation from an operator click."""
    doc = await db["profile_enhancements"].find_one(
        {"requirement_id": requirement_id, "trainer_id": trainer_id}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Run profile analysis first")
    if not payload.confirmed_by.strip():
        raise HTTPException(400, "Trainer name or confirmation reference is required")
    suggestions = (doc.get("analysis") or {}).get("suggestions") or []
    confirmed_ids = []
    for item in suggestions:
        statement = str(payload.confirmed_bullets.get(item.get("id")) or "").strip()
        if not statement or not item.get("requires_trainer_confirmation"):
            continue
        item.update({
            "resume_evidence": statement,
            "source_section": f"Trainer confirmation: {payload.confirmation_source}",
            "match_strength": "strong",
            "experience_depth": "trainer-confirmed; client-specific claim",
            "suggested_bullet": statement,
            "evidence_status": "confirmed",
            "requires_trainer_confirmation": False,
            "trainer_confirmed_by": payload.confirmed_by.strip(),
        })
        confirmed_ids.append(item.get("id"))
    if not confirmed_ids:
        raise HTTPException(400, "Enter at least one trainer-provided confirmation statement")
    now = datetime.utcnow()
    await db["profile_enhancements"].update_one(
        {"requirement_id": requirement_id, "trainer_id": trainer_id},
        {"$set": {"analysis.suggestions": suggestions, "status": "review_pending", "updated_at": now}},
    )
    audit = {
        "event_id": f"PA-{uuid.uuid4().hex[:10].upper()}", "event": "trainer_evidence_confirmed",
        "requirement_id": requirement_id, "trainer_id": trainer_id,
        "suggestion_ids": confirmed_ids, "actor": payload.confirmed_by.strip(),
        "source": payload.confirmation_source, "created_at": now,
    }
    await db["profile_enhancement_audit"].insert_one(audit)
    return {"success": True, "confirmed_count": len(confirmed_ids), "enhancement": {**doc, "analysis": {**(doc.get("analysis") or {}), "suggestions": suggestions}, "status": "review_pending", "updated_at": now}}


@router.get("/{requirement_id}/{trainer_id}")
async def get_profile_enhancement(requirement_id: str, trainer_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    doc = await db["profile_enhancements"].find_one(
        {"requirement_id": requirement_id, "trainer_id": trainer_id}, {"_id": 0}
    )
    return {"success": True, "enhancement": doc}


@router.post("/{requirement_id}/{trainer_id}/approve")
async def approve_profile_enhancement(
    requirement_id: str,
    trainer_id: str,
    payload: ApproveProfileRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    doc = await db["profile_enhancements"].find_one(
        {"requirement_id": requirement_id, "trainer_id": trainer_id}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Run profile analysis first")
    suggestions = (doc.get("analysis") or {}).get("suggestions") or []
    approved = []
    selected = set(payload.approved_suggestion_ids)
    for item in suggestions:
        if item.get("id") not in selected:
            continue
        if item.get("requires_trainer_confirmation"):
            continue
        bullet = str(payload.edited_bullets.get(item.get("id")) or item.get("suggested_bullet") or "").strip()
        if bullet:
            approved.append({**item, "approved_bullet": bullet})
    now = datetime.utcnow()
    update = {
        "status": "approved",
        "approved_suggestions": approved,
        "approved_bullets": [item["approved_bullet"] for item in approved],
        "confirmed_by": payload.confirmed_by,
        "approved_at": now,
        "updated_at": now,
    }
    await db["profile_enhancements"].update_one(
        {"requirement_id": requirement_id, "trainer_id": trainer_id}, {"$set": update}
    )
    await db["shortlists"].update_one(
        {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
        {"$set": {
            "top_trainers.$.profile_enhancement_status": "approved",
            "top_trainers.$.approved_profile_bullets": update["approved_bullets"],
            "top_trainers.$.profile_enhancement_id": doc.get("enhancement_id"),
            "updated_at": now,
        }},
    )
    version = {
        "version_id": f"PV-{uuid.uuid4().hex[:10].upper()}",
        "enhancement_id": doc.get("enhancement_id"), "requirement_id": requirement_id,
        "trainer_id": trainer_id, "approved_suggestions": approved,
        "approved_bullets": update["approved_bullets"], "approved_by": payload.confirmed_by,
        "created_at": now, "master_profile_modified": False,
    }
    await db["profile_versions"].insert_one(version)
    await db["profile_enhancement_audit"].insert_one({
        "event_id": f"PA-{uuid.uuid4().hex[:10].upper()}", "event": "profile_version_approved",
        "requirement_id": requirement_id, "trainer_id": trainer_id,
        "version_id": version["version_id"], "suggestion_ids": list(selected),
        "actor": payload.confirmed_by, "created_at": now,
    })
    version.pop("_id", None)
    return {"success": True, "approved_count": len(approved), "profile_version": version, "enhancement": {**doc, **update}}
