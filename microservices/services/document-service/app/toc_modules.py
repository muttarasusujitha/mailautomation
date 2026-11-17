"""Split whole-day TOC entries into coded modules for the reference (execution plan) exports.

Generated technology TOCs hold one seven-hour entry per day. The client
reference format lists several timed modules per day, each with its own
coded title (M1, M2 ...), lab, outcome, deliverable and success measure.
This module only rearranges content the day already has; it does not invent
technical topics.
"""
import math

# A day shorter than this is already module-sized (for example, an imported
# execution plan whose modules are 75-105 minutes), so it is left alone.
_WHOLE_DAY_MINUTES = 300
# Share of the day for concepts, applied practice, hands-on lab, validation.
_TEACHING_SPLIT = (90, 90, 150, 90)
_CAPSTONE_SPLIT = (300, 120)
# Fields that describe the whole day; they are kept once, on the first module,
# so readiness and prerequisite rows are not repeated for every module.
_FIRST_MODULE_ONLY = ("preparation_requirements", "prerequisites", "proposed_fields")


def _as_list(value):
    if isinstance(value, list):
        return [item for item in value if item not in (None, "")]
    return [value] if value not in (None, "") else []


def _text(value):
    if isinstance(value, list):
        return "; ".join(_text(item) for item in value if _text(item))
    if isinstance(value, dict):
        return str(value.get("topic") or value.get("title") or "")
    return str(value or "").strip()


def _scaled(split, total):
    """Scale a minute split to the day's total, in 15-minute steps, keeping the sum."""
    base = sum(split)
    if total == base:
        return list(split)
    minutes = [max(15, int(round(part * total / base / 15)) * 15) for part in split]
    minutes[-1] += total - sum(minutes)
    if minutes[-1] < 15:
        return list(split)
    return minutes


def _day_minutes(day):
    try:
        value = float(day.get("minutes"))
        return int(value) if math.isfinite(value) and value > 0 else None
    except (TypeError, ValueError):
        return None


def needs_split(day):
    # Unknown hours are never invented, so only a day with a stated whole-day
    # budget is divided into timed modules.
    minutes = _day_minutes(day)
    return minutes is not None and minutes >= _WHOLE_DAY_MINUTES


def _base(day, title, code, minutes):
    return {
        "day": day.get("day"), "date": day.get("date"), "week": day.get("week"),
        "timing": day.get("timing"), "tools": day.get("tools"),
        "focus_area": f"M{code} - {title}", "title": f"M{code} - {title}",
        # The day this module came from, for matching integration days and capstones.
        "source_title": day.get("focus_area") or day.get("topic") or day.get("title"),
        "minutes": minutes, "hours_per_day": None,
    }


def _step(method, minutes, activity, evidence):
    return [{"method": method, "minutes": minutes, "activity": activity, "evidence": evidence}]


def split_day(day, first_code):
    """Return the day as a list of coded modules, numbered from ``first_code``."""
    focus = _text(day.get("focus_area") or day.get("topic") or day.get("title")) or "Training"
    focus = focus.split(": ", 1)[1] if focus.lower().startswith("day ") and ": " in focus else focus
    subtopics = [_text(item) for item in _as_list(day.get("subtopics")) if _text(item)]
    objectives = [_text(item) for item in _as_list(day.get("learning_objectives")) if _text(item)]
    lab = _text(day.get("lab") or day.get("lab_task"))
    deliverable = _text(day.get("deliverable"))
    assessment = _text(day.get("assessment"))
    checks = [check for check in _as_list(day.get("acceptance_checks")) if isinstance(check, dict)]
    scenarios = _as_list(day.get("scenarios"))
    total = _day_minutes(day)
    modules = []

    if "capstone" in focus.lower():
        build, review = _scaled(_CAPSTONE_SPLIT, total)
        modules.append({**_base(day, f"{focus}: build", first_code, build),
            "subtopics": subtopics, "lab": lab or f"Build the {focus} deliverable",
            "learning_objectives": objectives[:max(1, len(objectives) - 1)] or [f"Complete the {focus} deliverable"],
            "deliverable": deliverable or "Working capstone solution",
            "assessment": "Solution meets the capstone requirements on the trainer's checklist",
            "delivery_steps": _step("Capstone build", build, lab or focus, deliverable or "Working capstone solution")})
        modules.append({**_base(day, f"{focus}: demo and review", first_code + 1, review),
            "subtopics": ["Solution demonstration", "Design decisions and trade-offs", "Trainer and peer review"],
            "lab": "Present the solution, explain design decisions and answer review questions",
            "learning_objectives": objectives[-1:] or [f"Defend the {focus} solution"],
            "deliverable": "Demonstration and review notes",
            "assessment": assessment or "Demonstration passes the trainer's review",
            "delivery_steps": _step("Demonstration and review", review, "Present and defend the capstone",
                                    "Demonstration and review notes")})
    else:
        concepts, practice, hands_on, validation = _scaled(_TEACHING_SPLIT, total)
        half = (len(subtopics) + 1) // 2
        first, second = subtopics[:half] or [focus], subtopics[half:] or subtopics[:half] or [focus]
        check_conditions = [_text(check.get("input_or_condition")) for check in checks if _text(check.get("input_or_condition"))]
        check_results = [_text(check.get("expected_result")) for check in checks if _text(check.get("expected_result"))]
        lab_objectives = objectives[2:] or objectives[-1:] or [f"Complete the {focus} lab"]
        modules.append({**_base(day, f"{focus}: {first[0]}", first_code, concepts),
            "subtopics": first, "lab": "Follow the trainer's live demonstration of " + ", ".join(first[:3]),
            "learning_objectives": objectives[:1] or [f"Explain {first[0]}"],
            "deliverable": "Working copy of the demonstrated example",
            "assessment": "Participant reproduces the demonstration and answers concept questions",
            "delivery_steps": _step("Concept explanation and demonstration", concepts,
                                    "Explain and demonstrate " + ", ".join(first[:3]), "Working copy of the demonstration")})
        modules.append({**_base(day, f"{focus}: {second[0]}", first_code + 1, practice),
            "subtopics": second, "lab": "Guided exercise: " + ", ".join(second[:3]),
            "learning_objectives": objectives[1:2] or objectives[:1] or [f"Apply {second[0]}"],
            "deliverable": "Completed guided exercise",
            "assessment": "Exercise output matches the trainer's expected result",
            "delivery_steps": _step("Guided practice", practice, "Guided exercise on " + ", ".join(second[:3]),
                                    "Completed guided exercise")})
        lab_module = {**_base(day, f"{focus}: hands-on lab", first_code + 2, hands_on),
            "subtopics": [lab] if lab else first + second, "lab": lab or f"Hands-on {focus} lab",
            "learning_objectives": lab_objectives, "deliverable": deliverable or f"{focus} lab artefact",
            "assessment": assessment or "Lab result reviewed against the trainer's expected result",
            "delivery_steps": _step("Hands-on lab", hands_on, lab or focus, deliverable or f"{focus} lab artefact")}
        if scenarios:
            lab_module["scenarios"] = scenarios
        elif day.get("scenario"):
            lab_module["scenario"] = day["scenario"]
        modules.append(lab_module)
        modules.append({**_base(day, f"{focus}: validation and review", first_code + 3, validation),
            "subtopics": check_conditions or ["Acceptance checks", "Edge-case input", "Review of results"],
            "lab": "Run the acceptance checks, then repeat the lab with an edge-case input",
            "learning_objectives": [f"Prove the {focus} result meets its acceptance checks"],
            "deliverable": "Acceptance check results with an explanation of the edge case",
            "assessment": "; ".join(check_results) or "Every acceptance check passes and the edge case is explained",
            "acceptance_checks": checks,
            "delivery_steps": _step("Validation and review", validation, "Acceptance checks and edge case",
                                    "Acceptance check results")})

    for key in _FIRST_MODULE_ONLY:
        if day.get(key):
            modules[0][key] = day[key]
    return modules


PROPOSED_SPLIT_NOTE = (
    "Modules marked 'proposed' were split automatically from a whole-day plan: the lab and topics come "
    "from the course, but module boundaries, timings and the demonstration, practice and validation "
    "wording are standard. A trainer should review them before client delivery.")


def to_modules(days, split=True, mark_proposed=True):
    """Flatten days into module rows; whole-day entries are split into coded modules.

    Authored modules that ask for it (``number_in_plan``) and split modules share
    one M1, M2 ... sequence across the programme. ``split=False`` keeps whole
    days (AI-written days carry their own timed delivery sequence).
    ``mark_proposed`` adds "(proposed)" to split module titles, for draft exports.
    """
    rows, code = [], 1
    for day in days:
        modules = day.get("modules") or []
        whole_day = {k: v for k, v in {**day, **(modules[0] if len(modules) == 1 else {})}.items() if k != "modules"}
        if split and len(modules) <= 1 and needs_split(whole_day):
            parts = split_day(whole_day, code)
            for module in parts:
                module["proposed_split"] = True
                if mark_proposed:
                    module["focus_area"] = module["title"] = module["title"] + " (proposed)"
            code += len(parts)
            rows.extend(parts)
        elif modules:
            for module in modules:
                title = module.get("title") or module.get("topic")
                numbered = bool(module.get("number_in_plan"))
                if numbered:
                    title = f"M{code} - {title}"
                    code += 1
                rows.append({**module, "day": day.get("day"), "date": day.get("date"),
                    "timing": module.get("timing") or day.get("timing"),
                    "focus_area": title, "title": title, "hours_per_day": None,
                    **({"source_title": day.get("focus_area") or day.get("title")} if numbered else {})})
        else:
            rows.append(day)
    return rows
