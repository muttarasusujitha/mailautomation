"""Deterministic Training TOC Agent.

The app controls curriculum structure here. Gemini may polish text later, but
it should not decide topic order, day count, labs, or capstone placement.
"""

from copy import deepcopy
from datetime import datetime, timedelta
import re

from app.toc_domain_dataset import get_domain


GROUP_RULES = [
    (5, {"foundation": 2, "core": 2, "advanced": 0, "observability": 0, "security": 0, "projects": 0, "revision": 0, "capstone": 1}),
    (10, {"foundation": 2, "core": 4, "advanced": 3, "observability": 0, "security": 0, "projects": 0, "revision": 0, "capstone": 1}),
    (20, {"foundation": 3, "core": 6, "advanced": 6, "observability": 1, "security": 1, "projects": 1, "revision": 0, "capstone": 2}),
    (30, {"foundation": 4, "core": 8, "advanced": 9, "observability": 2, "security": 1, "projects": 3, "revision": 1, "capstone": 2}),
    (50, {"foundation": 6, "core": 12, "advanced": 15, "observability": 4, "security": 2, "projects": 6, "revision": 1, "capstone": 4}),
    (100, {"foundation": 10, "core": 20, "advanced": 30, "observability": 8, "security": 4, "projects": 18, "revision": 5, "capstone": 5}),
]


def _normalize_level(level: str) -> str:
    value = str(level or "").strip().lower()
    aliases = {
        "basic": "beginner",
        "foundation": "beginner",
        "foundational": "beginner",
        "intermidate": "intermediate",
        "advance": "advanced",
        "expert": "advanced",
    }
    return aliases.get(value, value or "intermediate")


def _generic_domain(name: str) -> dict:
    technology = str(name or "Training").strip() or "Training"
    return {
        "name": technology,
        "icon": "book",
        "level_map": {
            "foundation": [
                {"topic": f"{technology} Foundations", "subtopics": ["Terminology", "Architecture", "Setup", "Basic workflows"], "tools": [technology], "lab": f"Set up {technology} environment"},
                {"topic": f"{technology} Core Concepts", "subtopics": ["Key components", "Common use cases", "Basic configuration", "Troubleshooting"], "tools": [technology], "lab": "Guided configuration exercise"},
            ],
            "core": [
                {"topic": f"{technology} Implementation", "subtopics": ["Project structure", "Integration points", "Configuration", "Validation"], "tools": [technology], "lab": "Build a practical workflow"},
                {"topic": f"{technology} Real-Time Use Cases", "subtopics": ["Business scenario", "Design", "Implementation", "Review"], "tools": [technology], "lab": "Implement a client-style use case"},
            ],
            "advanced": [
                {"topic": f"Advanced {technology}", "subtopics": ["Optimization", "Security", "Scaling", "Best practices"], "tools": [technology], "lab": "Advanced troubleshooting and optimization"},
            ],
            "capstone": [
                {"topic": f"{technology} Capstone Project", "subtopics": ["Requirements", "Design", "Implementation", "Testing", "Demo"], "tools": [technology], "lab": "End-to-end capstone project"},
            ],
        },
        "jira_practice": {"daily": ["Update sprint board", "Log time", "Move cards"], "weekly": ["Sprint review", "Retrospective"]},
        "certifications": [f"Relevant {technology} certification roadmap"],
    }


def _duration_rules(duration: int) -> dict:
    duration = max(1, min(int(duration or 1), 100))
    for max_days, rules in GROUP_RULES:
        if duration <= max_days:
            scaled = {key: round(value * duration / max_days) for key, value in rules.items()}
            break
    else:
        scaled = deepcopy(GROUP_RULES[-1][1])
    if duration >= 5:
        scaled["capstone"] = max(1, scaled.get("capstone", 0))
    total = sum(scaled.values())
    priority = ["core", "advanced", "foundation", "projects", "observability", "security", "revision", "capstone"]
    while total < duration:
        for key in priority:
            if total >= duration:
                break
            scaled[key] = scaled.get(key, 0) + 1
            total += 1
    while total > duration:
        for key in priority:
            if total <= duration:
                break
            if key == "capstone" and duration >= 5 and scaled.get(key, 0) <= 1:
                continue
            if scaled.get(key, 0) > 0:
                scaled[key] -= 1
                total -= 1
    return scaled


def _cycle(items: list, count: int) -> list:
    if count <= 0:
        return []
    if not items:
        return []
    return [deepcopy(items[index % len(items)]) for index in range(count)]


def _ordered_unique_topics(domain: dict, level: str = "") -> list:
    level_map = domain.get("level_map") or {}
    selected = []
    seen = set()
    normalized_level = _normalize_level(level)
    if normalized_level == "intermediate":
        groups = ("foundation", "core", "advanced", "observability")
    elif normalized_level == "advanced":
        groups = ("foundation", "core", "advanced", "observability", "security", "projects")
    else:
        groups = ("foundation", "core", "advanced", "observability", "security", "projects")
    for group in groups:
        for item in level_map.get(group) or []:
            name = str(item.get("topic") or "").strip().lower()
            if name and name not in seen:
                selected.append(deepcopy(item))
                seen.add(name)
    return selected


def _sample_progressive(items: list, count: int) -> list:
    if count <= 0 or not items:
        return []
    if count >= len(items):
        return deepcopy(items)
    if count >= max(1, int(len(items) * 0.75)):
        return deepcopy(items[:count])
    if count == 1:
        return [deepcopy(items[0])]
    indexes = []
    for i in range(count):
        idx = round(i * (len(items) - 1) / (count - 1))
        if idx not in indexes:
            indexes.append(idx)
    cursor = 0
    while len(indexes) < count and cursor < len(items):
        if cursor not in indexes:
            indexes.append(cursor)
        cursor += 1
    indexes.sort()
    return [deepcopy(items[index]) for index in indexes[:count]]


def _sample_cumulative(items: list, count: int, foundation_anchors: int = 2) -> list:
    """Keep essential early prerequisites, then sample the remaining roadmap."""
    if count <= 0 or not items:
        return []
    if count >= len(items):
        return deepcopy(items)
    anchor_count = min(max(foundation_anchors, count // 3), count, len(items))
    selected = deepcopy(items[:anchor_count])
    remaining = count - anchor_count
    if remaining:
        tail = items[anchor_count:]
        selected.extend(_sample_progressive(tail, remaining))
    return selected[:count]


def _project_day(index: int, domain_name: str) -> dict:
    return {
        "topic": f"Real-Time Project Sprint {index}",
        "subtopics": [
            "Requirement analysis and architecture planning",
            "Implementation sprint with selected tools",
            "Integration, troubleshooting, and review",
            "Demo preparation and documentation",
        ],
        "tools": ["Jira", "Git", domain_name],
        "lab": f"Build project sprint {index} deliverable and present progress",
    }


def _revision_day(index: int) -> dict:
    return {
        "topic": f"Revision, Assessment & Mock Interview {index}",
        "subtopics": ["Concept revision", "Hands-on assessment", "Interview questions", "Feedback and improvement plan"],
        "tools": ["Jira", "Collaboration Tools"],
        "lab": "Mock interview and practical assessment",
    }


def _standardize_compact_day_item(day_item: dict, domain_name: str) -> dict:
    item = {k: v for k, v in day_item.items() if k != "day"}
    if "lab_task" in item and "lab" not in item:
        item["lab"] = item.pop("lab_task")
    if "tools" not in item or not item.get("tools"):
        item["tools"] = [domain_name]
    return item


def _is_foundation_topic(item: dict) -> bool:
    text = " ".join([
        str(item.get("topic") or ""),
        " ".join(str(value) for value in item.get("subtopics") or []),
    ]).lower()
    markers = (" basics", "basic ", "fundamentals", "foundation", "orientation", "introduction", "getting started")
    return any(marker in f" {text}" for marker in markers)


def _select_topics(domain: dict, duration: int, level: str = "") -> list:
    duration = max(1, min(int(duration or 1), 100))
    compact_days = list(domain.get("days") or [])
    if compact_days:
        normalized_level = _normalize_level(level)
        capstones = [day for day in compact_days if "capstone" in str(day.get("topic") or "").lower()]
        curriculum = [day for day in compact_days if day not in capstones]
        slots = duration - 1 if capstones and duration >= 5 else duration
        total = len(curriculum)

        # The source curriculum is already ordered from foundation to production
        # practice. Select a depth band, preserving that order, instead of inventing
        # level-specific titles or filling gaps with synthetic project days.
        if normalized_level == "intermediate":
            start, end = 0, max(int(total * 0.80), slots)
        elif normalized_level == "advanced":
            start, end = 0, total
        else:
            start, end = 0, max(int(total * 0.45), slots)
        level_band = curriculum[start:end]
        if normalized_level == "beginner":
            compact_source = deepcopy(level_band[:min(slots, len(level_band))])
        else:
            compact_source = _sample_cumulative(level_band, min(slots, len(level_band)))
        if capstones and duration >= 5:
            compact_source.append(capstones[-1])
        selected = [_standardize_compact_day_item(day, domain.get("name", "Training")) for day in compact_source[:duration]]
        if len(selected) >= duration:
            return selected[:duration]
        fallback_domain = deepcopy(domain)
        fallback_domain.pop("days", None)
        while len(selected) < duration:
            selected.insert(max(0, len(selected) - 1), _project_day(len(selected) + 1, domain.get("name", "Training")))
        return selected[:duration]

    level_map = domain.get("level_map") or {}
    capstone_source = level_map.get("capstone") or []
    capstone = deepcopy(capstone_source[0]) if capstone_source else {
        "topic": f"{domain.get('name', 'Training')} Capstone Project",
        "subtopics": ["Requirements", "Design", "Implementation", "Testing", "Demo"],
        "tools": [domain.get("name", "Training")],
        "lab": "End-to-end capstone project",
    }
    if duration == 1:
        return [capstone]

    slots_before_capstone = duration - 1
    ordered = _ordered_unique_topics(domain, level)
    selected = _sample_progressive(ordered, min(slots_before_capstone, len(ordered)))

    project_index = 1
    revision_index = 1
    while len(selected) < slots_before_capstone:
        remaining = slots_before_capstone - len(selected)
        if remaining <= 2:
            selected.append(_revision_day(revision_index))
            revision_index += 1
        else:
            selected.append(_project_day(project_index, domain.get("name", "Training")))
            project_index += 1

    selected.append(capstone)
    return selected[:duration]


def _jira_activity(domain: dict, day_number: int, topic_name: str, notes: str = "") -> str:
    jira = domain.get("jira_practice") or {}
    daily = jira.get("daily") or ["Update sprint board", "Log time", "Move cards"]
    weekly = jira.get("weekly") or ["Sprint review", "Retrospective"]
    if day_number % 5 == 0:
        return f"{weekly[(day_number // 5 - 1) % len(weekly)]}; review progress for {topic_name}"
    if "jira" in str(notes or "").lower():
        return f"{daily[(day_number - 1) % len(daily)]}; create stories/subtasks for {topic_name}"
    return daily[(day_number - 1) % len(daily)]


PYTHON_SUBTOPIC_DETAILS = {
    "setup": ["Variables and assignment", "Naming conventions", "Built-in data types", "Indentation and code blocks", "Simple debugging"],
    "basics": ["Comments and docstrings", "Keywords and identifiers", "Naming conventions", "Indentation and code blocks", "Type conversion and simple debugging"],
    "control flow": ["Boolean expressions", "Nested conditions", "range() and iteration", "break, continue and pass", "Function arguments and return values"],
    "data structures": ["Indexing and slicing", "Mutability and copying", "Nested collections", "Iteration patterns", "Choosing the right collection"],
    "object-oriented": ["Constructors and instance state", "Class and static methods", "Composition versus inheritance", "Abstract classes", "Dataclasses and object representation"],
    "file handling": ["Text versus binary files", "Paths and directories", "Encoding considerations", "Logging failures", "Resource cleanup and validation"],
    "modules": ["Import resolution", "Project package structure", "Dependency pinning", "Virtual-environment workflow", "Publishing and reuse conventions"],
    "numpy": ["Array creation and dtypes", "Shape and reshape", "Vectorization", "Aggregation functions", "Handling missing and invalid values"],
    "pandas": ["Series operations", "Index management", "Missing-value treatment", "Aggregation and pivoting", "Data export and validation"],
    "api": ["Request and response models", "Status codes", "Input validation", "Authentication basics", "Error handling and API testing"],
    "fastapi": ["Dependency injection", "Pydantic validation", "Async endpoints", "Middleware", "OpenAPI testing"],
    "django": ["URL routing", "Model relationships", "Forms and validation", "Authentication and permissions", "Testing and deployment structure"],
    "testing": ["Test organization", "Fixtures and parametrization", "Mocking dependencies", "Coverage analysis", "Failure diagnosis"],
    "database": ["Connections and transactions", "Parameterized queries", "Schema mapping", "Indexes and query performance", "Error handling and migrations"],
    "async": ["Coroutines and tasks", "Event-loop behavior", "Concurrency limits", "Timeouts and cancellation", "Async error handling"],
    "capstone": ["Requirement decomposition", "Architecture design", "Incremental implementation", "Automated testing", "Documentation, demonstration and review"],
}


def _subtopic_target(topic_name: str) -> int:
    topic = str(topic_name or "").lower()
    very_large_markers = ("capstone", "project", "end-to-end")
    large_markers = ("architecture", "integration", "deployment", "security", "troubleshooting", "advanced")
    small_markers = ("basic", "fundamental", "foundation", "introduction", "orientation", "setup", "syntax", "variable", "overview")
    if any(marker in topic for marker in very_large_markers):
        return 4
    if any(marker in topic for marker in large_markers):
        return 6
    if any(marker in topic for marker in small_markers):
        return 10
    return 8


def _python_subtopics(topic_name: str, source_subtopics: list, target: int) -> list:
    values = [str(value).strip() for value in source_subtopics if str(value).strip()]
    topic_key = str(topic_name or "").lower()
    additions = next((items for marker, items in PYTHON_SUBTOPIC_DETAILS.items() if marker in topic_key), [
        "Implementation workflow", "Input and output validation", "Common errors and edge cases",
        "Debugging techniques", "Testing and maintainability practices",
    ])
    seen = {value.lower() for value in values}
    for addition in additions:
        if addition.lower() not in seen:
            values.append(addition)
            seen.add(addition.lower())
        if len(values) >= target:
            break
    for addition in ("Worked example", "Guided coding practice", "Review questions"):
        if len(values) >= target:
            break
        if addition.lower() not in seen:
            values.append(addition)
            seen.add(addition.lower())
    return values


def _enrich_daily_subtopics(domain_name: str, topic_name: str, source_subtopics: list) -> list:
    target = _subtopic_target(topic_name)
    if "python" in str(domain_name or "").lower():
        return _python_subtopics(topic_name, source_subtopics, target)
    values = [str(value).strip() for value in source_subtopics if str(value).strip()]
    additions = [
        "Terminology and scope",
        "Key components and responsibilities",
        "Configuration or workflow steps",
        "Implementation approach",
        "Integration considerations",
        "Hands-on use case",
        "Validation and testing",
        "Common mistakes and edge cases",
        "Troubleshooting approach",
        "Industry best practices",
        "Review questions and applied assessment",
    ]
    seen = {value.lower() for value in values}
    for addition in additions:
        if addition.lower() not in seen:
            values.append(addition)
            seen.add(addition.lower())
        if len(values) >= target:
            break
    return values


_GENERIC_LAB_ACTIVITIES = {
    "",
    "guided hands-on exercise",
    "guided hands-on exercise and evidence review",
    "guided lab",
    "guided configuration exercise",
    "practical exercise",
    "build a practical workflow",
    "implement a client-style use case",
    "extended lab",
}


def _is_generic_lab_activity(value: str) -> bool:
    normalized = " ".join(str(value or "").strip().lower().split())
    return normalized in _GENERIC_LAB_ACTIVITIES


def _specific_lab_activity(topic_name: str, tools) -> str:
    if isinstance(tools, (list, tuple, set)):
        tool_text = ", ".join(str(tool).strip() for tool in tools if str(tool).strip())
    else:
        tool_text = str(tools or "the listed tools").strip()
    tool_text = tool_text or "the listed tools"
    return (
        f"Configure, implement, validate, and troubleshoot {topic_name} using {tool_text}; "
        "submit working output, validation evidence, and one resolved failure scenario"
    )


def _day_learning_objectives(topic_name: str, tools) -> list:
    tool_text = ", ".join(tools) if isinstance(tools, list) else str(tools or "the listed tools")
    return [
        f"Explain the design choices and operational purpose of {topic_name}",
        f"Implement {topic_name} using {tool_text}",
        f"Validate the implementation, diagnose a realistic failure, and document the resolution",
        "Relate the deliverable to acceptance criteria, evidence, and Agile/Jira tracking",
    ]


def _day_entry(domain: dict, item: dict, day_number: int, total_days: int, notes: str) -> dict:
    topic_name = item.get("topic") or f"Day {day_number} Topic"
    source_subtopics = _enrich_daily_subtopics(
        str(domain.get("name") or "Training"), topic_name, list(item.get("subtopics") or [])
    )
    subtopics = list(source_subtopics)
    fallback_topics = [
        f"{topic_name} hands-on implementation",
        f"{topic_name} troubleshooting scenarios",
        f"{topic_name} best practices and review",
        f"{topic_name} trainer Q&A and knowledge check",
    ]
    fallback_index = 0
    while len(subtopics) < 8:
        subtopics.append(fallback_topics[fallback_index % len(fallback_topics)])
        fallback_index += 1
    tools = item.get("tools") or [domain.get("name", "Training")]
    candidate_lab = item.get("lab") or item.get("lab_task") or ""
    lab = candidate_lab if not _is_generic_lab_activity(candidate_lab) else _specific_lab_activity(topic_name, tools)
    jira_focus = item.get("jira_focus") or _jira_activity(domain, day_number, topic_name, notes)
    title = f"Day {day_number}: {topic_name}"
    if day_number == total_days and total_days >= 5 and "capstone" not in topic_name.lower():
        title = f"Day {day_number}: Capstone Project + Certification Roadmap"
        topic_name = "Capstone Project + Certification Roadmap"
        lab = "Final project implementation, demo, retrospective, and certification roadmap review"
        jira_focus = "Final sprint review, retrospective, release notes, and stakeholder demo"
    def covered(*indexes: int) -> str:
        selected = [subtopics[index] for index in indexes if index < len(subtopics)]
        return ", ".join(selected) if selected else f"{topic_name} guided practice"

    morning_1 = covered(0, 1, 2)
    morning_2 = covered(3, 4)
    afternoon_1 = covered(5, 6, 7)

    return {
        "day": day_number,
        "title": title,
        "focus_area": topic_name,
        "subtopics": source_subtopics,
        "tools": " + ".join(tools),
        "lab": lab,
        "jira_focus": jira_focus,
        "morning_session": {
            "time": "9:00 AM - 1:00 PM",
            "title": f"{topic_name} - Concepts",
            "topics": [
                {"time": "9:00 - 10:30", "topic": morning_1, "type": "lecture"},
                {"time": "10:30 - 10:45", "topic": "Break", "type": "break"},
                {"time": "10:45 - 12:15", "topic": morning_2, "type": "demo"},
                {"time": "12:15 - 1:00", "topic": f"Knowledge check, use cases, and Q&A for {topic_name}", "type": "qa"},
            ],
        },
        "afternoon_session": {
            "time": "1:00 PM - 5:00 PM",
            "title": f"{topic_name} - Hands-on",
            "topics": [
                {"time": "1:00 - 2:30", "topic": afternoon_1, "type": "lecture"},
                {"time": "2:30 - 2:45", "topic": "Break", "type": "break"},
                {"time": "2:45 - 4:00", "topic": f"Lab: {lab}", "type": "lab"},
                {"time": "4:00 - 5:00", "topic": f"Jira: {jira_focus}", "type": "jira"},
            ],
        },
        "learning_objectives": _day_learning_objectives(topic_name, tools),
        "jira_practice": [
            jira_focus,
            "Create/update Epics, Stories, Tasks, Subtasks, acceptance criteria, and story points",
            "Move tasks across the sprint board and review progress with comments/time logs",
        ],
    }


def _clean_session_topics(session: dict, fallback_focus: str) -> dict:
    session = dict(session or {})
    raw_topics = list(session.get("topics") or [])
    agenda_items = []
    for item in raw_topics:
        if not isinstance(item, dict):
            continue
        topic = str(item.get("topic") or "").strip()
        topic_type = str(item.get("type") or "").strip().lower()
        if not topic:
            continue
        if topic_type == "break" or topic.lower() in {"break", "lunch", "tea break"}:
            continue
        agenda_items.append({"time": item.get("time") or "", "topic": topic, "type": topic_type or "lecture"})

    agenda_cursor = 0
    break_count = 0

    def is_expected_pause(topic: str, slot: str, topic_type: str) -> bool:
        nonlocal break_count
        clean_topic = topic.lower()
        clean_slot = str(slot or "").lower()
        if topic_type != "break" or clean_topic not in {"break", "lunch", "tea break"}:
            return False
        if clean_topic == "lunch":
            allowed = clean_slot.strip().startswith(("12:", "1:")) and break_count < 2
        else:
            allowed = clean_slot.strip().startswith(("10:30", "10:45", "2:15", "2:30", "3:00", "3:15")) and break_count < 1
        if allowed:
            break_count += 1
        return allowed

    def next_agenda(slot: str, topic_type: str) -> dict:
        nonlocal agenda_cursor
        if agenda_cursor < len(agenda_items):
            agenda = agenda_items[agenda_cursor]
            agenda_cursor += 1
            return {**agenda, "time": slot or agenda.get("time") or ""}
        fallback_type = topic_type if topic_type and topic_type != "break" else "lecture"
        return {
            "time": slot or "",
            "topic": f"{fallback_focus} topic discussion, demo, and guided practice",
            "type": fallback_type,
        }

    repaired = []
    for item in raw_topics:
        if not isinstance(item, dict):
            continue
        topic = str(item.get("topic") or "").strip()
        topic_type = str(item.get("type") or "").strip().lower()
        slot = item.get("time") or ""
        if is_expected_pause(topic, slot, topic_type):
            repaired.append({"time": item.get("time") or "", "topic": topic.title(), "type": "break"})
            continue
        repaired.append(next_agenda(slot, topic_type))

    session["topics"] = repaired or [
        {"time": "", "topic": f"{fallback_focus} concepts and agenda walkthrough", "type": "lecture"},
        {"time": "", "topic": f"{fallback_focus} guided demo", "type": "demo"},
        {"time": "", "topic": f"Lab: Apply {fallback_focus} in a practical exercise", "type": "lab"},
    ]
    return session


def _programme_phase(week_number: int, total_weeks: int) -> str:
    if week_number == total_weeks:
        return "Capstone, readiness assessment, and presentation"
    if week_number == 1:
        return "Orientation, foundations, and professional delivery practices"
    if week_number == 2:
        return "Core concepts, tools, and guided troubleshooting"
    if week_number < total_weeks - 1:
        return "Applied implementation, scenarios, and operational practice"
    return "Consolidation, simulation, and capstone preparation"


def _training_start_date(value: str) -> datetime | None:
    raw = str(value or "")
    match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", raw)
    if match:
        return datetime.strptime(match.group(0), "%Y-%m-%d")
    match = re.search(r"\b[A-Za-z]{3,9}\s+\d{1,2},\s*\d{4}\b", raw)
    if match:
        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(match.group(0), fmt)
            except ValueError:
                continue
    match = re.search(r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b", raw)
    if match:
        for fmt in ("%d %B %Y", "%d %b %Y"):
            try:
                return datetime.strptime(match.group(0), fmt)
            except ValueError:
                continue
    for fmt in ("%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y"):
        match = re.search(r"\b\d{1,2}[-/]?(?:[A-Za-z]{3}|\d{1,2})[-/]?\d{4}\b", raw)
        if match:
            try:
                return datetime.strptime(match.group(0), fmt)
            except ValueError:
                continue
    return None


def _business_dates(start: datetime | None, count: int) -> list[str]:
    if not start:
        return ["" for _ in range(count)]
    dates = []
    current = start
    while len(dates) < count:
        # Training runs Monday through Saturday. Sunday is intentionally
        # skipped when allocating the day-wise client schedule.
        if current.weekday() < 6:
            dates.append(current.strftime("%d-%b-%Y"))
        current += timedelta(days=1)
    return dates


def _meaningful_category(day: dict, is_final_day: bool = False) -> str:
    """Derive a client-facing module name instead of the generic Core Learning label."""
    topic = str(day.get("focus_area") or day.get("title") or day.get("topic") or "Training Module")
    tools = str(day.get("tools") or "")
    text = f"{topic} {tools}".lower()
    if is_final_day or "capstone" in text or "final project" in text:
        return "Final Capstone Project"
    category_rules = (
        (("devsecops", "sonarqube", "trivy", "snyk", "security gate"), "DevSecOps and Quality Gates"),
        (("release", "blue-green", "blue green", "canary"), "Release Management and Deployment Strategies"),
        (("agile", "sdlc", "devops orientation", "devops concept"), "DevOps Concepts and Agile Delivery"),
        (("aws", "ec2", "s3", "iam"), "AWS Cloud and DevOps (hands-on)"),
        (("azure", "acr"), "Azure Cloud and DevOps (hands-on)"),
        (("gcp", "google cloud"), "GCP Cloud and DevOps (hands-on)"),
        (("kubernetes", "kubectl", "helm", "aks", "eks", "gke"), "Kubernetes and Container Orchestration (hands-on)"),
        (("docker", "container"), "Containerization Technologies (hands-on)"),
        (("jenkins", "ci/cd", "ci-cd", "pipeline"), "CI/CD Pipeline (hands-on)"),
        (("sre", "observability", "monitoring", "logging", "datadog"), "SRE and Observability"),
        (("linux", "shell", "network", "ssh", "web basics"), "Linux and Infrastructure Foundations (hands-on)"),
        (("git", "source code", "version control"), "Source Code Management"),
        (("ai", "llm", "agent", "langchain", "langgraph"), "AI and DevOps Automation"),
        (("python", "scripting", "automation"), "Programming and Automation Foundations"),
        (("database", "sql"), "Database Technologies (hands-on)"),
        (("frontend", "react", "angular", "javascript"), "Frontend Development (hands-on)"),
        (("backend", "spring", "django", "fastapi", "api"), "Backend Development (hands-on)"),
        (("testing", "selenium", "quality assurance"), "Testing and Quality Assurance (hands-on)"),
    )
    for keywords, category in category_rules:
        if any(keyword in text for keyword in keywords):
            return category
    return topic


def _enrich_programme_pack(toc: dict, audience_level: str = "", training_dates: str = "") -> dict:
    """Add the programme and assessment reasoning used by delivery-ready TOCs."""
    days = toc.get("days") or []
    duration = len(days)
    total_weeks = max(1, (duration + 4) // 5)
    dates = _business_dates(_training_start_date(training_dates), duration)
    audience = audience_level or f"{toc.get('level', 'Intermediate').title()} learners"
    weekly_plan = []
    assessments = []
    for week_index in range(total_weeks):
        start = week_index * 5
        week_days = days[start:start + 5]
        topics = [str(day.get("focus_area") or "Training") for day in week_days]
        week_number = week_index + 1
        outcome = (
            "Demonstrate job readiness through an end-to-end simulation and presentation."
            if week_number == total_weeks
            else f"Apply {toc.get('domain')} concepts in guided scenarios and document outcomes clearly."
        )
        weekly_plan.append({
            "week": week_number,
            "theme": _programme_phase(week_number, total_weeks),
            "key_topics": topics,
            "days": len(week_days),
            "assessment_activity": "Final capstone simulation and readiness assessment" if week_number == total_weeks else "Scenario role-play, weekly knowledge check, and facilitator feedback",
            "outcome": outcome,
        })
        assessments.append({
            "week": f"Week {week_number}",
            "assessment_type": "Capstone Simulation + Final Assessment" if week_number == total_weeks else "Weekly Knowledge Check + Scenario Role-Play",
            "topics_covered": ", ".join(topics),
            "format": "Observed scenario, short knowledge check, and practical evidence" if week_number == total_weeks else "20-question knowledge check plus scenario-based team exercise",
            "pass_threshold": "75% and facilitator rubric satisfactory" if week_number == total_weeks else "70% and facilitator rubric satisfactory",
            "action_if_not_passed": "Individual coaching plan and reassessment" if week_number == total_weeks else "Trainer coaching, targeted practice, and one reassessment",
        })
    for index, day in enumerate(days):
        day["week"] = index // 5 + 1
        day["date"] = dates[index]
        day["category"] = _meaningful_category(day, index == duration - 1)
        if (index + 1) % 5 == 0 and index + 1 < duration:
            day["assessment"] = "Weekly knowledge check and scenario role-play"
        elif index == duration - 1:
            day["assessment"] = "Final capstone simulation, presentation, and readiness assessment"
        else:
            day["assessment"] = "Daily knowledge check and lab evidence"
    toc["programme_philosophy"] = {
        "target_audience": audience,
        "programme_goal": f"Build practical {toc.get('domain')} capability through progressive concepts, guided practice, scenarios, and a final capstone.",
        "design_approach": "Each day pairs foundation concepts with applied work. Weekly scenario practice and evidence-based assessments confirm readiness before progressing.",
        "assessment_strategy": "Daily checks, weekly role-plays, milestone feedback, and a final capstone simulation measure applied competence rather than memorisation.",
    }
    toc["weekly_programme"] = weekly_plan
    toc["assessment_framework"] = assessments
    toc["capstone_plan"] = {
        "approach": "Incremental capstone: learners add one deliverable each week and receive facilitator feedback before the final demonstration.",
        "checkpoints": [f"Week {week['week']}: capstone checkpoint and feedback" for week in weekly_plan[:-1:2]],
        "finale": "Final week: end-to-end scenario, documented deliverable, demonstration, and retrospective.",
    }
    toc["reasoning"] = {
        "curriculum_sequence": "Foundation before implementation; implementation before scenario simulation; simulation before capstone.",
        "assessment_rule": "Every five delivery days end with evidence-based assessment and feedback.",
        "day_design_rule": "Every day contains concept learning, guided demonstration, practical activity, and a measurable outcome.",
    }
    return toc


# Explicit intermediate modules for combined corporate programmes.  Compact
# datasets are deliberately progressive from beginner setup, which is useful
# for foundation batches but wrong when a client asks for intermediate level.
INTERMEDIATE_COMBINED_TRACKS = {
    "devops": [
        ("Source, Build and Artifact Strategy", ["trunk-based vs GitFlow", "semantic versioning", "build lifecycle", "artifact repositories", "branch protection"], ["Git", "GitHub", "Maven", "Nexus"], "Implement a protected pull-request workflow and publish a versioned artifact"),
        ("CI/CD Pipeline Engineering", ["Jenkinsfile design", "pipeline libraries", "test and quality gates", "artifact promotion", "credentials management"], ["Jenkins", "GitHub Actions", "SonarQube"], "Build a tested multi-stage pipeline with gated artifact promotion"),
        ("Container Engineering and Supply Chain", ["multi-stage Dockerfiles", "layer optimization", "registries", "SBOM", "image signing and scanning"], ["Docker", "Trivy", "Syft", "Cosign"], "Build, scan, sign and publish a production container image"),
        ("Kubernetes Application Delivery", ["Deployments and Services", "Ingress", "ConfigMaps and Secrets", "probes", "resource requests and limits"], ["Kubernetes", "kubectl"], "Deploy and troubleshoot a resilient multi-service application"),
        ("Helm, GitOps and Release Strategies", ["Helm templating", "environment values", "Argo CD reconciliation", "blue-green and canary", "rollback"], ["Helm", "Argo CD", "Argo Rollouts"], "Package an application and execute a controlled GitOps release and rollback"),
        ("Infrastructure as Code at Scale", ["Terraform modules", "remote state and locking", "workspace strategy", "policy checks", "plan review"], ["Terraform", "S3", "OPA"], "Provision a reusable environment from reviewed Terraform modules"),
        ("Configuration and Secrets Automation", ["Ansible roles", "idempotency", "inventories", "Vault integration", "configuration drift"], ["Ansible", "HashiCorp Vault"], "Automate secure server configuration and validate idempotency"),
        ("DevSecOps and Policy Gates", ["SAST and SCA", "container scanning", "secret detection", "policy as code", "remediation workflow"], ["SonarQube", "Trivy", "Snyk", "OPA"], "Enforce security gates and remediate a deliberately vulnerable build"),
        ("Observability, SRE and Incident Response", ["SLI and SLO design", "PromQL", "logs and traces", "alert routing", "error budgets and runbooks"], ["Prometheus", "Grafana", "ELK", "OpenTelemetry"], "Diagnose a production incident using metrics, logs and traces"),
        ("Integrated Production Delivery Capstone", ["architecture and backlog", "IaC provisioning", "secure CI/CD", "Kubernetes GitOps release", "observability and rollback drill"], ["GitHub", "Jenkins", "Terraform", "Kubernetes", "Argo CD", "Grafana"], "Deliver, observe and recover an end-to-end application platform"),
    ],
    "aws": [
        ("AWS IAM and Network Design", ["least privilege", "IAM roles", "VPC", "subnets", "security groups"], ["AWS IAM", "VPC"], "Design a secure application network and role model"),
        ("AWS Container Delivery", ["ECR", "ECS/EKS", "ALB", "autoscaling"], ["ECR", "ECS", "EKS"], "Deploy a container service with load balancing"),
        ("AWS CI/CD and IaC", ["CodePipeline", "CodeBuild", "Terraform", "parameter management"], ["AWS CodePipeline", "Terraform"], "Automate an AWS application deployment"),
        ("AWS Monitoring and Cost Control", ["CloudWatch", "logs", "alarms", "tagging", "budgets"], ["CloudWatch", "AWS Budgets"], "Create operational alarms and cost controls"),
    ],
    "azure": [
        ("Azure Identity and Landing Zone", ["Entra ID", "managed identities", "VNets", "NSGs", "Key Vault"], ["Azure Entra ID", "Azure Key Vault"], "Configure secure service identity and secret access"),
        ("Azure DevOps CI/CD", ["YAML pipelines", "service connections", "variable groups", "approvals"], ["Azure DevOps"], "Build a gated multi-stage release pipeline"),
        ("AKS Application Delivery", ["AKS", "ACR", "ingress", "workload identity"], ["AKS", "ACR"], "Deploy and expose a containerized application on AKS"),
        ("Azure Observability", ["Azure Monitor", "Log Analytics", "Application Insights", "alerts"], ["Azure Monitor"], "Instrument an application and create actionable alerts"),
    ],
    "kubernetes": [
        ("Kubernetes Workloads and Networking", ["Deployments", "Services", "Ingress", "ConfigMaps", "Secrets"], ["kubectl", "Kind"], "Deploy a multi-service application with ingress"),
        ("Kubernetes Security and Storage", ["RBAC", "service accounts", "network policies", "PV/PVC"], ["Kubernetes", "OPA"], "Apply least privilege and persistent storage"),
        ("Helm and Production Operations", ["Helm charts", "values", "upgrades", "rollback", "resource limits"], ["Helm", "k9s"], "Package, deploy, and roll back an application"),
    ],
    "python": [
        ("Python API and Data Integration", ["REST clients", "Pydantic models", "JSON validation", "database access"], ["Python", "httpx", "Pydantic"], "Build a typed API integration service"),
        ("Python Automation and Reliability", ["asyncio", "logging", "retries", "pytest", "configuration"], ["Python", "pytest"], "Create a tested automation tool with retry and observability"),
    ],
    "agentic ai": [
        ("Agent Workflows with Tools", ["tool schemas", "structured outputs", "ReAct", "state management"], ["Python", "LangChain", "LangGraph"], "Build a tool-using agent with validated actions"),
        ("Production Agentic RAG", ["retrieval", "evaluation", "guardrails", "tracing", "human approval"], ["LangGraph", "Vector DB", "OpenTelemetry"], "Build and evaluate a grounded enterprise RAG agent"),
    ],
}


# Expert modules for a combined corporate programme.  This is intentionally a
# different path from intermediate: learners design and operate governed,
# resilient platforms rather than repeat implementation-level configuration.
ADVANCED_COMBINED_TRACKS = {
    "devops": [
        ("Platform Engineering and Golden Paths", ["platform product model", "developer experience metrics", "self-service templates", "backstage catalog", "guardrails", "service ownership"], ["Backstage", "GitHub", "Terraform", "Kubernetes"], "Design a self-service golden path that creates a governed service repository, infrastructure baseline and delivery workflow"),
        ("Enterprise CI/CD Architecture", ["pipeline topology", "build isolation", "ephemeral environments", "approval policy", "artifact promotion", "cross-region release"], ["GitHub Actions", "Jenkins", "Argo CD", "Nexus"], "Implement a policy-controlled multi-environment release architecture with traceable promotion and rollback"),
        ("Software Supply Chain Security", ["SLSA levels", "SBOM lifecycle", "provenance", "image signing", "dependency risk", "admission controls"], ["Syft", "Cosign", "Trivy", "Kyverno"], "Create and enforce signed-build provenance, SBOM scanning and Kubernetes admission controls for a release"),
        ("Progressive Delivery and Reliability Engineering", ["error budgets", "canary analysis", "feature flags", "automated rollback", "capacity signals", "release risk"], ["Argo Rollouts", "Prometheus", "Grafana", "Flagger"], "Run a metrics-driven canary deployment that automatically rolls back after an SLO breach"),
        ("Infrastructure Governance and Policy as Code", ["module contract design", "state isolation", "policy testing", "drift detection", "compliance evidence", "change governance"], ["Terraform", "OPA", "Sentinel", "Atlantis"], "Build a governed infrastructure change workflow with policy tests, plan review and drift remediation"),
        ("SRE Incident Command and Chaos Engineering", ["incident command", "runbooks", "game days", "fault injection", "postmortems", "reliability backlog"], ["Chaos Mesh", "PagerDuty", "Grafana", "OpenTelemetry"], "Conduct a controlled failure exercise, coordinate incident response and produce an evidence-based corrective-action backlog"),
        ("DevSecOps Operating Model and Executive Metrics", ["DORA metrics", "risk exceptions", "control ownership", "audit trails", "FinOps signals", "platform roadmap"], ["Jira", "Grafana", "OpenTelemetry", "Cloud Cost Tools"], "Create an executive-ready platform scorecard linking delivery speed, reliability, security controls and cost trends"),
    ],
    "aws": [
        ("AWS Multi-Account Landing Zone Governance", ["AWS Organizations", "SCPs", "Control Tower", "identity federation", "network segmentation", "audit account"], ["AWS Control Tower", "AWS Organizations", "IAM Identity Center", "CloudTrail"], "Design and validate a multi-account landing zone with preventive controls, delegated administration and centralized audit evidence"),
        ("Resilient EKS and Regional Architecture", ["multi-AZ design", "EKS control plane", "node strategies", "private endpoints", "cross-region recovery", "traffic management"], ["Amazon EKS", "Route 53", "AWS Global Accelerator", "AWS Backup"], "Architect and test a failure-tolerant EKS workload with regional recovery, traffic failover and recovery objectives"),
        ("AWS FinOps, Observability and Compliance Automation", ["allocation tags", "cost anomaly detection", "CloudWatch insights", "Config rules", "Security Hub", "evidence automation"], ["AWS Cost Explorer", "AWS Config", "Security Hub", "CloudWatch"], "Implement cost guardrails, compliance alerts and an operational dashboard for a production workload"),
    ],
    "azure": [
        ("Azure Enterprise Landing Zone and Identity Governance", ["management groups", "Azure Policy", "Entra ID", "PIM", "hub-spoke networking", "private endpoints"], ["Azure Landing Zones", "Microsoft Entra ID", "Azure Policy", "Defender for Cloud"], "Design an enterprise landing zone with least-privilege access, policy enforcement and private service connectivity"),
        ("AKS Fleet, GitOps and Workload Identity", ["AKS fleet", "workload identity", "Azure CNI", "private cluster", "GitOps", "upgrade orchestration"], ["AKS", "Azure Arc", "Flux", "Azure Container Registry"], "Operate a governed AKS fleet using GitOps, workload identity, controlled upgrades and image-policy enforcement"),
        ("Azure Reliability, Security and Cost Optimisation", ["Azure Monitor", "Application Insights", "Defender alerts", "Azure Advisor", "budgets", "chaos testing"], ["Azure Monitor", "Application Insights", "Azure Chaos Studio", "Azure Cost Management"], "Build an Azure reliability dashboard and execute a resilience drill with security and cost remediation actions"),
    ],
    "kubernetes": [
        ("Kubernetes Fleet Architecture and Multi-Tenancy", ["cluster tenancy", "namespaces", "resource quotas", "network isolation", "fleet management", "upgrade strategy"], ["Kubernetes", "Cluster API", "Cilium", "Kyverno"], "Design a multi-tenant cluster platform with isolation, fleet lifecycle controls and tenant onboarding standards"),
        ("Kubernetes Security, Service Mesh and Zero Trust", ["Pod Security Standards", "mTLS", "network policies", "external secrets", "OPA policies", "runtime security"], ["Istio", "Cilium", "Kyverno", "Falco"], "Enforce zero-trust service communication, workload policy and runtime detection for a microservices application"),
        ("Kubernetes SRE and Capacity Engineering", ["autoscaling", "HPA/VPA", "KEDA", "SLOs", "distributed tracing", "disaster recovery"], ["KEDA", "Prometheus", "Grafana", "Velero"], "Tune workload scaling from demand signals and validate recovery of a failed namespace using backups and observability evidence"),
    ],
    "python": [
        ("Python Automation Platform Design", ["package architecture", "plugin model", "typed contracts", "async orchestration", "idempotency", "secure configuration"], ["Python", "Pydantic", "httpx", "asyncio"], "Build a reusable asynchronous automation service with typed boundaries, idempotent actions and secure configuration handling"),
        ("Python Reliability, Testing and Performance Engineering", ["contract testing", "property testing", "load profiling", "structured logging", "OpenTelemetry", "failure injection"], ["pytest", "Hypothesis", "Locust", "OpenTelemetry"], "Create a reliability test suite, profile a bottleneck and instrument an automation workflow for production diagnostics"),
    ],
    "agentic ai": [
        ("Production Agent Architecture and Evaluation", ["agent state machines", "tool contracts", "model routing", "offline evaluation", "trace analysis", "human escalation"], ["LangGraph", "OpenAI API", "LangSmith", "OpenTelemetry"], "Build and evaluate a stateful tool-using agent with deterministic tool contracts, trace capture and human escalation"),
        ("LLMOps, Agent Governance and Safe Deployment", ["prompt versioning", "RAG quality", "red teaming", "guardrails", "PII controls", "cost and latency budgets"], ["LangGraph", "OpenTelemetry", "Vector DB", "Policy Engine"], "Deploy a governed agent workflow with evaluation gates, audit evidence, PII protection and production cost/latency controls"),
    ],
}


def _combined_track_key(technology: str) -> str:
    key = str(technology or "").strip().lower()
    aliases = {"agentic_ai": "agentic ai", "agentic": "agentic ai", "ai agents": "agentic ai", "k8s": "kubernetes"}
    return aliases.get(key, key)


def _intermediate_track_items(technology: str, days: int) -> list:
    items = INTERMEDIATE_COMBINED_TRACKS.get(_combined_track_key(technology)) or []
    return [
        {"topic": title, "subtopics": subtopics, "tools": tools, "lab": lab}
        for title, subtopics, tools, lab in items[:max(0, int(days or 0))]
    ]


def _advanced_track_items(technology: str, days: int) -> list:
    items = ADVANCED_COMBINED_TRACKS.get(_combined_track_key(technology)) or []
    return [
        {"topic": title, "subtopics": subtopics, "tools": tools, "lab": lab}
        for title, subtopics, tools, lab in items[:max(0, int(days or 0))]
    ]


def _combined_track_items(technology: str, days: int, level: str, domain_override: dict = None) -> list:
    """Return the delivery-ready track for a technology in a combined programme.

    The compact domain datasets are useful for a single-domain course, but a
    combined programme needs a level-specific integrated path. This prevents
    short allocations from restarting at orientation while omitting advanced
    platform, governance, security and operational work.
    """
    requested_days = max(1, int(days or 1))
    normalized_level = _normalize_level(level)
    if domain_override:
        return _select_topics(deepcopy(domain_override), requested_days, normalized_level)
    if normalized_level == "advanced":
        explicit = _advanced_track_items(technology, requested_days)
    elif normalized_level == "intermediate":
        explicit = _intermediate_track_items(technology, requested_days)
    else:
        explicit = []
    if len(explicit) >= requested_days:
        return explicit[:requested_days]

    domain = deepcopy(domain_override) if domain_override else (get_domain(technology, requested_days) or _generic_domain(technology))
    fallback = _select_topics(domain, requested_days, normalized_level)
    selected = list(explicit)
    known_topics = {str(item.get("topic") or "").strip().lower() for item in selected}
    for item in fallback:
        name = str(item.get("topic") or "").strip().lower()
        if name and name not in known_topics:
            selected.append(item)
            known_topics.add(name)
        if len(selected) >= requested_days:
            break
    while len(selected) < requested_days:
        selected.append(_project_day(len(selected) + 1, technology))
    return selected[:requested_days]


def generate_toc_from_dataset(domain_name: str, duration_days: int, level: str = "intermediate", mode: str = "Online", notes: str = "", domain_override: dict = None, audience_level: str = "", training_dates: str = "") -> dict:
    duration = max(1, min(int(duration_days or 1), 100))
    level = _normalize_level(level)
    domain = deepcopy(domain_override) if domain_override else (get_domain(domain_name, duration) or _generic_domain(domain_name))
    topics = _select_topics(domain, duration, level)
    days = [_day_entry(domain, item, index + 1, duration, notes) for index, item in enumerate(topics)]
    tools = []
    for item in topics:
        for tool in item.get("tools") or []:
            if tool not in tools:
                tools.append(tool)
    certs = domain.get("certifications") or [f"Relevant {domain.get('name')} certification roadmap"]
    overview_table = [
        {"day": day["day"], "focus_area": day["focus_area"], "primary_tools": day["tools"], "jira_focus": day["jira_focus"]}
        for day in days
    ]
    tools_reference = [
        {"category": "Primary Tools", "items": [f"{tool} - used in hands-on labs and project delivery" for tool in tools[:12]]},
        {"category": "Project Management", "items": ["Jira - epics, stories, tasks, sprint board, reports", "Agile ceremonies - planning, review, retrospective"]},
    ]
    normalized_level = str(level or "").strip().lower()
    if normalized_level == "intermediate":
        prerequisites = [
            f"Working knowledge of the core concepts and standard workflows used in {domain.get('name')}",
            f"Prior hands-on exposure to {domain.get('name')} or equivalent project experience",
            "Laptop with administrator access and the required lab software/accounts",
        ]
        learning_outcomes = [
            f"Design and implement production-oriented {domain.get('name')} workflows",
            "Apply reusable patterns, integrations, validation, and quality controls",
            "Troubleshoot realistic implementation and integration failures",
            "Evaluate implementation choices using maintainability, security, and performance criteria",
            "Deliver and defend an end-to-end capstone using measurable evidence",
        ]
    elif normalized_level == "advanced":
        prerequisites = [
            f"Strong production experience with {domain.get('name')} and its core toolchain",
            "Experience designing, troubleshooting, and operating distributed systems",
            "Laptop with administrator access and the required lab software/accounts",
        ]
        learning_outcomes = [
            f"Architect secure, scalable, and resilient {domain.get('name')} solutions",
            "Evaluate design trade-offs using reliability, security, performance, and cost evidence",
            "Diagnose complex failures and design automation and governance controls",
            "Lead architecture reviews and scenario-based technical evaluations",
            "Deliver and defend an enterprise-grade capstone architecture",
        ]
    else:
        prerequisites = [
            "Laptop with required software access",
            "Basic computer and internet usage",
            f"Interest in learning {domain.get('name')} through practical labs",
        ]
        learning_outcomes = [
            f"Understand {domain.get('name')} concepts from foundation to implementation",
            "Complete daily hands-on labs and milestone assignments",
            "Use industry tools in realistic project workflows",
            "Track delivery using Agile/Jira practices",
            "Complete final capstone and certification roadmap review",
        ]
    toc = {
        "title": f"{domain.get('name')} Mastery",
        "subtitle": f"{duration}-Day Intensive Training Program",
        "domain": domain.get("name"),
        "duration_days": duration,
        "level": level,
        "mode": mode,
        "overview": (
            f"This {duration}-day {domain.get('name')} program is generated by the Training TOC Agent using a structured domain curriculum. "
            f"It combines concepts, daily labs, Agile/Jira practice, milestone reviews, and a final capstone for {level} learners in {mode} mode."
        ),
        "overview_table": overview_table,
        "prerequisites": prerequisites,
        "learning_outcomes": learning_outcomes,
        "days": days,
        "tools_software": tools,
        "tools_reference": tools_reference,
        "hiring_preparation": [
            f"Screening Test: 30-45 minute MCQ/practical test covering core {domain.get('name')} concepts and tools",
            "Practical Assignment: hands-on task aligned with the client training requirement",
            "Mock Interview: trainer explains concepts, tools, troubleshooting approach, and delivery examples",
            "Trainer Demo: 15-20 minute sample teaching session with Q&A",
            "Evaluation Checklist: communication, technical depth, lab readiness, real-time examples, and client fit",
        ],
        "assessment_plan": [
            "Daily knowledge check or lab review",
            "Weekly practical assignment for programs longer than 5 days",
            "Mid-program project review for 20+ day programs",
            "Final capstone demo and viva-style technical discussion",
        ],
        "certification_roadmap": certs,
        "certification_guidance": f"Recommended certification path: {', '.join(certs)}.",
        "trainer_notes": "Generated by the Training TOC Agent from the curriculum knowledge base. Gemini may be used only for optional wording polish.",
        "agent": {
            "source": "admin_knowledge_base" if domain_override else "domain_dataset",
            "domain_found": bool(domain_override or get_domain(domain_name, duration)),
            "requested_days": duration,
            "mode": mode,
            "level": level,
        },
    }
    return validate_toc(_enrich_programme_pack(toc, audience_level, training_dates), duration)


def generate_combined_toc_from_datasets(allocations: list[dict], level: str = "intermediate", mode: str = "Online", notes: str = "", audience_level: str = "", training_dates: str = "", domain_overrides: dict = None) -> dict:
    """Create one delivery-ready TOC from explicit per-technology day allocations."""
    level = _normalize_level(level)
    normalized = []
    for allocation in allocations or []:
        name = str(allocation.get("technology") or allocation.get("domain") or "").strip()
        days = int(allocation.get("days") or 0)
        if name and days > 0:
            normalized.append({"technology": name, "days": days})
    if not normalized:
        raise ValueError("At least one technology allocation is required")

    duration = sum(item["days"] for item in normalized)
    names = [item["technology"] for item in normalized]
    combined_name = " + ".join(names)
    domains = []
    combined_days = []
    allocation_reasoning = []
    combined_tools = []
    day_number = 1
    domain_overrides = domain_overrides or {}
    for allocation in normalized:
        override = domain_overrides.get(allocation["technology"].strip().lower())
        domain = deepcopy(override) if override else (get_domain(allocation["technology"], allocation["days"]) or _generic_domain(allocation["technology"]))
        domains.append(domain)
        selected_items = _combined_track_items(allocation["technology"], allocation["days"], level, override)
        if allocation["technology"].lower() != str(domain.get("name") or "").lower():
            for item in selected_items:
                item["topic"] = f"{allocation['technology']}: {item.get('topic') or 'Core Concepts'}"
        selected_topics = [str(item.get("topic") or "Training topic") for item in selected_items]
        allocation_reasoning.append({
            "technology": allocation["technology"],
            "allocated_days": allocation["days"],
            "selection_rule": f"Selected from the {str(level or 'beginner').lower()} depth band while preserving curriculum prerequisite order.",
            "selected_topics": selected_topics,
            "day_range": f"Day {day_number}-Day {day_number + allocation['days'] - 1}",
        })
        for item in selected_items:
            combined_days.append(_day_entry(domain, item, day_number, duration, notes))
            for tool in item.get("tools") or []:
                if tool not in combined_tools:
                    combined_tools.append(tool)
            day_number += 1

    if duration >= 5 and combined_days:
        final_day = combined_days[-1]
        final_day["title"] = f"Day {duration}: Integrated Capstone - {combined_name}"
        final_day["focus_area"] = f"Integrated {combined_name} Capstone"
        final_day["subtopics"] = [
            "Integrate the requested technologies into one delivery workflow",
            "Validate logs, deployment status, alerts and remediation recommendations",
            "Apply secure identity, secrets handling, policy checks and approval gates",
            "Apply LLMOps evaluation gates, agent guardrails, human escalation and audit evidence",
            "Demonstrate rollback, incident triage and recovery decisions",
            "Present the solution architecture, evidence and operational trade-offs",
        ]
        final_day["lab"] = f"Build, deploy, observe, troubleshoot and demonstrate an integrated {combined_name} delivery solution"
        final_day["tools"] = " + ".join(combined_tools or ["Git", "Terraform", "Kubernetes", "Python", "LangGraph"])
        final_day["learning_objectives"] = [
            "Integrate the requested technologies into one production-oriented delivery workflow",
            "Validate deployment, observability, security controls, LLMOps evaluation gates and AI-agent guardrails using evidence",
            "Explain design, rollback and incident-response decisions to stakeholders",
        ]
        final_day["morning_session"]["title"] = "Integrated Capstone - Design and Demonstration"
        final_day["afternoon_session"]["title"] = "Integrated Capstone - Hands-on"
        final_day["afternoon_session"]["topics"][2]["topic"] = f"Lab: {final_day['lab']}"

    tools = list(combined_tools)
    certs = []
    for domain in domains:
        for tool in domain.get("tools") or []:
            if tool not in tools:
                tools.append(tool)
        for certification in domain.get("certifications") or []:
            if certification not in certs:
                certs.append(certification)

    toc = generate_toc_from_dataset(combined_name, duration, level, mode, notes, audience_level=audience_level, training_dates=training_dates)
    toc.update({
        "title": f"{combined_name} Combined Training Programme",
        "subtitle": f"{duration}-Day Integrated Training Program",
        "domain": combined_name,
        "duration_days": duration,
        "days": combined_days,
        "tools_software": tools,
        "certification_roadmap": certs or toc.get("certification_roadmap", []),
        "overview": f"A {duration}-day integrated programme with explicit allocations: " + ", ".join(f"{item['technology']} ({item['days']} days)" for item in normalized) + ". Each day combines explained concepts, guided demonstration, practical lab work, and a knowledge check.",
        "technology_allocations": normalized,
        "curriculum_decision_layer": {
            "allocation_rule": "Use the exact day allocation provided for each requested technology; never borrow days from another technology.",
            "sequence_rule": "Teach prerequisites and foundations before configuration, implementation, troubleshooting, and integrated practice.",
            "day_design_rule": "Each day includes explanation, demonstration, guided hands-on work, lab evidence, and a knowledge check.",
            "integration_rule": "Keep technology modules distinct while connecting them through the final integrated learning outcome.",
            "technology_reasoning": allocation_reasoning,
        },
    })
    if domain_overrides:
        toc.setdefault("agent", {})["source"] = "admin_knowledge_base"
    return validate_toc(_enrich_programme_pack(toc, audience_level, training_dates), duration)


def _as_list(value) -> list:
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value or "").strip() else []


def validate_toc(toc_data: dict, duration_days: int) -> dict:
    toc = deepcopy(toc_data or {})
    expected = max(1, min(int(duration_days or 1), 100))
    days = list(toc.get("days") or [])
    if len(days) > expected:
        days = days[:expected]
    while len(days) < expected:
        day_number = len(days) + 1
        days.append(_day_entry(_generic_domain("Training"), {"topic": "Extended Practice", "subtopics": ["Review", "Implementation", "Lab", "Assessment"], "tools": ["Training"], "lab": "Extended lab"}, day_number, expected, ""))
    for day in days:
        focus = day.get("focus_area") or day.get("title") or "Training"
        lab = str(day.get("lab") or day.get("lab_task") or "").strip()
        raw_tools = day.get("tools") or [toc.get("domain") or "Training"]
        if not lab or _is_generic_lab_activity(lab):
            day["lab"] = _specific_lab_activity(focus, raw_tools)
        subtopics = _as_list(day.get("subtopics"))
        target = _subtopic_target(str(focus))
        if len(subtopics) < target:
            day["subtopics"] = _enrich_daily_subtopics(str(toc.get("domain") or "Training"), str(focus), subtopics)
        if not _as_list(day.get("learning_objectives")):
            day["learning_objectives"] = _day_learning_objectives(str(focus), raw_tools)
        for session_key in ("morning_session", "afternoon_session"):
            day[session_key] = _clean_session_topics(day.get(session_key) or {}, focus)
    toc["days"] = days
    toc["overview_table"] = [
        {"day": day.get("day"), "focus_area": day.get("focus_area"), "primary_tools": day.get("tools"), "jira_focus": day.get("jira_focus")}
        for day in days
    ]
    if not toc.get("hiring_preparation"):
        title = str(toc.get("title") or "Training").replace(" Mastery", "")
        toc["hiring_preparation"] = [
            f"Screening Test: 30-45 minute MCQ/practical test covering core {title} concepts and tools",
            "Practical Assignment: hands-on task aligned with the client training requirement",
            "Mock Interview: trainer explains concepts, tools, troubleshooting approach, and delivery examples",
            "Trainer Demo: 15-20 minute sample teaching session with Q&A",
            "Evaluation Checklist: communication, technical depth, lab readiness, real-time examples, and client fit",
        ]
    if not toc.get("assessment_plan"):
        toc["assessment_plan"] = [
            "Daily knowledge check or lab review",
            "Weekly practical assignment for programs longer than 5 days",
            "Mid-program project review for 20+ day programs",
            "Final capstone demo and viva-style technical discussion",
        ]
    toc["validation"] = {
        "requested_days": expected,
        "generated_days": len(days),
        "valid": len(days) == expected,
        "rules": [
            "Total days exactly match requested duration",
            "Every day has topics, tools, lab, and Jira practice",
            "Final day is reserved for capstone/certification when duration is 5+ days",
        ],
    }
    focus_names = [str(day.get("focus_area") or day.get("title") or "").strip().lower() for day in days]
    quality_passed = (
        len(days) == expected
        and len(focus_names) == len(set(focus_names))
        and all(not _is_generic_lab_activity(day.get("lab")) for day in days)
        and all(len(_as_list(day.get("subtopics"))) >= _subtopic_target(day.get("focus_area") or day.get("title")) for day in days)
        and all(_as_list(day.get("learning_objectives")) for day in days)
    )
    toc["quality"] = {
        "status": "approved" if quality_passed else "requires_regeneration",
        "checks": [
            "Exact requested day count",
            "Unique day-level modules",
            "Detailed subtopics for every day",
            "Specific practical lab for every day",
            "Measurable learning objectives for every day",
        ],
    }
    return toc
