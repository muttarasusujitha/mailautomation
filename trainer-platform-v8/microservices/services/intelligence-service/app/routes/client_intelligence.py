"""Client intelligence — analyse inbound emails and extract structured data."""
import json
import logging
import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.database import get_db
from app.config import get_settings

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()


def _anthropic_client():
    try:
        import anthropic
        key = settings.ANTHROPIC_API_KEY.strip()
        return anthropic.AsyncAnthropic(api_key=key) if key else anthropic.AsyncAnthropic()
    except ImportError:
        return None


def _extract_json(text: str) -> Dict[str, Any]:
    clean = re.sub(r"^```(?:json)?", "", (text or "").strip(), flags=re.IGNORECASE).strip()
    clean = re.sub(r"```$", "", clean).strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", clean, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise ValueError("No JSON found in response")


def _regex_extract(text: str) -> Dict[str, Any]:
    """Fast regex-based extraction for common patterns."""
    budget = None
    bm = re.search(r"(?:budget|rate|cost)[:\s]*(?:INR|USD|Rs\.?)?\s*([\d,]+)", text, re.IGNORECASE)
    if bm:
        try:
            budget = float(bm.group(1).replace(",", ""))
        except ValueError:
            pass

    duration = None
    dm = re.search(r"(\d+)\s*(?:days?|weeks?|months?)", text, re.IGNORECASE)
    if dm:
        duration = int(dm.group(1))

    participants = None
    pm = re.search(r"(\d+)\s*(?:participants?|learners?|trainees?|people|pax)", text, re.IGNORECASE)
    if pm:
        participants = int(pm.group(1))

    skills = []
    for tech in ["Python", "Java", "React", "Angular", "AWS", "Azure", "GCP", "DevOps",
                  "Docker", "Kubernetes", "SQL", "MongoDB", "Machine Learning", "Gen AI",
                  "Salesforce", "SAP", "ServiceNow", "Power BI", "Tableau"]:
        if re.search(rf"\b{re.escape(tech)}\b", text, re.IGNORECASE):
            skills.append(tech)

    return {
        "budget": budget,
        "duration_days": duration,
        "num_participants": participants,
        "skills": skills,
        "extraction_method": "regex",
    }


class AnalyseEmailRequest(BaseModel):
    subject: str = ""
    body: str
    sender_email: str = ""
    sender_name: str = ""
    use_ai: bool = True
    save: bool = False
    customer_id: Optional[str] = None


@router.post("/analyse-email")
async def analyse_email(payload: AnalyseEmailRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Extract structured requirement data from an inbound client email."""
    text = f"Subject: {payload.subject}\n\n{payload.body}"

    # Always run regex extraction first (instant fallback)
    regex_result = _regex_extract(text)
    ai_result: Dict[str, Any] = {}

    if payload.use_ai:
        client = _anthropic_client()
        if client:
            try:
                prompt = (
                    "Extract a structured training requirement from this email. "
                    "Return ONLY valid JSON with keys: technology, skills (list), domain, "
                    "budget (number or null), duration_days (int or null), num_participants (int or null), "
                    "location, delivery_mode, client_name, client_company, urgency (low/medium/high), "
                    "intent_score (0-1), is_training_request (bool), summary.\n\n"
                    f"Email:\n{text[:4000]}"
                )
                msg = await client.messages.create(
                    model=settings.ANTHROPIC_MODEL, max_tokens=800, temperature=0,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
                ai_result = _extract_json(raw)
                ai_result["extraction_method"] = "ai"
            except Exception as exc:
                logger.warning("AI analysis failed, using regex: %s", exc)

    final = {**regex_result, **{k: v for k, v in ai_result.items() if v is not None}}

    if payload.save and payload.customer_id:
        from datetime import datetime
        await db.email_analysis.insert_one({
            "customer_id": payload.customer_id,
            "subject": payload.subject,
            "sender_email": payload.sender_email,
            "analysis": final,
            "created_at": datetime.utcnow(),
        })

    return {"success": True, "analysis": final}


@router.post("/score-intent")
async def score_intent(payload: AnalyseEmailRequest):
    """Quick intent scoring — is this email a training request?"""
    text = f"{payload.subject} {payload.body}".lower()
    score = 0.0
    signals = ["training", "trainer", "requirement", "course", "workshop", "certification",
               "batch", "participants", "learners", "days", "budget", "technology"]
    for sig in signals:
        if sig in text:
            score += 1 / len(signals)
    is_request = score > 0.3
    return {"intent_score": round(score, 3), "is_training_request": is_request}
