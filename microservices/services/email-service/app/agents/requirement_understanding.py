"""Understand a client requirement email with one LLM call, then verify it.

The model reads the email and returns structured JSON (what the client wants,
from whom, when, where, and what they asked us for). Python then checks every
value against the email text and drops anything the email does not support,
so the reply can never repeat an invented fact. The checked understanding
replaces the rule-based guesses in the reply plan.

This module has no third-party dependencies; the caller supplies the model call.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

ITEM_KINDS = (
    "trainer_profile", "cv", "toc", "lab_cost", "lab_environment", "commercials", "availability",
    "call_slots", "certification_details", "duration_recommendation", "delivery_plan", "materials", "other",
)
FIELDS = ("dates", "duration", "delivery mode", "location", "budget", "participant count", "audience level", "lab setup")

UNDERSTANDING_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "is_training_requirement": {"type": "boolean"},
        "topic": {"type": "string"},
        "scope_topics": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        "for_end_client": {"type": "boolean"},
        "urgent": {"type": "boolean"},
        "deadline": {"type": "string"},
        "trainers": {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
                "experience_years": {"type": "string"},
                "skills": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
                "onsite": {"type": "boolean"},
                "location": {"type": "string"},
                "engagement_length": {"type": "string"},
            },
            "required": ["count", "experience_years", "skills", "onsite", "location", "engagement_length"],
        },
        "schedule": {
            "type": "object",
            "properties": {
                "start": {"type": "string"},
                "duration": {"type": "string"},
                "hours_per_day": {"type": "string"},
                "mode": {"type": "string", "enum": ["online", "offline", "hybrid", "unknown"]},
            },
            "required": ["start", "duration", "hours_per_day", "mode"],
        },
        "participants": {
            "type": "object",
            "properties": {"count": {"type": "string"}, "level": {"type": "string"}},
            "required": ["count", "level"],
        },
        "requested_from_us": {
            "type": "array",
            "maxItems": 10,
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": list(ITEM_KINDS)},
                    "client_words": {"type": "string"},
                },
                "required": ["kind", "client_words"],
            },
        },
        "lab": {
            "type": "object",
            "properties": {"days": {"type": "string"}, "hours_per_day": {"type": "string"}, "cloud": {"type": "string"}},
            "required": ["days", "hours_per_day", "cloud"],
        },
        "commercial_basis": {"type": "string"},
        "budget_mentioned": {"type": "boolean"},
        "to_be_confirmed": {"type": "array", "items": {"type": "string", "enum": list(FIELDS)}},
        "asks_us_to_recommend": {"type": "array", "items": {"type": "string", "enum": list(FIELDS)}},
        "conflicts": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "about": {"type": "string"},
                    "values": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
                },
                "required": ["about", "values"],
            },
        },
    },
    "required": [
        "is_training_requirement", "topic", "scope_topics", "for_end_client", "urgent", "deadline", "trainers",
        "schedule", "participants", "requested_from_us", "lab", "commercial_basis", "budget_mentioned",
        "to_be_confirmed", "asks_us_to_recommend", "conflicts",
    ],
}

SYSTEM = (
    "You read corporate training requirement emails sent to Clahan Technologies, a trainer provider. "
    "Extract what the email says into the JSON schema. Read the whole email, including tables and bullet lists. "
    "Rules: use only facts written in the email; use an empty string, 0, false, or [] when a value is not stated. "
    "Copy names, numbers, dates, and places exactly as written. "
    "topic: the technology or subject of the training in a few words (e.g. 'Azure Data Explorer', 'SAP IBP'). "
    "scope_topics: up to 6 module or topic names the training must cover, short. "
    "for_end_client: true when the sender is arranging the training for their own client or customer. "
    "urgent: true for urgent, ASAP, immediate, priority, or 'at the earliest'. deadline: a stated reply deadline. "
    "trainers.skills: up to 5 short skills or experience areas the trainer must have. "
    "trainers.onsite: true for onsite, classroom, in-person, or client-location delivery. "
    "requested_from_us: each thing the sender asks Clahan to send or do, in the email's order, with the "
    "sender's own words in client_words. Skills the trainer needs, topics to cover, and facts the sender states "
    "are not requests. Use duration_recommendation when they ask us to propose the duration, delivery_plan for "
    "a proposed schedule or delivery approach, lab_environment for sandbox or lab access, call_slots for a "
    "screening, evaluation, technical, or interview call. "
    "commercial_basis: how they want pricing quoted (e.g. 'per day', 'per batch', 'per month'), else ''. "
    "to_be_confirmed: fields the sender says are still open (TBD, to be confirmed, to be decided). "
    "asks_us_to_recommend: fields the sender wants us to propose instead of telling us. "
    "conflicts: details stated inconsistently in the email, such as two different start dates or lab days that "
    "differ from training days; values must be copied from the email. "
    "is_training_requirement: false for sales pitches from other training companies, newsletters, invoices, or "
    "replies that ask nothing. Return JSON only."
)


def understanding_prompt(subject: str, body: str) -> str:
    return f"Email subject:\n{subject}\n\nEmail body:\n{str(body or '')[:8000]}"


def parse_understanding(raw: Any) -> Optional[Dict[str, Any]]:
    """Parse model output into a dict, tolerating code fences and surrounding text."""
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(text[start:end + 1])
        except ValueError:
            return None
    return data if isinstance(data, dict) else None


_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30,
}
_STOP = {"the", "and", "for", "with", "of", "in", "on", "to", "a", "an", "or", "per", "day", "days", "training",
         "program", "programme", "&", "/", "-", "\u2013", "based", "at", "by", "from"}


def _norm(text: str) -> str:
    return re.sub(r"[\u2010-\u2015]", "-", re.sub(r"\s+", " ", str(text or ""))).lower()


def _words(text: str) -> List[str]:
    return [word for word in re.findall(r"[a-z0-9+#.]+", _norm(text))
            if word not in _STOP and (len(word) > 1 or word.isdigit())]


def _supported(value: Any, email: str, share: float = 0.7) -> str:
    """Return the value if most of its words appear in the email, else ''."""
    text = re.sub(r"\s+", " ", str(value or "")).strip(" .,;:")
    if not text or len(text) > 160:
        return ""
    words = _words(text)
    if not words:
        # Only common words, such as "per day": the phrase itself must appear.
        return text if _norm(text) in email else ""
    present = sum(1 for word in words if re.search(rf"(?<![a-z0-9]){re.escape(word.rstrip('.'))}", email))
    return text if present / len(words) >= share else ""


def _number_supported(value: Any, email: str) -> int:
    try:
        number = int(float(str(value).strip().rstrip("+")))
    except (TypeError, ValueError):
        return 0
    if number <= 0:
        return 0
    words = [word for word, num in _NUMBER_WORDS.items() if num == number]
    if re.search(rf"(?<!\d){number}(?!\d)", email) or any(re.search(rf"\b{word}\b", email) for word in words):
        return number
    return 0


def _years_supported(value: Any, email: str) -> str:
    match = re.match(r"\s*(\d{1,2})\s*(\+)?", str(value or ""))
    if not match or not _number_supported(match.group(1), email):
        return ""
    plus = match.group(2) or ("+" if re.search(rf"{match.group(1)}\s*\+", email) else "")
    return f"{match.group(1)}{plus}"


def _list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def ground_understanding(data: Optional[Dict[str, Any]], subject: str, body: str) -> Optional[Dict[str, Any]]:
    """Keep only what the email supports. Returns None when nothing usable remains."""
    if not isinstance(data, dict):
        return None
    email = _norm(f"{subject}\n{body}")
    trainers, schedule = _dict(data.get("trainers")), _dict(data.get("schedule"))
    participants, lab = _dict(data.get("participants")), _dict(data.get("lab"))
    dropped: List[str] = []

    def keep(label: str, value: Any, share: float = 0.7) -> str:
        result = _supported(value, email, share)
        if str(value or "").strip() and not result:
            dropped.append(label)
        return result

    items = []
    for entry in _list(data.get("requested_from_us"))[:10]:
        entry = _dict(entry)
        kind = str(entry.get("kind") or "")
        if kind not in ITEM_KINDS:
            continue
        words = keep(f"request:{kind}", entry.get("client_words"), 0.6)
        if kind == "other" and not words:
            continue
        items.append({"kind": kind, "client_words": words})

    conflicts = []
    for entry in _list(data.get("conflicts"))[:3]:
        entry = _dict(entry)
        values = [str(value).strip() for value in _list(entry.get("values"))[:3] if str(value).strip()]
        grounded = [value for value in values if _supported(value, email, 1.0)]
        if len(grounded) >= 2 and len({_norm(value) for value in grounded}) >= 2:
            conflicts.append({"about": re.sub(r"\s+", " ", str(entry.get("about") or "detail")).strip()[:60],
                              "values": grounded})
        elif values:
            dropped.append("conflict")

    mode = str(schedule.get("mode") or "unknown").lower()
    if mode not in {"online", "offline", "hybrid"}:
        mode = ""
    elif mode == "online" and not re.search(r"online|virtual|remote|vilt|teams|zoom", email):
        mode, _ = "", dropped.append("mode")
    elif mode == "offline" and not re.search(r"offline|onsite|on-site|classroom|in-person|in person|client (?:site|location)", email):
        mode, _ = "", dropped.append("mode")

    understanding = {
        "is_training_requirement": bool(data.get("is_training_requirement", True)),
        "topic": keep("topic", data.get("topic"), 0.75),
        "scope_topics": [topic for topic in (keep("scope", value, 0.75) for value in _list(data.get("scope_topics"))[:6]) if topic],
        "for_end_client": bool(data.get("for_end_client")) and bool(re.search(r"client|customer", email)),
        "urgent": bool(data.get("urgent")),
        "deadline": keep("deadline", data.get("deadline"), 0.8),
        "trainers": {
            "count": _number_supported(trainers.get("count"), email) or 1,
            "experience_years": _years_supported(trainers.get("experience_years"), email),
            "skills": [skill for skill in (keep("skill", value, 0.75) for value in _list(trainers.get("skills"))[:5]) if skill],
            "onsite": bool(trainers.get("onsite")),
            "location": keep("location", trainers.get("location"), 0.8),
            "engagement_length": keep("engagement", trainers.get("engagement_length"), 0.8),
        },
        "schedule": {
            "start": keep("start", schedule.get("start"), 0.8),
            "duration": keep("duration", schedule.get("duration"), 0.8),
            "hours_per_day": keep("hours_per_day", schedule.get("hours_per_day"), 0.8),
            "mode": mode,
        },
        "participants": {
            "count": keep("participants", participants.get("count"), 0.8),
            "level": keep("level", participants.get("level"), 0.75),
        },
        "requested_from_us": items,
        "lab": {
            "days": str(_number_supported(lab.get("days"), email) or ""),
            "hours_per_day": str(_number_supported(lab.get("hours_per_day"), email) or ""),
            "cloud": keep("cloud", lab.get("cloud"), 1.0),
        },
        "commercial_basis": keep("commercial_basis", data.get("commercial_basis"), 0.6),
        "budget_mentioned": bool(data.get("budget_mentioned")) and bool(re.search(r"budget", email)),
        "to_be_confirmed": [field for field in _list(data.get("to_be_confirmed")) if field in FIELDS],
        "asks_us_to_recommend": [field for field in _list(data.get("asks_us_to_recommend")) if field in FIELDS],
        "conflicts": conflicts,
        "dropped_unsupported": dropped,
    }
    if understanding["urgent"] and not re.search(
        r"urgent|asap|immediate|priority|earliest|critical|time[- ]sensitive", email
    ):
        understanding["urgent"] = False
    return understanding


_FIELD_TO_PLAN = {
    "dates": "dates", "duration": "duration", "delivery mode": "delivery mode", "location": "location",
    "budget": "budget", "participant count": "participant count", "audience level": "audience level",
    "lab setup": "lab setup",
}
_RECOMMEND_TO_PLAN = {
    "dates": "dates", "duration": "duration", "delivery mode": "mode", "lab setup": "lab_setup",
    "participant count": "participants", "audience level": "audience",
}


def apply_understanding(plan: Dict[str, Any], understanding: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return a copy of the rule-based plan with the verified understanding applied."""
    if not understanding:
        return plan
    plan = {**plan, "lab": dict(plan.get("lab") or {})}
    u = understanding
    trainers, schedule, lab = u["trainers"], u["schedule"], u["lab"]

    if u["topic"]:
        plan["technology"] = u["topic"]
    if u["scope_topics"]:
        plan["scope"] = u["scope_topics"][:3]
    plan["urgent"] = u["urgent"] or plan.get("urgent", False)
    plan["deadline"] = u["deadline"]
    plan["end_client"] = u["for_end_client"]
    plan["trainer_count"] = trainers["count"]
    plan["experience_years"] = trainers["experience_years"] or plan.get("experience_years", "")
    if trainers["skills"]:
        plan["trainer_skills"] = trainers["skills"][:3]
        plan["trainer_details"] = trainers["skills"]
    plan["onsite"] = trainers["onsite"] or schedule["mode"] == "offline"
    plan["location"] = trainers["location"] or plan.get("location", "")
    plan["engagement_length"] = trainers["engagement_length"]
    if schedule["mode"]:
        plan["mode"] = schedule["mode"]
    plan["schedule"] = dict(schedule)
    plan["participants_count"] = u["participants"]["count"]
    plan["audience_level"] = u["participants"]["level"]
    plan["commercial_basis"] = u["commercial_basis"]
    for key in ("days", "hours_per_day", "cloud"):
        if lab[key]:
            plan["lab"]["hours" if key == "hours_per_day" else key] = int(lab[key]) if key == "days" else lab[key]

    kinds = [entry["kind"] for entry in u["requested_from_us"]]
    if kinds:
        items: List[Dict[str, Any]] = []
        for entry in u["requested_from_us"]:
            kind, words = entry["kind"], entry["client_words"]
            if kind in {"trainer_profile", "cv"}:
                if not any(item["kind"] == "trainer" for item in items):
                    items.append({"kind": "trainer", "text": words})
            elif kind == "toc":
                items.append({"kind": "toc", "text": words})
            elif kind in {"lab_cost", "lab_environment"}:
                items.append({"kind": "lab", "text": words or ("lab cost" if kind == "lab_cost" else "lab environment"),
                              "environment_only": kind == "lab_environment"})
            elif kind == "commercials":
                items.append({"kind": "commercials", "text": words})
            elif kind == "duration_recommendation":
                items.append({"kind": "recommend", "field": "duration", "text": words or "Recommended duration"})
            elif kind == "delivery_plan":
                items.append({"kind": "recommend", "field": "dates", "text": words or "Proposed delivery plan"})
            elif kind in {"certification_details", "materials", "other"} and words:
                items.append({"kind": "other", "text": words})
        trainer_first = [item for item in items if item["kind"] == "trainer"]
        plan["items"] = trainer_first + [item for item in items if item["kind"] != "trainer"]
        plan["cv_requested"] = "cv" in kinds or plan.get("cv_requested", False)
        plan["availability_requested"] = "availability" in kinds
        plan["call_requested"] = "call_slots" in kinds
        plan["trainer_requested"] = True
        plan["lab"]["requested"] = any(item["kind"] == "lab" for item in plan["items"])

    tentative = [_FIELD_TO_PLAN[field] for field in u["to_be_confirmed"]]
    recommended = {_RECOMMEND_TO_PLAN[field] for field in u["asks_us_to_recommend"] if field in _RECOMMEND_TO_PLAN}
    recommended |= {item.get("field") for item in plan.get("items") or [] if item["kind"] == "recommend"}
    plan["tentative"] = tentative or plan.get("tentative") or []
    plan["missing"] = _missing_details(plan, recommended)

    conflicts = list(plan.get("conflicts") or [])
    for conflict in u["conflicts"]:
        values = conflict["values"]
        if any(set(_norm(value) for value in values) & set(_norm(v) for v in existing.get("values", [])) for existing in conflicts):
            continue
        conflicts.append({
            "kind": "llm:" + re.sub(r"\W+", "_", conflict["about"].lower()).strip("_"),
            "values": values,
            "question": f"The {conflict['about'].lower()}, as the email mentions both {values[0]} and {values[1]}",
            "must_mention": [_words(value)[0] for value in values[:2] if _words(value)],
        })
    plan["conflicts"] = conflicts[:3]
    plan["understanding_source"] = "llm_verified"
    return plan


def _missing_details(plan: Dict[str, Any], recommended: set) -> List[Dict[str, str]]:
    """Ask only for details the client has not given, left open, or asked us to recommend."""
    kinds = {item["kind"] for item in plan.get("items") or []}
    tentative = set(plan.get("tentative") or [])
    schedule = plan.get("schedule") or {}
    lab = plan.get("lab") or {}
    lab_items = [item for item in plan.get("items") or [] if item["kind"] == "lab"]
    lab_cost_requested = any(not item.get("environment_only") for item in lab_items)
    missing: List[Dict[str, str]] = []
    if lab_cost_requested and not lab.get("cloud") and "lab_setup" not in recommended and "lab setup" not in tentative:
        missing.append({"key": "cloud", "question": "The preferred cloud platform for the lab (AWS, Azure, or GCP)"})
    if (not plan.get("participants_count") and "participant count" not in tentative and "participants" not in recommended
            and (lab_cost_requested or "commercials" in kinds or plan["batch_type"] == "proposal")):
        missing.append({"key": "participants", "question": "The number of participants"})
    if plan["batch_type"] == "proposal":
        if (not schedule.get("start") and "dates" not in tentative and "dates" not in recommended
                and not plan.get("availability_requested") and not plan.get("engagement_length")):
            missing.append({"key": "dates", "question": "The preferred training dates"})
        if (not schedule.get("duration") and not plan.get("engagement_length") and "duration" not in tentative
                and "duration" not in recommended):
            missing.append({"key": "duration", "question": (
                "The number of training days" if schedule.get("hours_per_day")
                else "The expected duration (number of days and hours per day)")})
        if (not plan.get("mode") and not plan.get("onsite") and not plan.get("location")
                and "delivery mode" not in tentative and "mode" not in recommended):
            missing.append({"key": "mode", "question": "The delivery mode (online or offline)"})
        if ("toc" in kinds and not missing and not plan.get("audience_level")
                and "audience level" not in tentative and "audience" not in recommended):
            missing.append({"key": "audience", "question": "The experience level of the participants"})
    return missing[:3]
