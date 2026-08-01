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
LOCATION_ALIASES = [
    ("Kolkata", ["kolkata", "calcutta"]),
    ("Bangalore", ["bangalore", "banglore", "bengaluru", "bengalore"]),
    ("Hyderabad", ["hyderabad", "hyderbad", "hydrabad"]),
    ("Chennai", ["chennai"]),
    ("Mumbai", ["mumbai", "bombay"]),
    ("Pune", ["pune"]),
    ("Delhi NCR", ["delhi", "new delhi", "ncr", "gurgaon", "gurugram", "noida"]),
    ("Ahmedabad", ["ahmedabad"]),
    ("Jaipur", ["jaipur"]),
    ("Kochi", ["kochi", "cochin"]),
    ("Coimbatore", ["coimbatore"]),
    ("Indore", ["indore"]),
    ("Lucknow", ["lucknow"]),
    ("Bhubaneswar", ["bhubaneswar"]),
    ("Nagpur", ["nagpur"]),
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


def _upload_as_trainer(upload: Dict[str, Any]) -> Dict[str, Any]:
    extracted = upload.get("extracted_data") if isinstance(upload.get("extracted_data"), dict) else {}
    trainer = {**extracted}
    for key in (
        "upload_id",
        "trainer_id",
        "filename",
        "file_size",
        "processing_status",
        "confidence_score",
        "created_at",
        "processed_at",
        "updated_at",
        "extracted_text",
    ):
        if upload.get(key) is not None and trainer.get(key) in (None, "", []):
            trainer[key] = upload.get(key)
    for key in ("location", "city", "state", "country", "current_location", "domain", "technology_category", "primary_category"):
        if upload.get(key) not in (None, "", []):
            trainer[key] = upload.get(key)
    trainer["source"] = trainer.get("source") or "resume_upload"
    trainer["source_sheet"] = trainer.get("source_sheet") or "resume_upload"
    trainer["status"] = trainer.get("status") or upload.get("processing_status") or "uploaded"
    if upload.get("_id") is not None:
        trainer["_id"] = str(upload["_id"])
    return trainer


def _trainer_profile_from_upload(upload: Dict[str, Any], corrections: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    trainer = _upload_as_trainer(upload)
    if corrections:
        trainer.update(corrections)
    trainer["original_trainer_id"] = trainer.get("trainer_id") or upload.get("trainer_id")
    trainer["trainer_id"] = upload.get("upload_id") or trainer["original_trainer_id"]
    trainer["upload_id"] = upload.get("upload_id") or trainer.get("upload_id")
    trainer["resume_filename"] = upload.get("filename") or trainer.get("resume_filename")
    trainer["processing_status"] = "confirmed"
    trainer["status"] = trainer.get("status") or "pending_review"
    trainer["updated_at"] = datetime.utcnow()
    trainer.setdefault("created_at", upload.get("created_at") or trainer["updated_at"])
    trainer.pop("_id", None)
    trainer.pop("extracted_text", None)
    return trainer


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


def _alias_variants(value: str) -> List[str]:
    text = _clean_text(value)
    if not text:
        return []

    lower = text.lower()
    variants = {text, lower}
    normalized = re.sub(r"[\s\-_]+", " ", lower).strip()
    variants.update({normalized, normalized.replace(" ", ""), normalized.replace(" ", "_"), normalized.replace(" ", "-")})

    if normalized in {"fullstack", "full stack", "full_stack", "full-stack"}:
        variants.update({"fullstack", "full stack", "full_stack", "full-stack"})

    location_aliases = {
        alias.lower(): names
        for names, aliases in LOCATION_ALIASES
        for alias in aliases
    }
    if normalized in location_aliases:
        variants.update(location_aliases[normalized])

    if normalized in {"kolkatha", "kolkata"}:
        variants.update({"kolkata", "kolkatha"})

    return [item for item in _unique_list(list(variants)) if item]


def _regex_clause(field: str, value: str) -> Dict[str, Any]:
    variants = _alias_variants(value)
    if not variants:
        return {field: {"$regex": "", "$options": "i"}}
    pattern = "|".join(re.escape(v) for v in variants)
    return {field: {"$regex": f"(?:{pattern})", "$options": "i"}}


def _trainer_search_clauses(value: str) -> List[Dict[str, Any]]:
    return [
        _regex_clause("name", value),
        _regex_clause("email", value),
        _regex_clause("location", value),
        _regex_clause("city", value),
        _regex_clause("state", value),
        _regex_clause("country", value),
        _regex_clause("current_location", value),
        _regex_clause("preferred_locations", value),
        _regex_clause("skills", value),
        _regex_clause("technologies", value),
        _regex_clause("technology_category", value),
        _regex_clause("primary_category", value),
        _regex_clause("category", value),
        _regex_clause("domain", value),
        _regex_clause("secondary_categories", value),
        _regex_clause("summary", value),
        _regex_clause("bio", value),
        _regex_clause("resume", value),
        _regex_clause("combined_text", value),
    ]


def _upload_search_clauses(value: str) -> List[Dict[str, Any]]:
    clauses = [
        _regex_clause("filename", value),
        _regex_clause("extracted_text", value),
    ]
    for field in (
        "name",
        "email",
        "location",
        "city",
        "state",
        "country",
        "current_location",
        "skills",
        "technologies",
        "technology_category",
        "primary_category",
        "category",
        "domain",
        "secondary_categories",
        "summary",
    ):
        clauses.append(_regex_clause(f"extracted_data.{field}", value))
    return clauses


def _search_tokens(value: str) -> List[str]:
    stop_words = {"trainer", "trainers", "training", "mentor", "in", "at", "from", "near", "based"}
    corrections = {
        "kolkatha": "kolkata",
        "banglore": "bangalore",
        "bengalore": "bangalore",
        "bangalor": "bangalore",
        "hyderbad": "hyderabad",
        "hydrabad": "hyderabad",
        "fullstac": "fullstack",
        "fullstak": "fullstack",
        "fullstacvk": "fullstack",
        "fullsatck": "fullstack",
    }
    tokens = []
    seen = set()
    for token in re.findall(r"[A-Za-z0-9+#.]{2,}", value or ""):
        clean = token.strip()
        key = clean.lower()
        clean = corrections.get(key, clean)
        key = clean.lower()
        if key in stop_words or key in seen:
            continue
        seen.add(key)
        tokens.append(clean)
    return tokens[:6]


def _location_from_search(value: str) -> str:
    haystack = f" {' '.join(_search_tokens(value))} ".lower()
    for location_name, aliases in LOCATION_ALIASES:
        if any(re.search(rf"(^|[^a-z0-9]){re.escape(alias)}($|[^a-z0-9])", haystack, re.IGNORECASE) for alias in aliases):
            return location_name
    return ""


def _domain_from_search(value: str) -> str:
    haystack = f" {' '.join(_search_tokens(value))} ".lower()
    if re.search(r"(^|[^a-z0-9])full\s*stack($|[^a-z0-9])", haystack) or "fullstack" in haystack:
        return "Full Stack"
    for category, keywords in CATEGORY_RULES:
        aliases = [category.lower(), category.lower().replace(" ", ""), *keywords]
        if any(re.search(rf"(^|[^a-z0-9+#.]){re.escape(alias)}($|[^a-z0-9+#.])", haystack, re.IGNORECASE) for alias in aliases):
            return category
    return ""


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
    if text.lower() in {"", "-", "--", "unknown", "n/a", "na", "none", "null", "not available", "not specified", "location not set"}:
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
        _clean_text(trainer.get("location")),
        _clean_text(trainer.get("city")),
        _clean_text(trainer.get("state")),
        _clean_text(trainer.get("country")),
        _clean_text(trainer.get("current_location")),
        _clean_text(trainer.get("preferred_locations")),
        _clean_text(trainer.get("primary_category")),
        _clean_text(trainer.get("technology_category")),
        _clean_text(trainer.get("category")),
        _clean_text(trainer.get("domain")),
        _clean_text(trainer.get("role_designation")),
        _clean_text(trainer.get("technologies")),
        _clean_text(trainer.get("summary")),
        _clean_text(trainer.get("bio")),
        _clean_text(trainer.get("resume")),
        _clean_text(trainer.get("combined_text")),
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
    raw = " ".join([
        _clean_text(trainer.get("experience_raw")),
        _clean_text(trainer.get("experience")),
        _clean_text(trainer.get("total_experience")),
        _clean_text(trainer.get("summary")),
        _clean_text(trainer.get("bio")),
        _clean_text(trainer.get("resume")),
        _clean_text(trainer.get("combined_text")),
    ])
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
    years = _experience_years(trainer)
    if years and not _safe_float(trainer.get("experience_years")):
        trainer["experience_years"] = years
        trainer["experience_raw"] = f"{years:g} years"
    if not _clean_text(trainer.get("technologies")) and skills:
        trainer["technologies"] = ", ".join(skills)
    if not _clean_text(trainer.get("location")):
        inferred_location = _trainer_location(trainer)
        if inferred_location != "Location not set":
            trainer["location"] = inferred_location
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


async def _location_rows(db: AsyncIOMotorDatabase) -> List[Dict[str, Any]]:
    counts: Dict[str, int] = {}
    fields = {
        "location": 1,
        "city": 1,
        "state": 1,
        "country": 1,
        "current_location": 1,
        "preferred_locations": 1,
        "summary": 1,
        "bio": 1,
        "resume": 1,
        "combined_text": 1,
    }
    async def add_location_counts(trainer: Dict[str, Any]) -> None:
        values: List[Any] = [
            trainer.get("location"),
            trainer.get("city"),
            trainer.get("state"),
            trainer.get("country"),
            trainer.get("current_location"),
        ]
        preferred = trainer.get("preferred_locations")
        if isinstance(preferred, list):
            values.extend(preferred)
        elif preferred:
            values.append(preferred)
        values.append(_trainer_location(trainer))
        for value in values:
            text = str(value or "").strip()
            if text:
                counts[text] = counts.get(text, 0) + 1

    async for trainer in db.trainers.find({}, fields):
        await add_location_counts(trainer)
    async for upload in db.resume_uploads.find({}, {**fields, "extracted_data": 1, "upload_id": 1, "trainer_id": 1, "filename": 1, "processing_status": 1, "extracted_text": 1}):
        await add_location_counts(_upload_as_trainer(upload))
    return [
        {"location": location, "count": count}
        for location, count in sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))
    ]


def _trainer_location(trainer: Dict[str, Any]) -> str:
    explicit_values = [
        trainer.get("location"),
        trainer.get("city"),
        trainer.get("current_location"),
        trainer.get("preferred_locations"),
        trainer.get("state"),
        trainer.get("country"),
    ]
    for value in explicit_values:
        if isinstance(value, list):
            for item in value:
                cleaned = _clean_text(item)
                if cleaned:
                    return cleaned
        else:
            cleaned = _clean_text(value)
            if cleaned:
                return cleaned

    text = _searchable_text(trainer)
    for location, aliases in LOCATION_ALIASES:
        if any(re.search(rf"(^|[^a-z0-9]){re.escape(alias)}($|[^a-z0-9])", text, re.IGNORECASE) for alias in aliases):
            return location
    return "Location not set"


def _matches_location_filter(trainer: Dict[str, Any], location_filter: str) -> bool:
    location = _location_filter_text(location_filter)
    if not location:
        return True
    return _trainer_location(trainer).lower() == location.lower()


def _location_filter_text(value: Any) -> str:
    raw = str(value or "").strip()
    if raw.lower() == "location not set":
        return "Location not set"
    return _clean_text(raw)


def _domain_rank_score(trainer: Dict[str, Any], domain: str) -> int:
    """Rank a trainer inside a location/domain bucket using resume strength and domain fit."""
    score = _safe_float(trainer.get("profile_score") or trainer.get("resume_rank_score"))
    text = _searchable_text(trainer)
    domain_text = _clean_text(domain).lower()
    if domain_text and domain_text in text:
        score += 12
    domain_tokens = _search_tokens(domain)
    if domain_tokens:
        score += min(18, sum(4 for token in domain_tokens if token.lower() in text))
    if _clean_text(trainer.get("resume") or trainer.get("summary") or trainer.get("bio")):
        score += 5
    if _clean_text(trainer.get("location") or trainer.get("city") or trainer.get("current_location")):
        score += 3
    return max(0, min(130, round(score)))


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
    base_url = settings.DOCUMENT_SERVICE_URL.rstrip("/")
    if base_url.startswith("https://document-service:8006"):
        base_url = base_url.replace("https://", "http://", 1)

    last_error = ""
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{base_url}/api/v1/documents/resume/upload",
                files={"file": (part.filename, part.data, part.content_type)},
            )
        if response.status_code < 400:
            return response.json()
        # Document service returned an HTTP error (reachable but processing failed).
        try:
            return response.json()
        except Exception:
            raise HTTPException(response.status_code, f"Document service upload failed: {response.text[:300]}")
    except Exception as exc:
        last_error = str(exc)
    raise HTTPException(502, f"Document service upload failed: {last_error}")
    # All attempts failed due to connection errors.
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
    location: Optional[str] = None,
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
    if location:
        _append_or(query, [
            _regex_clause("location", location),
            _regex_clause("city", location),
            _regex_clause("state", location),
            _regex_clause("country", location),
            _regex_clause("current_location", location),
            _regex_clause("preferred_locations", location),
            _regex_clause("resume", location),
            _regex_clause("combined_text", location),
            _regex_clause("summary", location),
            _regex_clause("bio", location),
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
        tokens = _search_tokens(search)
        if len(tokens) > 1:
            for token in tokens:
                _append_or(query, _trainer_search_clauses(token))
        else:
            _append_or(query, _trainer_search_clauses(search))
    skip = (page - 1) * page_size
    projection = {"resume": 0, "combined_text": 0}
    if location:
        matched_items = []
        location_filter = _location_filter_text(location)
        async for doc in db.trainers.find(query, projection).sort("created_at", -1):
            trainer = _enrich_trainer_profile(_oid(doc))
            if _matches_location_filter(trainer, location_filter):
                matched_items.append(trainer)
        total = len(matched_items)
        items = matched_items[skip:skip + page_size]
    else:
        total = await db.trainers.count_documents(query)
        cursor = db.trainers.find(query, projection).skip(skip).limit(page_size).sort("created_at", -1)
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


@router.get("/locations")
async def list_trainer_locations(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Return all distinct trainer locations."""
    return {"success": True, "locations": await _location_rows(db)}


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


@router.get("/location-groups")
async def trainer_location_groups(
    location: Optional[str] = None,
    search: Optional[str] = None,
    domain: Optional[str] = None,
    limit: int = Query(200, ge=1, le=500),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Return trainers grouped by location and domain for drill-down browsing."""
    query: Dict[str, Any] = {}
    upload_query: Dict[str, Any] = {}
    derived_location = _location_from_search(search or "")
    derived_domain = _domain_from_search(search or "")
    location_filter = _location_filter_text(location or derived_location)
    domain_filter = _clean_text(domain or derived_domain)
    if location_filter and location_filter.lower() != "location not set":
        trainer_location_clauses = [
            _regex_clause("location", location_filter),
            _regex_clause("city", location_filter),
            _regex_clause("state", location_filter),
            _regex_clause("country", location_filter),
            _regex_clause("current_location", location_filter),
            _regex_clause("preferred_locations", location_filter),
            _regex_clause("resume", location_filter),
            _regex_clause("combined_text", location_filter),
            _regex_clause("summary", location_filter),
            _regex_clause("bio", location_filter),
        ]
        upload_location_clauses = [
            _regex_clause("location", location_filter),
            _regex_clause("city", location_filter),
            _regex_clause("current_location", location_filter),
            _regex_clause("extracted_text", location_filter),
            _regex_clause("extracted_data.location", location_filter),
            _regex_clause("extracted_data.city", location_filter),
            _regex_clause("extracted_data.state", location_filter),
            _regex_clause("extracted_data.country", location_filter),
            _regex_clause("extracted_data.current_location", location_filter),
            _regex_clause("extracted_data.summary", location_filter),
        ]
        _append_or(query, trainer_location_clauses)
        _append_or(upload_query, upload_location_clauses)
    if domain_filter:
        trainer_domain_clauses = [
            _regex_clause("technology_category", domain_filter),
            _regex_clause("primary_category", domain_filter),
            _regex_clause("category", domain_filter),
            _regex_clause("domain", domain_filter),
            _regex_clause("secondary_categories", domain_filter),
            _regex_clause("skills", domain_filter),
            _regex_clause("technologies", domain_filter),
        ]
        upload_domain_clauses = [
            _regex_clause("domain", domain_filter),
            _regex_clause("technology_category", domain_filter),
            _regex_clause("primary_category", domain_filter),
            _regex_clause("category", domain_filter),
            _regex_clause("extracted_data.domain", domain_filter),
            _regex_clause("extracted_data.technology_category", domain_filter),
            _regex_clause("extracted_data.primary_category", domain_filter),
            _regex_clause("extracted_data.category", domain_filter),
            _regex_clause("extracted_data.secondary_categories", domain_filter),
            _regex_clause("extracted_data.skills", domain_filter),
            _regex_clause("extracted_data.technologies", domain_filter),
            _regex_clause("extracted_text", domain_filter),
        ]
        _append_or(query, trainer_domain_clauses)
        _append_or(upload_query, upload_domain_clauses)
    if search:
        for token in _search_tokens(search):
            _append_or(query, _trainer_search_clauses(token))
            _append_or(upload_query, _upload_search_clauses(token))

    cursor = db.trainers.find(query).sort("created_at", -1).limit(limit)
    locations: Dict[str, Dict[str, Any]] = {}
    seen_keys = set()

    def add_to_groups(trainer: Dict[str, Any]) -> None:
        location_key = _trainer_location(trainer)
        if location_filter and not _matches_location_filter(trainer, location_filter):
            return
        domain_key = _infer_category(trainer) or _clean_text(trainer.get("domain")) or "Uncategorised"
        if domain_filter and domain_key.lower() != domain_filter.lower():
            return
        key_parts = [
            _clean_text(trainer.get("email")).lower(),
            _clean_text(trainer.get("name")).lower(),
            _clean_text(trainer.get("phone")),
            _clean_text(trainer.get("resume_filename") or trainer.get("filename")).lower(),
        ]
        key = "|".join(part for part in key_parts if part)
        if not key:
            key = trainer.get("original_trainer_id") or trainer.get("trainer_id") or trainer.get("upload_id") or trainer.get("_id")
        if key:
            dedupe_key = str(key).lower()
            if dedupe_key in seen_keys:
                return
            seen_keys.add(dedupe_key)
        trainer.pop("resume", None)
        trainer.pop("combined_text", None)
        trainer.pop("extracted_text", None)
        location_bucket = locations.setdefault(
            location_key,
            {"location": location_key, "count": 0, "domains": {}},
        )
        domain_bucket = location_bucket["domains"].setdefault(
            domain_key,
            {"domain": domain_key, "count": 0, "trainers": []},
        )
        location_bucket["count"] += 1
        domain_bucket["count"] += 1
        trainer["domain_rank_score"] = _domain_rank_score(trainer, domain_key)
        domain_bucket["trainers"].append(trainer)

    async for doc in cursor:
        add_to_groups(_enrich_trainer_profile(_oid(doc)))

    upload_cursor = db.resume_uploads.find(
        upload_query,
        {"combined_text": 0},
    ).sort("created_at", -1).limit(limit)
    async for upload in upload_cursor:
        add_to_groups(_enrich_trainer_profile(_upload_as_trainer(upload)))

    rows = []
    for location_bucket in locations.values():
        for domain_bucket in location_bucket["domains"].values():
            ranked_trainers = sorted(
                domain_bucket["trainers"],
                key=lambda item: (
                    -_safe_float(item.get("domain_rank_score")),
                    -_safe_float(item.get("profile_score") or item.get("resume_rank_score")),
                    _clean_text(item.get("name")).lower(),
                ),
            )
            for index, trainer in enumerate(ranked_trainers, start=1):
                trainer["domain_location_rank"] = index
                trainer["rank_label"] = f"Top {index}"
            domain_bucket["trainers"] = ranked_trainers[:20]
        domains = sorted(
            location_bucket["domains"].values(),
            key=lambda item: (-item["count"], item["domain"].lower()),
        )
        rows.append({
            "location": location_bucket["location"],
            "count": location_bucket["count"],
            "domains": domains,
        })
    rows.sort(key=lambda item: (-item["count"], item["location"].lower()))
    return {"success": True, "locations": rows, "count": sum(item["count"] for item in rows)}


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
    data = payload.model_dump(exclude_unset=True)
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
    upload = await db["resume_uploads"].find_one({"upload_id": upload_id}, {"_id": 0})
    if not upload:
        raise HTTPException(404, "Upload not found")
    result = await db["resume_uploads"].update_one(
        {"upload_id": upload_id},
        {"$set": {"processing_status": "confirmed", "confirmed_at": datetime.utcnow(), "updated_at": datetime.utcnow()}},
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Upload not found")
    trainer_profile = _trainer_profile_from_upload(upload)
    save_result = await db["trainers"].update_one(
        {"trainer_id": trainer_profile["trainer_id"]},
        {"$set": trainer_profile},
        upsert=True,
    )
    return {
        "success": True,
        "upload_id": upload_id,
        "trainer_id": trainer_profile["trainer_id"],
        "status": "confirmed",
        "inserted": 1 if save_result.upserted_id else 0,
        "updated": 0 if save_result.upserted_id else 1,
    }


@router.post("/confirm-resumes")
async def confirm_resumes_alias(
    payload: BulkConfirmAliasRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Alias: POST /resume-uploads/confirm-resumes."""
    confirmed = 0
    missing = 0
    inserted = 0
    updated = 0
    now = datetime.utcnow()
    corrections = payload.corrections or {}
    for uid in payload.upload_ids:
        upload = await db["resume_uploads"].find_one({"upload_id": uid}, {"_id": 0})
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
        trainer_profile = _trainer_profile_from_upload(upload, corrections.get(uid))
        save_result = await db["trainers"].update_one(
            {"trainer_id": trainer_profile["trainer_id"]},
            {"$set": trainer_profile},
            upsert=True,
        )
        if save_result.upserted_id:
            inserted += 1
        else:
            updated += 1
    return {
        "success": missing == 0,
        "confirmed": confirmed,
        "total": len(payload.upload_ids),
        "saved_count": confirmed,
        "inserted": inserted,
        "updated": updated,
        "error_count": missing,
    }
