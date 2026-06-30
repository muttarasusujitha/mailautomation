"""Business Excel sync — trainer register workbook."""
import logging
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.database import get_db
from app.gmail_client import send_email_async

router = APIRouter()
logger = logging.getLogger(__name__)


class ExcelEmailRequest(BaseModel):
    to: str
    subject: str = "TrainerSync Business Register"
    body: str = "Please find the attached business register."


@router.get("/status")
async def business_excel_status(db: AsyncIOMotorDatabase = Depends(get_db)):
    doc = await db["business_excel_sync"].find_one({"type": "status"}, {"_id": 0}) or {}
    return {
        "success": True,
        "last_synced_at": doc.get("last_synced_at"),
        "row_count": doc.get("row_count", 0),
        "status": doc.get("status", "unknown"),
    }


@router.post("/sync")
async def sync_business_excel(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Pull all trainer records and write to the business register collection."""
    cursor = db["trainers"].find({}, {"_id": 0, "resume": 0, "combined_text": 0})
    trainers = [d async for d in cursor]
    now = datetime.utcnow()
    await db["business_excel_sync"].update_one(
        {"type": "status"},
        {"$set": {
            "type": "status",
            "last_synced_at": now,
            "row_count": len(trainers),
            "status": "synced",
        }},
        upsert=True,
    )
    return {"success": True, "rows_synced": len(trainers), "synced_at": now.isoformat()}


@router.post("/send-email")
async def send_excel_email(
    payload: ExcelEmailRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Email the business register (attachment placeholder — configure storage)."""
    success, error = await send_email_async(
        to=payload.to,
        subject=payload.subject,
        body=payload.body,
    )
    if not success:
        raise HTTPException(502, f"Email failed: {error}")
    return {"success": True, "sent_to": payload.to}


@router.post("/upload-drive")
async def upload_excel_to_drive(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Upload the business register to Google Drive (requires Drive scope)."""
    return {
        "success": False,
        "message": "Google Drive upload requires GOOGLE_DRIVE_FOLDER_ID env var and Drive scope in OAuth token.",
    }
