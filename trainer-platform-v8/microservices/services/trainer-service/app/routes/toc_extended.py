"""TOC extended routes — knowledge base CRUD, PDF generation, email, auto-generate."""
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
import base64
from fastapi import APIRouter, Body, Depends, HTTPException, Response
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.config import get_settings
from app.database import get_db
from app.toc_pdf_template import build_toc_html

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


LEVEL_KEYS = (
    "foundation",
    "core",
    "advanced",
    "observability",
    "security",
    "projects",
    "revision",
    "capstone",
)


def _slugify_domain(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in value.strip())
    return "_".join(part for part in slug.split("_") if part)


def _domain_filter(key: str) -> Dict[str, Any]:
    return {
        "$or": [
            {"domain": {"$regex": f"^{key}$", "$options": "i"}},
            {"key": key},
        ]
    }


def _normalise_toc_knowledge(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = (payload.get("name") or payload.get("domain") or payload.get("key") or "").strip()
    key = (payload.get("key") or _slugify_domain(name)).strip()
    if not name:
        raise HTTPException(422, "Domain name is required")
    if not key:
        raise HTTPException(422, "Domain key is required")

    level_map = payload.get("level_map") if isinstance(payload.get("level_map"), dict) else {}
    toc = payload.get("toc") if isinstance(payload.get("toc"), dict) else {}
    if not level_map and toc:
        level_map = toc.get("level_map") or {}

    return {
        **payload,
        "key": key,
        "name": name,
        "domain": name,
        "icon": payload.get("icon") or "book",
        "aliases": payload.get("aliases") or [],
        "active": payload.get("active", True),
        "level_map": {level: level_map.get(level, []) for level in LEVEL_KEYS},
        "jira_practice": payload.get("jira_practice") or {},
        "certifications": payload.get("certifications") or [],
        "toc": toc or {"level_map": level_map},
    }


def _parse_import_text(text: str) -> List[Dict[str, Any]]:
    docs = []
    blocks = []
    current_block = []
    for raw_line in text.splitlines():
        if raw_line.strip().lower().startswith("technology name:") and current_block:
            blocks.append("\n".join(current_block).strip())
            current_block = []
        current_block.append(raw_line)
    if current_block:
        blocks.append("\n".join(current_block).strip())

    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        name = ""
        aliases = []
        level_map = {level: [] for level in LEVEL_KEYS}
        current_level = "foundation"
        tools = []
        certifications = []

        for line in lines:
            lower = line.lower()
            if lower.startswith("technology name:"):
                name = line.split(":", 1)[1].strip()
            elif lower.startswith("aliases:"):
                aliases = [item.strip() for item in line.split(":", 1)[1].split(",") if item.strip()]
            elif lower.startswith("tools:"):
                tools = [item.strip() for item in line.split(":", 1)[1].split(",") if item.strip()]
            elif lower.startswith("certifications:"):
                certifications = [line.split(":", 1)[1].strip()]
            elif "foundation" in lower and "topic" in lower:
                current_level = "foundation"
            elif "core" in lower and "topic" in lower:
                current_level = "core"
            elif "advanced" in lower and "topic" in lower:
                current_level = "advanced"
            elif line[0].isdigit() or line.startswith("-"):
                topic = line.lstrip("- ").split(".", 1)[-1].strip()
                if topic:
                    level_map[current_level].append({"topic": topic, "subtopics": [], "tools": tools, "lab": ""})

        if name:
            docs.append(_normalise_toc_knowledge({
                "name": name,
                "key": _slugify_domain(name),
                "aliases": aliases,
                "level_map": level_map,
                "certifications": [item for item in certifications if item],
            }))
    return docs


def _legacy_build_rich_toc_html(toc: Dict[str, Any]) -> str:
    """Build comprehensive, professional HTML from TOC data."""
    title = toc.get("title") or toc.get("program_title") or toc.get("domain") or "Training Programme"
    subtitle = toc.get("subtitle") or (f"{toc.get('level', '')} • {toc.get('mode', '')}".strip(" • ")) or ""
    trainer_name = toc.get("trainer_name", "")
    duration_days = toc.get("duration_days")
    overview = toc.get("overview", "")

    metadata_items = []
    if trainer_name:
        metadata_items.append(f"Trainer: {trainer_name}")
    if duration_days is not None and duration_days != "":
        metadata_items.append(f"Duration: {duration_days} days")
    if toc.get("level"):
        metadata_items.append(f"Level: {toc.get('level')}")
    if toc.get("mode"):
        metadata_items.append(f"Mode: {toc.get('mode')}")
    metadata_text = " | ".join(metadata_items)
    
    # Header
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #000; padding: 40px; max-width: 900px; margin: 0 auto; background: #fff; }}
        .header {{ text-align: center; border-bottom: 3px solid #1d4ed8; padding-bottom: 20px; margin-bottom: 30px; }}
        .company {{ color: #475569; font-size: 12px; margin-bottom: 10px; }}
        h1 {{ color: #1d4ed8; margin: 10px 0; font-size: 34px; }}
        h2 {{ color: #0f172a; margin-top: 30px; margin-bottom: 15px; border-left: 4px solid #1d4ed8; padding-left: 10px; }}
        h3 {{ color: #0f172a; margin-top: 20px; margin-bottom: 10px; }}
        .subtitle {{ color: #0f172a; font-size: 14px; margin: 5px 0; }}
        .metadata {{ background: #f1f5f9; padding: 10px 15px; margin: 10px 0; border-radius: 4px; font-size: 12px; color: #334155; }}
        .section {{ margin-bottom: 25px; }}
        .overview {{ background: #f8fafc; padding: 15px; border-left: 3px solid #1d4ed8; margin-bottom: 20px; color: #0f172a; }}
        .roadmap-table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
        .roadmap-table th, .roadmap-table td {{ padding: 10px; text-align: left; border: 1px solid #cbd5e1; vertical-align: top; }}
        .roadmap-table th {{ background: #1d4ed8; color: white; font-weight: bold; }}
        .roadmap-table tr:nth-child(even) {{ background: #f8fafc; }}
        .day-section {{ page-break-inside: avoid; margin: 20px 0; padding: 0; }}
        .day-title {{ color: #1d4ed8; font-size: 24px; font-weight: 700; margin-bottom: 6px; }}
        .day-meta {{ color: #475569; font-size: 13px; margin-bottom: 16px; }}
        .session-heading {{ font-size: 16px; font-weight: 600; color: #0f172a; margin: 14px 0 8px; }}
        .session-items, .standard-list {{ margin: 8px 0 0 0; padding-left: 20px; color: #0f172a; }}
        .session-items li, .standard-list li {{ margin: 5px 0; line-height: 1.5; }}
        .section-block {{ margin-top: 12px; }}
        .tools-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin: 10px 0; }}
        .tool-item {{ padding: 8px; background: #f1f5f9; border-radius: 3px; font-size: 12px; }}
        .cert-list {{ list-style: none; padding-left: 0; }}
        .cert-item {{ padding: 6px 0; padding-left: 20px; position: relative; }}
        .cert-item:before {{ content: "✓"; position: absolute; left: 0; color: #16a34a; }}
        ul {{ margin: 10px 0; padding-left: 20px; color: #0f172a; }}
        li {{ margin: 5px 0; }}
        .assessment {{ background: #fef3c7; padding: 10px; border-radius: 3px; margin: 10px 0; }}
        .page-break {{ page-break-after: always; }}
    </style>
</head>
<body>
    <!-- Header -->
    <div class="header">
        <div class="company">Clahan Technologies | TrainerSync</div>
        <h1>{title}</h1>
        <div class="subtitle">{subtitle}</div>
        {f'<div class="metadata">{metadata_text}</div>' if metadata_text else ''}
    </div>
"""
    
    # Program Overview Section
    if overview:
        html += f"""
    <div class="section">
        <h2>Program Overview</h2>
        <div class="overview">{overview}</div>
    </div>
"""
    
    # Program Roadmap
    days = toc.get("days", [])
    if days:
        html += """
    <div class="section">
        <h2>Program Roadmap</h2>
        <table class="roadmap-table">
            <tr><th>Day</th><th>Topic</th><th>Tools</th><th>Jira Focus</th></tr>
"""
        for day in days:
            day_num = day.get('day', '')
            title_day = day.get('title') or day.get('topic') or ''
            tools_data = day.get('tools', [])
            tools = ', '.join(tools_data) if isinstance(tools_data, list) else tools_data
            jira = day.get('jira_focus', '')
            html += f"            <tr><td>{day_num}</td><td>{title_day}</td><td>{tools}</td><td>{jira}</td></tr>\n"
        html += """        </table>
    </div>
"""
    
    # Prerequisites
    prereqs = toc.get("prerequisites", [])
    if prereqs:
        html += """
    <div class="section">
        <h2>Prerequisites</h2>
        <ul>
"""
        for prereq in prereqs:
            html += f"            <li>{prereq}</li>\n"
        html += """        </ul>
    </div>
"""
    
    # Learning Outcomes
    outcomes = toc.get("learning_outcomes", [])
    if outcomes:
        html += """
    <div class="section">
        <h2>Learning Outcomes</h2>
        <ul>
"""
        for outcome in outcomes:
            html += f"            <li>{outcome}</li>\n"
        html += """        </ul>
    </div>
"""
    
    # Detailed Day Breakdowns
    def render_session(session_data: Dict[str, Any], default_title: str) -> str:
        if not session_data:
            return ""
        title_text = session_data.get("title", default_title)
        time_slot = session_data.get("time", "")
        heading = f"<div class=\"session-heading\">{title_text}{f' ({time_slot})' if time_slot else ''}</div>"
        items = []
        for topic in session_data.get("topics", []):
            if isinstance(topic, dict):
                time_range = topic.get("time", "")
                topic_text = topic.get("topic", "")
                topic_type = topic.get("type", "")
                text = " - ".join(part for part in [time_range, topic_text] if part)
                if topic_type:
                    text += f" [{topic_type}]"
            else:
                text = str(topic)
            items.append(f"<li>{text}</li>")

        if items:
            return f"{heading}<ul class=\"session-items\">{''.join(items)}</ul>"
        return heading

    def render_section_list(title: str, items: List[Any]) -> str:
        if not items:
            return ""
        list_items = "".join(f"<li>{item}</li>" for item in items)
        return f"            <div class=\"section-block\">\n                <div class=\"session-heading\">{title}</div>\n                <ul class=\"standard-list\">{list_items}</ul>\n            </div>\n"

    if days:
        html += """
    <div class="page-break"></div>
    <div class="section">
        <h2>Detailed Daily Breakdown</h2>
"""
        for day in days:
            day_num = day.get('day', '')
            title_day = day.get('title') or day.get('topic') or ''
            tools_data = day.get('tools', [])
            tools = ', '.join(tools_data) if isinstance(tools_data, list) else tools_data
            jira_focus = day.get('jira_focus', '')
            morning_text = render_session(day.get('morning_session', {}), 'Morning Session')
            afternoon_text = render_session(day.get('afternoon_session', {}), 'Afternoon Session')
            if not morning_text and not afternoon_text and day.get('subtopics'):
                morning_text = render_session({'title': 'Topic Coverage', 'topics': day.get('subtopics', [])}, 'Topic Coverage')
            subtopics_text = render_section_list('Subtopics', day.get('subtopics', [])) if day.get('subtopics') else ''
            lab_task = day.get('lab_task')
            objective_text = render_section_list('Learning Objectives', day.get('learning_objectives', []))
            jira_text = ''
            if jira_focus:
                jira_text = render_section_list('Jira Focus', [jira_focus])
            if day.get('jira_practice'):
                jira_text += render_section_list('Jira Practice', day.get('jira_practice', []))
            lab_text = f"            <div class=\"section-block\">\n                <div class=\"session-heading\">Lab Task</div>\n                <ul class=\"standard-list\"><li>{lab_task}</li></ul>\n            </div>\n" if lab_task else ""

            html += f"""
        <div class="day-section">
            <div class="day-title">Day {day_num}: {title_day}</div>
            <div class="day-meta">Tools: {tools}{f' | Jira Focus: {jira_focus}' if jira_focus else ''}</div>
            {morning_text}
            {afternoon_text}
"""
            html += subtopics_text
            html += lab_text
            html += objective_text
            html += jira_text
            html += """        </div>
"""
        html += """    </div>
"""
    
    # Tools & Software
    tools_list = toc.get("tools_software", [])
    if tools_list:
        html += """
    <div class="page-break"></div>
    <div class="section">
        <h2>Tools & Software</h2>
        <div class="tools-grid">
"""
        for tool in tools_list:
            html += f'            <div class="tool-item">✓ {tool}</div>\n'
        html += """        </div>
    </div>
"""
    
    # Assessment Plan
    assessment = toc.get("assessment_plan", [])
    if assessment:
        html += """
    <div class="section">
        <h2>Assessment Plan</h2>
"""
        for item in assessment:
            html += f'        <div class="assessment">✓ {item}</div>\n'
        html += """    </div>
"""
    
    # Hiring & Test Preparation
    hiring = toc.get("hiring_preparation", [])
    if hiring:
        html += """
    <div class="section">
        <h2>Hiring & Test Preparation</h2>
"""
        for item in hiring:
            html += f'        <div class="assessment">✓ {item}</div>\n'
        html += """    </div>
"""
    
    # Certification Roadmap
    certs = toc.get("certification_roadmap", [])
    if certs:
        html += """
    <div class="section">
        <h2>Certification Roadmap</h2>
        <ul class="cert-list">
"""
        for cert in certs:
            html += f'            <li class="cert-item">{cert}</li>\n'
        html += """        </ul>
    </div>
"""
    
    # Certification Guidance
    cert_guidance = toc.get("certification_guidance", "")
    if cert_guidance:
        html += f"""
    <div class="section">
        <h2>Certification Guidance</h2>
        <p>{cert_guidance}</p>
    </div>
"""
    
    # Trainer Notes
    trainer_notes = toc.get("trainer_notes", "")
    if trainer_notes:
        html += f"""
    <div class="section" style="font-size: 11px; color: #7f8c8d; border-top: 1px solid #ecf0f1; padding-top: 15px; margin-top: 30px;">
        <strong>Trainer Notes:</strong> {trainer_notes}
    </div>
"""
    
    html += """
</body>
</html>
"""
    return html


@router.get("/domains")
async def list_toc_domains(db: AsyncIOMotorDatabase = Depends(get_db)):
    cursor = db["toc_knowledge"].find({}, {"_id": 0, "domain": 1}).sort("domain", 1)
    domains = [d["domain"] async for d in cursor]
    return {"success": True, "domains": domains}


@router.get("/knowledge")
async def list_toc_knowledge(db: AsyncIOMotorDatabase = Depends(get_db)):
    cursor = db["toc_knowledge"].find({}, {"_id": 0}).sort("domain", 1)
    items = [d async for d in cursor]
    return {"success": True, "count": len(items), "items": items, "domains": items}


@router.get("/knowledge/{key}")
async def get_toc_knowledge(key: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    doc = await db["toc_knowledge"].find_one(
        _domain_filter(key),
        {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, f"TOC knowledge not found for: {key}")
    return {"success": True, "item": doc, "domain": doc}


@router.post("/knowledge")
async def save_toc_knowledge(payload: Dict[str, Any] = Body(...), db: AsyncIOMotorDatabase = Depends(get_db)):
    now = datetime.utcnow()
    doc = _normalise_toc_knowledge(payload)
    await db["toc_knowledge"].update_one(
        _domain_filter(doc["key"]),
        {"$set": {**doc, "updated_at": now},
         "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return {"success": True, "domain": doc, "item": doc}


@router.post("/knowledge/import")
async def import_toc_knowledge(payload: Dict[str, Any] = Body(...), db: AsyncIOMotorDatabase = Depends(get_db)):
    imported = 0
    now = datetime.utcnow()
    docs = []
    if isinstance(payload.get("items"), list):
        docs = [_normalise_toc_knowledge(item) for item in payload["items"]]
    elif isinstance(payload.get("text"), str):
        docs = _parse_import_text(payload["text"])
    if not docs:
        raise HTTPException(422, "Import requires pasted text or at least one item")

    for item in docs:
        await db["toc_knowledge"].update_one(
            _domain_filter(item["key"]),
            {"$set": {**item, "updated_at": now},
             "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        imported += 1
    return {"success": True, "imported": imported, "domains": docs, "items": docs}


@router.delete("/knowledge/{key}")
async def delete_toc_knowledge(key: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    result = await db["toc_knowledge"].delete_one(
        _domain_filter(key)
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


TOC_METADATA_FIELDS = (
    "domain",
    "technology",
    "duration_days",
    "level",
    "mode",
    "trainer_name",
    "training_dates",
    "timing",
)


def _with_toc_metadata(toc: Dict[str, Any], source: Dict[str, Any]) -> Dict[str, Any]:
    enriched = dict(toc or {})
    for field in TOC_METADATA_FIELDS:
        value = source.get(field)
        if value not in (None, "") and not enriched.get(field):
            enriched[field] = value
    if source.get("audience_level") and not enriched.get("level"):
        enriched["level"] = source["audience_level"]
    return enriched


@router.post("/generate-pdf")
async def generate_toc_pdf(payload: TocIdRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Convert a TOC dict or stored TOC by id to HTML then PDF via document-service."""
    toc = payload.toc
    if toc is None:
        if not payload.toc_id:
            raise HTTPException(422, "toc_id or toc is required")
        doc = await db["toc_generations"].find_one(
            {"toc_id": payload.toc_id},
            {
                "_id": 0,
                "toc": 1,
                "domain": 1,
                "duration_days": 1,
                "audience_level": 1,
                "mode": 1,
                "trainer_name": 1,
                "training_dates": 1,
                "timing": 1,
            },
        )
        if not doc:
            raise HTTPException(404, f"TOC not found: {payload.toc_id}")
        toc = _with_toc_metadata(doc["toc"], doc)

    title = toc.get("title", "Training Programme")
    html = build_toc_html(toc)

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{DOC_SVC}/api/v1/documents/pdf/html-to-pdf",
                params={"filename": f"{title}.pdf"},
                content=html,
                headers={"Content-Type": "text/html"},
                timeout=60,
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
            {
                "_id": 0,
                "toc": 1,
                "trainer_email": 1,
                "trainer_name": 1,
                "toc_id": 1,
                "domain": 1,
                "duration_days": 1,
                "audience_level": 1,
                "mode": 1,
                "training_dates": 1,
                "timing": 1,
            },
        )
        if not doc:
            raise HTTPException(404, f"TOC not found: {payload.toc_id}")
        toc = _with_toc_metadata(doc["toc"], doc)
        payload.toc_id = doc.get("toc_id")
        to_email = to_email or doc.get("trainer_email") or ""
        trainer_name = trainer_name or doc.get("trainer_name") or "Trainer"
    if trainer_name and trainer_name != "Trainer":
        toc = _with_toc_metadata(toc, {"trainer_name": trainer_name})

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
            html = build_toc_html(toc)
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(
                    f"{DOC_SVC}/api/v1/documents/pdf/html-to-pdf",
                    params={"filename": f"{title}.pdf"},
                    content=html,
                    headers={"Content-Type": "text/html"},
                    timeout=60,
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
