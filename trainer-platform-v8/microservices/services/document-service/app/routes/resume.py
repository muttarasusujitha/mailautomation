"""Resume upload, parsing, and storage."""
import asyncio
import io
import json
import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database import get_db
from app.config import get_settings

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()

COMMON_SKILLS = [
    "Python", "Java", "JavaScript", "TypeScript", "React", "Angular", "Node.js",
    "Django", "Flask", "FastAPI", "Spring Boot", "AWS", "Azure", "GCP",
    "Docker", "Kubernetes", "Terraform", "Jenkins", "DevOps", "Machine Learning",
    "Deep Learning", "Generative AI", "LangChain", "LLM", "OpenAI",
    "Data Engineering", "Spark", "Databricks", "Kafka", "Airflow",
    "SQL", "MongoDB", "PostgreSQL", "Cybersecurity", "SRE",
]


def _extract_pdf_text(file_bytes: bytes) -> str:
    try:
        import fitz  # PyMuPDF
        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            if doc.needs_pass:
                raise HTTPException(400, "PDF is password-protected. Remove the password and re-upload.")
            return "\n".join(page.get_text("text") for page in doc).strip()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f"Could not read PDF: {exc}") from exc


def _extract_docx_text(file_bytes: bytes) -> str:
    from docx import Document
    doc = Document(io.BytesIO(file_bytes))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            parts.extend(c.text for c in row.cells if c.text.strip())
    return "\n".join(parts).strip()


def extract_text(file_bytes: bytes, filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        text = _extract_pdf_text(file_bytes)
    elif lower.endswith(".docx"):
        text = _extract_docx_text(file_bytes)
    else:
        raise HTTPException(400, "Only PDF and DOCX resumes are supported.")
    if len(text.strip()) < 50:
        raise HTTPException(400, "Could not extract enough text from this file.")
    return text


def _regex_profile(text: str, filename: str) -> Dict[str, Any]:
    email_m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text[:12000])
    phone_m = re.search(r"\+?\d[\d ().-]{8,20}\d", text[:12000])
    li_m = re.search(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[^\s,;)>]{1,120}", text[:12000], re.IGNORECASE)
    exp_vals = [float(m.group(1)) for m in re.finditer(r"(\d+(?:\.\d+)?)\+?\s*(?:years?|yrs?)", text, re.IGNORECASE)]
    lower = text.lower()
    skills = [s for s in COMMON_SKILLS if s.lower() in lower]

    # Derive name: first non-empty line that looks like a name
    name = ""
    for line in text.splitlines()[:12]:
        clean = re.sub(r"[^A-Za-z .'-]", " ", line).strip()
        clean = re.sub(r"\s+", " ", clean)
        words = clean.split()
        if 2 <= len(words) <= 5 and not any(w.lower() in {"resume", "cv", "email", "phone"} for w in words):
            name = clean.title()
            break
    if not name:
        stem = re.sub(r"[_\-]+", " ", filename.rsplit(".", 1)[0]).strip().title()
        name = re.sub(r"\b(Resume|Cv|Profile|Trainer)\b", "", stem, flags=re.IGNORECASE).strip()

    return {
        "name": name,
        "email": email_m.group(0) if email_m else "",
        "phone": phone_m.group(0).strip() if phone_m else "",
        "linkedin": li_m.group(0) if li_m else "",
        "experience_years": max(exp_vals) if exp_vals else 0,
        "skills": skills,
        "extraction_method": "regex_fallback",
        "needs_review": True,
    }


async def _gemini_profile(text: str) -> Dict[str, Any]:
    try:
        import google.generativeai as genai
        key = settings.GEMINI_API_KEY.strip()
        if not key:
            return {}
        genai.configure(api_key=key)
        model = genai.GenerativeModel(
            settings.GEMINI_MODEL,
            generation_config={"temperature": 0, "max_output_tokens": 1600, "response_mime_type": "application/json"},
        )
        prompt = (
            "Extract from this resume. Return ONLY valid JSON with keys: "
            "name, email, phone, location, experience_years (number), role_designation, linkedin, "
            "education, skills (list), certifications (list), past_clients (list), "
            "training_count (int or null), day_rate (number or null), "
            "technology_category, secondary_categories (list), summary.\n\n"
            f"Resume:\n{text[:50000]}"
        )
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, model.generate_content, prompt)
        raw = getattr(resp, "text", "") or ""
        raw = re.sub(r"^```(?:json)?", "", raw.strip(), flags=re.IGNORECASE).strip().rstrip("`")
        return json.loads(raw)
    except Exception as exc:
        logger.warning("Gemini extraction failed: %s", exc)
        return {}


@router.post("/upload")
async def upload_resume(
    file: UploadFile = File(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    if file.size and file.size > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (max 10 MB)")

    file_bytes = await file.read()
    if len(file_bytes) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (max 10 MB)")

    raw_text = extract_text(file_bytes, file.filename or "resume")
    profile = await _gemini_profile(raw_text)
    if not profile.get("name"):
        profile = _regex_profile(raw_text, file.filename or "resume")
    else:
        profile["extraction_method"] = "gemini"
        profile["needs_review"] = False

    trainer_id = f"TR-{uuid.uuid4().hex[:8].upper()}"
    upload_id = f"RES-{uuid.uuid4().hex[:12].upper()}"
    now = datetime.utcnow()

    # Check duplicate by email
    existing = None
    if profile.get("email"):
        existing = await db.trainers.find_one(
            {"email": {"$regex": f"^{re.escape(profile['email'])}$", "$options": "i"}},
            {"_id": 0, "trainer_id": 1},
        )

    if existing:
        trainer_id = existing["trainer_id"]
        action = "updated"
        await db.trainers.update_one(
            {"trainer_id": trainer_id},
            {"$set": {**profile, "updated_at": now}},
        )
    else:
        action = "inserted"
        trainer_doc = {
            **profile,
            "trainer_id": trainer_id,
            "source": "resume_upload",
            "status": "new",
            "resume": raw_text[:50000],
            "created_at": now,
            "updated_at": now,
        }
        await db.trainers.insert_one(trainer_doc)

    await db.resume_uploads.insert_one({
        "upload_id": upload_id,
        "trainer_id": trainer_id,
        "filename": file.filename,
        "processing_status": "completed",
        "extracted_data": profile,
        "extracted_text": raw_text[:50000],
        "created_at": now,
    })

    return {
        "success": True,
        "action": action,
        "trainer_id": trainer_id,
        "upload_id": upload_id,
        "duplicate": existing is not None,
        "profile": {k: v for k, v in profile.items() if k not in {"resume", "combined_text"}},
    }


@router.get("/uploads")
async def list_uploads(
    limit: int = 50,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    cursor = db.resume_uploads.find({}, {"_id": 0, "extracted_text": 0}).limit(limit).sort("created_at", -1)
    items = [d async for d in cursor]
    return {"items": items, "count": len(items)}


@router.get("/uploads/{upload_id}")
async def get_upload(upload_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    doc = await db.resume_uploads.find_one({"upload_id": upload_id}, {"_id": 0, "extracted_text": 0})
    if not doc:
        raise HTTPException(404, "Upload not found")
    return doc
