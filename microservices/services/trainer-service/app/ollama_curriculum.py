"""Client-specific Ollama planning with optional local curriculum references."""
import asyncio
import json
import re
import time

from pydantic import Field, StrictInt, StringConstraints
from typing import Annotated

from app.curriculum_reasoning import (
    Brief, Contract, load_records, retrieve,
)
from app.ollama_client import OllamaClient
from shared.toc_quality import topic_is_covered


SpecificText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=12)]


class LabCheck(Contract):
    input_or_condition: SpecificText
    expected_result: SpecificText
    evidence: SpecificText


class ClientDay(Contract):
    day: StrictInt
    focus_area: str = Field(min_length=3)
    subtopics: list[str] = Field(min_length=3, max_length=5)
    lab: str = Field(min_length=30)
    learning_objectives: list[str] = Field(min_length=3, max_length=4)
    tools: list[str] = Field(min_length=1)
    prerequisites: list[SpecificText] = Field(min_length=1)
    preparation_requirements: list[SpecificText] = Field(min_length=1)
    prerequisite_days: list[StrictInt]
    deliverable: SpecificText
    assessment: SpecificText
    acceptance_checks: list[LabCheck] = Field(min_length=3, max_length=4)


class ClientCurriculum(Contract):
    overview: str = Field(min_length=20)
    excluded_topics: list[str]
    days: list[ClientDay]


def _materialize_curriculum(plan, request):
    """Add delivery fields to the model-designed daily topics and exercises."""
    days = plan.model_dump()["days"]
    hours = request.hours_per_day or 6
    daily_minutes = int(hours * 60)
    if daily_minutes < 90:
        raise ValueError("At least 90 training minutes per day are needed for the requested topics, lab and assessment")
    for day in days:
        topic = day["focus_area"]
        lab = day["lab"]
        subtopics = day["subtopics"]
        day["title"] = f"Day {day['day']}: {topic}"
        day["minutes"] = daily_minutes
        day["scenario"] = f"A {request.audience_level or request.level} participant applies {topic.lower()} to a task described in the client request."
        setup = max(15, daily_minutes // 6)
        assessment_minutes = max(15, daily_minutes // 12)
        practice = daily_minutes - setup - assessment_minutes
        day["delivery_steps"] = [
            {"method": "Explain and demonstrate", "minutes": setup,
             "activity": f"Introduce {topic} using the client objectives, then demonstrate a short example.",
             "evidence": f"Participants identify the key steps for {subtopics[0]}"},
            {"method": "Guided practice", "minutes": practice,
             "activity": lab,
             "evidence": day["deliverable"]},
            {"method": "Assessment", "minutes": assessment_minutes,
             "activity": day["assessment"],
             "evidence": "; ".join(check["evidence"] for check in day["acceptance_checks"])},
        ]
    outcomes = list(dict.fromkeys(item for day in days for item in day["learning_objectives"]))
    brief = Brief(
        audience=request.audience_level or f"{request.level} learners",
        outcomes=outcomes,
        required_topics=[item.strip() for item in re.split(r"[;,\n]+", request.custom_topics or "") if item.strip()],
        excluded_topics=[], prior_knowledge=[], constraints=[], clarification_questions=[],
    )
    return brief, days


def validate_curriculum(plan, request):
    """Validate requirement coverage, day sequence and time without catalog dependence."""
    from app.toc_evaluation import concrete_acceptance_check, evaluate_toc

    days = plan.get("days") or []
    if [day.get("day") for day in days] != list(range(1, int(request.duration_days) + 1)):
        raise ValueError("Ollama must return exactly the requested days in sequential order")
    required = [item.strip() for item in re.split(r"[;,\n]+", request.custom_topics or "") if item.strip()]
    excluded = plan.get("excluded_topics") or []
    coverage = {topic: [] for topic in required}
    errors = []
    for day in days:
        teaching = " ".join([day.get("focus_area", ""), *day.get("subtopics", []), day.get("lab", ""), *day.get("learning_objectives", [])])
        for topic in required:
            if topic_is_covered(topic, teaching):
                coverage[topic].append(day["day"])
        for topic in excluded:
            if topic_is_covered(topic, teaching):
                errors.append(f"Day {day['day']}: includes excluded topic {topic}")
        if any(n < 1 or n >= day["day"] for n in day.get("prerequisite_days", [])):
            errors.append(f"Day {day['day']}: prerequisites must refer to earlier days")
        if len(day.get("learning_objectives", [])) < 3:
            errors.append(f"Day {day['day']}: needs at least three learning objectives")
        if day.get("minutes", 0) < 10 * len(day.get("subtopics", [])) + 60:
            errors.append(f"Day {day['day']}: insufficient time for topics, practice and assessment")
        if sum(step["minutes"] for step in day.get("delivery_steps", [])) != day.get("minutes"):
            errors.append(f"Day {day['day']}: activity minutes must equal daily minutes")
        checks = day.get("acceptance_checks", [])
        signatures = {(check.get("expected_result", "").strip().lower(),
                       check.get("evidence", "").strip().lower()) for check in checks}
        if len(checks) < 3 or not all(concrete_acceptance_check(check) for check in checks) or len(signatures) != len(checks):
            errors.append(f"Day {day['day']}: needs three distinct, lab-specific acceptance checks")
    if any(not value for value in coverage.values()):
        errors.extend("Missing requested topic: " + key for key, value in coverage.items() if not value)
    evaluation = evaluate_toc(plan, required_topics=required, excluded_topics=excluded,
                              requested_days=int(request.duration_days), hours_per_day=request.hours_per_day)
    errors.extend(evaluation.get("blocking_issues", []))
    return list(dict.fromkeys(errors)), coverage, evaluation


async def generate_client_curriculum(request, settings):
    # Topic banks offer optional examples. Ollama chooses and sequences the topics.
    records = await load_records(request._knowledge_db)
    search_text = " ".join([request.domain, request.custom_topics or "", request.client_notes or "", request.notes or ""])
    sources, retrieval = await retrieve(None, None, records, [search_text], limit=4)
    references = [{key: record.get(key) for key in ("domain", "title", "subtopics")}
                  for record in sources]
    raw = request.model_dump(exclude={"toc_id", "trainer_email", "trainer_name", "trainer_id", "client_email"})
    instructions = (
        "Create a new training outline from THIS client's goals, audience, prior knowledge, requested topics, "
        "exclusions, duration and notes. Choose a suitable topic sequence yourself. Use the local examples only "
        "as optional reference; do not copy their day sequence. Use your knowledge when no reference matches. "
        "Return exactly the requested number of sequential days. Give each day a distinct focus area, 3-5 specific "
        "subtopics, one concise practical lab tied to the client goals, and 3-4 measurable learning objectives. "
        "Progress from prerequisites to applied work. Cover every explicit requested topic; do not include exclusions. "
        "Retain the client's exact requested topic names in subtopics and preserve their business identifiers; "
        "do not substitute different business entities. "
        "For each lab author its actual deliverable, assessment procedure, tools, required prior skills, "
        "trainer preparation (fixtures/accounts/files), and prerequisite day numbers (earlier days only). "
        "Supply three distinct acceptance checks: a normal case, a failure/edge case, and a transfer or repeatability case. "
        "Each check must name a concrete input or action, its observable expected result, and the artifact or command "
        "that proves it. Avoid generic claims such as 'meets the objectives', 'completes the lab', or 'recorded results'. "
        "Adapt depth and examples to the audience. Never invent client facts; use a clearly generic scenario if the "
        "notes contain none. Write a concise overview. Return the requested JSON only."
    )
    schema = ClientCurriculum.model_json_schema()
    schema["properties"]["days"].update(minItems=int(request.duration_days), maxItems=int(request.duration_days))
    timeout = max(60, settings.OLLAMA_TOC_TIMEOUT_SECONDS)
    deadline = time.monotonic() + timeout
    feedback = []
    for attempt in range(1, 3):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise asyncio.TimeoutError('Ollama curriculum generation exceeded its total time budget')
        # Reference examples can carry a different client's business entities.
        # A correction must not keep copying the same conflicting example.
        context = {"optional_references": references if attempt == 1 else [], "request": raw,
                   "required_topic_names": [item.strip() for item in re.split(r"[;,\n]+", request.custom_topics or "") if item.strip()]}
        if feedback:
            context['corrections_required'] = feedback
            context['correction_instruction'] = (
                'Regenerate from the client request only. Include each required_topic_name verbatim '
                'inside a substantive subtopic and teach it in the lab and assessment. '
                'Do not copy business entities or identifiers from earlier optional examples.'
            )
        try:
            response = await asyncio.wait_for(
                OllamaClient(settings.OLLAMA_URL, timeout=remaining).responses.create(
                    model=settings.OLLAMA_MODEL, instructions=instructions,
                    input=json.dumps(context, ensure_ascii=False),
                    text={"format": {"type": "json_schema", "name": "client_training_outline", "schema": schema}},
                    native_schema=True, think=False,
                    max_output_tokens=min(32000, 1000 + int(request.duration_days) * 1000),
                ), timeout=remaining,
            )
            generated = ClientCurriculum.model_validate_json(response.output_text)
            brief, days = _materialize_curriculum(generated, request)
            brief.excluded_topics = generated.excluded_topics
            plan = {"overview": generated.overview, "days": days, "excluded_topics": generated.excluded_topics}
            errors, coverage, evaluation = validate_curriculum(plan, request)
        except ValueError as exc:
            if attempt == 2:
                raise
            feedback = [str(exc)[:2000]]
            continue
        if not errors or attempt == 2:
            break
        feedback = errors[:12]
    warnings = ["Ollama-designed topics and sequence require trainer review for technical accuracy and client fit",
                *evaluation["issues"], *errors]
    if not request.hours_per_day:
        warnings.append("Confirm the assumed six-hour training day")
    toc = {
        "title": f"{request.domain} training for {brief.audience}",
        "overview": generated.overview,
        "prerequisites": list(dict.fromkeys(value for day in days for value in day["prerequisites"])),
        "learning_outcomes": brief.outcomes,
        "assumptions": [] if request.hours_per_day else ["Assumed six training hours per day; confirm with the client"],
        "clarification_questions": [],
        "domain": request.domain, "level": request.level, "mode": request.mode,
        "duration_days": int(request.duration_days), "hours_per_day": request.hours_per_day or 6,
        "planning_method": "ollama_client_curriculum", "ai_provider": "ollama",
        "generation_attempts": attempt,
        "requirement_brief": brief.model_dump(), "coverage_matrix": coverage,
        "retrieval": retrieval, "reference_candidates": references,
        "quality": {"status": "requires_regeneration" if errors else "requires_review",
                    "validation_errors": errors, "review_warnings": list(dict.fromkeys(warnings)),
                    "content_evaluation": evaluation, "content_score": evaluation["score"]},
    }
    from app.toc_generation_agent import _business_dates, _training_start_date
    dates = _business_dates(_training_start_date(request.training_dates), len(days)) if request.training_dates else []
    for index, day in enumerate(days):
        day["lab_task"] = day["lab"]
        if dates:
            day["date"] = dates[index]
        day["morning_session"] = {"topics": [{"topic": topic, "type": "lecture"} for topic in day["subtopics"]]}
        day["afternoon_session"] = {"topics": [{"topic": day["lab"], "type": "lab"},
                                                {"topic": day["assessment"], "type": "assessment"}]}
    toc["days"] = days
    return toc
