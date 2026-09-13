"""TOC extended routes — knowledge base CRUD, PDF generation, email, auto-generate."""
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
import base64
from fastapi import APIRouter, Body, Depends, HTTPException, Response
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.config import get_settings
from shared.database.service import get_db
from shared.lab_cost_inputs import validate_lab_cost_inputs
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


class LabCostRequest(BaseModel):
    lab_generation_mode: Optional[str] = None
    lab_day_mapping: Optional[List[Dict[str, Any]]] = None
    toc: Optional[Dict[str, Any]] = None
    toc_id: Optional[str] = None
    cloud_provider: Optional[str] = None
    cloud_region: Optional[str] = None
    hours_per_day: Optional[float] = None
    participant_count: Optional[int] = None
    fx_rate: Optional[float] = None
    contingency_percent: float = 10
    tax_percent: float = 0
    lab_package: str = "standard"
    lab_support_per_participant: Optional[float] = None
    quote_validity_days: int = 7
    include_internal_pricing: bool = False
    clahan_margin_percent: float = 0
    storage_gb: float = 10
    disk_gb_per_node: float = 20
    egress_gb: float = 1
    build_minutes: float = 60
    monitoring_gb: float = 1
    k8s_worker_nodes: int = 1
    rate_card_overrides: Optional[Dict[str, Dict[str, Any]]] = None
    vm_profile_rates: Optional[Dict[str, float]] = None
    vm_profile_sources: Optional[Dict[str, str]] = None
    rate_snapshot_source: Optional[str] = None
    rate_checked_at: Optional[str] = None
    price_change_review_threshold_percent: float = 5
    pricing_selections: Optional[Dict[str, Dict[str, Any]]] = None
    ai_usage: Optional[Dict[str, Any]] = None


class AIPricingEvidenceRequest(BaseModel):
    provider: str
    model: str
    input_per_million: float = 0
    output_per_million: float = 0
    gpu_per_hour: float = 0
    source_url: str
    title: str = "Approved pricing evidence"
    excerpt: str = ""
    effective_date: str = ""
    approved: bool = True


@router.put('/ai-pricing/evidence')
async def save_ai_pricing_evidence(payload: AIPricingEvidenceRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Save an approved pricing document chunk for deterministic manual RAG."""
    from shared.ai_pricing import _number
    if not payload.source_url.startswith(('https://', 'http://')):
        raise HTTPException(422, 'source_url must be an http(s) URL')
    row = payload.model_dump()
    for key in ('input_per_million', 'output_per_million', 'gpu_per_hour'):
        _number(row[key], key)
    row.update(provider=row['provider'].strip().lower(), model=row['model'].strip(),
               updated_at=datetime.now(timezone.utc), approved=bool(row['approved']))
    await db['ai_pricing_evidence'].update_one(
        {'provider': row['provider'], 'model': row['model'], 'source_url': row['source_url']},
        {'$set': row}, upsert=True)
    return {'status': 'saved', 'source': 'manual_rag_approved', 'provider': row['provider'], 'model': row['model']}


class LabPricingCatalogRequest(BaseModel):
    cloud_provider: str
    cloud_region: str
    selections: Dict[str, Dict[str, Any]]


def _pricing_catalog_key(provider: str, region: str) -> tuple[str, str]:
    checked = validate_lab_cost_inputs({
        "cloud_provider": provider,
        "cloud_region": region,
        "hours_per_day": 1,
        "participant_count": 1,
        "fx_rate": 1,
    })
    return checked["cloud_provider"], checked["cloud_region"]


def _lab_cost_delivery_summary(requirement: Dict[str, Any], log: Dict[str, Any], workbook: Dict[str, Any]) -> Dict[str, Any]:
    """Public, client-facing audit record for one delivered lab-cost workbook.

    Commercial margin and trainer/client percentage logic deliberately do not
    appear here.  Lab cost is a separate operational estimate.
    """
    return {
        "email_id": log.get("email_id"),
        "requirement_id": requirement.get("requirement_id") or log.get("requirement_id"),
        "client_name": requirement.get("client_name") or requirement.get("client_company") or log.get("recipient") or "Client",
        "client_email": requirement.get("client_email") or log.get("recipient") or log.get("to_email") or "",
        "technology": requirement.get("technology_needed") or requirement.get("domain") or requirement.get("title") or "Training",
        "duration_days": requirement.get("duration_days") or requirement.get("duration") or "",
        "training_dates": requirement.get("training_dates") or requirement.get("preferred_dates") or "",
        "sent_at": log.get("sent_at") or log.get("created_at"),
        "mail_type": log.get("mail_type"),
        "subject": log.get("subject") or "Lab Cost Estimate",
        "workbook_filename": workbook.get("filename") or "Lab Cost Estimate.xlsx",
        "has_download": bool(workbook.get("content_base64") or workbook.get("_available")),
        "summary": {
            "scope": "TOC-based lab infrastructure estimate",
            "cost_status": "Included in the attached workbook",
            "note": "Lab cost is separate from trainer commercial, client commercial, margin, and percentage calculations.",
        },
    }


@router.get("/lab-cost/client-deliveries")
async def list_client_lab_cost_deliveries(db: AsyncIOMotorDatabase = Depends(get_db)):
    """List the exact lab-cost workbooks successfully sent to clients."""
    query = {
        "direction": "outbound",
        "status": "sent",
        "mail_type": {"$in": ["client_slots", "client_lab_cost_revised"]},
        "lab_cost_workbooks.0": {"$exists": True},
    }
    logs = [doc async for doc in db["email_logs"].find(query, {"_id": 0, "lab_cost_workbooks.content_base64": 0}).sort("sent_at", -1).limit(200)]
    requirement_ids = list({str(doc.get("requirement_id") or "") for doc in logs if doc.get("requirement_id")})
    requirements = [doc async for doc in db["requirements"].find({"requirement_id": {"$in": requirement_ids}}, {"_id": 0})]
    by_id = {str(item.get("requirement_id")): item for item in requirements}
    items = []
    for log in logs:
        requirement = by_id.get(str(log.get("requirement_id"))) or {"requirement_id": log.get("requirement_id")}
        for workbook in log.get("lab_cost_workbooks") or []:
            display_workbook = {**workbook, "_available": True}
            items.append(_lab_cost_delivery_summary(requirement, log, display_workbook))
    return {"items": items, "total": len(items)}


@router.get("/lab-cost/pricing-catalog/{cloud_provider}/{cloud_region}")
async def get_lab_pricing_catalog(
    cloud_provider: str,
    cloud_region: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Return resource selectors; live prices are fetched only when quoting."""
    try:
        provider, region = _pricing_catalog_key(cloud_provider, cloud_region)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    catalog = await db["lab_pricing_catalogs"].find_one(
        {"provider": provider, "region": region}, {"_id": 0}
    )
    if not catalog:
        raise HTTPException(404, "No live-pricing catalog configured for this provider and region")
    return catalog


@router.put("/lab-cost/pricing-catalog")
async def save_lab_pricing_catalog(
    payload: LabPricingCatalogRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Verify every selector against current public pricing before saving it."""
    try:
        provider, region = _pricing_catalog_key(payload.cloud_provider, payload.cloud_region)
        from shared.live_lab_pricing import refresh_rates
        from starlette.concurrency import run_in_threadpool
        snapshot = await run_in_threadpool(refresh_rates, {
            "cloud_provider": provider,
            "cloud_region": region,
            "hours_per_day": 1,
            "participant_count": 1,
            "fx_rate": 1,
            "quote_validity_days": 7,
            "pricing_selections": payload.selections,
        })
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        logger.exception("Lab pricing catalog validation failed")
        raise HTTPException(503, "Provider prices could not verify this catalog") from exc
    now = datetime.now(timezone.utc)
    document = {
        "provider": provider,
        "region": region,
        "selections": payload.selections,
        "validated_at": now,
        "validation_snapshot": {
            name: {key: row[key] for key in ("sku", "dimension", "unit", "source", "effective_date")}
            for name, row in snapshot["rate_card_overrides"].items()
        },
        "updated_at": now,
    }
    await db["lab_pricing_catalogs"].update_one(
        {"provider": provider, "region": region}, {"$set": document}, upsert=True
    )
    return {
        "provider": provider,
        "region": region,
        "validated_at": now,
        "resources": document["validation_snapshot"],
    }


@router.get("/lab-cost/client-deliveries/{email_id}/download")
async def download_client_lab_cost_delivery(email_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Download the same lab-cost workbook that was attached to the sent mail."""
    log = await db["email_logs"].find_one(
        {"email_id": email_id, "direction": "outbound", "status": "sent"},
        {"_id": 0, "lab_cost_workbooks": 1},
    )
    workbook = next((item for item in (log or {}).get("lab_cost_workbooks") or [] if item.get("content_base64")), None)
    if not workbook:
        raise HTTPException(404, "The sent lab-cost workbook is not available for this delivery")
    try:
        content = base64.b64decode(workbook["content_base64"])
    except Exception as exc:
        raise HTTPException(500, "The saved lab-cost workbook is invalid") from exc
    filename = str(workbook.get("filename") or "Lab Cost Estimate.xlsx").replace('"', "")
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class AutoGenerateRequest(BaseModel):
    requirement_id: str
    domain: Optional[str] = ""
    # Omit the duration to inherit it from the requirement.  A default of
    # three silently overrode real requirement durations in auto-generation.
    duration_days: Optional[float] = None
    level: Optional[str] = None


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


def _safe_excel_filename(title: str) -> str:
    stem = "".join(ch if ch.isalnum() or ch in (" ", "-", "_") else "_" for ch in title).strip()
    stem = "_".join(stem.split())
    return f"{stem or 'training_toc'}.xlsx"


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
        <div class="company">Clahan Technologies</div>
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
    from shared.requirement_duration import training_duration
    duration_inputs = training_duration(req)
    duration = payload.duration_days if payload.duration_days is not None else duration_inputs.get("duration_days", 3.0)
    training_dates = (
        req.get("training_dates")
        or " to ".join(part for part in [req.get("timeline_start"), req.get("timeline_end")] if part)
        or req.get("preferred_dates")
        or ""
    )

    mode_setting = await db["automation_settings"].find_one({"key": "generation_mode"}, {"_id": 0}) or {}
    generation_mode = "ai" if str(mode_setting.get("value") or "").strip().lower() == "ai" else "template"

    # Delegate to existing /toc/generate using the pipeline-wide AI switch.
    from app.routes.toc import generate_toc, TocRequest
    toc_req = TocRequest(
        domain=domain,
        duration_days=duration,
        level=payload.level or req.get("level") or req.get("audience_level") or req.get("participant_level") or "intermediate",
        requirement_id=payload.requirement_id,
        mode=req.get("mode") or "Online",
        audience_level=req.get("audience_level") or req.get("participant_level") or "",
        training_dates=training_dates,
        timing=req.get("timing") or req.get("session_timing") or "",
        generation_mode=generation_mode,
        hours_per_day=duration_inputs.get("hours_per_day"),
        participant_count=int(req.get("participant_count") or req.get("participants") or 1),
        custom_topics="; ".join(str(item).strip() for value in (
            req.get("technology_needed"), req.get("domain"), req.get("skills"),
            req.get("required_skills"), req.get("requested_topics"), req.get("topics"), req.get("custom_topics"),
        ) if value for item in (value if isinstance(value, list) else [value]) if str(item).strip()),
        client_notes=str(req.get("client_notes") or req.get("notes") or req.get("description") or "").strip(),
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
    from shared.toc_quality import toc_delivery_error
    error = toc_delivery_error(toc)
    if error:
        raise HTTPException(422, error)
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


@router.post("/generate-lab-cost")
async def generate_toc_lab_cost(payload: LabCostRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Generate a formula-driven multi-cloud lab-cost workbook for a TOC."""
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

    try:
        validate_lab_cost_inputs(payload.model_dump())
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    provider = payload.cloud_provider.lower()
    if provider not in {"aws", "azure", "gcp"}:
        raise HTTPException(422, "cloud_provider must be aws, azure, or gcp")
    if payload.hours_per_day <= 0 or payload.participant_count <= 0 or payload.fx_rate <= 0:
        raise HTTPException(422, "hours_per_day, participant_count, and fx_rate must be positive")
    if min(payload.storage_gb, payload.egress_gb, payload.build_minutes, payload.monitoring_gb) < 0 or payload.k8s_worker_nodes < 0:
        raise HTTPException(422, "usage quantities cannot be negative")
    if not 0 <= payload.contingency_percent <= 100 or not 0 <= payload.tax_percent <= 100:
        raise HTTPException(422, "contingency_percent and tax_percent must be between 0 and 100")
    if not 0 <= payload.clahan_margin_percent <= 100:
        raise HTTPException(422, "clahan_margin_percent must be between 0 and 100")
    if (payload.lab_support_per_participant is not None and payload.lab_support_per_participant < 0) or payload.quote_validity_days < 1:
        raise HTTPException(422, "lab_support_per_participant must be non-negative and quote_validity_days must be positive")
    package = payload.lab_package.strip().lower()
    if package not in {"basic", "standard", "advanced"}:
        raise HTTPException(422, "lab_package must be basic, standard, or advanced")

    issued_at = datetime.now(timezone.utc)
    resource_mapping = payload.lab_day_mapping
    if payload.lab_generation_mode is None and toc.get("requested_generation_mode") == "ai":
        payload.lab_generation_mode = "ai"
    if payload.lab_generation_mode not in {None, "template"}:
        from shared.lab_planning import plan_resources
        try:
            if payload.lab_generation_mode == 'ai':
                from openai import AsyncOpenAI
                async with AsyncOpenAI(api_key=settings.OPENAI_API_KEY) as planner:
                    resource_mapping = await plan_resources(
                        'ai', toc, payload.model_dump(), planner, settings.OPENAI_MODEL)
            else:
                resource_mapping = await plan_resources(
                    payload.lab_generation_mode, toc, payload.model_dump())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(502, "AI lab planning failed. Retry or select Template mode explicitly.") from exc
    quote_id = f"LCQ-{uuid.uuid4().hex[:12].upper()}"
    checked_at = payload.rate_checked_at or issued_at.isoformat()
    valid_until = issued_at + timedelta(days=payload.quote_validity_days)
    has_live_vm_rates = bool(
        payload.vm_profile_rates
        and payload.vm_profile_sources
        and all(payload.vm_profile_rates.get(profile) is not None for profile in ("Light", "Heavy"))
        and all(payload.vm_profile_sources.get(profile) for profile in ("Light", "Heavy"))
    )
    pricing_status = "live_sku_rates_supplied" if has_live_vm_rates else "template_fallback_review_required"

    try:
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(
                f"{DOC_SVC}/api/v1/documents/excel/toc/lab-cost",
                json={
                    "toc": toc,
                    "assumptions": {
                        "cloud_provider": provider,
                        "cloud_region": payload.cloud_region,
                        "hours_per_day": payload.hours_per_day,
                        "participant_count": payload.participant_count,
                        "fx_rate": payload.fx_rate,
                        "contingency_percent": payload.contingency_percent,
                        "tax_percent": payload.tax_percent,
                        "lab_package": package,
                        "lab_support_per_participant": payload.lab_support_per_participant,
                        "quote_validity_days": payload.quote_validity_days,
                        "include_internal_pricing": payload.include_internal_pricing,
                        "clahan_margin_percent": payload.clahan_margin_percent,
                        "storage_gb": payload.storage_gb,
                        "disk_gb_per_node": payload.disk_gb_per_node,
                        "egress_gb": payload.egress_gb,
                        "build_minutes": payload.build_minutes,
                        "monitoring_gb": payload.monitoring_gb,
                        "k8s_worker_nodes": payload.k8s_worker_nodes,
                        "rate_card_overrides": payload.rate_card_overrides,
                        "vm_profile_rates": payload.vm_profile_rates,
                        "vm_profile_sources": payload.vm_profile_sources,
                        "rate_snapshot_id": quote_id,
                        "rate_snapshot_source": payload.rate_snapshot_source or "",
                        "rate_checked_at": checked_at,
                        "quote_valid_until": valid_until.isoformat(),
                        "price_change_review_threshold_percent": payload.price_change_review_threshold_percent,
                        "pricing_status": pricing_status,
                        "pricing_selections": payload.pricing_selections,
                        "ai_usage": payload.ai_usage,
                        "lab_generation_mode": payload.lab_generation_mode,
                        "lab_day_mapping": resource_mapping,
                    },
                },
            )
        if response.status_code >= 400:
            raise HTTPException(response.status_code, f"Document service error: {response.text[:1000]}")
        quote_id = response.headers['X-Lab-Cost-Quote-ID']
        valid_until = datetime.fromisoformat(response.headers['X-Lab-Cost-Quote-Valid-Until'])
        pricing_status = response.headers['X-Lab-Cost-Pricing-Status']
        domain = _slugify_domain(str(toc.get("domain") or toc.get("title") or "training"))
        filename = f"{domain}_{provider}_lab_cost.xlsx"
        await db["lab_cost_quotes"].insert_one({
            "quote_id": quote_id,
            "created_at": issued_at,
            "quote_valid_until": valid_until,
            "pricing_status": pricing_status,
            "submitted_rate_inputs_unverified": {
                "provider": provider,
                "region": payload.cloud_region,
                "source": payload.rate_snapshot_source or "",
                "checked_at": checked_at,
                "review_threshold_percent": payload.price_change_review_threshold_percent,
                "rate_card_overrides": payload.rate_card_overrides or {},
                "vm_profile_rates": payload.vm_profile_rates or {},
                "vm_profile_sources": payload.vm_profile_sources or {},
            },
                "scope": {
                "domain": toc.get("domain") or toc.get("title"),
                "duration_days": len(toc.get("days") or []),
                "participant_count": payload.participant_count,
                    "hours_per_day": payload.hours_per_day,
                    "ai_usage": payload.ai_usage or {},
            },
            "workbook_filename": filename,
        })
        return Response(
            content=response.content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "X-Lab-Cost-Quote-ID": quote_id,
                "X-Lab-Cost-Quote-Valid-Until": valid_until.isoformat(),
            },
        )
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
    if (toc.get("quality") or {}).get("status") in {"requires_regeneration", "requires_review"}:
        raise HTTPException(422, "TOC requires review before delivery; resolve its quality warnings first")
    body = payload.body or (
        f"Dear {trainer_name},\n\n"
        f"Please find attached the Table of Contents workbook for {title}.\n\n"
        "We look forward to your confirmation.\n\nRegards,\nClahan Technologies"
    )
    try:
        # Generate the client-facing three-sheet Excel TOC workbook for the email.
        attachment_payload = None
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(
                    f"{DOC_SVC}/api/v1/documents/excel/toc",
                    json={"toc": toc},
                    timeout=60,
                )
            if r.status_code == 200 and r.content:
                content_b64 = base64.b64encode(r.content).decode()
                attachment_payload = [{
                    "filename": _safe_excel_filename(title),
                    "content_base64": content_b64,
                    "subtype": "vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                }]
        except Exception:
            logger.exception("Failed to generate TOC Excel workbook for email attachment")

        if not attachment_payload:
            raise HTTPException(502, "TOC workbook generation failed; email was not sent")

        async with httpx.AsyncClient(timeout=30) as client:
            email_json = {
                "to": to_email,
                "subject": payload.subject or f"TOC - {title}",
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
