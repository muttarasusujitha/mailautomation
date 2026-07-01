"""AI analysis routes — analyze-reply, log-usage, assistant/chat."""
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.database import get_db
from app.config import get_settings

router = APIRouter()
logger = logging.getLogger(__name__)

NEGATIVE = ["not interested","not available","unable","cannot","busy","decline","withdraw"]
POSITIVE = ["available","interested","confirm","accept","happy to","yes","proceed"]


class AnalyzeReplyRequest(BaseModel):
    body: str
    subject: Optional[str] = ""
    from_email: Optional[str] = ""
    email_id: Optional[str] = ""
    trainer_id: Optional[str] = ""


class LogUsageRequest(BaseModel):
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    operation: Optional[str] = ""
    trainer_id: Optional[str] = ""
    requirement_id: Optional[str] = ""
    cost_usd: Optional[float] = 0.0



@router.post("/analyze-reply")
async def analyze_reply(payload: AnalyzeReplyRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    text = payload.body.lower()
    if any(s in text for s in NEGATIVE):
        sentiment, action = "negative", "mark_declined"
    elif any(s in text for s in POSITIVE):
        sentiment, action = "positive", "mark_interested"
    else:
        sentiment, action = "neutral", "requires_review"

    result = {"sentiment": sentiment, "action": action, "email_id": payload.email_id,
              "trainer_id": payload.trainer_id, "from_email": payload.from_email}

    if payload.email_id:
        now = datetime.utcnow()
        await db["email_logs"].update_one(
            {"email_id": payload.email_id},
            {"$set": {"sentiment": sentiment, "action": action, "replied": True,
                      "reply_analyzed_at": now, "updated_at": now}},
        )
    return {"success": True, **result}


@router.post("/log-usage")
async def log_ai_usage(payload: LogUsageRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    now = datetime.utcnow()
    doc = {**payload.model_dump(), "usage_id": f"AI-{uuid.uuid4().hex[:10].upper()}",
           "created_at": now}
    await db["ai_usage_logs"].insert_one(doc)
    doc.pop("_id", None)
    return {"success": True, "usage_id": doc["usage_id"]}
