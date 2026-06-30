"""CRUD endpoints for trainers."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.database import get_db

router = APIRouter()


class TrainerCreate(BaseModel):
    name: str
    email: Optional[str] = ""
    phone: Optional[str] = ""
    linkedin: Optional[str] = ""
    skills: List[str] = []
    technology_category: Optional[str] = "Multi-Skillset"
    secondary_categories: List[str] = []
    experience_years: Optional[float] = 0
    location: Optional[str] = ""
    day_rate: Optional[float] = None
    bio: Optional[str] = ""
    metadata: Dict[str, Any] = {}


class TrainerUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    linkedin: Optional[str] = None
    skills: Optional[List[str]] = None
    technology_category: Optional[str] = None
    secondary_categories: Optional[List[str]] = None
    experience_years: Optional[float] = None
    location: Optional[str] = None
    day_rate: Optional[float] = None
    bio: Optional[str] = None
    status: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


def _oid(doc: dict) -> dict:
    doc["_id"] = str(doc["_id"])
    return doc


@router.get("")
async def list_trainers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    query: dict = {}
    if status:
        query["status"] = status
    if category:
        query["technology_category"] = {"$regex": category, "$options": "i"}
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
            {"skills": {"$regex": search, "$options": "i"}},
            {"technology_category": {"$regex": search, "$options": "i"}},
        ]
    total = await db.trainers.count_documents(query)
    skip = (page - 1) * page_size
    cursor = db.trainers.find(query, {"resume": 0, "combined_text": 0}).skip(skip).limit(page_size).sort("created_at", -1)
    items = [_oid(d) async for d in cursor]
    return {"items": items, "total": total, "page": page, "page_size": page_size, "pages": max(1, (total + page_size - 1) // page_size)}


@router.post("", status_code=201)
async def create_trainer(
    payload: TrainerCreate,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    import uuid
    now = datetime.utcnow()
    doc = payload.model_dump()
    doc.update({
        "trainer_id": f"TR-{uuid.uuid4().hex[:8].upper()}",
        "status": "new",
        "source": "manual",
        "created_at": now,
        "updated_at": now,
    })
    result = await db.trainers.insert_one(doc)
    created = await db.trainers.find_one({"_id": result.inserted_id}, {"resume": 0, "combined_text": 0})
    return _oid(created)


@router.get("/{trainer_id}")
async def get_trainer(trainer_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    doc = await db.trainers.find_one(
        {"$or": [{"trainer_id": trainer_id}, {"_id": ObjectId(trainer_id)} if len(trainer_id) == 24 else {"trainer_id": trainer_id}]},
        {"resume": 0, "combined_text": 0},
    )
    if not doc:
        raise HTTPException(404, "Trainer not found")
    return _oid(doc)


@router.patch("/{trainer_id}")
async def update_trainer(
    trainer_id: str,
    payload: TrainerUpdate,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not data:
        raise HTTPException(400, "No fields to update")
    data["updated_at"] = datetime.utcnow()
    result = await db.trainers.update_one({"trainer_id": trainer_id}, {"$set": data})
    if result.matched_count == 0:
        raise HTTPException(404, "Trainer not found")
    doc = await db.trainers.find_one({"trainer_id": trainer_id}, {"resume": 0, "combined_text": 0})
    return _oid(doc)


@router.delete("/{trainer_id}", status_code=204)
async def delete_trainer(trainer_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    result = await db.trainers.delete_one({"trainer_id": trainer_id})
    if result.deleted_count == 0:
        raise HTTPException(404, "Trainer not found")



# ─── Extra discovery endpoints ────────────────────────────────────────────────

@router.get("/categories")
async def list_trainer_categories(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Return all distinct primary technology categories."""
    pipeline = [
        {"$group": {"_id": "$technology_category", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$match": {"_id": {"$ne": None}}},
    ]
    categories = [{"category": r["_id"], "count": r["count"]} async for r in db.trainers.aggregate(pipeline)]
    return {"success": True, "categories": categories}


@router.get("/domains")
async def list_trainer_domains(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Return all distinct domains across trainers."""
    pipeline = [
        {"$unwind": {"path": "$secondary_categories", "preserveNullAndEmptyArrays": False}},
        {"$group": {"_id": "$secondary_categories", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    domains = [{"domain": r["_id"], "count": r["count"]} async for r in db.trainers.aggregate(pipeline)]
    return {"success": True, "domains": domains}


@router.get("/industries")
async def list_trainer_industries(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Return all distinct industries from trainer profiles."""
    pipeline = [
        {"$group": {"_id": "$industry_focus", "count": {"$sum": 1}}},
        {"$match": {"_id": {"$ne": None, "$ne": []}}},
        {"$sort": {"count": -1}},
    ]
    industries = [{"industry": r["_id"], "count": r["count"]} async for r in db.trainers.aggregate(pipeline)]
    return {"success": True, "industries": industries}


@router.get("/categorise-jobs/{job_id}")
async def get_categorise_job(job_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Get the status of a bulk categorisation job."""
    from app.config import get_settings
    from app.config import get_settings
    cfg = get_settings()
    # Check in-memory job registry (imported lazily to avoid circular import)
    try:
        import sys
        job = sys.modules.get("_categorise_jobs", {}).get(job_id)
    except Exception:
        job = None
    if not job:
        doc = await db["categorise_jobs"].find_one({"job_id": job_id}, {"_id": 0})
        if not doc:
            raise HTTPException(404, "Categorisation job not found")
        return {"success": True, "job": doc}
    return {"success": True, "job": job}


@router.post("/categorise-all")
async def categorise_all_trainers(
    limit: int = 50,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Trigger bulk AI categorisation for all uncategorised trainers via intelligence-service."""
    import uuid, httpx
    from datetime import datetime
    job_id = f"CAT-{uuid.uuid4().hex[:10].upper()}"
    now = datetime.utcnow()
    await db["categorise_jobs"].insert_one({
        "job_id": job_id, "status": "queued", "limit": limit,
        "created_at": now, "updated_at": now,
    })
    # Delegate to intelligence-service
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                "http://intelligence-service:8005/api/v1/intelligence/categorise/bulk",
                json={"limit": limit, "dry_run": False},
            )
        await db["categorise_jobs"].update_one(
            {"job_id": job_id},
            {"$set": {"status": "dispatched", "updated_at": datetime.utcnow()}},
        )
    except Exception as exc:
        await db["categorise_jobs"].update_one(
            {"job_id": job_id},
            {"$set": {"status": "dispatch_failed", "error": str(exc), "updated_at": datetime.utcnow()}},
        )
    return {"success": True, "job_id": job_id, "status": "dispatched", "limit": limit}


@router.post("/{trainer_id}/categorise")
async def categorise_single_trainer(trainer_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Trigger AI categorisation for a single trainer via intelligence-service."""
    import httpx
    trainer = await db.trainers.find_one({"trainer_id": trainer_id}, {"_id": 0})
    if not trainer:
        raise HTTPException(404, "Trainer not found")
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                "http://intelligence-service:8005/api/v1/intelligence/categorise",
                json={"trainer_id": trainer_id, "trainer": trainer, "save": True},
            )
        if r.status_code < 400:
            return r.json()
        raise HTTPException(502, f"Intelligence service error: {r.text[:200]}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc



# ─── /trainers aliases for resume-upload endpoints ────────────────────────────
# The monolith exposes these under /trainers/* — microservice canonical path is
# /resume-uploads/* but we also serve them here for drop-in compatibility.

@router.post("/upload-resume")
async def upload_resume_alias(
    file: UploadFile = File(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Alias: delegates to document-service resume upload."""
    import httpx as _httpx
    data = await file.read()
    try:
        async with _httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                "http://document-service:8006/api/v1/documents/resume/upload",
                files={"file": (file.filename, data, file.content_type or "application/octet-stream")},
            )
        return r.json()
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc


@router.get("/resume-status/{upload_id}")
async def trainer_resume_status_alias(upload_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Alias: GET /resume-uploads/resume-status/{upload_id}."""
    doc = await db["resume_uploads"].find_one(
        {"upload_id": upload_id},
        {"_id": 0, "upload_id": 1, "processing_status": 1, "trainer_id": 1, "filename": 1, "created_at": 1},
    )
    if not doc:
        raise HTTPException(404, "Upload not found")
    return {"success": True, **doc}


@router.get("/by-upload/{upload_id}")
async def trainer_by_upload_alias(upload_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Alias: GET /resume-uploads/by-upload/{upload_id}."""
    upload = await db["resume_uploads"].find_one({"upload_id": upload_id}, {"_id": 0, "extracted_text": 0})
    if not upload:
        raise HTTPException(404, "Upload not found")
    trainer_id = upload.get("trainer_id")
    trainer = {}
    if trainer_id:
        trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0, "resume": 0}) or {}
    return {"success": True, "upload": upload, "trainer": trainer}


@router.post("/confirm-resume/{upload_id}")
async def confirm_resume_alias(
    upload_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Alias: POST /resume-uploads/confirm-resume/{upload_id} (no corrections body)."""
    from datetime import datetime
    result = await db["resume_uploads"].update_one(
        {"upload_id": upload_id},
        {"$set": {"processing_status": "confirmed", "confirmed_at": datetime.utcnow(), "updated_at": datetime.utcnow()}},
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Upload not found")
    return {"success": True, "upload_id": upload_id, "status": "confirmed"}


@router.post("/confirm-resumes")
async def confirm_resumes_alias(
    upload_ids: List[str],
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Alias: POST /resume-uploads/confirm-resumes."""
    from datetime import datetime
    confirmed = 0
    now = datetime.utcnow()
    for uid in upload_ids:
        result = await db["resume_uploads"].update_one(
            {"upload_id": uid},
            {"$set": {"processing_status": "confirmed", "confirmed_at": now, "updated_at": now}},
        )
        if result.matched_count:
            confirmed += 1
    return {"success": True, "confirmed": confirmed, "total": len(upload_ids)}
