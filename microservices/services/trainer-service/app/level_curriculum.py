"""Level-specific course datasets: separate Beginner, Intermediate and Advanced tracks.

Each file in ``datasets_levels/`` (except ``categories.json``) holds one technology
with three authored levels. The TOC generator uses it instead of cutting one
mixed course into depth bands:

* A request no longer than the level is selected from that level only.
* A longer request continues into the next level (Beginner -> Intermediate ->
  Advanced). An Advanced request longer than the Advanced track starts with
  the last Intermediate days as a refresher.
* ``mixed`` takes days from all three levels, in order.

Domains without a level file keep using ``datasets_compact`` unchanged.
"""
import json
import logging
import re
import sys
from copy import deepcopy
from pathlib import Path

logger = logging.getLogger(__name__)

LEVELS = ("beginner", "intermediate", "advanced")
LEVEL_LABELS = {"beginner": "Beginner", "intermediate": "Intermediate", "advanced": "Advanced"}
VERSION = "level-curriculum-v1"
# Marks authored days so the generator keeps their content unchanged. Like the
# rest of the catalog the days stay review_status "unreviewed"; their concrete
# acceptance checks count toward the content score.
STAGE = "level_authored_unreviewed"
REVIEW_WARNING = (
    "Authored level curriculum pending trainer review: confirm technical accuracy, "
    "lab timings and acceptance cases before client delivery."
)
_DIR = Path(__file__).parent / "datasets_levels"
# Files in datasets_levels that are not single-technology courses.
_SPECIAL_FILES = {"categories.json", "combined.json"}
_COURSES = None
_CATEGORIES = None
_COMBINED = None


def _key(value):
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def _load_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def categories():
    """Top-level categories, each with its list of domain names."""
    global _CATEGORIES
    if _CATEGORIES is None:
        path = _DIR / "categories.json"
        _CATEGORIES = _load_json(path).get("categories", []) if path.exists() else []
    return _CATEGORIES


def category_for(domain_name):
    key = _key(domain_name)
    for category in categories():
        if any(_key(domain) == key for domain in category.get("domains", [])):
            return category.get("name")
    course = get_level_course(domain_name)
    return (course or {}).get("category")


def _expand_day(day, course, level, position):
    """Turn a compact authored day into the fields the TOC generator and evaluator read."""
    topic = day["topic"]
    lab = day["lab_task"]
    subtopics = list(day["subtopics"])
    checks = [
        {"input_or_condition": check[0], "expected_result": check[1], "evidence": check[2]}
        for check in day.get("checks", [])
    ]
    assessment = day.get("assessment") or "Trainer verifies: " + "; ".join(
        f"{check['input_or_condition']} -> {check['expected_result']}" for check in checks)
    previous = day.get("prerequisites") or (
        [f"{course['levels'][level]['days'][position - 1]['topic']} (previous day)"] if position
        else list(course["levels"][level].get("prerequisites") or [])[:2])
    concepts = ", ".join(subtopics[:4])
    practice = ", ".join(subtopics[4:]) or concepts
    return {
        "topic": topic,
        "subtopics": subtopics,
        "tools": list(day.get("tools") or course.get("tools") or [course["domain"]]),
        "lab_task": lab,
        "deliverable": day["deliverable"],
        "assessment": assessment,
        "acceptance_checks": checks,
        "learning_objectives": list(day["objectives"]),
        "prerequisites": previous,
        "preparation_requirements": list(day.get("preparation") or [
            f"Starter files, sample data and a worked solution for: {lab}",
            "One failing or edge-case input prepared for the acceptance checks",
        ]),
        "delivery_steps": [
            {"method": "Concept explanation", "minutes": 90, "activity": f"Explain {concepts}",
             "evidence": "Participant notes and answers to concept questions"},
            {"method": "Live demonstration", "minutes": 60, "activity": f"Demonstrate {practice}",
             "evidence": "Demonstrated working example shared with participants"},
            {"method": "Guided lab", "minutes": 150, "activity": lab, "evidence": day["deliverable"]},
            {"method": "Independent extension", "minutes": 60,
             "activity": "Repeat the lab with the prepared edge-case input and explain the difference",
             "evidence": "Edge-case result with a written explanation"},
            {"method": "Review and assessment", "minutes": 60, "activity": assessment,
             "evidence": "Acceptance check results and trainer feedback"},
        ],
        "minutes": 420,
        "duration_basis": "Proposed seven-hour day; the trainer confirms timings during review",
        "proposed_fields": ["delivery_steps", "minutes", "preparation_requirements"],
        "difficulty": LEVEL_LABELS.get(level, "Integrated"),
        "course_level": level,
        **({"shared_key": day["shared_key"]} if day.get("shared_key") else {}),
        "content_quality_stage": STAGE,
        "content_enrichment_version": VERSION,
        "review_status": "unreviewed",
    }


_REQUIRED_DAY_FIELDS = ("topic", "subtopics", "lab_task", "deliverable", "checks", "objectives")


def validate_course(course):
    """Problems that would make a level course unusable or fail the TOC quality gate."""
    from app.toc_generation_agent import _subtopic_target
    problems = []
    if not course.get("domain"):
        problems.append("missing domain")
    topics = []
    for level in LEVELS:
        track = (course.get("levels") or {}).get(level)
        if not track or not track.get("days"):
            problems.append(f"{level}: missing level or days")
            continue
        days = track["days"]
        if not track.get("prerequisites") or not track.get("outcomes"):
            problems.append(f"{level}: missing prerequisites or outcomes")
        if "capstone" not in str(days[-1].get("topic") or "").lower():
            problems.append(f"{level}: last day must be a capstone")
        for number, day in enumerate(days, 1):
            day_problems = _day_problems(day, f"{level} day {number}")
            problems += day_problems
            if day.get("topic"):
                topics.append(day["topic"].strip().lower())
    if len(topics) != len(set(topics)):
        problems.append("day topics must be unique across all three levels")
    return problems


def _day_problems(day, label):
    from app.toc_generation_agent import _subtopic_target
    missing = [field for field in _REQUIRED_DAY_FIELDS if not day.get(field)]
    if missing:
        return [f"{label}: missing {', '.join(missing)}"]
    problems = []
    need = _subtopic_target(day["topic"])
    if len(day["subtopics"]) < need:
        problems.append(f"{label}: {len(day['subtopics'])} subtopics, needs {need}")
    checks = day["checks"]
    if len(checks) < 3 or any(len(check) != 3 or not all(check) for check in checks):
        problems.append(f"{label}: needs 3 checks of [input, expected result, evidence]")
    elif len({check[1].strip().lower() for check in checks}) != len(checks):
        problems.append(f"{label}: checks must have different expected results")
    return problems


def _load_courses():
    global _COURSES
    if _COURSES is not None:
        return _COURSES
    courses = {}
    if _DIR.exists():
        for path in sorted(_DIR.glob("*.json")):
            if path.name in _SPECIAL_FILES:
                continue
            try:
                course = _load_json(path)
                problems = validate_course(course)
                if problems:
                    raise ValueError("; ".join(problems[:5]))
                course["category"] = course.get("category") or next(
                    (c.get("name") for c in categories() if course["domain"] in c.get("domains", [])), "")
                for level in LEVELS:
                    track = course["levels"][level]
                    track["days"] = [_expand_day(day, course, level, index) for index, day in enumerate(track["days"])]
            except (ValueError, KeyError, TypeError, OSError) as exc:
                # A broken file must not stop TOC generation; that domain keeps the old dataset.
                logger.warning("Skipping level dataset %s: %s", path.name, exc)
                continue
            for name in (course["domain"], course.get("name"), *(course.get("aliases") or [])):
                if name:
                    courses[_key(name)] = course
    _COURSES = courses
    return courses


def get_level_course(name):
    return _load_courses().get(_key(name))


def _is_capstone(day):
    return "capstone" in day["topic"].lower()


def _spread(items, count):
    """Keep order; take the first days as anchors, then evenly spaced later days."""
    if count >= len(items):
        return list(items)
    if count <= 0:
        return []
    anchors = min(max(2, count // 3), count)
    chosen = list(range(anchors))
    rest = list(range(anchors, len(items)))
    need = count - anchors
    if need and rest:
        step = len(rest) / need
        chosen += [rest[int(i * step)] for i in range(need)]
    return [items[index] for index in sorted(set(chosen))][:count]


def _split(track):
    days = track["days"]
    return [d for d in days if not _is_capstone(d)], next((d for d in reversed(days) if _is_capstone(d)), None)


def select_level_days(course, level, duration):
    """Return (days, levels_used), or None when all three levels together are too short."""
    duration = max(1, int(duration or 1))
    tracks = {name: _split(course["levels"][name]) for name in LEVELS}
    with_capstone = duration >= 5
    slots = duration - 1 if with_capstone else duration
    if level == "mixed":
        shares = [slots // 3 + (1 if i < slots % 3 else 0) for i in range(3)]
        picked, used = [], []
        for name, share in zip(LEVELS, shares):
            body = tracks[name][0]
            if share > len(body):
                return None
            if share:
                picked += _spread(body, share)
                used.append(name)
        last = "advanced"
    else:
        start = LEVELS.index(level if level in LEVELS else "intermediate")
        chain = list(LEVELS[start:])
        first_body = tracks[chain[0]][0]
        if slots <= len(first_body):
            picked, used = _spread(first_body, slots), [chain[0]]
        else:
            picked, used = [], []
            for name in chain:
                if len(picked) >= slots:
                    break
                picked += tracks[name][0][: slots - len(picked)]
                used.append(name)
            if len(picked) < slots and start > 0:
                # Advanced (or Intermediate) longer than the remaining tracks: refresh the level below first.
                below = tracks[LEVELS[start - 1]][0]
                need = slots - len(picked)
                if need > len(below):
                    return None
                picked = below[-need:] + picked
                used.insert(0, LEVELS[start - 1])
            if len(picked) < slots:
                return None
        last = used[-1]
    if with_capstone:
        capstone = tracks[last][1]
        if capstone is None:
            return None
        picked = picked + [capstone]
    return deepcopy(picked), used


def level_programme(domain_name, duration, level):
    """Days, prerequisites and outcomes for the requested level, or None to use the old dataset."""
    course = get_level_course(domain_name)
    if not course:
        return None
    level = level if level in (*LEVELS, "mixed") else "intermediate"
    selection = select_level_days(course, level, duration)
    if not selection:
        return None
    days, used = selection
    first = "beginner" if level == "mixed" else used[0] if used[0] != level else level
    prerequisites = list(course["levels"][first].get("prerequisites") or [])
    outcomes = []
    for name in used:
        for outcome in course["levels"][name].get("outcomes") or []:
            if outcome not in outcomes:
                outcomes.append(outcome)
    return {
        "domain": {
            "name": course.get("name") or course["domain"],
            "icon": course.get("icon") or "book",
            "days": days,
            "jira_practice": {},
            "certifications": list(course.get("certifications") or []),
        },
        "days": days,
        "levels_used": used,
        "category": course.get("category") or "",
        "prerequisites": prerequisites,
        "outcomes": outcomes,
        "review_warning": REVIEW_WARNING,
    }


def combined_track(course, level, count, used_shared=None, exclude_topics=()):
    """Non-capstone days for one technology inside a combined programme.

    Follows the same level rules as select_level_days. Days whose shared_key was
    already taught by an earlier technology (for example cloud concepts) are skipped.
    """
    if count <= 0:
        return []
    used_shared = used_shared if used_shared is not None else set()
    excluded = {str(topic).strip().lower() for topic in exclude_topics}

    def body(name):
        return [day for day in _split(course["levels"][name])[0]
                if day.get("shared_key") not in used_shared and day["topic"].strip().lower() not in excluded]

    if level == "mixed":
        shares = [count // 3 + (1 if i < count % 3 else 0) for i in range(3)]
        picked = []
        for name, share in zip(LEVELS, shares):
            days = body(name)
            if share > len(days):
                return None
            picked += _spread(days, share)
    else:
        start = LEVELS.index(level if level in LEVELS else "intermediate")
        first = body(LEVELS[start])
        if count <= len(first):
            picked = _spread(first, count)
        else:
            picked = []
            for name in LEVELS[start:]:
                picked += body(name)[: count - len(picked)]
            if len(picked) < count and start > 0:
                need = count - len(picked)
                below = body(LEVELS[start - 1])
                if need > len(below):
                    return None
                picked = below[-need:] + picked
            if len(picked) < count:
                return None
    for day in picked:
        if day.get("shared_key"):
            used_shared.add(day["shared_key"])
    return deepcopy(picked)


def _expand_extra(day, label, prerequisites):
    holder = {"domain": label, "tools": day.get("tools") or [label],
              "levels": {"combined": {"days": [day], "prerequisites": prerequisites}}}
    expanded = _expand_day(day, holder, "combined", 0)
    expanded["difficulty"] = "Integrated"
    return expanded


def _load_combined():
    global _COMBINED
    if _COMBINED is not None:
        return _COMBINED
    data = {"integrations": [], "capstones": []}
    path = _DIR / "combined.json"
    if path.exists():
        try:
            raw = _load_json(path)
        except (ValueError, OSError) as exc:
            logger.warning("Skipping combined.json: %s", exc)
            raw = {}
        for kind, names_key in (("integrations", "between"), ("capstones", "applies_to")):
            for index, entry in enumerate(raw.get(kind) or []):
                names = list(entry.get(names_key) or [])
                problems = _day_problems(entry.get("day") or {}, f"{kind} {index + 1}")
                if len(names) < 2 or problems:
                    logger.warning("Skipping combined.json %s %s: %s", kind, index + 1, "; ".join(problems) or "needs 2+ technologies")
                    continue
                prerequisites = [f"{name} days earlier in this programme" for name in names]
                data[kind].append({"techs": {_key(n) for n in names}, "names": names,
                                   "day": _expand_extra(entry["day"], " + ".join(names), prerequisites)})
    _COMBINED = data
    return data


def integration_days(technologies):
    """Integration days whose technology pair is fully requested, with the pair's names."""
    requested = {_key(name) for name in technologies}
    return [(entry["names"], deepcopy(entry["day"])) for entry in _load_combined()["integrations"]
            if entry["techs"] <= requested]


def combined_capstone(technologies):
    """The most specific authored capstone covering every requested technology, or None."""
    requested = {_key(name) for name in technologies}
    matches = [entry for entry in _load_combined()["capstones"] if requested <= entry["techs"]]
    if not matches:
        return None
    return deepcopy(min(matches, key=lambda entry: len(entry["techs"]))["day"])


def canonical_name(name):
    course = get_level_course(name)
    return course["domain"] if course else name


def coverage_report():
    """Which domains in each category already have level courses."""
    built = {_key(course["domain"]) for course in _load_courses().values()}
    report = []
    for category in categories():
        domains = category.get("domains", [])
        done = [d for d in domains if _key(d) in built]
        report.append({"category": category.get("name"), "built": done,
                       "pending": [d for d in domains if _key(d) not in built]})
    return report


def _check():
    """python -m app.level_curriculum --check: validate every level file and show coverage."""
    failed = False
    for path in sorted(_DIR.glob("*.json")):
        if path.name in _SPECIAL_FILES:
            continue
        try:
            problems = validate_course(_load_json(path))
        except ValueError as exc:
            problems = [f"invalid JSON: {exc}"]
        failed = failed or bool(problems)
        print(f"{'FAIL' if problems else 'OK  '} {path.name}")
        for problem in problems:
            print(f"     - {problem}")
    combined_path = _DIR / "combined.json"
    if combined_path.exists():
        try:
            raw = _load_json(combined_path)
            problems = [p for kind in ("integrations", "capstones")
                        for i, entry in enumerate(raw.get(kind) or [])
                        for p in _day_problems(entry.get("day") or {}, f"{kind} {i + 1}")]
        except ValueError as exc:
            problems = [f"invalid JSON: {exc}"]
        failed = failed or bool(problems)
        print(f"{'FAIL' if problems else 'OK  '} combined.json")
        for problem in problems:
            print(f"     - {problem}")
    total = built = 0
    for row in coverage_report():
        total += len(row["built"]) + len(row["pending"])
        built += len(row["built"])
        print(f"{row['category']}: {len(row['built'])}/{len(row['built']) + len(row['pending'])} built")
    print(f"Domains with level courses: {built}/{total}")
    return 1 if failed else 0


if __name__ == "__main__" and "--check" in sys.argv:
    sys.exit(_check())
