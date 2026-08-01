import re
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId
from datetime import datetime

from app.database import get_db

router = APIRouter()


EXCLUDED_TRAINER_STATUSES = {"interested", "confirmed", "declined"}
PIPELINE_VERSION = "trainer-match-microservice-v1"


def _public_doc(doc: Optional[dict]) -> Optional[dict]:
    if not doc:
        return None
    public = dict(doc)
    if "_id" in public:
        public["_id"] = str(public["_id"])
        public.setdefault("id", public["_id"])
    return public


def _requirement_query(req_id: str) -> dict:
    clauses: List[dict] = [{"requirement_id": req_id}]
    if ObjectId.is_valid(req_id):
        clauses.append({"_id": ObjectId(req_id)})
    return {"$or": clauses}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw = value
    elif isinstance(value, (tuple, set)):
        raw = list(value)
    elif isinstance(value, str):
        raw = re.split(r",|;|\n|\|", value)
    else:
        raw = [value]
    cleaned: List[str] = []
    seen = set()
    for item in raw:
        text = _clean(item)
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            cleaned.append(text)
    return cleaned


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _norm(value: Any) -> str:
    if isinstance(value, list):
        value = " ".join(_clean(item) for item in value)
    elif isinstance(value, dict):
        value = " ".join(f"{key} {val}" for key, val in value.items())
    return re.sub(r"[^a-z0-9+#.]+", " ", _clean(value).lower()).strip()


def _tokens(value: Any) -> set[str]:
    return {token for token in _norm(value).split() if len(token) > 1}


def _profile_text(trainer: Dict[str, Any]) -> str:
    parts = [
        trainer.get("name"),
        trainer.get("trainer_name"),
        trainer.get("title"),
        trainer.get("role_designation"),
        trainer.get("technologies"),
        trainer.get("skills"),
        trainer.get("certifications"),
        trainer.get("primary_category"),
        trainer.get("technology_category"),
        trainer.get("category"),
        trainer.get("domain"),
        trainer.get("secondary_categories"),
        trainer.get("specialisation_tags"),
        trainer.get("specialty_tags"),
        trainer.get("industry_focus"),
        trainer.get("summary"),
        trainer.get("past_clients"),
        trainer.get("combined_text", "")[:8000] if isinstance(trainer.get("combined_text"), str) else "",
        trainer.get("resume", "")[:5000] if isinstance(trainer.get("resume"), str) else "",
    ]
    return _norm(parts)


def _category_text(trainer: Dict[str, Any]) -> str:
    return _norm([
        trainer.get("primary_category"),
        trainer.get("technology_category"),
        trainer.get("category"),
        trainer.get("domain"),
        trainer.get("secondary_categories"),
        trainer.get("specialisation_tags"),
        trainer.get("specialty_tags"),
        trainer.get("technologies"),
        trainer.get("skills"),
    ])


def _trainer_experience(trainer: Dict[str, Any]) -> float:
    direct = _safe_float(trainer.get("experience_years"), -1)
    if direct >= 0:
        return direct
    raw = " ".join([
        _clean(trainer.get("experience_raw")),
        _clean(trainer.get("summary")),
        _clean(trainer.get("resume")),
    ])
    match = re.search(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)", raw, flags=re.IGNORECASE)
    return _safe_float(match.group(1), 0.0) if match else 0.0


def _has_resume(trainer: Dict[str, Any]) -> bool:
    return bool(
        trainer.get("resume")
        or trainer.get("resume_url")
        or trainer.get("upload_id")
        or trainer.get("source_sheet") == "resume_upload"
    )


def _quality(score: float) -> str:
    if score >= 80:
        return "excellent"
    if score >= 60:
        return "strong"
    if score >= 40:
        return "good"
    return "exploratory"


def _term_matches(terms: List[str], text: str) -> List[str]:
    matches: List[str] = []
    for term in terms:
        norm = _norm(term)
        if norm and f" {norm} " in f" {text} ":
            matches.append(term)
    return matches


def _score_trainer(trainer: Dict[str, Any], requirement: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if requirement.get("must_have_linkedin") and not trainer.get("linkedin"):
        return None
    if requirement.get("must_have_resume") and not _has_resume(trainer):
        return None

    technology = _clean(
        requirement.get("technology_needed")
        or requirement.get("domain")
        or requirement.get("title")
        or requirement.get("job_title")
    )
    required_skills = _as_list(requirement.get("required_skills") or requirement.get("skills"))
    preferred_skills = _as_list(requirement.get("preferred_skills"))
    required_terms = [term for term in [technology, *required_skills] if term]

    profile = _profile_text(trainer)
    category = _category_text(trainer)
    score = 0.0
    breakdown: Dict[str, Any] = {}

    technology_tokens = _tokens(technology)
    category_tokens = set(category.split())
    profile_tokens = set(profile.split())
    if technology:
        norm_technology = _norm(technology)
        if f" {norm_technology} " in f" {category} ":
            tech_score = 35.0
        elif f" {norm_technology} " in f" {profile} ":
            tech_score = 28.0
        else:
            overlap = len(technology_tokens & (category_tokens | profile_tokens)) / max(len(technology_tokens), 1)
            tech_score = 18.0 * overlap
        score += tech_score
        breakdown["technology"] = round(tech_score, 2)

    required_matches = _term_matches(required_skills, profile)
    if required_skills:
        skill_score = 25.0 * (len(required_matches) / max(len(required_skills), 1))
    elif not technology:
        skill_score = 8.0
    else:
        skill_score = 0.0
    preferred_matches = _term_matches(preferred_skills, profile)
    skill_score += min(8.0, 2.0 * len(preferred_matches))
    score += skill_score
    breakdown["skills"] = round(skill_score, 2)
    breakdown["matched_required_skills"] = required_matches
    breakdown["matched_preferred_skills"] = preferred_matches

    min_exp = _safe_float(requirement.get("min_experience_years"), 0.0)
    exp = _trainer_experience(trainer)
    if min_exp > 0:
        exp_score = 15.0 if exp >= min_exp else 10.0 * (exp / max(min_exp, 1.0))
    else:
        exp_score = min(exp * 1.5, 15.0)
    score += exp_score
    breakdown["experience"] = round(exp_score, 2)

    preferred_location = _clean(requirement.get("preferred_location") or requirement.get("location"))
    trainer_location = _clean(trainer.get("location"))
    location_score = 0.0
    if preferred_location and trainer_location:
        location_score = 10.0 if _norm(preferred_location) in _norm(trainer_location) else 0.0
    score += location_score
    breakdown["location"] = round(location_score, 2)

    credibility_score = 0.0
    if trainer.get("linkedin"):
        credibility_score += 2.0
    if _has_resume(trainer):
        credibility_score += 3.0
    if _as_list(trainer.get("certifications")):
        credibility_score += 2.0
    if trainer.get("training_count") or trainer.get("past_clients"):
        credibility_score += 2.0
    credibility_score += min(_safe_float(trainer.get("resume_rank_score"), 0.0) * 0.1, 3.0)
    score += credibility_score
    breakdown["credibility"] = round(credibility_score, 2)

    if required_terms and not _term_matches(required_terms, profile) and score < 20:
        return None

    public = {k: v for k, v in trainer.items() if k not in {"_id", "combined_text"}}
    public["trainer_id"] = _clean(public.get("trainer_id")) or f"TR-{uuid.uuid4().hex[:8].upper()}"
    public["name"] = _clean(public.get("name") or public.get("trainer_name") or "Trainer")
    public["email"] = _clean(public.get("email") or public.get("trainer_email"))
    public["title"] = _clean(public.get("role_designation") or public.get("title"))
    public["technologies"] = _clean(public.get("technologies") or public.get("technology_category") or public.get("domain"))
    public["experience_years"] = exp
    public["match_score"] = round(min(score, 100.0), 2)
    public["score_breakdown"] = breakdown
    public["match_quality"] = _quality(public["match_score"])
    public["recommended_next_action"] = "Contact trainer and confirm availability"
    return public


def _normalise_requirement_payload(payload: Dict[str, Any], existing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = dict(existing or {})
    data.update({k: v for k, v in payload.items() if v is not None})

    technology = _clean(
        data.get("technology_needed")
        or data.get("domain")
        or data.get("title")
        or data.get("job_title")
    )
    if not technology:
        raise HTTPException(400, "Technology / domain is required")

    data["technology_needed"] = technology
    data.setdefault("title", data.get("job_title") or f"{technology} Trainer")
    data.setdefault("domain", technology)
    data["required_skills"] = _as_list(data.get("required_skills") or data.get("skills") or [technology])
    data["preferred_skills"] = _as_list(data.get("preferred_skills"))
    data["required_certifications"] = _as_list(data.get("required_certifications"))
    data["client_name"] = _clean(data.get("client_name") or data.get("client_company"))
    data["client_company"] = _clean(data.get("client_company") or data.get("client_name"))
    data["client_email"] = _clean(data.get("client_email"))
    data["client_phone"] = _clean(data.get("client_phone"))
    data["client_whatsapp"] = _clean(data.get("client_whatsapp"))
    data["timeline_start"] = _clean(data.get("timeline_start"))
    data["timeline_end"] = _clean(data.get("timeline_end"))
    data["timing"] = _clean(data.get("timing"))
    data["preferred_location"] = _clean(data.get("preferred_location") or data.get("location"))
    data["top_n"] = max(1, min(_safe_int(data.get("top_n"), 5), 20))
    data["min_experience_years"] = _safe_int(data.get("min_experience_years"), 2)
    data["send_emails"] = bool(data.get("send_emails", False))
    data.setdefault("status", "active")
    data.setdefault("priority", "medium")
    data.setdefault("customer_id", data.get("client_email") or "manual")
    data.setdefault("metadata", {})

    if not data.get("training_dates") and (data["timeline_start"] or data["timeline_end"]):
        data["training_dates"] = " to ".join(part for part in [data["timeline_start"], data["timeline_end"]] if part)
    for field in ("duration_days", "duration_hours", "budget"):
        if data.get(field) not in (None, ""):
            data[field] = _safe_float(data.get(field), 0.0)
    if not data.get("duration_days") and data.get("duration_hours"):
        data["duration_days"] = max(1, round(_safe_float(data["duration_hours"]) / 7, 2))
    return data


def _merge_pipeline_state(new_trainer: Dict[str, Any], old_trainer: Dict[str, Any]) -> Dict[str, Any]:
    preserve_keys = {
        "pipeline_status",
        "status",
        "last_mail_type",
        "last_mailed_at",
        "email_stage",
        "reply_received",
        "reply_text",
        "reply_sentiment",
        "slots",
        "selected",
        "client_slot_sent",
        "client_slot_sent_at",
        "commercial_status",
        "toc_status",
        "interview_date",
        "interview_link",
    }
    merged = dict(new_trainer)
    for key, value in old_trainer.items():
        if key in preserve_keys or key.startswith("last_") or key.endswith("_at"):
            merged[key] = value
    return merged


async def _build_shortlist_for_requirement(
    db: AsyncIOMotorDatabase,
    requirement: Dict[str, Any],
) -> Dict[str, Any]:
    req_id = requirement.get("requirement_id")
    if not req_id:
        raise HTTPException(400, "Requirement id missing")

    all_trainers = await db["trainers"].find({}, {"_id": 0}).to_list(10000)
    available_trainers = [
        trainer for trainer in all_trainers
        if _clean(trainer.get("status")).lower() not in EXCLUDED_TRAINER_STATUSES
    ]
    scored = [
        scored_trainer
        for trainer in available_trainers
        if (scored_trainer := _score_trainer(trainer, requirement)) is not None
    ]
    scored.sort(
        key=lambda trainer: (
            _safe_float(trainer.get("match_score"), 0),
            _safe_float(trainer.get("experience_years"), 0),
            1 if trainer.get("email") else 0,
        ),
        reverse=True,
    )

    top_n = max(1, min(_safe_int(requirement.get("top_n"), 5), 20))
    top_trainers = scored[:top_n]
    existing = await db["shortlists"].find_one({"requirement_id": req_id}, {"_id": 0}) or {}
    old_by_id = {
        _clean(trainer.get("trainer_id")): trainer
        for trainer in existing.get("top_trainers", [])
        if trainer.get("trainer_id")
    }
    for index, trainer in enumerate(top_trainers, start=1):
        trainer["rank"] = index
        trainer["pipeline_status"] = trainer.get("pipeline_status") or "shortlisted"
        old = old_by_id.get(_clean(trainer.get("trainer_id")))
        if old:
            trainer.update(_merge_pipeline_state(trainer, old))

    now = datetime.utcnow()
    warnings = [] if all_trainers else ["No trainers available in database."]
    shortlist_doc = {
        "shortlist_id": existing.get("shortlist_id") or f"SL-{uuid.uuid4().hex[:8].upper()}",
        "requirement_id": req_id,
        "technology_needed": requirement.get("technology_needed", ""),
        "top_trainers": top_trainers,
        "total_matched": len(scored),
        "total_trainers_scanned": len(all_trainers),
        "total_available": len(available_trainers),
        "category_filter_applied": False,
        "no_category_match": bool(requirement.get("technology_needed")) and len(scored) == 0,
        "category_match_count": len(scored),
        "pipeline_summary": {
            "pipeline_version": PIPELINE_VERSION,
            "status": "completed",
            "total_candidates": len(available_trainers),
            "ranked_count": len(scored),
            "top_count": len(top_trainers),
            "warnings": warnings,
            "errors": [],
        },
        "pipeline_stage_log": [
            {
                "stage": "microservice_matching",
                "status": "completed",
                "detail": {
                    "total_trainers_scanned": len(all_trainers),
                    "available_trainers": len(available_trainers),
                    "ranked_count": len(scored),
                    "top_count": len(top_trainers),
                },
                "at": now.isoformat(),
            }
        ],
        "matching_pipeline_version": PIPELINE_VERSION,
        "pipeline_warnings": warnings,
        "pipeline_errors": [],
        "auto_created": True,
        "updated_at": now,
        "created_at": existing.get("created_at") or now,
    }

    set_doc = {k: v for k, v in shortlist_doc.items() if k not in {"shortlist_id", "created_at"}}
    await db["shortlists"].update_one(
        {"requirement_id": req_id},
        {
            "$set": set_doc,
            "$setOnInsert": {
                "shortlist_id": shortlist_doc["shortlist_id"],
                "created_at": shortlist_doc["created_at"],
            },
        },
        upsert=True,
    )
    await db["requirements"].update_one(
        {"requirement_id": req_id},
        {"$set": {
            "total_matched": len(scored),
            "top_count": len(top_trainers),
            "updated_at": now,
        }},
    )
    for trainer in top_trainers:
        trainer_id = trainer.get("trainer_id")
        if not trainer_id:
            continue
        await db["trainers"].update_one(
            {"trainer_id": trainer_id},
            {"$set": {
                "match_score": trainer.get("match_score"),
                "rank": trainer.get("rank"),
                "status": "contacted" if requirement.get("send_emails") else "pending_review",
                "updated_at": now,
            }},
        )
    return shortlist_doc


@router.get("")
async def list_requirements(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    customer_id: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    query: dict = {}
    if customer_id:
        query["customer_id"] = customer_id
    if status:
        query["status"] = status
    total = await db.requirements.count_documents(query)
    skip = (page - 1) * page_size
    cursor = db.requirements.find(query).skip(skip).limit(page_size).sort("created_at", -1)
    items = [_public_doc(d) async for d in cursor]
    pages = max(1, (total + page_size - 1) // page_size)
    return {
        "items": items,
        "requirements": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
    }


@router.post("", status_code=201)
async def create_requirement(
    payload: Dict[str, Any],
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    now = datetime.utcnow()
    doc = _normalise_requirement_payload(payload)
    req_id = doc.get("requirement_id") or f"REQ-{uuid.uuid4().hex[:8].upper()}"
    doc.update({"requirement_id": req_id, "created_at": now, "updated_at": now})
    await db.requirements.insert_one(doc)
    shortlist = await _build_shortlist_for_requirement(db, doc)
    top_trainers = shortlist.get("top_trainers", [])
    return {
        "requirement_id": req_id,
        "client_email": doc.get("client_email", ""),
        "total_trainers_scanned": shortlist.get("total_trainers_scanned", 0),
        "total_available": shortlist.get("total_available", 0),
        "total_matched": shortlist.get("total_matched", 0),
        "top_trainers": len(top_trainers),
        "emails_sent": 0,
        "emails_failed": 0,
        "top_trainers_list": top_trainers,
        "category_filter_applied": shortlist.get("category_filter_applied", False),
        "no_category_match": shortlist.get("no_category_match", False),
        "category_match_count": shortlist.get("category_match_count", 0),
        "pipeline_summary": shortlist.get("pipeline_summary", {}),
        "requirement": _public_doc(await db.requirements.find_one({"requirement_id": req_id})),
    }


@router.get("/{req_id}")
async def get_requirement(
    req_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    doc = await db.requirements.find_one(_requirement_query(req_id))
    if not doc:
        raise HTTPException(404, "Requirement not found")
    return _public_doc(doc)


@router.patch("/{req_id}")
async def update_requirement(
    req_id: str,
    payload: Dict[str, Any],
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    current = await db.requirements.find_one(_requirement_query(req_id))
    if not current:
        raise HTTPException(404, "Requirement not found")
    data = {k: v for k, v in payload.items() if v is not None}
    if not data:
        raise HTTPException(400, "No fields to update")
    if any(key in data for key in ("technology_needed", "domain", "title", "job_title")):
        data = _normalise_requirement_payload(data, current)
    data.pop("_id", None)
    data["updated_at"] = datetime.utcnow()
    result = await db.requirements.update_one(_requirement_query(req_id), {"$set": data})
    if result.matched_count == 0:
        raise HTTPException(404, "Requirement not found")
    updated = await db.requirements.find_one(_requirement_query(req_id))
    return _public_doc(updated)


@router.delete("/{req_id}", status_code=204)
async def delete_requirement(
    req_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    doc = await db.requirements.find_one(_requirement_query(req_id), {"_id": 0, "requirement_id": 1})
    result = await db.requirements.delete_one(_requirement_query(req_id))
    if result.deleted_count == 0:
        raise HTTPException(404, "Requirement not found")
    requirement_id = (doc or {}).get("requirement_id") or req_id
    await db["shortlists"].delete_many({"requirement_id": requirement_id})



# ─── Client PO + budget routes ────────────────────────────────────────────────

from pydantic import BaseModel as _BaseModel
import httpx as _httpx


class ClientPORequest(_BaseModel):
    client_email: str = ""
    client_name: str = ""
    trainer_id: str = ""
    trainer_name: str = ""
    subject: str = ""
    body: str = ""
    notes: str = ""
    training_dates: str = ""


class BudgetIncreaseRequest(_BaseModel):
    current_budget: float = 0.0
    requested_budget: float = 0.0
    reason: str = ""
    client_email: str = ""


class InvoiceFromPORequest(_BaseModel):
    invoice_number: str = ""
    trainer_id: str = ""
    client_email: str = ""
    client_name: str = ""
    client_po_number: str = ""
    client_po_date: str = ""
    client_billing_address: str = ""
    client_gstin: str = ""
    client_pan: str = ""
    training_dates: str = ""
    duration_days: int = 0
    mode: str = ""
    day_rate: float = 0.0
    total_amount: float = 0.0
    gst_rate: float = 18.0
    payment_terms: str = ""
    client_po_notes: str = ""
    technology: str = ""
    course_name: str = ""
    items: List[Dict[str, Any]] = []
    gst_number: str = ""
    invoice_date: str = ""
    due_date: str = ""
    invoice_type: str = ""
    tax_type: str = ""
    hsn_sac: str = ""
    quantity: float = 0.0
    additional_notes: str = ""


@router.post("/{req_id}/request-client-po")
async def request_client_po(
    req_id: str,
    payload: ClientPORequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Send a Purchase Order request email to the client for a requirement."""
    doc = await db.requirements.find_one({"requirement_id": req_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Requirement not found")

    client_email = payload.client_email or doc.get("client_email", "")
    if not client_email:
        raise HTTPException(400, "client_email is required")

    subject = payload.subject or f"Request for Purchase Order"

    if payload.body:
        body = payload.body
    else:
        tech = doc.get('technology_needed') or doc.get('technology') or 'DevOps'
        duration = str(doc.get('duration_days') or doc.get('training_duration') or '10 Days')
        training_dates = payload.training_dates or doc.get('training_dates') or doc.get('timeline_start') or ''
        duration_line = f"- **Duration:** {duration}\n" if duration else ''
        dates_line = f"- **Training Dates:** {training_dates}\n" if training_dates else ''
        day_rate = (str(doc.get('day_rate')) + ' per day') if doc.get('day_rate') else '₹18,000 per day'
        body = (
            f"Dear {payload.client_name or doc.get('client_name') or doc.get('client_company') or 'Client'},\n\n"
            f"Thank you for confirming the **{tech}** training requirement.\n\n"
            f"We have identified a suitable trainer for this engagement.\n\n"
            f"**Training Details:**\n\n"
            f"- **Domain:** {tech}\n"
            f"{duration_line}"
            f"{dates_line}"
            f"- **Commercials:** {day_rate}\n\n"
            f"Kindly share the Purchase Order (PO) at your earliest convenience so that we can proceed with trainer confirmation and the remaining training arrangements.\n\n"
            f"Please let us know if you require any additional information.\n\n"
            f"Regards,\nRecruitment Team\nClahan Technologies"
        )

    try:
        async with _httpx.AsyncClient(timeout=30) as client:
            await client.post(
                "https://email-service:8002/api/v1/email/send",
                json={
                    "to": client_email,
                    "subject": subject,
                    "body": body,
                    "requirement_id": req_id,
                    "mail_type": "client_po_request",
                    "trainer_id": payload.trainer_id,
                    "trainer_name": payload.trainer_name,
                },
            )
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc

    now = datetime.utcnow()
    await db.requirements.update_one(
        {"requirement_id": req_id},
        {"$set": {"client_po_requested": True, "client_po_requested_at": now, "updated_at": now}},
    )
    return {"success": True, "requirement_id": req_id, "sent_to": client_email}


@router.post("/{req_id}/request-client-budget-increase")
async def request_client_budget_increase(
    req_id: str,
    payload: BudgetIncreaseRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Email the client requesting a budget increase for a requirement."""
    doc = await db.requirements.find_one({"requirement_id": req_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Requirement not found")

    client_email = payload.client_email or doc.get("client_email", "")
    if not client_email:
        raise HTTPException(400, "client_email is required")

    subject = f"Budget Increase Request — {req_id}"
    body = (
        f"Dear {doc.get('client_name') or doc.get('client_company') or 'Client'},\n\n"
        f"We are writing regarding training requirement {req_id}.\n\n"
        f"The current approved budget is ₹{payload.current_budget:,.0f}. "
        f"Based on trainer profiles and market rates, we would like to request an "
        f"increase to ₹{payload.requested_budget:,.0f}.\n\n"
        f"Reason: {payload.reason or 'Market rate adjustment required.'}\n\n"
        "Please confirm your approval at your earliest convenience.\n\n"
        "Regards,\nTrainerSync Team"
    )

    try:
        async with _httpx.AsyncClient(timeout=30) as client:
            await client.post(
                "https://email-service:8002/api/v1/email/send",
                json={"to": client_email, "subject": subject, "body": body,
                      "requirement_id": req_id, "mail_type": "budget_increase_request"},
            )
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc

    now = datetime.utcnow()
    await db.requirements.update_one(
        {"requirement_id": req_id},
        {"$set": {
            "budget_increase_requested": True,
            "budget_increase_amount": payload.requested_budget,
            "budget_increase_requested_at": now,
            "updated_at": now,
        }},
    )
    return {"success": True, "requirement_id": req_id, "sent_to": client_email,
            "requested_budget": payload.requested_budget}


@router.post("/{req_id}/client-po/generate-invoice")
async def generate_invoice_from_requirement_po(
    req_id: str,
    payload: InvoiceFromPORequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Generate an invoice from the PO linked to a requirement via trainer-service."""
    doc = await db.requirements.find_one({"requirement_id": req_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Requirement not found")

    # Find linked PO
    po = await db["purchase_orders"].find_one({"requirement_id": req_id}, {"_id": 0})
    if not po:
        trainer_id = payload.trainer_id or doc.get("selected_trainer_id") or f"MANUAL-{req_id}"

        items = payload.items or []
        if not items:
            amount = float(payload.total_amount or 0.0)
            duration = payload.duration_days or doc.get("duration_days") or 1
            if amount <= 0:
                raise HTTPException(400, "Invoice items or total_amount are required when no linked purchase order exists")

            items = [{
                "description": f"{payload.course_name or payload.technology or doc.get('technology_needed') or 'Training'} Training",
                "hsn_sac": "999293",
                "quantity": int(duration) if duration else 1,
                "rate": round(amount / (int(duration) if duration else 1)) if duration else amount,
                "amount": amount,
            }]

        po_payload = {
            "requirement_id": req_id,
            "trainer_id": trainer_id,
            "vendor_name": doc.get("selected_trainer_name", "") or "Manual Invoice",
            "client_name": payload.client_name or doc.get("client_name") or doc.get("client_company", ""),
            "client_email": payload.client_email or doc.get("client_email", ""),
            "client_po_number": payload.client_po_number or doc.get("client_po_number", ""),
            "client_po_date": payload.client_po_date or doc.get("client_po_date", ""),
            "client_billing_address": payload.client_billing_address or doc.get("client_billing_address", ""),
            "client_gstin": payload.client_gstin or doc.get("client_gstin", ""),
            "client_pan": payload.client_pan or doc.get("client_pan", ""),
            "training_domain": payload.technology or payload.course_name or doc.get("technology_needed", ""),
            "training_dates": payload.training_dates or doc.get("training_dates", ""),
            "mode": payload.mode or doc.get("mode", ""),
            "duration": str(payload.duration_days or doc.get("duration_days", "")),
            "day_rate": payload.day_rate,
            "total_amount": payload.total_amount,
            "gst_rate": payload.gst_rate,
            "payment_terms": payload.payment_terms,
            "items": items,
            "notes": payload.client_po_notes or payload.additional_notes or "",
        }

        try:
            async with _httpx.AsyncClient(timeout=30) as client:
                po_resp = await client.post(
                    "https://trainer-service:8004/api/v1/purchase-orders/generate",
                    json=po_payload,
                )
            if po_resp.status_code >= 400:
                raise HTTPException(502, f"Trainer service PO creation error: {po_resp.text[:200]}")
            po = po_resp.json().get("purchase_order") or {}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(502, str(exc)) from exc

    po_id = po.get("po_id", "")
    if not po_id:
        raise HTTPException(502, "Unable to determine purchase order id")
    po_update = {
        "client_name": payload.client_name or po.get("client_name") or doc.get("client_name") or doc.get("client_company", ""),
        "client_email": payload.client_email or po.get("client_email") or doc.get("client_email", ""),
        "client_po_number": payload.client_po_number or po.get("client_po_number") or po.get("po_number", ""),
        "po_number": payload.client_po_number or po.get("po_number") or po_id,
        "client_po_date": payload.client_po_date or po.get("client_po_date", ""),
        "client_billing_address": payload.client_billing_address or po.get("client_billing_address", ""),
        "client_gstin": payload.client_gstin or po.get("client_gstin", ""),
        "client_pan": payload.client_pan or po.get("client_pan", ""),
        "training_domain": payload.technology or payload.course_name or po.get("training_domain") or doc.get("technology_needed", ""),
        "training_dates": payload.training_dates or po.get("training_dates", ""),
        "duration": str(payload.duration_days or po.get("duration") or doc.get("duration_days", "")),
        "mode": payload.mode or po.get("mode", ""),
        "day_rate": payload.day_rate or po.get("day_rate", 0.0),
        "total_amount": payload.total_amount or po.get("total_amount", 0.0),
        "gst_rate": payload.gst_rate,
        "payment_terms": payload.payment_terms or po.get("payment_terms", ""),
        "items": payload.items or po.get("items", []),
        "notes": payload.client_po_notes or payload.additional_notes or po.get("notes", ""),
        "updated_at": datetime.utcnow(),
    }
    await db["purchase_orders"].update_one({"po_id": po_id}, {"$set": po_update})
    try:
        async with _httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"https://trainer-service:8004/api/v1/purchase-orders/{po_id}/generate-invoice",
                json={
                    "invoice_number": payload.invoice_number,
                    "gst_number": payload.gst_number,
                    "invoice_date": payload.invoice_date,
                    "due_date": payload.due_date,
                    "invoice_type": payload.invoice_type,
                    "tax_type": payload.tax_type,
                    "gst_rate": payload.gst_rate,
                    "additional_notes": payload.additional_notes,
                },
            )
        if r.status_code < 400:
            return r.json()
        raise HTTPException(502, f"Trainer service error: {r.text[:200]}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
