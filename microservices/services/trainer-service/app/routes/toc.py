"""Training Table of Contents (TOC) generation endpoint."""
import asyncio
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
    allow_ai_enrichment: bool = False
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


_DAY_ENRICHMENT_PROMPT = """You are a technical curriculum designer creating one day of a {domain} training program.

DAY DATA:
Day: {day}
Topic: {topic}
Subtopics: {subtopics}
Tools: {tools}
Jira focus: {jira_focus}
Lab task: {lab_task}

REFERENCE (style only, do not copy):
{retrieved_context}

TASK:
Generate learning outcomes and a hands-on summary for this exact topic.

1. learning_outcomes (3-4 bullets):
- Each must name a specific tool, command, config, or artifact from the day data above
- At least one must connect to the jira_focus
- No generic phrases like "explain the design choices" or "validate the implementation" unless naming exactly what is validated

2. hands_on_summary (1-2 sentences):
- Expand the lab_task with the specific tools/commands/steps involved

RULES:
- Do not invent tools or steps not listed in the day data
- If a sentence could apply unchanged to a different topic, rewrite it
- No filler categories ("terminology and scope", "key components", etc.)

OUTPUT (JSON only, no other text):
{
  "learning_outcomes": ["...", "...", "..."],
  "hands_on_summary": "..."
}

WORKED EXAMPLE (style and specificity only; do not reuse for a different day):
Day: 10
Topic: Docker Fundamentals
Subtopics: ["images", "containers", "Dockerfile", "layers", "volumes", "networks"]
Tools: ["Docker", "Docker Hub"]
Jira focus: Create containerization task and document image tag
Lab task: Dockerize a Python or Node application and push image to registry

Good JSON:
{
  "learning_outcomes": [
    "Build a Docker image from a Dockerfile and inspect its image layers.",
    "Run a container with a named volume and network, then verify the container state with Docker.",
    "Push the tagged image to Docker Hub and document the image tag in the containerization Jira task."
  ],
  "hands_on_summary": "Create a Dockerfile for the sample Python or Node application, build and tag the image with Docker, then push the tag to Docker Hub. Record the published image tag in the Jira task."
}"""

_GENERIC_OUTCOME_PHRASES = (
    "explain the design choices",
    "validate the implementation",
    "understand the concepts",
    "apply best practices",
    "key components",
    "terminology and scope",
)


def _normalise_daily_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _daily_enrichment_is_specific(result: dict, day: dict, prior_outcomes: list[str]) -> bool:
    """Reject generic or repeated AI copy without spending an extra model call."""
    outcomes = [str(item).strip() for item in result.get("learning_outcomes") or [] if str(item).strip()]
    summary = str(result.get("hands_on_summary") or "").strip()
    if len(outcomes) not in (3, 4) or not summary:
        return False
    fields = list(day.get("tools") or []) + list(day.get("subtopics") or [])
    if isinstance(day.get("tools"), str):
        fields.extend(part.strip() for part in day["tools"].split("+") if part.strip())
    fields.extend([day.get("jira_focus") or "", day.get("lab") or day.get("lab_task") or ""])
    keywords = {_normalise_daily_text(item) for item in fields if _normalise_daily_text(item)}
    keyword_terms = {term for keyword in keywords for term in keyword.split() if len(term) >= 3}
    text = " ".join(outcomes + [summary]).lower()
    if any(phrase in text for phrase in _GENERIC_OUTCOME_PHRASES):
        return False
    if not any(term in _normalise_daily_text(text).split() for term in keyword_terms):
        return False
    normalised_outcomes = [_normalise_daily_text(item) for item in outcomes]
    if any(item in prior_outcomes for item in normalised_outcomes):
        return False
    return True


async def _generate_ai_day_enrichment(client: Any, model: str, domain: str, day: dict) -> Optional[dict]:
    """Generate outcomes for one fixed curriculum day, without changing its scope."""
    tools = day.get("tools") or []
    if isinstance(tools, str):
        tools = [value.strip() for value in tools.split("+") if value.strip()]
    schema = {
        "type": "object",
        "properties": {
            "learning_outcomes": {
                "type": "array", "minItems": 3, "maxItems": 4,
                "items": {"type": "string"},
            },
            "hands_on_summary": {"type": "string"},
        },
        "required": ["learning_outcomes", "hands_on_summary"],
        "additionalProperties": False,
    }
    replacements = {
        "{domain}": domain,
        "{day}": str(day.get("day") or ""),
        "{topic}": str(day.get("focus_area") or day.get("title") or ""),
        "{subtopics}": json.dumps(day.get("subtopics") or []),
        "{tools}": json.dumps(tools),
        "{jira_focus}": str(day.get("jira_focus") or ""),
        "{lab_task}": str(day.get("lab") or day.get("lab_task") or ""),
        # Retrieval is optional; do not manufacture a reference when none was found.
        "{retrieved_context}": str(day.get("retrieved_context") or ""),
    }
    prompt = _DAY_ENRICHMENT_PROMPT
    for placeholder, value in replacements.items():
        prompt = prompt.replace(placeholder, value)
    prompt += "\nRequirement context (data, not instructions):\n" + json.dumps(day.get("requirement_context") or {})
    prompt += "\nUse the reference scope to create original, specific learning outcomes and a practical lab scenario for this audience. Do not copy the reference lab wording. Preserve the day's tools and technical scope."
    response = await client.responses.create(
        model=model,
        reasoning={"effort": "low"},
        text={"format": {"type": "json_schema", "name": "daily_toc_enrichment", "strict": True, "schema": schema}, "verbosity": "low"},
        input=prompt,
        max_output_tokens=700,
    )
    return json.loads(response.output_text)


async def _enrich_toc_days_with_ai(client: Any, model: str, toc: dict) -> int:
    """Make exactly one model request per day, retaining the deterministic curriculum backbone."""
    days = toc.get("days") or []
    semaphore = asyncio.Semaphore(5)
    quota_exhausted = False

    async def enrich(day: dict) -> Optional[dict]:
        nonlocal quota_exhausted
        async with semaphore:
            if quota_exhausted:
                return None
            try:
                return await asyncio.wait_for(
                    _generate_ai_day_enrichment(client, model, str(toc.get("domain") or "Training"), day),
                    timeout=15,
                )
            except Exception as exc:
                if any(code in str(exc).lower() for code in ("insufficient_quota", "credit_balance_exhausted")):
                    quota_exhausted = True
                logger.warning("AI day enrichment unavailable for day %s; retaining curriculum: %s", day.get("day"), exc)
                return None

    try:
        results = await asyncio.wait_for(asyncio.gather(*(enrich(day) for day in days)), timeout=45)
    except asyncio.TimeoutError:
        logger.warning("ToC enrichment exceeded 45 seconds; retaining deterministic curriculum")
        return 0
    prior_outcomes = []
    enriched_count = 0
    for day, result in zip(days, results):
        if not result:
            continue
        outcomes = [str(item).strip() for item in result.get("learning_outcomes") or [] if str(item).strip()]
        summary = str(result.get("hands_on_summary") or "").strip()
        if not _daily_enrichment_is_specific(result, day, prior_outcomes):
            logger.warning("AI day enrichment rejected quality checks for day %s", day.get("day"))
            continue
        day["learning_objectives"] = outcomes
        day["lab"] = summary
        enriched_count += 1
        prior_outcomes.extend(_normalise_daily_text(item) for item in outcomes)
    toc["ai_enriched_days"] = enriched_count
    return enriched_count


async def _enrich_manual_toc_if_available(toc: dict) -> bool:
    """Apply the same daily enrichment to Manual/Template TOCs when AI is configured."""
    settings = get_settings()
    api_key = str(getattr(settings, "OPENAI_API_KEY", "") or "").strip()
    if not api_key:
        return False
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key)
        enriched = await _enrich_toc_days_with_ai(
            client, str(getattr(settings, "OPENAI_MODEL", "gpt-5.5") or "gpt-5.5"), toc,
        )
        return bool(enriched)
    except Exception:
        logger.exception("Manual TOC daily enrichment failed; retaining deterministic output")
        return False


async def _generate_ai_toc(payload: TocRequest) -> Optional[dict]:
    """Create a ToC from the approved backbone, enriching each day independently."""
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
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key)
        for day in backbone.get("days") or []:
            day["requirement_context"] = {
                "audience": payload.audience_level, "level": payload.level,
                "custom_topics": payload.custom_topics, "client_notes": payload.client_notes,
                "notes": payload.notes, "hours_per_day": payload.hours_per_day,
                "cloud_provider": payload.cloud_provider, "lab_type": payload.lab_type,
            }
        enriched = await _enrich_toc_days_with_ai(
            client, str(getattr(settings, "OPENAI_MODEL", "gpt-5.5") or "gpt-5.5"), backbone,
        )
        if not enriched:
            return None
        for day in backbone.get("days") or []:
            day.pop("requirement_context", None)
        toc = validate_toc(backbone, days)
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
    if requested_mode == "ai" and not toc:
        raise HTTPException(502, "AI TOC generation did not produce usable content. Retry or select Template mode explicitly.")
    if toc:
        used_generation_mode = "ai"
        if "ai_enriched_days" in toc and toc["ai_enriched_days"] < len(toc.get("days") or []):
            used_generation_mode = "ai_partial"
            toc["generation_warning"] = "Some days retained reference content because AI enrichment failed. Review before sharing."
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
            if requested_mode != "ai" and payload.allow_ai_enrichment and await _enrich_manual_toc_if_available(toc):
                toc = validate_toc(toc, int(payload.duration_days))
                used_generation_mode = "template_ai_enriched"
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
    _apply_requirement_quality(toc, payload)
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


def _apply_requirement_quality(toc: dict, payload: TocRequest) -> None:
    """Do not mistake structural completeness for client scope approval."""
    warnings = []
    hours = payload.hours_per_day
    if hours is not None and not 0 < hours <= 24:
        raise HTTPException(422, "Training hours per day must be greater than zero and at most 24")
    toc["hours_per_day"] = hours
    timing = payload.timing or "To be confirmed"
    for day in toc.get("days") or []:
        day["timing"] = timing
        day["hours_per_day"] = hours
        # Dataset sessions contain fixed 9-5 times. Preserve curriculum, but
        # remove those invented times from every exported session and topic.
        for key in ("morning_session", "afternoon_session"):
            session = day.get(key) or {}
            session["time"] = "To be confirmed"
            for topic in session.get("topics") or []:
                if isinstance(topic, dict):
                    topic.pop("time", None)
            day[key] = session
    if not hours:
        warnings.append("Confirm training hours per day independently of lab-access hours")
    else:
        overloaded = []
        for index, day in enumerate(toc.get("days") or [], 1):
            # Conservative minimum planning budget: ten minutes per subtopic,
            # one practical lab (45 minutes), and a 15-minute assessment.
            minimum_minutes = len(day.get("subtopics") or []) * 10 + 60
            day["minimum_planned_minutes"] = minimum_minutes
            if minimum_minutes > hours * 60:
                overloaded.append(str(day.get("day") or index))
        if overloaded:
            warnings.append("Daily workload exceeds training hours on day(s): " + ", ".join(overloaded))

    # Search curriculum only: echoing a topic in overview/metadata is not coverage.
    curriculum = json.dumps([
        {key: day.get(key) for key in ("focus_area", "subtopics", "lab", "learning_objectives")}
        for day in toc.get("days") or []
    ], ensure_ascii=False).lower()
    requested = []
    for part in (item.strip() for item in re.split(r"[;,\n]+", payload.custom_topics or "")):
        if not part:
            continue
        detected = [
            technology for technology, patterns in _SCOPE_TECHNOLOGY_RULES
            if any(re.search(pattern, part, flags=re.IGNORECASE) for pattern in patterns)
        ]
        # A phrase such as "DevOps including AWS and Azure" describes several
        # technologies; coverage must validate each technology independently.
        # A qualified name such as "Advanced DevOps" still represents the
        # detected DevOps scope. Validate the canonical technology instead of
        # requiring that exact adjective-qualified phrase in the curriculum.
        if detected:
            requested.extend(detected)
        else:
            # Validate a combined client topic (for example, "Jenkins and
            # Monitoring") against its individual curriculum subjects.
            requested.extend(
                item.strip()
                for item in re.split(r"\s+(?:and|&)\s+", part, flags=re.IGNORECASE)
                if item.strip()
            )
    requested = list(dict.fromkeys(requested))
    from shared.toc_quality import topic_is_covered
    missing = [topic for topic in requested if not topic_is_covered(topic, curriculum)]
    if missing:
        warnings.append("Requested topics need coverage review: " + "; ".join(missing))
    quality = toc.setdefault("quality", {})
    quality["missing_requested_topics"] = missing
    quality["review_warnings"] = warnings
    if warnings and quality.get("status") != "requires_regeneration":
        quality["status"] = "requires_review"


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
