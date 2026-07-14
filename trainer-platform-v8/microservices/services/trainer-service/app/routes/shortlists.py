"""Shortlist management — send mail, send interview link, send client slots."""
import asyncio
import logging
import re
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

EMAIL_SVC = settings.EMAIL_SERVICE_URL.rstrip("/")
NOTIF_SVC = settings.NOTIFICATION_SERVICE_URL.rstrip("/")
EXCLUDED_TRAINER_STATUSES = {"interested", "confirmed", "declined"}
PIPELINE_VERSION = "trainer-match-microservice-v1"
ACTIVE_PIPELINE_STAGES = {
    "mail1",
    "waiting_reply1",
    "mail1_replied",
    "mail2",
    "waiting_reply2",
    "details_received",
    "mail3",
    "slot_booked",
    "interview_scheduled",
    "selected",
    "toc_requested",
    "toc_received_pending",
    "training_confirmed",
}


class SendMailRequest(BaseModel):
    requirement_id: str
    trainer_id: Optional[str] = ""
    trainer_ids: Optional[List[str]] = None
    to_email: Optional[str] = ""
    to_name: Optional[str] = ""
    mail_type: str = "mail1"
    subject: Optional[str] = ""
    body: Optional[str] = ""
    smtp_config: Optional[Dict[str, Any]] = None


class SendInterviewLinkRequest(BaseModel):
    requirement_id: str
    trainer_id: str
    to_email: Optional[str] = ""
    trainer_name: Optional[str] = ""
    interview_link: str
    interview_date: Optional[str] = ""
    date_time: Optional[str] = ""
    platform: Optional[str] = "Google Meet"
    technology: Optional[str] = ""
    client_email: Optional[str] = ""
    client_name: Optional[str] = ""
    smtp_config: Optional[Dict[str, Any]] = None


class SendClientSlotsRequest(BaseModel):
    requirement_id: str
    trainer_id: str
    slots: List[Dict[str, Any]] = []
    slot_text: Optional[str] = ""
    trainer_name: Optional[str] = ""
    client_email: Optional[str] = ""
    client_name: Optional[str] = ""
    force: bool = False
    smtp_config: Optional[Dict[str, Any]] = None


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _client_interview_message(
    *,
    client_name: str,
    trainer_name: str,
    technology: str,
    requirement_id: str,
    interview_date: str,
    platform: str,
    interview_link: str,
) -> Dict[str, str]:
    subject = f"Interview Schedule Confirmation - {technology} | Ref: {requirement_id}"
    date_line = f"Date & Time: {interview_date}\n" if interview_date else ""
    body = (
        f"Dear {client_name or 'Team'},\n\n"
        f"The interview/discussion with Trainer {trainer_name or 'the trainer'} for the {technology} requirement is confirmed.\n\n"
        "Interview Details:\n"
        f"{date_line}"
        f"Platform: {platform or 'Google Meet'}\n"
        f"Meeting Link: {interview_link}\n\n"
        "Kindly join on time and let us know if any change is required.\n\n"
        "Regards,\n"
        "TrainerSync Team"
    )
    return {"subject": subject, "body": body}


def _is_mail_quota_error(value: Any) -> bool:
    text = str(value or "").lower()
    return any(marker in text for marker in (
        "daily user sending limit exceeded",
        "user-rate limit exceeded",
        "ratelimitexceeded",
        "mail sending",
        "gmail sending quota exceeded",
    ))


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


def _term_matches(terms: List[str], text: str) -> List[str]:
    matches: List[str] = []
    for term in terms:
        norm = _norm(term)
        if norm and f" {norm} " in f" {text} ":
            matches.append(term)
    return matches


def _quality(score: float) -> str:
    if score >= 80:
        return "excellent"
    if score >= 60:
        return "strong"
    if score >= 40:
        return "good"
    return "exploratory"


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
    all_tokens = set(category.split()) | set(profile.split())
    if technology:
        norm_technology = _norm(technology)
        if f" {norm_technology} " in f" {category} ":
            tech_score = 35.0
        elif f" {norm_technology} " in f" {profile} ":
            tech_score = 28.0
        else:
            tech_score = 18.0 * (len(technology_tokens & all_tokens) / max(len(technology_tokens), 1))
        score += tech_score
        breakdown["technology"] = round(tech_score, 2)

    required_matches = _term_matches(required_skills, profile)
    preferred_matches = _term_matches(preferred_skills, profile)
    skill_score = 25.0 * (len(required_matches) / max(len(required_skills), 1)) if required_skills else 0.0
    skill_score += min(8.0, 2.0 * len(preferred_matches))
    score += skill_score
    breakdown["skills"] = round(skill_score, 2)
    breakdown["matched_required_skills"] = required_matches
    breakdown["matched_preferred_skills"] = preferred_matches

    min_exp = _safe_float(requirement.get("min_experience_years"), 0.0)
    exp = _trainer_experience(trainer)
    exp_score = 15.0 if min_exp and exp >= min_exp else min(exp * 1.5, 15.0)
    score += exp_score
    breakdown["experience"] = round(exp_score, 2)

    preferred_location = _clean(requirement.get("preferred_location") or requirement.get("location"))
    trainer_location = _clean(trainer.get("location"))
    location_score = 10.0 if preferred_location and _norm(preferred_location) in _norm(trainer_location) else 0.0
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


def _is_active_pipeline_trainer(trainer: Dict[str, Any]) -> bool:
    stage = _clean(trainer.get("pipeline_status") or trainer.get("status")).lower()
    return stage in ACTIVE_PIPELINE_STAGES


async def _sync_shortlist_with_trainers(
    db: AsyncIOMotorDatabase,
    requirement: Dict[str, Any],
    existing: Optional[Dict[str, Any]] = None,
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
    existing = existing or {}
    old_trainers = existing.get("top_trainers", []) or []
    old_by_id = {
        _clean(trainer.get("trainer_id")): trainer
        for trainer in old_trainers
        if trainer.get("trainer_id")
    }
    top_trainers = scored[:top_n]
    new_ids = {_clean(trainer.get("trainer_id")) for trainer in top_trainers}
    for index, trainer in enumerate(top_trainers, start=1):
        trainer["rank"] = index
        trainer["pipeline_status"] = trainer.get("pipeline_status") or "shortlisted"
        old = old_by_id.get(_clean(trainer.get("trainer_id")))
        if old:
            trainer.update(_merge_pipeline_state(trainer, old))

    active_old_trainers = [
        trainer for trainer in old_trainers
        if _clean(trainer.get("trainer_id")) not in new_ids and _is_active_pipeline_trainer(trainer)
    ]
    top_trainers.extend(active_old_trainers)

    now = datetime.utcnow()
    warnings = [] if all_trainers else ["No trainers available in database."]
    doc = {
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
                "stage": "trainer_db_sync",
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
    set_doc = {k: v for k, v in doc.items() if k not in {"shortlist_id", "created_at"}}
    await db["shortlists"].update_one(
        {"requirement_id": req_id},
        {
            "$set": set_doc,
            "$setOnInsert": {
                "shortlist_id": doc["shortlist_id"],
                "created_at": doc["created_at"],
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
    return doc


def _shortlist_response(doc: Dict[str, Any]) -> Dict[str, Any]:
    trainers = doc.get("top_trainers", []) or []
    return {
        "success": True,
        **doc,
        "shortlist": doc,
        "top_trainers": trainers,
        "trainers": trainers,
    }


def _thread_log_response(log: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(log)
    if item.get("direction") == "outbound":
        item["direction"] = "sent"
    elif item.get("direction") == "inbound":
        item["direction"] = "received"
    if not item.get("body") and item.get("body_snippet"):
        item["body"] = item.get("body_snippet")
    return item


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
    messages = [_thread_log_response(log) for log in logs]
    return {"success": True, "requirement_id": requirement_id, "thread": messages, "messages": messages}


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


@router.get("/{requirement_id}")
async def get_shortlist(requirement_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    doc = await db["shortlists"].find_one({"requirement_id": requirement_id}, {"_id": 0})
    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0})
    if requirement:
        doc = await _sync_shortlist_with_trainers(db, requirement, doc)
    elif not doc:
        raise HTTPException(404, "Shortlist not found")
    return _shortlist_response(doc)


@router.post("/send-mail")
async def send_shortlist_mail(
    payload: SendMailRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Send the configured mail_type email to one or all trainers on a shortlist."""
    shortlist = await db["shortlists"].find_one({"requirement_id": payload.requirement_id}, {"_id": 0}) or {}
    requirement = await db["requirements"].find_one({"requirement_id": payload.requirement_id}, {"_id": 0}) or {}
    top_trainers: List[Dict[str, Any]] = shortlist.get("top_trainers") or []

    if payload.to_email:
        targets = [{
            "trainer_id": payload.trainer_id or "",
            "email": payload.to_email,
            "name": payload.to_name or "Recipient",
        }]
    elif payload.trainer_ids:
        targets = [t for t in top_trainers if t.get("trainer_id") in payload.trainer_ids]
    else:
        targets = [t for t in top_trainers if t.get("pipeline_status") not in ("stopped_selected", "declined")]

    if not targets:
        return {"success": True, "sent": 0, "message": "No eligible trainers found"}

    results = []
    attempted_recipients = set()
    quota_blocked = False
    for t in targets:
        trainer_email = t.get("email") or t.get("trainer_email") or ""
        trainer_name = payload.to_name or t.get("name") or t.get("trainer_name") or "Trainer"
        if payload.to_email:
            trainer_email = payload.to_email
            trainer_name = payload.to_name or trainer_name
        if not trainer_email:
            results.append({"trainer_id": t.get("trainer_id"), "status": "skipped_no_email"})
            continue
        if quota_blocked:
            results.append({
                "trainer_id": t.get("trainer_id"),
                "email": trainer_email,
                "status": "skipped_quota_blocked",
                "error_message": "Gmail sending quota exceeded; remaining sends were not attempted.",
            })
            continue
        recipient_key = trainer_email.strip().lower()
        if recipient_key in attempted_recipients:
            results.append({
                "trainer_id": t.get("trainer_id"),
                "email": trainer_email,
                "status": "skipped_duplicate_recipient",
            })
            continue

        prior_attempt = await db["email_logs"].find_one(
            {
                "requirement_id": payload.requirement_id,
                "mail_type": payload.mail_type,
                "recipient": {"$regex": f"^{re.escape(trainer_email)}$", "$options": "i"},
                "status": "sent",
            },
            {"_id": 0, "status": 1, "email_id": 1},
            sort=[("created_at", -1)],
        )
        if prior_attempt:
            results.append({
                "trainer_id": t.get("trainer_id"),
                "email": trainer_email,
                "status": f"skipped_already_{prior_attempt.get('status')}",
                "email_id": prior_attempt.get("email_id"),
            })
            continue
        attempted_recipients.add(recipient_key)

        error_message = ""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                domain = _clean(
                    requirement.get("technology_needed")
                    or requirement.get("domain")
                    or shortlist.get("technology_needed")
                    or "Training"
                )
                duration = _clean(
                    requirement.get("duration_text")
                    or (f"{requirement.get('duration_days')} day(s)" if requirement.get("duration_days") else "")
                    or (f"{requirement.get('duration_hours')} hour(s)" if requirement.get("duration_hours") else "")
                )
                subject = payload.subject or f"Training Opportunity - {payload.requirement_id}"
                body = payload.body or (
                    f"Dear {trainer_name},\n\n"
                    "We have a training requirement matching your profile. Please revert if interested.\n\n"
                    "Regards,\nTrainerSync Team"
                )
                if not payload.body:
                    tmpl_response = None
                    base_template_payload = {
                        "name": trainer_name,
                        "technology": domain,
                        "requirement_id": payload.requirement_id,
                        "client_name": _clean(requirement.get("client_name") or requirement.get("client_company")),
                    }
                    if payload.mail_type in ("mail1", "first"):
                        tmpl_response = await client.post(
                            f"{EMAIL_SVC}/api/v1/email/templates/shortlist-first",
                            json={
                                "trainer_name": trainer_name,
                                "domain": domain,
                                "duration": duration,
                                "mode": _clean(requirement.get("mode")),
                                "participants": _clean(requirement.get("participant_count")),
                            },
                        )
                    else:
                        template_map = {
                            "mail2": "mail2",
                            "mail2_followup": "mail2-followup",
                            "trainer_acknowledgment": "trainer-ack",
                            "trainer_commercials_to_client": "send-commercials",
                            "client_budget_reply": "client-budget-reply",
                            "client_budget_acknowledgment": "client-budget-ack",
                            "rate_gap_resolution": "rate-gap-resolution",
                            "trainer_rate_discussion": "trainer-rate-discussion",
                            "client_toc_details_request": "client-toc-request",
                            "client_proceed": "client-proceed",
                            "client_rate_gap_option2": "client-alternative",
                            # Additional mappings used by Shortlist1 frontend
                            "client_rate_gap_option1": "client-proceed",
                            "client_rate_gap_option2": "client-alternative",
                            "client_toc_details_followup": "client-toc-request",
                            "commercial_negotiation": "send-commercials",
                            "trainer_negotiation_client_update": "client/proceed-ack",
                            "commercial_details_notification": "send-commercials",
                            "trainer_rate_accepted": "trainer-ack",
                            "trainer_rate_rejected": "mail5-rejection",
                            "mail3": "mail3-slot-booking",
                            "mail3_slot_booking": "mail3-slot-booking",
                            "mail3_slot_followup": "mail3-too-few",
                            "mail3_too_many": "mail3-too-many",
                            "mail3_too_many_slots": "mail3-too-many",
                            "mail3_too_few": "mail3-too-few",
                            "mail3_too_few_slots": "mail3-too-few",
                            "mail4": "interview",
                            "mail5": "mail5-selection",
                            "mail5_ok": "mail5-selection",
                            "mail5_selection": "mail5-selection",
                            "mail5_no": "mail5-rejection",
                            "mail5_rejection": "mail5-rejection",
                            "mail6": "mail6-toc-request",
                            "mail6_toc": "mail6-toc-request",
                            "toc-request": "toc-request",
                            "mail7": "mail7-training-confirmation",
                            "mail7_confirm": "mail7-training-confirmation",
                            "training_confirmation": "mail7-training-confirmation",
                        }
                        template_name = template_map.get(payload.mail_type)
                        if template_name:
                            tmpl_response = await client.post(
                                f"{EMAIL_SVC}/api/v1/email/templates/{template_name}",
                                json={**base_template_payload, "trainer_name": trainer_name},
                            )
                    if tmpl_response is not None and tmpl_response.status_code < 400:
                        tmpl = tmpl_response.json()
                        subject = payload.subject or tmpl.get("subject") or subject
                        body = tmpl.get("body") or body
                r = await client.post(f"{EMAIL_SVC}/api/v1/email/send", json={
                    "to": trainer_email,
                    "subject": subject,
                    "body": body,
                    "mail_type": payload.mail_type,
                    "trainer_id": t.get("trainer_id"),
                    "trainer_name": trainer_name,
                    "requirement_id": payload.requirement_id,
                    "smtp_config": payload.smtp_config,
                })
            ok = r.status_code < 400
            if not ok:
                error_message = f"{r.status_code}: {r.text[:300]}"
            else:
                await asyncio.sleep(1.5)
        except Exception as exc:
            logger.error("Email send failed for %s: %s", trainer_email, exc)
            ok = False
            error_message = str(exc)

        results.append({
            "trainer_id": t.get("trainer_id"),
            "email": trainer_email,
            "status": "sent" if ok else "failed",
            "error_message": error_message,
        })
        if not ok and _is_mail_quota_error(error_message):
            quota_blocked = True

        now = datetime.utcnow()
        set_fields = {
            "top_trainers.$.last_mail_type_attempted": payload.mail_type,
            "top_trainers.$.last_mail_attempted_at": now,
        }
        if ok:
            set_fields.update({
                "top_trainers.$.pipeline_status": payload.mail_type,
                "top_trainers.$.last_mail_type": payload.mail_type,
                "top_trainers.$.last_mailed_at": now,
                "top_trainers.$.last_mail_error": "",
            })
        else:
            set_fields["top_trainers.$.last_mail_error"] = error_message or "Email delivery failed"

        await db["shortlists"].update_one(
            {"requirement_id": payload.requirement_id, "top_trainers.trainer_id": t.get("trainer_id")},
            {"$set": set_fields},
        )

    sent = sum(1 for r in results if r["status"] == "sent")
    return {"success": True, "sent": sent, "total": len(results), "results": results}


@router.post("/send-interview-link")
async def send_interview_link(
    payload: SendInterviewLinkRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Email an interview link to the trainer and the client."""
    req = await db["requirements"].find_one({"requirement_id": payload.requirement_id}, {"_id": 0}) or {}
    shortlist = await db["shortlists"].find_one({"requirement_id": payload.requirement_id}, {"_id": 0}) or {}
    trainer = await db["trainers"].find_one({"trainer_id": payload.trainer_id}, {"_id": 0}) or {}
    shortlist_trainer = next(
        (t for t in shortlist.get("top_trainers") or [] if str(t.get("trainer_id") or "") == str(payload.trainer_id or "")),
        {},
    )
    email = _clean(payload.to_email or trainer.get("email") or shortlist_trainer.get("email") or shortlist_trainer.get("trainer_email"))
    name = _clean(payload.trainer_name or trainer.get("name") or shortlist_trainer.get("name") or shortlist_trainer.get("trainer_name")) or "Trainer"
    technology = _clean(
        payload.technology
        or req.get("technology_needed")
        or req.get("technology")
        or req.get("domain")
        or shortlist.get("technology_needed")
    ) or "training"
    interview_date = _clean(payload.interview_date or payload.date_time)
    platform = _clean(payload.platform) or "Google Meet"
    client_email = _clean(
        payload.client_email
        or req.get("client_email")
        or req.get("contact_email")
        or shortlist.get("client_email")
    )
    client_name = _clean(
        payload.client_name
        or req.get("client_name")
        or req.get("client_company")
        or shortlist.get("client_name")
    ) or "Client"

    if not email:
        raise HTTPException(400, "Trainer email not found")
    if not client_email:
        raise HTTPException(400, "Client email not found; cannot send the meeting link to the client")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{EMAIL_SVC}/api/v1/email/templates/interview", json={
                "trainer_name": name,
                "technology": technology,
                "req_id": payload.requirement_id,
                "interview_date": interview_date,
                "interview_link": payload.interview_link,
            })
            r.raise_for_status()
            tmpl = r.json()
            trainer_response = await client.post(f"{EMAIL_SVC}/api/v1/email/send", json={
                "to": email,
                "subject": tmpl.get("subject", f"Interview – {technology}"),
                "body": tmpl.get("body", ""),
                "mail_type": "mail4",
                "trainer_id": payload.trainer_id,
                "trainer_name": name,
                "requirement_id": payload.requirement_id,
                "smtp_config": payload.smtp_config,
            })
            trainer_response.raise_for_status()
            trainer_sent = trainer_response.json()

            client_message = _client_interview_message(
                client_name=client_name,
                trainer_name=name,
                technology=technology,
                requirement_id=payload.requirement_id,
                interview_date=interview_date,
                platform=platform,
                interview_link=payload.interview_link,
            )
            client_response = await client.post(f"{EMAIL_SVC}/api/v1/email/send", json={
                "to": client_email,
                "subject": client_message["subject"],
                "body": client_message["body"],
                "mail_type": "client_interview_schedule",
                "trainer_id": payload.trainer_id,
                "trainer_name": name,
                "requirement_id": payload.requirement_id,
                "smtp_config": payload.smtp_config,
            })
            client_response.raise_for_status()
            client_sent = client_response.json()
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc

    now = datetime.utcnow()
    trainer_email_id = trainer_sent.get("email_id", "")
    client_email_id = client_sent.get("email_id", "")
    common_fields = {
        "requirement_id": payload.requirement_id,
        "trainer_id": payload.trainer_id,
        "trainer_name": name,
        "trainer_email": email,
        "client_email": client_email,
        "client_name": client_name,
        "technology": technology,
        "domain": technology,
        "interview_scheduled": True,
        "interview_date": interview_date,
        "date_time_text": interview_date,
        "interview_link": payload.interview_link,
        "meet_link": payload.interview_link,
        "platform": platform,
        "updated_at": now,
    }
    if trainer_email_id:
        await db["email_logs"].update_one(
            {"email_id": trainer_email_id},
            {"$set": {
                **common_fields,
                "to_email": email,
                "trainer_email_sent": True,
                "client_email_sent": True,
                "client_interview_email_id": client_email_id,
            }},
        )
    if client_email_id:
        await db["email_logs"].update_one(
            {"email_id": client_email_id},
            {"$set": {
                **common_fields,
                "to_email": client_email,
                "trainer_email_sent": True,
                "client_email_sent": True,
                "trainer_interview_email_id": trainer_email_id,
                "source_trainer_email_id": trainer_email_id,
            }},
        )

    await db["shortlists"].update_one(
        {"requirement_id": payload.requirement_id, "top_trainers.trainer_id": payload.trainer_id},
        {"$set": {
            "top_trainers.$.pipeline_status": "interview_scheduled",
            "top_trainers.$.slot_status": "interview_link_sent",
            "top_trainers.$.mail4_email_id": trainer_email_id,
            "top_trainers.$.client_mail4_email_id": client_email_id,
            "top_trainers.$.mail4_sent_at": now,
            "top_trainers.$.client_mail4_sent_at": now,
            "top_trainers.$.interview_scheduled_at": now,
            "top_trainers.$.interview_date": interview_date,
            "top_trainers.$.interview_link": payload.interview_link,
            "top_trainers.$.meet_link": payload.interview_link,
            "top_trainers.$.client_email_sent": True,
            "top_trainers.$.trainer_email_sent": True,
            "top_trainers.$.last_mail_type": "mail4",
            "top_trainers.$.last_mail_type_attempted": "mail4",
            "top_trainers.$.last_mail_attempted_at": now,
            "top_trainers.$.last_mailed_at": now,
            "top_trainers.$.last_mail_error": "",
            "top_trainers.$.updated_at": now,
            "updated_at": now,
        }},
    )

    return {
        "success": True,
        "trainer_sent_to": email,
        "client_sent_to": client_email,
        "trainer_email_id": trainer_email_id,
        "client_email_id": client_email_id,
        "interview_link": payload.interview_link,
    }


@router.post("/send-client-slots")
async def send_client_slots(
    payload: SendClientSlotsRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Forward trainer availability slots to the client via email."""
    req = await db["requirements"].find_one({"requirement_id": payload.requirement_id}, {"_id": 0}) or {}
    shortlist = await db["shortlists"].find_one({"requirement_id": payload.requirement_id}, {"_id": 0}) or {}
    trainer = next(
        (t for t in shortlist.get("top_trainers") or [] if str(t.get("trainer_id") or "") == str(payload.trainer_id or "")),
        {},
    )
    trainer_name = _clean(payload.trainer_name or trainer.get("name") or trainer.get("trainer_name")) or "Trainer"
    client_email = payload.client_email
    if not client_email:
        client_email = req.get("client_email", "")

    if not client_email:
        raise HTTPException(400, "client_email is required")

    if not payload.force:
        existing = await db["email_logs"].find_one(
            {
                "direction": "outbound",
                "status": "sent",
                "mail_type": "client_slots",
                "requirement_id": payload.requirement_id,
                "trainer_id": payload.trainer_id,
            },
            {"_id": 0, "email_id": 1, "recipient": 1, "to_email": 1, "sent_at": 1},
            sort=[("created_at", -1)],
        )
        if existing:
            return {
                "success": True,
                "already_sent": True,
                "email_id": existing.get("email_id"),
                "sent_to": existing.get("to_email") or existing.get("recipient"),
                "slots_count": len(payload.slots),
            }

    slots_text = _clean(payload.slot_text)
    if not slots_text:
        slots_text = "\n".join(
            f"Slot {i+1}: {s.get('date_display', '')} {s.get('time_display', '')}".strip()
            for i, s in enumerate(payload.slots)
        )
    if not slots_text:
        slots_text = "The trainer's availability slots will be shared shortly."

    technology = _clean(req.get("technology_needed") or req.get("technology") or req.get("domain")) or "training"
    client_name = _clean(payload.client_name or req.get("client_name") or req.get("client_company")) or "Client"

    body = (
        f"Dear {client_name},\n\n"
        f"Trainer {trainer_name} has shared the available interview slots for the {technology} requirement.\n\n"
        "Available slots:\n"
        f"{slots_text}\n\n"
        "Kindly confirm your preferred slot at the earliest.\n\n"
        "Regards,\nTrainerSync Team"
    )

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(f"{EMAIL_SVC}/api/v1/email/send", json={
                "to": client_email,
                "subject": f"Trainer Interview Slots - {technology} | {trainer_name}",
                "body": body,
                "mail_type": "client_slots",
                "requirement_id": payload.requirement_id,
                "trainer_id": payload.trainer_id,
                "trainer_name": trainer_name,
                "smtp_config": payload.smtp_config,
            })
            response.raise_for_status()
            sent_payload = response.json()
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc

    now = datetime.utcnow()
    await db["shortlists"].update_one(
        {"requirement_id": payload.requirement_id, "top_trainers.trainer_id": payload.trainer_id},
        {"$set": {
            "top_trainers.$.client_slots_sent": True,
            "top_trainers.$.client_slots_sent_at": now,
            "top_trainers.$.client_slots_email_id": sent_payload.get("email_id", ""),
            "top_trainers.$.slot_status": "sent_to_client",
            "top_trainers.$.slot_reply_text": slots_text,
            "top_trainers.$.client_slot_error": "",
            "top_trainers.$.updated_at": now,
            "updated_at": now,
        }},
    )

    return {
        "success": True,
        "email_id": sent_payload.get("email_id"),
        "sent_to": client_email,
        "slots_count": len(payload.slots),
        "slot_text": slots_text,
    }
