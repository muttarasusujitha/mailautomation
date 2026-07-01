"""CRUD endpoints for trainers."""
import io
import re
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.config import get_settings
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


class BulkConfirmAliasRequest(BaseModel):
    upload_ids: List[str] = []
    corrections: Optional[Dict[str, Dict[str, Any]]] = None


class _UploadPart:
    def __init__(self, filename: str, data: bytes, content_type: str = "application/octet-stream"):
        self.filename = filename
        self.data = data
        self.content_type = content_type or "application/octet-stream"


def _oid(doc: dict) -> dict:
    doc["_id"] = str(doc["_id"])
    return doc


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


def _append_or(query: Dict[str, Any], clauses: List[Dict[str, Any]]) -> None:
    if not clauses:
        return
    existing = query.get("$and", [])
    existing.append({"$or": clauses})
    query["$and"] = existing


def _regex_clause(field: str, value: str) -> Dict[str, Any]:
    return {field: {"$regex": re.escape(value.strip()), "$options": "i"}}


def _experience_range(value: str) -> Optional[Dict[str, Any]]:
    if not value:
        return None
    text = value.strip().lower()
    if "-" in text:
        left, right = text.split("-", 1)
        try:
            return {"$gte": float(left), "$lte": float(right)}
        except ValueError:
            return None
    if text.endswith("+"):
        try:
            return {"$gte": float(text[:-1])}
        except ValueError:
            return None
    return None


async def _domain_rows(db: AsyncIOMotorDatabase) -> List[Dict[str, Any]]:
    counts: Dict[str, int] = {}
    fields = {
        "technology_category": 1,
        "primary_category": 1,
        "category": 1,
        "domain": 1,
        "secondary_categories": 1,
    }
    async for trainer in db.trainers.find({}, fields):
        values: List[Any] = [
            trainer.get("technology_category"),
            trainer.get("primary_category"),
            trainer.get("category"),
            trainer.get("domain"),
        ]
        secondary = trainer.get("secondary_categories")
        if isinstance(secondary, list):
            values.extend(secondary)
        elif secondary:
            values.append(secondary)
        for value in values:
            text = str(value or "").strip()
            if text:
                counts[text] = counts.get(text, 0) + 1
    return [
        {"domain": domain, "count": count}
        for domain, count in sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))
    ]


def _upload_result(filename: str, response_data: Dict[str, Any]) -> Dict[str, Any]:
    profile = response_data.get("profile") or response_data.get("extracted_data") or {}
    return _json_safe({
        "success": bool(response_data.get("success", True)),
        "filename": filename,
        "upload_id": response_data.get("upload_id"),
        "trainer_id": response_data.get("trainer_id"),
        "action": response_data.get("action"),
        "duplicate": bool(response_data.get("duplicate", False)),
        "extraction_source": profile.get("extraction_method") or response_data.get("extraction_source") or "document_service",
        "confidence_score": profile.get("confidence_score", 0.95 if profile else 0),
        **profile,
    })


async def _post_to_document_service(part: _UploadPart) -> Dict[str, Any]:
    import httpx

    settings = get_settings()
    base_urls = [settings.DOCUMENT_SERVICE_URL.rstrip("/")]
    local_url = "http://127.0.0.1:8006"
    if local_url not in base_urls:
        base_urls.append(local_url)

    last_error = ""
    for base_url in base_urls:
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    f"{base_url}/api/v1/documents/resume/upload",
                    files={"file": (part.filename, part.data, part.content_type)},
                )
            if response.status_code < 400:
                return response.json()
            last_error = response.text[:300]
        except Exception as exc:
            last_error = str(exc)
            continue
    raise HTTPException(502, f"Document service upload failed: {last_error}")


def _expand_zip_upload(filename: str, data: bytes) -> List[_UploadPart]:
    parts: List[_UploadPart] = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                inner_name = info.filename.replace("\\", "/").rsplit("/", 1)[-1]
                lower = inner_name.lower()
                if not lower.endswith((".pdf", ".docx")):
                    continue
                content_type = (
                    "application/pdf"
                    if lower.endswith(".pdf")
                    else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                )
                parts.append(_UploadPart(inner_name, archive.read(info), content_type))
    except zipfile.BadZipFile as exc:
        raise HTTPException(400, f"{filename} is not a valid ZIP file") from exc
    return parts


@router.get("")
async def list_trainers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    limit: Optional[int] = Query(None, ge=1, le=100),
    search: Optional[str] = None,
    category: Optional[str] = None,
    domain: Optional[str] = None,
    industry: Optional[str] = None,
    experience: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    if limit is not None:
        page_size = limit
    query: dict = {}
    if status:
        query["status"] = status
    if category:
        _append_or(query, [
            _regex_clause("technology_category", category),
            _regex_clause("primary_category", category),
            _regex_clause("category", category),
        ])
    if domain:
        _append_or(query, [
            _regex_clause("technology_category", domain),
            _regex_clause("primary_category", domain),
            _regex_clause("category", domain),
            _regex_clause("domain", domain),
            _regex_clause("secondary_categories", domain),
            _regex_clause("skills", domain),
            _regex_clause("technologies", domain),
        ])
    if industry:
        _append_or(query, [
            _regex_clause("industry_focus", industry),
            _regex_clause("past_clients", industry),
        ])
    exp_query = _experience_range(experience or "")
    if exp_query:
        query["experience_years"] = exp_query
    if search:
        _append_or(query, [
            {"name": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
            {"skills": {"$regex": search, "$options": "i"}},
            {"technology_category": {"$regex": search, "$options": "i"}},
            {"primary_category": {"$regex": search, "$options": "i"}},
            {"domain": {"$regex": search, "$options": "i"}},
        ])
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
    return {"success": True, "domains": await _domain_rows(db)}


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
    return {"success": True, "domains": await _domain_rows(db)}


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
    request: Request,
    confirm: bool = Query(False),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Frontend-compatible alias: accepts file/files fields and optional ZIPs."""
    form = await request.form()
    raw_files = []
    for field_name in ("file", "files"):
        raw_files.extend(form.getlist(field_name))

    upload_parts: List[_UploadPart] = []
    archive_count = 0
    for item in raw_files:
        if not hasattr(item, "filename") or not hasattr(item, "read"):
            continue
        filename = item.filename or "resume"
        data = await item.read()
        if filename.lower().endswith(".zip"):
            archive_count += 1
            upload_parts.extend(_expand_zip_upload(filename, data))
            continue
        upload_parts.append(_UploadPart(filename, data, item.content_type or "application/octet-stream"))

    if not upload_parts:
        raise HTTPException(400, "Upload at least one PDF, DOCX, or ZIP containing resumes.")

    results: List[Dict[str, Any]] = []
    for part in upload_parts:
        try:
            response_data = await _post_to_document_service(part)
            result = _upload_result(part.filename, response_data)
            if confirm and result.get("upload_id"):
                now = datetime.utcnow()
                await db["resume_uploads"].update_one(
                    {"upload_id": result["upload_id"]},
                    {"$set": {"processing_status": "confirmed", "confirmed_at": now, "updated_at": now}},
                )
            results.append(result)
        except Exception as exc:
            results.append({
                "success": False,
                "filename": part.filename,
                "error": str(getattr(exc, "detail", None) or exc),
            })

    success_count = sum(1 for item in results if item.get("success"))
    error_count = len(results) - success_count
    inserted = sum(1 for item in results if item.get("success") and item.get("action") == "inserted")
    updated = sum(1 for item in results if item.get("success") and item.get("action") == "updated")
    response: Dict[str, Any] = {
        "success": error_count == 0,
        "results": results,
        "success_count": success_count,
        "error_count": error_count,
        "saved_count": success_count if confirm else 0,
        "inserted": inserted,
        "updated": updated,
        "archive_count": archive_count,
        "archive_resume_count": len(upload_parts) if archive_count else 0,
    }
    if len(results) == 1:
        response.update(results[0])
    return _json_safe(response)


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
    payload: BulkConfirmAliasRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Alias: POST /resume-uploads/confirm-resumes."""
    confirmed = 0
    missing = 0
    now = datetime.utcnow()
    corrections = payload.corrections or {}
    for uid in payload.upload_ids:
        upload = await db["resume_uploads"].find_one({"upload_id": uid}, {"_id": 0, "trainer_id": 1})
        if not upload:
            missing += 1
            continue
        update_fields: Dict[str, Any] = {
            "processing_status": "confirmed",
            "confirmed_at": now,
            "updated_at": now,
        }
        if corrections.get(uid):
            update_fields["corrections_applied"] = corrections[uid]
        result = await db["resume_uploads"].update_one(
            {"upload_id": uid},
            {"$set": update_fields},
        )
        if result.matched_count:
            confirmed += 1
        trainer_id = upload.get("trainer_id")
        if trainer_id and corrections.get(uid):
            await db["trainers"].update_one(
                {"trainer_id": trainer_id},
                {"$set": {**corrections[uid], "updated_at": now}},
            )
    return {
        "success": missing == 0,
        "confirmed": confirmed,
        "total": len(payload.upload_ids),
        "saved_count": confirmed,
        "inserted": confirmed,
        "updated": 0,
        "error_count": missing,
    }
