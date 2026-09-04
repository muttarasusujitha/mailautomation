"""Training Table of Contents (TOC) generation endpoint."""
import json
import logging
import re
import uuid
from datetime import datetime
from math import ceil
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, root_validator

from shared.database.service import get_db
from app.config import get_settings
from app.toc_generation_agent import (
    _enrich_programme_pack,
    generate_combined_toc_from_datasets,
    generate_toc_from_dataset,
    validate_toc,
)

router = APIRouter()
logger = logging.getLogger(__name__)


class TechnologyAllocation(BaseModel):
    technology: str
    days: int


class TocRequest(BaseModel):
    domain: Optional[str] = None
    technology: Optional[str] = None
    duration_days: float = 5.0
    level: str = "intermediate"
    mode: str = "Online"
    notes: Optional[str] = ""
    requirement_id: Optional[str] = None
    trainer_id: Optional[str] = None
    trainer_name: Optional[str] = None
    trainer_email: Optional[str] = None
    audience_level: Optional[str] = None
    training_dates: Optional[str] = None
    timing: Optional[str] = None
    hours_per_day: Optional[float] = None
    participant_count: Optional[int] = None
    cloud_provider: Optional[str] = None
    cloud_region: Optional[str] = None
    lab_type: Optional[str] = None
    # AI is the standard ToC path.  The deterministic dataset generator is
    # retained only as a safe fallback when an AI response cannot be used.
    generation_mode: Optional[str] = "ai"
    toc_type: Optional[str] = "standard"
    custom_topics: Optional[str] = ""
    client_notes: Optional[str] = ""
    toc_id: Optional[str] = None
    technology_allocations: List[TechnologyAllocation] = []

    @root_validator(skip_on_failure=True)
    def require_domain_or_technology(cls, values):
        domain = values.get("domain") or values.get("technology")
        if not domain:
            raise ValueError("domain or technology is required")
        values["domain"] = domain
        return values

    @root_validator(skip_on_failure=True)
    def validate_duration_days(cls, values):
        duration_days = values.get("duration_days")
        if duration_days is None or duration_days <= 0:
            raise ValueError("duration_days must be a positive number")
        return values

    @root_validator(skip_on_failure=True)
    def validate_technology_allocations(cls, values):
        allocations = values.get("technology_allocations") or []
        if allocations and sum(item.days for item in allocations) != int(values.get("duration_days") or 0):
            raise ValueError("technology_allocations days must equal duration_days")
        return values


_SCOPE_TECHNOLOGY_RULES = (
    ("DevOps", (r"\bdevops\b",)),
    ("AWS", (r"\baws\b", r"\bamazon web services\b")),
    ("Azure", (r"\bazure\b",)),
    ("Kubernetes", (r"\bkubernetes\b", r"\bk8s\b")),
    ("Python", (r"\bpython\b",)),
    ("Agentic AI", (r"\bagentic\s*ai\b", r"\bai agents?\b", r"\blangchain\b", r"\blanggraph\b")),
)
_COMBINED_SCOPE_WEIGHTS = {
    "DevOps": 7,
    "AWS": 3,
    "Azure": 3,
    "Kubernetes": 3,
    "Python": 2,
    "Agentic AI": 2,
}
_GENERIC_LAB_TEXT = {
    "guided hands-on exercise",
    "guided hands-on exercise and evidence review",
    "guided lab",
    "practical exercise",
}


def _scope_text(payload: TocRequest) -> str:
    return " ".join(str(value or "").strip() for value in (
        payload.domain, payload.custom_topics, payload.client_notes, payload.notes,
    ) if str(value or "").strip())


def _toc_knowledge_key(value: str) -> str:
    return "_".join(part for part in re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).split("_") if part)


def _knowledge_domain(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a persisted toc_knowledge document into the generator contract."""
    nested = doc.get("toc") if isinstance(doc.get("toc"), dict) else {}
    domain = {**nested, **{key: value for key, value in doc.items() if key not in {"toc", "_id"}}}
    domain["name"] = doc.get("name") or doc.get("domain") or nested.get("name") or nested.get("domain")
    domain["domain"] = domain["name"]
    if not domain.get("level_map"):
        domain["level_map"] = nested.get("level_map") or {}
    return domain


async def _load_toc_knowledge(db: AsyncIOMotorDatabase, technology: str) -> Optional[Dict[str, Any]]:
    """Load active manual/template knowledge by canonical name, key, or alias."""
    name = str(technology or "").strip()
    if not name:
        return None
    key = _toc_knowledge_key(name)
    exact = f"^{re.escape(name)}$"
    doc = await db["toc_knowledge"].find_one({
        "active": {"$ne": False},
        "$or": [
            {"key": key},
            {"name": {"$regex": exact, "$options": "i"}},
            {"domain": {"$regex": exact, "$options": "i"}},
            {"aliases": {"$regex": exact, "$options": "i"}},
        ],
    }, {"_id": 0})
    return _knowledge_domain(doc) if doc else None


async def _load_toc_knowledge_overrides(
    db: AsyncIOMotorDatabase, allocations: List[Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    overrides: Dict[str, Dict[str, Any]] = {}
    for allocation in allocations:
        technology = str(allocation.get("technology") or "").strip()
        knowledge = await _load_toc_knowledge(db, technology)
        if knowledge:
            overrides[technology.lower()] = knowledge
    return overrides


def _detected_scope_technologies(payload: TocRequest) -> List[str]:
    """Extract named technologies from the requirement, not just its short title."""
    if payload.technology_allocations:
        return [item.technology.strip() for item in payload.technology_allocations if item.technology.strip()]
    scope = _scope_text(payload).lower()
    detected = []
    for technology, patterns in _SCOPE_TECHNOLOGY_RULES:
        if any(re.search(pattern, scope, flags=re.IGNORECASE) for pattern in patterns):
            detected.append(technology)
    return detected


def _inferred_technology_allocations(payload: TocRequest) -> List[dict]:
    """Create a transparent day split only for an explicit multi-tech scope.

    For the standard 20-day DevOps + AWS + Azure + Kubernetes + Python +
    Agentic AI programme, this produces 7 + 3 + 3 + 3 + 2 + 2 days.
    Explicit client allocations always take precedence.
    """
    if payload.technology_allocations:
        return [item.dict() for item in payload.technology_allocations]
    technologies = _detected_scope_technologies(payload)
    total_days = int(payload.duration_days or 0)
    if len(technologies) < 2 or total_days < len(technologies):
        return []
    weights = [_COMBINED_SCOPE_WEIGHTS.get(technology, 1) for technology in technologies]
    weight_total = sum(weights) or len(technologies)
    raw = [total_days * weight / weight_total for weight in weights]
    allocated = [max(1, int(value)) for value in raw]

    # Largest-remainder allocation keeps the exact requested duration.
    while sum(allocated) < total_days:
        index = max(range(len(technologies)), key=lambda item: (raw[item] - int(raw[item]), weights[item], -item))
        allocated[index] += 1
        raw[index] = int(raw[index])
    while sum(allocated) > total_days:
        index = max((item for item in range(len(technologies)) if allocated[item] > 1), key=lambda item: (allocated[item], weights[item]))
        allocated[index] -= 1
    return [
        {"technology": technology, "days": days}
        for technology, days in zip(technologies, allocated)
    ]


def _ai_level_contract(level: str) -> str:
    normalized = str(level or "intermediate").strip().lower()
    if normalized in {"basic", "beginner", "foundation", "foundational"}:
        return (
            "BEGINNER: assume no prior product experience. Establish terminology and prerequisites, then use guided "
            "configuration and small labs. Avoid production-scale architecture until the final integrated exercise."
        )
    if normalized in {"advanced", "advance", "expert"}:
        return (
            "ADVANCED CUMULATIVE PATH: include a concise but meaningful foundation, then intermediate implementation, "
            "then advanced architecture trade-offs, scale, security, performance, failure diagnosis, governance, optimization, "
            "and production-grade scenario labs. Never produce an advanced-only fragment without its prerequisite roadmap."
        )
    return (
        "INTERMEDIATE CUMULATIVE PATH: include the essential basic foundation and then progress into implementation, "
        "integration, automation, troubleshooting, security, and realistic project labs. Do not omit prerequisites."
    )


def _ai_toc_passes_level_gate(toc: dict, level: str) -> bool:
    normalized = str(level or "intermediate").strip().lower()
    if normalized in {"basic", "beginner", "foundation", "foundational"}:
        return True
    introductory = ("basic", "fundamental", "foundation", "orientation", "introduction", "getting started")
    rows = [
        " ".join([str(day.get("focus_area") or ""), str(day.get("title") or "")]).lower()
        for day in toc.get("days") or []
    ]
    intro_count = sum(any(marker in row for marker in introductory) for row in rows)
    # Cumulative paths intentionally include foundations. Reject only curricula
    # dominated by introductions with no room for the requested higher depth.
    maximum_introductory = max(2, len(rows) // 3)
    return intro_count <= maximum_introductory


def _required_technologies(payload: TocRequest) -> List[str]:
    detected = _detected_scope_technologies(payload)
    if detected:
        return detected
    domain = str(payload.domain or "").strip()
    parts = re.split(r"\s*(?:\+|,|&|\band\b)\s*", domain, flags=re.IGNORECASE)
    return [part for part in parts if part] or ([domain] if domain else [])


def _ai_toc_passes_requirement_gate(toc: dict, payload: TocRequest, expected_days: int) -> bool:
    days = toc.get("days") or []
    if len(days) != expected_days:
        return False
    searchable = json.dumps(toc, ensure_ascii=False).lower()
    if any(technology.lower() not in searchable for technology in _required_technologies(payload)):
        return False
    for day in days:
        lab = str(day.get("lab") or day.get("lab_task") or "").strip()
        if len(lab) < 16 or lab.lower() in _GENERIC_LAB_TEXT:
            return False
        title = str(day.get("focus_area") or day.get("title") or "").lower()
        if any(marker in title for marker in ("capstone", "project", "end-to-end")):
            minimum = 4
        elif any(marker in title for marker in ("architecture", "integration", "deployment", "security", "troubleshooting", "advanced")):
            minimum = 6
        elif any(marker in title for marker in ("basic", "fundamental", "foundation", "introduction", "orientation", "setup", "syntax", "variable", "overview")):
            minimum = 10
        else:
            minimum = 8
        if len(day.get("subtopics") or []) < minimum:
            return False
    focus_areas = [str(day.get("focus_area") or "").strip().lower() for day in days]
    return len(focus_areas) == len(set(focus_areas))


def _ai_curriculum_rules() -> str:
    return (
        " REQUIREMENT PRIORITY: (1) explicit client topics, (2) explicit technologies, (3) duration and schedule, "
        "(4) audience/experience level, (5) delivery mode and practical requirements, (6) industry-standard supporting "
        "topics. Lower-priority supporting content must never override explicit client topics or technologies. Cover every "
        "requested technology with meaningful depth and do not add unrelated technology. Use exactly the requested number "
        "of training days. Distribute topics realistically; do not compress an entire technology into one day merely to "
        "claim coverage. Avoid repeated modules. Prioritize industry-relevant content when time is limited. Use a corporate, "
        "practice-oriented progression appropriate to the requested level: prerequisites/fundamentals when needed, then core "
        "concepts, configuration, integration, automation, security, monitoring, troubleshooting, advanced practice, and a "
        "project where supported by the scope and duration. Every lab must directly exercise that day's theory. For cloud "
        "courses, use services from only the requested provider(s). For DevOps, sequence applicable scope through Linux/Git, "
        "CI/CD, containers, Kubernetes, cloud, IaC, monitoring, and security. For Kubernetes, sequence applicable scope through "
        "architecture, objects, workloads, services, configuration, storage, networking, security, scaling, monitoring, and "
        "troubleshooting. Use professional module names suitable for corporate practitioners, not an academic syllabus. Do "
        "not invent participant count, trainer, commercial, location, dates, access, or other client facts. Missing facts must "
        "remain unspecified. Before returning, verify exact day count, coverage of every requested technology/topic, logical "
        "ordering, unique modules, scope relevance, and realistic labs. Training dates, weekdays, and Sunday exclusions are "
        "calculated deterministically by the application; never invent or modify them. Use adaptive topic detail: provide "
        "about 10 concise subtopics for small/foundational concepts, about 8 for normal modules, and 4-6 substantial "
        "subtopics for large architecture, integration, troubleshooting, deployment, security, or project modules. Never "
        "split a large concept into artificial filler merely to reach a count. A foundational Python day "
        "should explicitly cover applicable items "
        "such as syntax, comments/docstrings, variables, naming rules, data types, operators, input/output, indentation, "
        "type conversion, and simple debugging. Do not use repeated filler to reach the count."
    )


async def _generate_ai_toc(payload: TocRequest) -> Optional[dict]:
    """Create a validated ToC from the dedicated AI ToC contract.

    This is deliberately content-only: dates, workbooks, lab pricing and
    workflow decisions remain deterministic system responsibilities.
    """
    settings = get_settings()
    api_key = str(getattr(settings, "OPENAI_API_KEY", "") or "").strip()
    if not api_key:
        return None
    days = max(1, min(int(payload.duration_days), 100))
    allocations = _inferred_technology_allocations(payload)
    if allocations:
        backbone = generate_combined_toc_from_datasets(
            allocations, payload.level, payload.mode,
            payload.notes or "", payload.audience_level or "", payload.training_dates or "",
        )
    else:
        backbone = generate_toc_from_dataset(
            payload.domain, days, payload.level, payload.mode, payload.notes or "",
            audience_level=payload.audience_level or "", training_dates=payload.training_dates or "",
        )
    ordered_backbone = [day.get("focus_area") for day in backbone.get("days") or []]
    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "overview": {"type": "string"},
            "days": {
                "type": "array",
                "minItems": days,
                "maxItems": days,
                "items": {
                    "type": "object",
                    "properties": {
                        "day": {"type": "integer"},
                        "title": {"type": "string"},
                        "focus_area": {"type": "string"},
                        "subtopics": {"type": "array", "items": {"type": "string"}},
                        "tools": {"type": "array", "items": {"type": "string"}},
                        "lab": {"type": "string"},
                        "learning_objectives": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["day", "title", "focus_area", "subtopics", "tools", "lab", "learning_objectives"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["title", "overview", "days"],
        "additionalProperties": False,
    }
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key)
        response = await client.responses.create(
            model=str(getattr(settings, "OPENAI_MODEL", "gpt-5.5") or "gpt-5.5"),
            reasoning={"effort": "low"},
            text={"format": {"type": "json_schema", "name": "ai_toc_template", "strict": True, "schema": schema}, "verbosity": "low"},
            instructions=(
                "Create a professional corporate-training Table of Contents using exactly the supplied requirement scope. "
                "The output will be inserted into the approved green eight-column Excel template: Day Number, Training "
                "Date, Weekday, Timing, Main Topic, Subtopics, Hands-on / Lab Activity, and Learning Outcomes. Produce "
                "one complete row of content for each training day: focus_area maps to Main Topic, subtopics maps to "
                "Subtopics, lab maps to Hands-on / Lab Activity, and learning_objectives maps to Learning Outcomes. "
                "Use exactly the requested number of days. Every day must have a main topic, practical subtopics, named "
                "tools/services, a realistic hands-on exercise, and measurable learning outcomes. Order content from "
                "foundations through implementation, automation, monitoring/security, and an end-to-end deployment where "
                "the supplied technology scope supports it. Cover every technology explicitly requested by the client; do "
                "not substitute a generic curriculum or omit requested technologies. Dates, weekday, daily hours, and "
                "participant count are applied by the workbook renderer from the supplied requirement details. Do not invent "
                "client facts, certifications, pricing, dates, or product access. Return only JSON matching the schema."
                f" Level contract: {_ai_level_contract(payload.level)} The ordered curriculum backbone supplied in the "
                "input is mandatory: preserve its prerequisite sequence and technical depth. Expand it into specific "
                "subtopics, labs, and measurable outcomes; do not replace it with a generic syllabus."
                f"{_ai_curriculum_rules()}"
            ),
            input=json.dumps({
                "technology": " + ".join(_required_technologies(payload)),
                "technology_allocations": allocations,
                "duration_days": days,
                "level": payload.level,
                "mode": payload.mode,
                "audience_level": payload.audience_level or "",
                "client_topics": payload.custom_topics or "",
                "client_notes": payload.client_notes or payload.notes or "",
                "training_dates": payload.training_dates or "",
                "timing": payload.timing or "",
                "hours_per_day": payload.hours_per_day or "",
                "participant_count": payload.participant_count or "",
                "ordered_curriculum_backbone": ordered_backbone,
            }, ensure_ascii=False),
            max_output_tokens=6000,
        )
        toc = json.loads(response.output_text)
        for item in toc.get("days") or []:
            subtopics = [str(value).strip() for value in item.get("subtopics") or [] if str(value).strip()]
            item["morning_session"] = {"time": "", "title": "Concepts", "topics": subtopics[:max(1, len(subtopics) // 2)]}
            item["afternoon_session"] = {"time": "", "title": "Hands-on", "topics": subtopics[max(1, len(subtopics) // 2):] or [item.get("lab") or "Guided lab"]}
        toc = validate_toc(toc, days)
        if not _ai_toc_passes_level_gate(toc, payload.level) or not _ai_toc_passes_requirement_gate(toc, payload, days):
            logger.warning("AI ToC rejected because it violated level, duration, technology coverage, or uniqueness rules")
            return None
        # The AI contract must not invent dates, but the application owns the
        # supplied schedule. Apply the same weekday-aware date enrichment used
        # by the manual/dataset path after the AI content passes validation.
        toc = _enrich_programme_pack(toc, payload.audience_level or "", payload.training_dates or "")
        return toc
    except Exception:
        logger.exception("AI ToC generation failed; falling back to approved template generator")
        return None


@router.post("/generate")
async def generate_toc(payload: TocRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """
    Generate a structured TOC for a training programme.
    Uses the richer TOC generator with curriculum dataset support.
    """
    requested_mode = (payload.generation_mode or "ai").lower()
    used_generation_mode = "template"
    toc = await _generate_ai_toc(payload) if requested_mode == "ai" else None
    if toc:
        used_generation_mode = "ai"
    try:
        if toc is None:
            # Approved deterministic Template mode, and safe fallback when
            # an AI key is not configured or the AI response is invalid.
            allocations = _inferred_technology_allocations(payload)
            use_manual_knowledge = requested_mode != "ai"
            if allocations:
                knowledge_overrides = (
                    await _load_toc_knowledge_overrides(db, allocations)
                    if use_manual_knowledge else {}
                )
                toc = generate_combined_toc_from_datasets(
                    allocations, payload.level, payload.mode,
                    payload.notes or "", payload.audience_level or "", payload.training_dates or "",
                    domain_overrides=knowledge_overrides,
                )
                if knowledge_overrides:
                    used_generation_mode = "template_knowledge"
            else:
                knowledge = await _load_toc_knowledge(db, payload.domain) if use_manual_knowledge else None
                toc = generate_toc_from_dataset(
                    domain_name=payload.domain, duration_days=int(payload.duration_days), level=payload.level,
                    mode=payload.mode, notes=payload.notes or "", audience_level=payload.audience_level or "",
                    training_dates=payload.training_dates or "",
                    domain_override=knowledge,
                )
                if knowledge:
                    used_generation_mode = "template_knowledge"
            toc = validate_toc(toc, int(payload.duration_days))
    except Exception:
        # Fallback to minimal if generator fails
        toc = _minimal_toc(payload.domain, payload.duration_days)

    toc.update({
        "domain": payload.domain,
        "duration_days": int(payload.duration_days),
        "level": payload.level,
        "mode": payload.mode,
        "generation_mode": used_generation_mode,
        "requested_generation_mode": requested_mode,
        "technology_allocations": _inferred_technology_allocations(payload),
    })
    if payload.training_dates:
        toc["training_dates"] = payload.training_dates
    if payload.timing:
        toc["timing"] = payload.timing
    if payload.trainer_name:
        toc["trainer_name"] = payload.trainer_name
    _attach_ai_generation_templates(toc, payload)

    toc_id = payload.toc_id or f"TOC-{uuid.uuid4().hex[:10].upper()}"

    await db.toc_generations.insert_one({
        "toc_id": toc_id,
        "requirement_id": payload.requirement_id,
        "trainer_id": payload.trainer_id,
        "trainer_name": payload.trainer_name,
        "trainer_email": payload.trainer_email,
        "domain": payload.domain,
        "duration_days": payload.duration_days,
        "audience_level": payload.audience_level,
        "training_dates": payload.training_dates,
        "timing": payload.timing,
        "generation_mode": toc.get("generation_mode"),
        "toc_type": payload.toc_type,
        "custom_topics": payload.custom_topics,
        "client_notes": payload.client_notes,
        "technology_allocations": toc.get("technology_allocations") or [],
        "toc": toc,
        "created_at": datetime.utcnow(),
    })

    return {"success": True, "toc_id": toc_id, "toc_data": toc}


def _as_text_list(value) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value:
        return [str(value).strip()]
    return []


def _day_subtopics(day: dict) -> List[str]:
    values = _as_text_list(day.get("subtopics"))
    for session_key in ("morning_session", "afternoon_session"):
        for item in (day.get(session_key) or {}).get("topics") or []:
            text = item.get("topic") if isinstance(item, dict) else item
            if text and str(text).strip() not in values:
                values.append(str(text).strip())
    return values


def _resource_type(text: str) -> str:
    value = str(text or "").lower()
    if any(term in value for term in ("eks", "aks", "gke", "kubernetes", "cluster")):
        return "Kubernetes / container lab"
    if any(term in value for term in ("ec2", "azure vm", "virtual machine", "linux", "jenkins", "docker")):
        return "Cloud compute / VM"
    if any(term in value for term in ("rds", "database", "sql", "postgres", "mysql")):
        return "Managed database / database lab"
    if any(term in value for term in ("s3", "blob", "storage")):
        return "Cloud storage"
    return "Software / tool lab"


def _attach_ai_generation_templates(toc: dict, payload: TocRequest) -> None:
    """Attach compact internal AI contracts used by both output generators.

    These are not client-facing workbook templates. They make the generated
    day-wise ToC the sole structured source for the ToC and lab-cost outputs.
    """
    default_timing = payload.timing or toc.get("timing") or "To be confirmed"
    hours = float(payload.hours_per_day or 0) or 0
    schedule_rows = []
    lab_rows = []
    for index, day in enumerate(toc.get("days") or [], 1):
        subtopics = _day_subtopics(day)
        tools = _as_text_list(day.get("tools"))
        practical = str(day.get("lab") or day.get("lab_task") or "Guided hands-on exercise").strip()
        outcome = "; ".join(_as_text_list(day.get("learning_objectives"))[:2]) or f"Apply {day.get('focus_area') or toc.get('domain')} in a guided lab."
        schedule_rows.append({
            "sr_no": day.get("day") or index,
            "date": day.get("date") or "To be confirmed",
            "day": f"Day {day.get('day') or index}",
            "timings": default_timing,
            "hours": hours or "To be confirmed",
            "main_topic": day.get("category") or day.get("focus_area") or day.get("title") or "Training",
            "subtopics": subtopics,
            "practical_hands_on": practical,
            "daily_outcome": outcome,
            "day_summary": "",  # deliberately trainer-owned
        })
        requirements = list(dict.fromkeys([*tools, practical]))
        for item in requirements:
            lab_rows.append({
                "day": f"Day {day.get('day') or index}",
                "main_topic": day.get("category") or day.get("focus_area") or "Training",
                "practical_hands_on": practical,
                "tool_or_service": item,
                "resource_type": _resource_type(item),
                "configuration": "To be sized from participant count and hands-on scope",
                "quantity": payload.participant_count or "To be confirmed",
                "usage_hours": hours or "To be confirmed",
                "pricing_source": "Configured provider rate card; replace with approved live pricing when available",
                "assumptions_notes": "Generated from the same AI ToC day row; verify provider region and paid licences.",
            })
    toc["ai_toc_template"] = {
        "template_name": "daily_training_schedule_v1",
        "internal_only": True,
        "fields": ["Sr No", "Date", "Day", "Timings", "Hours", "Main Topic", "Subtopics", "Practical / Hands-on", "Daily Outcome", "Day Summary"],
        "trainer_owned_fields": ["Day Summary"],
        "sunday_excluded": True,
        "rows": schedule_rows,
    }
    toc["ai_lab_cost_template"] = {
        "template_name": "lab_cost_input_v1",
        "internal_only": True,
        "inputs": {
            "technology": toc.get("domain"), "participants": payload.participant_count or "To be confirmed",
            "cloud_provider": payload.cloud_provider or "To be confirmed", "cloud_region": payload.cloud_region or "To be confirmed",
            "lab_type": payload.lab_type or "To be confirmed", "hours_per_day": hours or "To be confirmed",
        },
        "rows": lab_rows,
    }


def _minimal_toc(domain: str, days: float) -> dict:
    rounded_days = max(1, ceil(days))
    return {
        "title": f"{domain} Training",
        "subtitle": f"{rounded_days}-Day Programme",
        "domain": domain,
        "duration_days": rounded_days,
        "overview": f"A {days}-day {domain} training programme.",
        "days": [
            {
                "day": i + 1,
                "title": f"Day {i + 1}: {domain} Module {i + 1}",
                "focus_area": f"{domain} concepts and labs",
                "tools": domain,
                "morning_session": {"time": "9:00 AM - 1:00 PM", "title": "Concepts", "topics": []},
                "afternoon_session": {"time": "1:00 PM - 5:00 PM", "title": "Hands-on", "topics": []},
                "learning_objectives": [f"Understand {domain} Day {i + 1} topics"],
                "jira_practice": ["Update sprint board"],
            }
            for i in range(rounded_days)
        ],
        "tools_software": [domain],
        "certification_roadmap": [f"{domain} certification roadmap"],
    }


@router.get("/knowledge-base")
async def list_knowledge_base(db: AsyncIOMotorDatabase = Depends(get_db)):
    """List available TOC knowledge-base entries."""
    cursor = db.toc_knowledge.find({}, {"_id": 0, "domain": 1, "created_at": 1}).sort("domain", 1)
    items = [d async for d in cursor]
    return {"domains": items, "count": len(items)}
