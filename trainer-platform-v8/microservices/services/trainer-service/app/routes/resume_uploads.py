"""Resume uploads — list, get status, delete, confirm previews."""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.database import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


class ConfirmResumeRequest(BaseModel):
    upload_id: str
    corrections: Optional[Dict[str, Any]] = None


class BulkConfirmRequest(BaseModel):
    upload_ids: List[str] = []
    corrections: Optional[Dict[str, Dict[str, Any]]] = None


@router.get("")
async def list_resume_uploads(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    query: Dict[str, Any] = {}
    if status:
        query["processing_status"] = status
    total = await db["resume_uploads"].count_documents(query)
    skip = (page - 1) * page_size
    cursor = (
        db["resume_uploads"]
        .find(query, {"_id": 0, "extracted_text": 0})
        .sort("created_at", -1)
        .skip(skip)
        .limit(page_size)
    )
    items = [d async for d in cursor]
    return {
        "success": True,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
        "uploads": items,
    }


@router.get("/by-upload/{upload_id}")
async def get_trainer_by_upload(upload_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    upload = await db["resume_uploads"].find_one({"upload_id": upload_id}, {"_id": 0, "extracted_text": 0})
    if not upload:
        raise HTTPException(404, "Upload not found")
    trainer_id = upload.get("trainer_id")
    trainer = {}
    if trainer_id:
        trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0, "resume": 0}) or {}
    return {"success": True, "upload": upload, "trainer": trainer}


@router.get("/{upload_id}")
async def get_resume_upload(upload_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    doc = await db["resume_uploads"].find_one({"upload_id": upload_id}, {"_id": 0, "extracted_text": 0})
    if not doc:
        raise HTTPException(404, "Upload not found")
    return {"success": True, "upload": doc}


@router.get("/resume-status/{upload_id}")
async def get_resume_status(upload_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    doc = await db["resume_uploads"].find_one(
        {"upload_id": upload_id},
        {"_id": 0, "upload_id": 1, "processing_status": 1, "trainer_id": 1, "filename": 1, "created_at": 1},
    )
    if not doc:
        raise HTTPException(404, "Upload not found")
    return {"success": True, **doc}


@router.post("/confirm-resume/{upload_id}")
async def confirm_resume(
    upload_id: str,
    payload: ConfirmResumeRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Apply manual corrections to a parsed resume and mark it confirmed."""
    upload = await db["resume_uploads"].find_one({"upload_id": upload_id}, {"_id": 0})
    if not upload:
        raise HTTPException(404, "Upload not found")

    trainer_id = upload.get("trainer_id")
    now = datetime.utcnow()
    corrections = payload.corrections or {}

    update_fields: Dict[str, Any] = {"processing_status": "confirmed", "confirmed_at": now, "updated_at": now}
    if corrections:
        update_fields["corrections_applied"] = corrections

    await db["resume_uploads"].update_one({"upload_id": upload_id}, {"$set": update_fields})

    if trainer_id and corrections:
        await db["trainers"].update_one(
            {"trainer_id": trainer_id},
            {"$set": {**corrections, "updated_at": now}},
        )

    return {"success": True, "upload_id": upload_id, "trainer_id": trainer_id, "status": "confirmed"}


@router.post("/confirm-resumes")
async def confirm_resumes_bulk(
    payload: BulkConfirmRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Bulk-confirm multiple resume uploads."""
    confirmed = 0
    for uid in payload.upload_ids:
        corrections = (payload.corrections or {}).get(uid, {})
        req = ConfirmResumeRequest(upload_id=uid, corrections=corrections or None)
        try:
            await confirm_resume(uid, req, db)
            confirmed += 1
        except HTTPException:
            pass
    return {"success": True, "confirmed": confirmed, "total": len(payload.upload_ids)}


@router.delete("/{upload_id}")
async def delete_resume_upload(upload_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    doc = await db["resume_uploads"].find_one({"upload_id": upload_id}, {"_id": 0, "trainer_id": 1})
    if not doc:
        raise HTTPException(404, "Upload not found")
    await db["resume_uploads"].delete_one({"upload_id": upload_id})
    return {"success": True, "deleted": upload_id, "trainer_id": doc.get("trainer_id")}
