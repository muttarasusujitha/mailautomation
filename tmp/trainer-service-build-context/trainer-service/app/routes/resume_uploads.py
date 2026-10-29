"""Resume uploads — list, get status, delete, confirm previews."""
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from shared.database.service import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


class ConfirmResumeRequest(BaseModel):
    upload_id: str
    corrections: Optional[Dict[str, Any]] = None


class BulkConfirmRequest(BaseModel):
    upload_ids: List[str] = []
    corrections: Optional[Dict[str, Dict[str, Any]]] = None


PROFILE_FIELDS = {
    "name", "email", "phone", "location", "linkedin", "role_designation",
    "experience_years", "experience_raw", "skills", "technologies",
    "technology_category", "primary_category", "domain", "summary",
    "certifications", "training_count", "past_clients", "day_rate", "hourly_rate",
}


async def _confirm_extracted_profile(db, upload: Dict[str, Any], corrections: Optional[Dict[str, Any]] = None) -> str:
    """Apply only reviewed profile fields, then make the trainer match-eligible."""
    trainer_id = upload.get("trainer_id")
    if not trainer_id:
        raise HTTPException(422, "Resume upload has no trainer identity")
    profile = dict(upload.get("extracted_data") or {})
    profile.update(corrections or {})
    safe_profile = {
        key: value for key, value in profile.items()
        if key in PROFILE_FIELDS and value not in (None, "", [])
    }
    if not safe_profile.get("name") and not safe_profile.get("email"):
        raise HTTPException(422, "Add a trainer name or email before confirming this resume")

    existing = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0, "trainer_id": 1, "created_at": 1})
    if not existing and safe_profile.get("email"):
        existing = await db["trainers"].find_one(
            {"email": {"$regex": f"^{re.escape(str(safe_profile['email']))}$", "$options": "i"}},
            {"_id": 0, "trainer_id": 1, "created_at": 1},
        )
        if existing:
            trainer_id = existing["trainer_id"]
            upload["trainer_id"] = trainer_id
            await db["resume_uploads"].update_one(
                {"upload_id": upload.get("upload_id")},
                {"$set": {"trainer_id": trainer_id, "matched_existing_trainer": True}},
            )
    now = datetime.utcnow()
    fields = {**safe_profile, "needs_review": False, "updated_at": now}
    if upload.get("extracted_text"):
        fields["resume"] = upload["extracted_text"][:50000]
    if not existing:
        fields.update({
            "trainer_id": trainer_id,
            "source": "resume_upload",
            "status": "new",
            "created_at": now,
        })
    await db["trainers"].update_one(
        {"trainer_id": trainer_id},
        {"$set": fields},
        upsert=not bool(existing),
    )
    return "updated" if existing else "inserted"


def _json_safe(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    return value


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
    items = [_json_safe(d) async for d in cursor]
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
    return {"success": True, "upload": _json_safe(upload), "trainer": _json_safe(trainer)}


@router.get("/{upload_id}")
async def get_resume_upload(upload_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    doc = await db["resume_uploads"].find_one({"upload_id": upload_id}, {"_id": 0, "extracted_text": 0})
    if not doc:
        raise HTTPException(404, "Upload not found")
    return {"success": True, "upload": _json_safe(doc)}


@router.get("/resume-status/{upload_id}")
async def get_resume_status(upload_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    doc = await db["resume_uploads"].find_one(
        {"upload_id": upload_id},
        {"_id": 0, "upload_id": 1, "processing_status": 1, "trainer_id": 1, "filename": 1, "created_at": 1},
    )
    if not doc:
        raise HTTPException(404, "Upload not found")
    return {"success": True, **_json_safe(doc)}


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

    action = "already_confirmed"
    trainer_state = await db["trainers"].find_one(
        {"trainer_id": trainer_id}, {"_id": 0, "needs_review": 1},
    ) if trainer_id else None
    if upload.get("processing_status") != "confirmed" or not trainer_state or trainer_state.get("needs_review"):
        action = await _confirm_extracted_profile(
            db, upload, corrections or upload.get("corrections_applied") or {},
        )
    trainer_id = upload.get("trainer_id")

    update_fields: Dict[str, Any] = {"processing_status": "confirmed", "confirmed_at": now, "updated_at": now}
    if corrections:
        update_fields["corrections_applied"] = corrections

    await db["resume_uploads"].update_one({"upload_id": upload_id}, {"$set": update_fields})

    return {"success": True, "upload_id": upload_id, "trainer_id": trainer_id, "status": "confirmed", "action": action}


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
