"""Client-specific Ollama planning with optional local curriculum references."""
import asyncio
import json
import re

from pydantic import Field, StrictInt

from app.curriculum_reasoning import (
    AcceptanceCheck, Brief, Contract, DeliveryStep, load_records, retrieve,
)
from app.ollama_client import OllamaClient
from shared.toc_quality import normalize_topic, topic_is_covered


class ClientDay(Contract):
    day: StrictInt
    focus_area: str = Field(min_length=3)
    subtopics: list[str] = Field(min_length=3, max_length=5)
    lab: str = Field(min_length=30)
    learning_objectives: list[str] = Field(min_length=3, max_length=4)


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
        outcomes = day["learning_objectives"]
        day["title"] = f"Day {day['day']}: {topic}"
        day["tools"] = [request.domain]
        day["minutes"] = daily_minutes
        day["assessment"] = "Check the lab deliverable against the learning objectives and record failed cases for correction."
        day["deliverable"] = f"Completed lab output for {topic}, with validation evidence."
        day["scenario"] = f"A {request.audience_level or request.level} participant applies {topic.lower()} to a task described in the client request."
        day["prerequisite_days"] = [day["day"] - 1] if day["day"] > 1 else []
        day["prerequisites"] = [request.audience_level or request.level]
        day["preparation_requirements"] = [f"Prepare a sample exercise and expected results for: {lab}"]
        setup = max(15, daily_minutes // 6)
        assessment_minutes = max(15, daily_minutes // 12)
        practice = daily_minutes - setup - assessment_minutes
        day["delivery_steps"] = [
            {"method": "Explain and demonstrate", "minutes": setup,
             "activity": f"Introduce {topic} using the client objectives, then demonstrate a short example.",
             "evidence": f"Participants identify the key steps for {subtopics[0]}"},
            {"method": "Guided practice", "minutes": practice,
             "activity": lab,
             "evidence": f"Completed exercise showing: {', '.join(outcomes[:2])}"},
            {"method": "Assessment", "minutes": assessment_minutes,
             "activity": f"Review each participant's lab output against the requested outcomes: {', '.join(outcomes[:3])}.",
             "evidence": "Participant output and recorded assessment results"},
        ]
        day["acceptance_checks"] = [
            {"input_or_condition": f"Standard exercise for {topic}",
             "expected_result": "Participant completes the lab and meets the stated objectives.",
             "evidence": day["deliverable"]},
            {"input_or_condition": f"A failure case in the {topic} exercise",
             "expected_result": "Participant identifies the failure and describes an appropriate correction.",
             "evidence": "Failure case and correction captured in assessment notes"},
            {"input_or_condition": "A new example related to the client objectives",
             "expected_result": "Participant applies the same method to the new example.",
             "evidence": "Independent output reviewed against the objectives"},
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
    from app.toc_evaluation import evaluate_toc

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
        "Adapt depth and examples to the audience. Never invent client facts; use a clearly generic scenario if the "
        "notes contain none. Write a concise overview. Return the requested JSON only."
    )
    schema = ClientCurriculum.model_json_schema()
    schema["properties"]["days"].update(minItems=int(request.duration_days), maxItems=int(request.duration_days))
    timeout = max(60, settings.OLLAMA_TOC_TIMEOUT_SECONDS)
    response = await asyncio.wait_for(
        OllamaClient(settings.OLLAMA_URL, timeout=timeout).responses.create(
            model=settings.OLLAMA_MODEL, instructions=instructions,
            input=json.dumps({"request": raw, "optional_references": references}, ensure_ascii=False),
            text={"format": {"type": "json_schema", "name": "client_training_outline", "schema": schema}},
            native_schema=True, think=False,
            max_output_tokens=min(8000, 500 + int(request.duration_days) * 250),
        ), timeout=timeout,
    )
    generated = ClientCurriculum.model_validate_json(response.output_text)
    brief, days = _materialize_curriculum(generated, request)
    brief.excluded_topics = generated.excluded_topics
    plan = {"overview": generated.overview, "days": days, "excluded_topics": generated.excluded_topics}
    errors, coverage, evaluation = validate_curriculum(plan, request)
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
