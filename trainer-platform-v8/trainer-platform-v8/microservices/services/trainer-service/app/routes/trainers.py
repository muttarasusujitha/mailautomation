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

CATEGORY_RULES = [
    ("DevOps", ["devops", "docker", "kubernetes", "jenkins", "terraform", "ansible", "ci/cd", "prometheus", "grafana", "helm"]),
    ("Cloud", ["aws", "azure", "gcp", "cloud", "ec2", "s3", "lambda"]),
    ("Data Science", ["data science", "machine learning", "deep learning", "pandas", "numpy", "statistics", "tensorflow", "pytorch"]),
    ("Data Engineering", ["data engineering", "spark", "databricks", "kafka", "airflow", "etl", "bigquery"]),
    ("Cybersecurity", ["cybersecurity", "security", "soc", "siem", "ethical hacking", "vapt"]),
    ("Database", ["sql", "postgresql", "mysql", "mongodb", "oracle", "database"]),
    ("Frontend Development", ["react", "angular", "vue", "html", "css", "redux", "frontend"]),
    ("Backend Development", ["node.js", "node", "express", "django", "flask", "fastapi", "spring boot", "backend", "api"]),
    ("Programming Languages", ["python", "java", "javascript", "typescript", "c++", "c#", "go", "rust"]),
]
EMPTY_CATEGORIES = {"", "-", "unknown", "uncategorised", "uncategorized", "general", "multi-skillset", "not available"}
SKILL_PATTERNS = [
    ("Python", ["python", "python trainer"]),
    ("Java", ["java", "java trainer"]),
    ("JavaScript", ["javascript", "js"]),
    ("TypeScript", ["typescript", "ts"]),
    ("React", ["react", "react.js", "reactjs", "react trainer"]),
    ("Angular", ["angular"]),
    ("Vue.js", ["vue", "vue.js"]),
    ("Node.js", ["node", "node.js", "nodejs"]),
    ("Express.js", ["express", "express.js"]),
    ("MERN Stack", ["mern", "mern stack"]),
    ("MongoDB", ["mongodb", "mongo db"]),
    ("Django", ["django"]),
    ("Flask", ["flask"]),
    ("FastAPI", ["fastapi", "fast api"]),
    ("Spring Boot", ["spring boot"]),
    ("HTML", ["html"]),
    ("CSS", ["css"]),
    ("Redux", ["redux"]),
    ("Next.js", ["next.js", "nextjs"]),
    ("AWS", ["aws", "amazon web services"]),
    ("Azure", ["azure"]),
    ("GCP", ["gcp", "google cloud"]),
    ("Docker", ["docker"]),
    ("Kubernetes", ["kubernetes", "k8s"]),
    ("Jenkins", ["jenkins"]),
    ("Terraform", ["terraform"]),
    ("SQL", ["sql"]),
    ("PostgreSQL", ["postgresql", "postgres"]),
]


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


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "-", "--", "unknown", "n/a", "na", "none", "null", "not available", "not specified"}:
        return ""
    return text


def _clean_list(value: Any) -> List[str]:
    if isinstance(value, list):
        raw_items = value
    elif value:
        raw_items = re.split(r"[,;\n]", str(value))
    else:
        raw_items = []
    seen = set()
    items = []
    for item in raw_items:
        text = _clean_text(item)
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            items.append(text)
    return items


def _unique_list(values: List[str]) -> List[str]:
    seen = set()
    items = []
    for value in values:
        text = _clean_text(value)
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            items.append(text)
    return items


def _has_skill_alias(text: str, alias: str) -> bool:
    pattern = rf"(^|[^a-z0-9+#.]){re.escape(alias)}($|[^a-z0-9+#.])"
    return re.search(pattern, text, re.IGNORECASE) is not None


def _searchable_text(trainer: Dict[str, Any]) -> str:
    return " ".join([
        _clean_text(trainer.get("name")),
        _clean_text(trainer.get("primary_category")),
        _clean_text(trainer.get("technology_category")),
        _clean_text(trainer.get("category")),
        _clean_text(trainer.get("domain")),
        _clean_text(trainer.get("role_designation")),
        _clean_text(trainer.get("technologies")),
        _clean_text(trainer.get("summary")),
        _clean_text(trainer.get("bio")),
        _clean_text(trainer.get("resume")),
        " ".join(_clean_list(trainer.get("skills"))),
        " ".join(_clean_list(trainer.get("secondary_categories"))),
        " ".join(_clean_list(trainer.get("specialisation_tags") or trainer.get("specialty_tags"))),
    ]).lower()


def _detected_skills_from_text(text: str) -> List[str]:
    matches = [
        skill
        for skill, aliases in SKILL_PATTERNS
        if any(_has_skill_alias(text, alias) for alias in aliases)
    ]
    if "MERN Stack" in matches:
        matches.extend(["MongoDB", "Express.js", "React", "Node.js", "JavaScript"])
    return _unique_list(matches)


def _all_skills(trainer: Dict[str, Any]) -> List[str]:
    return _unique_list(_clean_list(trainer.get("skills")) + _detected_skills_from_text(_searchable_text(trainer)))


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        match = re.search(r"(\d+(?:\.\d+)?)", str(value or ""))
        return float(match.group(1)) if match else 0.0


def _infer_category(trainer: Dict[str, Any]) -> str:
    for key in ("primary_category", "technology_category", "category", "domain"):
        text = _clean_text(trainer.get(key))
        if text and text.lower() not in EMPTY_CATEGORIES:
            return text

    skills = _all_skills(trainer)
    haystack = _searchable_text(trainer)
    has_frontend = any(keyword in haystack for keyword in ["react", "angular", "vue", "javascript", "typescript", "html", "css"])
    has_backend = any(keyword in haystack for keyword in ["python", "java", "node", "django", "flask", "fastapi", "spring boot", "api"])
    if has_frontend and has_backend:
        return "Full Stack"

    matches = []
    for category, keywords in CATEGORY_RULES:
        count = sum(1 for keyword in keywords if keyword in haystack)
        if count:
            matches.append((count, category))
    if matches:
        matches.sort(reverse=True)
        return matches[0][1]
    return "Software Development" if skills else ""


def _normalise_score(value: Any) -> float:
    number = _safe_float(value)
    if number <= 0:
        return 0
    if number <= 1:
        return number * 100
    if number <= 5:
        return number * 20
    return min(100, number)


def _experience_years(trainer: Dict[str, Any]) -> float:
    years = _safe_float(trainer.get("experience_years"))
    if years:
        return years
    raw = _clean_text(trainer.get("experience_raw") or trainer.get("experience") or trainer.get("total_experience"))
    match = re.search(r"(\d+(?:\.\d+)?)\+?\s*(?:years?|yrs?)", raw, re.IGNORECASE)
    return float(match.group(1)) if match else 0.0


def _profile_score(trainer: Dict[str, Any], category: str) -> int:
    skills = _all_skills(trainer)
    certs = _clean_list(trainer.get("certifications"))
    clients = _clean_list(trainer.get("past_clients"))
    years = _experience_years(trainer)
    inferred = 30 if skills else 0
    inferred += min(25, len(skills) * 4)
    inferred += 12 if category else 0
    inferred += 6 if _clean_text(trainer.get("name")) else 0
    inferred += min(12, sum(1 for key in ("email", "phone", "linkedin") if _clean_text(trainer.get(key))) * 4)
    inferred += min(15, round(years * 2.5))
    inferred += 4 if _clean_text(trainer.get("location")) else 0
    inferred += 7 if _clean_text(trainer.get("summary") or trainer.get("bio") or trainer.get("resume")) else 0
    inferred += min(7, len(certs) * 3)
    inferred += min(4, len(clients) * 2)
    inferred += 3 if _safe_float(trainer.get("training_count")) else 0
    explicit = max(_normalise_score(trainer.get(key)) for key in (
        "profile_score", "resume_rank_score", "overall_score", "match_score", "fit_score", "confidence_score", "confidence"
    ))
    return max(0, min(100, round(max(inferred, explicit))))


def _profile_breakdown(trainer: Dict[str, Any], category: str) -> Dict[str, Dict[str, int]]:
    existing = trainer.get("score_breakdown")
    existing = existing if isinstance(existing, dict) else {}
    skills = _all_skills(trainer)
    certs = _clean_list(trainer.get("certifications"))
    years = _experience_years(trainer)
    fallback = {
        "technology": {"score": 35 if category else 0, "max": 35},
        "skills": {"score": min(25, len(skills) * 4 + (1 if _clean_text(trainer.get("technologies")) else 0)), "max": 25},
        "experience": {"score": min(15, round(years * 2.5)), "max": 15},
        "certifications": {"score": min(10, len(certs) * 5), "max": 10},
        "location": {"score": 10 if _clean_text(trainer.get("location")) else 0, "max": 10},
    }
    merged: Dict[str, Dict[str, int]] = {}
    for key, fallback_item in fallback.items():
        current = existing.get(key) if isinstance(existing.get(key), dict) else {}
        current_score = _safe_float(current.get("score"))
        fallback_score = _safe_float(fallback_item.get("score"))
        current_max = _safe_float(current.get("max"))
        if not current_max or fallback_score > current_score:
            merged[key] = fallback_item
        else:
            merged[key] = {"score": round(current_score), "max": round(current_max)}
    return merged


def _enrich_trainer_profile(doc: Dict[str, Any]) -> Dict[str, Any]:
    trainer = dict(doc)
    skills = _all_skills(trainer)
    if skills:
        trainer["skills"] = skills
    category = _infer_category(trainer)
    if category:
        for key in ("primary_category", "technology_category", "domain"):
            if not _clean_text(trainer.get(key)):
                trainer[key] = category
    score = _profile_score(trainer, category)
    if not _normalise_score(trainer.get("profile_score")):
        trainer["profile_score"] = score
    if not _normalise_score(trainer.get("resume_rank_score")):
        trainer["resume_rank_score"] = score
    if not _normalise_score(trainer.get("trainer_rating")):
        trainer["trainer_rating"] = round(score / 20, 1) if score else 0
    trainer["score_breakdown"] = _profile_breakdown(trainer, category)
    if not _clean_text(trainer.get("technologies")) and skills:
        trainer["technologies"] = ", ".join(skills)
    return trainer


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
    items = [_enrich_trainer_profile(_oid(d)) async for d in cursor]
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
    return _enrich_trainer_profile(_oid(created))


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
        {"combined_text": 0},
    )
    if not doc:
        raise HTTPException(404, "Trainer not found")
    return _enrich_trainer_profile(_oid(doc))


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
    return _enrich_trainer_profile(_oid(doc))


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
                "https://intelligence-service:8005/api/v1/intelligence/categorise/bulk",
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
                "https://intelligence-service:8005/api/v1/intelligence/categorise",
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
