"""TOC extended routes — knowledge base CRUD, PDF generation, email, auto-generate."""
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
import base64
from fastapi import APIRouter, Depends, HTTPException, Response
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.config import get_settings
from app.database import get_db

settings = get_settings()

router = APIRouter()
logger = logging.getLogger(__name__)

DOC_SVC = settings.DOCUMENT_SERVICE_URL.rstrip("/")
EMAIL_SVC = settings.EMAIL_SERVICE_URL.rstrip("/")


class TocKnowledgeItem(BaseModel):
    domain: str
    toc: Dict[str, Any]
    notes: Optional[str] = ""


class TocImportRequest(BaseModel):
    items: List[TocKnowledgeItem]


class TocEmailRequest(BaseModel):
    toc: Optional[Dict[str, Any]] = None
    toc_id: Optional[str] = None
    to_email: Optional[str] = ""
    trainer_name: Optional[str] = ""
    subject: Optional[str] = ""
    body: Optional[str] = None


class AutoGenerateRequest(BaseModel):
    requirement_id: str
    domain: Optional[str] = ""
    duration_days: Optional[float] = 3.0
    level: Optional[str] = "intermediate"


@router.get("/domains")
async def list_toc_domains(db: AsyncIOMotorDatabase = Depends(get_db)):
    cursor = db["toc_knowledge"].find({}, {"_id": 0, "domain": 1}).sort("domain", 1)
    domains = [d["domain"] async for d in cursor]
    return {"success": True, "domains": domains}


@router.get("/knowledge")
async def list_toc_knowledge(db: AsyncIOMotorDatabase = Depends(get_db)):
    cursor = db["toc_knowledge"].find({}, {"_id": 0}).sort("domain", 1)
    items = [d async for d in cursor]
    return {"success": True, "count": len(items), "items": items}


@router.get("/knowledge/{key}")
async def get_toc_knowledge(key: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    doc = await db["toc_knowledge"].find_one(
        {"$or": [{"domain": {"$regex": f"^{key}$", "$options": "i"}}, {"key": key}]},
        {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, f"TOC knowledge not found for: {key}")
    return {"success": True, "item": doc}


@router.post("/knowledge")
async def save_toc_knowledge(payload: TocKnowledgeItem, db: AsyncIOMotorDatabase = Depends(get_db)):
    now = datetime.utcnow()
    await db["toc_knowledge"].update_one(
        {"domain": {"$regex": f"^{payload.domain}$", "$options": "i"}},
        {"$set": {**payload.model_dump(), "key": payload.domain.lower(), "updated_at": now},
         "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return {"success": True, "domain": payload.domain}


@router.post("/knowledge/import")
async def import_toc_knowledge(payload: TocImportRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    imported = 0
    now = datetime.utcnow()
    for item in payload.items:
        await db["toc_knowledge"].update_one(
            {"domain": {"$regex": f"^{item.domain}$", "$options": "i"}},
            {"$set": {**item.model_dump(), "key": item.domain.lower(), "updated_at": now},
             "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        imported += 1
    return {"success": True, "imported": imported}


@router.delete("/knowledge/{key}")
async def delete_toc_knowledge(key: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    result = await db["toc_knowledge"].delete_one(
        {"$or": [{"domain": {"$regex": f"^{key}$", "$options": "i"}}, {"key": key}]}
    )
    if result.deleted_count == 0:
        raise HTTPException(404, f"TOC knowledge not found: {key}")
    return {"success": True, "deleted": key}


@router.post("/auto-generate")
async def auto_generate_toc(payload: AutoGenerateRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Auto-generate a TOC from a requirement_id."""
    req = await db["requirements"].find_one({"requirement_id": payload.requirement_id}, {"_id": 0}) or {}
    domain = payload.domain or req.get("technology_needed") or req.get("job_title") or "Training"
    duration = payload.duration_days if payload.duration_days is not None else float(req.get("duration_days") or 3.0)

    # Delegate to existing /toc/generate
    from app.routes.toc import generate_toc, TocRequest
    toc_req = TocRequest(
        domain=domain,
        duration_days=duration,
        level=payload.level or "intermediate",
        requirement_id=payload.requirement_id,
    )
    result = await generate_toc(toc_req, db)
    return {"success": True, "requirement_id": payload.requirement_id, "domain": domain, **result}


class TocIdRequest(BaseModel):
    toc: Optional[Dict[str, Any]] = None
    toc_id: Optional[str] = None


@router.post("/generate-pdf")
async def generate_toc_pdf(payload: TocIdRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Convert a TOC dict or stored TOC by id to HTML then PDF via document-service."""
    toc = payload.toc
    if toc is None:
        if not payload.toc_id:
            raise HTTPException(422, "toc_id or toc is required")
        doc = await db["toc_generations"].find_one({"toc_id": payload.toc_id}, {"_id": 0, "toc": 1})
        if not doc:
            raise HTTPException(404, f"TOC not found: {payload.toc_id}")
        toc = doc["toc"]

    title = toc.get("title", "Training Programme")
    rows = ""
    for day in toc.get("days", []):
        rows += f"<tr><td>{day.get('day')}</td><td><b>{day.get('title','')}</b><br>{day.get('focus_area','')}</td></tr>"

    html = f"""<html><body style="font-family:Arial;padding:30px">
    <h1>{title}</h1><p>{toc.get('overview','')}</p>
    <table border="1" cellpadding="6" style="border-collapse:collapse;width:100%">
    <tr><th>Day</th><th>Topic</th></tr>{rows}</table></body></html>"""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{DOC_SVC}/api/v1/documents/pdf/html-to-pdf",
                params={"filename": f"{title}.pdf"},
                content=html,
                headers={"Content-Type": "text/plain"},
            )
        if r.status_code >= 400:
            raise HTTPException(502, f"Document service error: {r.text[:200]}")
        return Response(content=r.content, media_type="application/pdf",
                        headers={"Content-Disposition": f"attachment; filename=toc.pdf"})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc


@router.post("/send-email")
async def send_toc_email(payload: TocEmailRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Email a TOC to a trainer."""
    toc = payload.toc
    trainer_name = payload.trainer_name or "Trainer"
    to_email = payload.to_email or ""

    if toc is None:
        if not payload.toc_id:
            raise HTTPException(422, "toc_id or toc is required")
        doc = await db["toc_generations"].find_one(
            {"toc_id": payload.toc_id},
            {"_id": 0, "toc": 1, "trainer_email": 1, "trainer_name": 1, "toc_id": 1},
        )
        if not doc:
            raise HTTPException(404, f"TOC not found: {payload.toc_id}")
        toc = doc["toc"]
        payload.toc_id = doc.get("toc_id")
        to_email = to_email or doc.get("trainer_email") or ""
        trainer_name = trainer_name or doc.get("trainer_name") or "Trainer"

    if not to_email:
        raise HTTPException(400, "to_email is required")

    title = toc.get("title", "Training Programme TOC")
    body = payload.body or (
        f"Dear {trainer_name},\n\n"
        f"Please find below the Table of Contents for {title}.\n\n"
        "We look forward to your confirmation.\n\nRegards,\nTrainerSync Team"
    )
    try:
        # Attempt to generate a PDF attachment for the TOC and include it in the email
        attachment_payload = None
        try:
            # build minimal HTML same as generate_toc_pdf
            rows = ""
            for day in toc.get("days", []):
                rows += f"<tr><td>{day.get('day')}</td><td><b>{day.get('title','')}</b><br>{day.get('focus_area','')}</td></tr>"
            html = f"""<html><body style=\"font-family:Arial;padding:30px\">\n    <h1>{title}</h1><p>{toc.get('overview','')}</p>\n    <table border=\"1\" cellpadding=\"6\" style=\"border-collapse:collapse;width:100%\">\n    <tr><th>Day</th><th>Topic</th></tr>{rows}</table></body></html>"""
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    f"{DOC_SVC}/api/v1/documents/pdf/html-to-pdf",
                    params={"filename": f"{title}.pdf"},
                    content=html,
                    headers={"Content-Type": "text/plain"},
                )
            if r.status_code == 200 and r.content:
                content_b64 = base64.b64encode(r.content).decode()
                attachment_payload = [{
                    "filename": "toc.pdf",
                    "content_base64": content_b64,
                    "subtype": "pdf",
                }]
        except Exception:
            # if PDF generation fails, proceed without attachment but log
            logger.exception("Failed to generate TOC PDF for email attachment")

        async with httpx.AsyncClient(timeout=30) as client:
            email_json = {
                "to": to_email,
                "subject": payload.subject or f"TOC — {title}",
                "body": body,
            }
            if attachment_payload:
                email_json["attachments"] = attachment_payload
            response = await client.post(f"{EMAIL_SVC}/api/v1/email/send", json=email_json)
        if response.status_code >= 400:
            raise HTTPException(502, f"Email service error: {response.text[:200]}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"success": True, "toc_id": payload.toc_id, "to_email": to_email}
