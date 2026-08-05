"""Voice assistant endpoints for recruiter workflows."""
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.config import get_settings
from shared.database.service import get_db

router = APIRouter()
settings = get_settings()


class VoiceAssistantRequest(BaseModel):
    transcript: str
    source: Optional[str] = "voice_ai_page"


class VoiceTaskRequest(VoiceAssistantRequest):
    title: Optional[str] = None
    priority: Optional[str] = "medium"


class VoiceExecuteRequest(VoiceAssistantRequest):
    client_name: Optional[str] = ""
    client_email: Optional[str] = ""
    top_n: Optional[int] = 5
    send_emails: Optional[bool] = False


SKILL_ALIASES = {
    "Python": ["python"],
    "Java": ["java"],
    "React": ["react", "react.js", "reactjs"],
    "Angular": ["angular"],
    "Node.js": ["node", "node.js", "nodejs"],
    "AWS": ["aws", "amazon web services"],
    "Azure": ["azure"],
    "GCP": ["gcp", "google cloud"],
    "Docker": ["docker"],
    "Kubernetes": ["kubernetes", "k8s"],
    "Jenkins": ["jenkins"],
    "Terraform": ["terraform"],
    "DevOps": ["devops", "ci/cd"],
    "Power BI": ["power bi", "powerbi"],
    "Salesforce": ["salesforce"],
    "Cybersecurity": ["cybersecurity", "security"],
}

LOCATIONS = [
    "Hyderabad", "Bengaluru", "Bangalore", "Chennai", "Pune", "Mumbai", "Delhi",
    "New Delhi", "Gurugram", "Gurgaon", "Noida", "Kolkata", "Ahmedabad", "India",
]


def _clean(text: Any) -> str:
    return str(text or "").strip()


def _contains_word(text: str, alias: str) -> bool:
    escaped = re.escape(alias)
    return bool(re.search(rf"(^|[^a-z0-9+#.]){escaped}($|[^a-z0-9+#.])", text, re.I))


def _extract_skills(text: str) -> List[str]:
    found: List[str] = []
    for skill, aliases in SKILL_ALIASES.items():
        if any(_contains_word(text, alias) for alias in aliases):
            found.append(skill)
    return found


def _extract_location(text: str) -> str:
    for location in LOCATIONS:
        if _contains_word(text, location.lower()):
            if location == "Bangalore":
                return "Bengaluru"
            if location == "Gurgaon":
                return "Gurugram"
            return location
    return ""


def _extract_amount(text: str) -> float:
    patterns = [
        r"(?:inr|rs\.?|₹)\s*([0-9][0-9,]*(?:\.\d+)?)\s*(k|thousand|lakh|lakhs)?",
        r"\b(?:budget|commercials?|rate|charges?|cost)\b\D{0,50}([0-9][0-9,]*(?:\.\d+)?)\s*(k|thousand|lakh|lakhs)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if not match:
            continue
        amount = float(str(match.group(1)).replace(",", ""))
        suffix = str(match.group(2) or "").lower()
        if suffix in {"k", "thousand"}:
            amount *= 1000
        elif suffix in {"lakh", "lakhs"}:
            amount *= 100000
        return amount
    return 0.0


def _extract_duration_hours(text: str) -> float:
    match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|hr)\b", text, flags=re.I)
    return float(match.group(1)) if match else 0.0


def _extract_participants(text: str) -> int:
    match = re.search(r"\b(\d+)\s*(?:participants?|learners?|people|employees|students)\b", text, flags=re.I)
    return int(match.group(1)) if match else 0


def _intent(text: str) -> str:
    lower = text.lower()
    if any(word in lower for word in ("mail", "email", "follow up", "follow-up")):
        return "email_draft"
    if any(word in lower for word in ("interview", "slot", "schedule", "calendar")):
        return "interview_schedule"
    if any(word in lower for word in ("client", "requirement", "budget", "timeline")):
        return "client_requirement"
    if any(word in lower for word in ("find", "shortlist", "match", "trainer")):
        return "trainer_shortlist"
    return "recruiter_task"


def _draft(intent: str, transcript: str, skills: List[str], location: str) -> str:
    skill_text = ", ".join(skills) if skills else "the required skills"
    location_text = f" in {location}" if location else ""
    if intent == "trainer_shortlist":
        return (
            f"Search and shortlist trainers for {skill_text}{location_text}. "
            "Rank profiles by resume evidence, availability, fit score, commercials, and contact completeness."
        )
    if intent == "email_draft":
        return (
            "Hi, thanks for connecting. Please share your updated profile/resume, availability, commercials, "
            f"and suitable interview slots for {skill_text}. We will review and proceed with the next step."
        )
    if intent == "interview_schedule":
        return (
            "Please confirm two available interview slots, timezone, meeting preference, and the best contact details. "
            "Once confirmed, we will share the invite with the client."
        )
    if intent == "client_requirement":
        return (
            f"Requirement captured for {skill_text}{location_text}. Please confirm timeline, delivery mode, budget, "
            "number of trainers needed, audience level, and evaluation criteria."
        )
    return f"Recruiter task captured: {transcript}"


def _requirement_payload(payload: VoiceExecuteRequest, analysis: Dict[str, Any]) -> Dict[str, Any]:
    transcript = _clean(payload.transcript)
    skills = analysis.get("skills") or []
    technology = skills[0] if skills else ""
    if not technology:
        raise HTTPException(400, "Could not identify a technology/domain from the voice command")

    budget = _extract_amount(transcript)
    duration_hours = _extract_duration_hours(transcript)
    participants = _extract_participants(transcript)
    top_n = max(1, min(int(payload.top_n or 5), 20))
    location = analysis.get("location") or ""
    requirement: Dict[str, Any] = {
        "technology_needed": technology,
        "domain": technology,
        "title": f"{technology} Trainer",
        "required_skills": skills or [technology],
        "preferred_location": location,
        "location": location,
        "top_n": top_n,
        "send_emails": bool(payload.send_emails),
        "priority": analysis.get("priority") or "medium",
        "source": payload.source or "voice_ai_page",
        "metadata": {
            "created_by": "voice_ai",
            "voice_transcript": transcript,
            "voice_intent": analysis.get("intent"),
        },
    }
    if payload.client_name:
        requirement["client_name"] = payload.client_name
        requirement["client_company"] = payload.client_name
    if payload.client_email:
        requirement["client_email"] = payload.client_email
    if budget:
        requirement["budget_per_day"] = budget
        requirement["budget"] = budget
    if duration_hours:
        requirement["duration_hours"] = duration_hours
    if participants:
        requirement["participant_count"] = participants
        requirement["participants"] = participants
    return requirement


def _call_script(skills: List[str], location: str) -> str:
    skill_text = ", ".join(skills) if skills else "your training expertise"
    location_line = f" I also noticed the requirement is for {location}." if location else ""
    return "\n".join([
        "Recruiter call script",
        "",
        "Hi, this is from TrainerSync. Is this a good time for a quick trainer opportunity discussion?",
        f"We are checking availability for {skill_text}.{location_line}",
        "Could you confirm your current availability, delivery mode, commercials, and preferred interview slots?",
        "Do you have an updated resume or profile that we can share with the client?",
        "I will summarize your details and come back with the next step after client review.",
    ])


def _analysis(transcript: str) -> Dict[str, Any]:
    text = _clean(transcript)
    if not text:
        raise HTTPException(400, "Transcript is required")
    skills = _extract_skills(text)
    location = _extract_location(text.lower())
    intent = _intent(text)
    checklist = [
        "Confirm technology and seniority",
        "Check location or remote preference",
        "Verify resume/profile availability",
        "Capture commercials and trainer availability",
        "Prepare client-ready summary",
    ]
    return {
        "intent": intent,
        "intent_label": intent.replace("_", " ").title(),
        "skills": skills,
        "location": location,
        "priority": "high" if any(word in text.lower() for word in ("urgent", "today", "asap")) else "medium",
        "draft": _draft(intent, text, skills, location),
        "call_script": _call_script(skills, location),
        "checklist": checklist,
        "summary": f"{intent.replace('_', ' ').title()} request captured from voice note.",
    }


def _safe_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    doc = dict(doc)
    if "_id" in doc:
        doc["_id"] = str(doc["_id"])
    for key, value in list(doc.items()):
        if isinstance(value, datetime):
            doc[key] = value.isoformat()
    return doc


@router.post("/analyze")
async def analyze_voice_note(payload: VoiceAssistantRequest):
    return {"success": True, "analysis": _analysis(payload.transcript)}


@router.post("/notes")
async def save_voice_note(payload: VoiceAssistantRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    analysis = _analysis(payload.transcript)
    doc = {
        "note_id": f"VN-{uuid4().hex[:10].upper()}",
        "transcript": payload.transcript,
        "source": payload.source or "voice_ai_page",
        "analysis": analysis,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    await db.voice_ai_notes.insert_one(doc)
    return {"success": True, "note": _safe_doc(doc)}


@router.post("/tasks")
async def create_voice_task(payload: VoiceTaskRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    analysis = _analysis(payload.transcript)
    doc = {
        "task_id": f"VA-{uuid4().hex[:10].upper()}",
        "title": _clean(payload.title) or analysis["summary"],
        "status": "open",
        "priority": payload.priority or analysis["priority"],
        "transcript": payload.transcript,
        "analysis": analysis,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    await db.voice_ai_tasks.insert_one(doc)
    return {"success": True, "task": _safe_doc(doc)}


@router.post("/execute")
async def execute_voice_action(payload: VoiceExecuteRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    analysis = _analysis(payload.transcript)
    if analysis["intent"] != "trainer_shortlist":
        raise HTTPException(400, "Only trainer shortlist voice commands can be executed right now")

    requirement_payload = _requirement_payload(payload, analysis)
    core_url = settings.CORE_API_URL.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(f"{core_url}/api/v1/requirements", json=requirement_payload)
            if response.status_code >= 400 and core_url != "http://127.0.0.1:8001":
                response = await client.post("http://127.0.0.1:8001/api/v1/requirements", json=requirement_payload)
    except httpx.RequestError as exc:
        raise HTTPException(502, f"Could not reach requirement service: {exc}") from exc

    if response.status_code >= 400:
        raise HTTPException(response.status_code, response.text[:500])

    result = response.json()
    doc = {
        "task_id": f"VA-{uuid4().hex[:10].upper()}",
        "title": f"Executed: {requirement_payload['technology_needed']} trainer shortlist",
        "status": "completed",
        "priority": analysis["priority"],
        "transcript": payload.transcript,
        "analysis": analysis,
        "action": "create_requirement_and_shortlist",
        "requirement_payload": requirement_payload,
        "result": {
            "requirement_id": result.get("requirement_id"),
            "total_matched": result.get("total_matched", 0),
            "top_trainers": result.get("top_trainers", 0),
        },
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    await db.voice_ai_tasks.insert_one(doc)
    return {"success": True, "analysis": analysis, "requirement_payload": requirement_payload, "result": result, "task": _safe_doc(doc)}


@router.get("/notes")
async def list_voice_notes(limit: int = 20, db: AsyncIOMotorDatabase = Depends(get_db)):
    cursor = db.voice_ai_notes.find({}, {"_id": 0}).sort("created_at", -1).limit(max(1, min(limit, 100)))
    return {"success": True, "items": [item async for item in cursor]}


@router.get("/tasks")
async def list_voice_tasks(limit: int = 20, db: AsyncIOMotorDatabase = Depends(get_db)):
    cursor = db.voice_ai_tasks.find({}, {"_id": 0}).sort("created_at", -1).limit(max(1, min(limit, 100)))
    return {"success": True, "items": [item async for item in cursor]}
