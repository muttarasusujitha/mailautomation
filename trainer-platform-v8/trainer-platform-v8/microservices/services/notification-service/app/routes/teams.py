from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel
from typing import Any, Dict, Optional

from app.database import get_db
from app.teams import send_teams_notification

router = APIRouter()


class TeamsNotificationRequest(BaseModel):
    stage: str
    trainer_name: str = ""
    requirement_id: str = ""
    technology: str = ""
    context: Optional[Dict[str, Any]] = None


@router.post("/send")
async def send_notification(
    payload: TeamsNotificationRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    return await send_teams_notification(
        db,
        stage=payload.stage,
        trainer_name=payload.trainer_name,
        requirement_id=payload.requirement_id,
        technology=payload.technology,
        context=payload.context,
    )


@router.get("/logs")
async def get_teams_logs(
    limit: int = 50,
    status: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    query: Dict[str, Any] = {}
    if status:
        query["status"] = status
    cursor = db["teams_logs"].find(query, {"_id": 0}).limit(limit).sort("created_at", -1)
    items = [d async for d in cursor]
    return {"items": items, "count": len(items)}
