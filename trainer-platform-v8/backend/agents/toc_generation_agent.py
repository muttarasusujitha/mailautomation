"""Deterministic Training TOC Agent.

The app controls curriculum structure here. Gemini may polish text later, but
it should not decide topic order, day count, labs, or capstone placement.
"""

from copy import deepcopy

from agents.toc_domain_dataset import get_domain


GROUP_RULES = [
    (5, {"foundation": 2, "core": 2, "advanced": 0, "observability": 0, "security": 0, "projects": 0, "revision": 0, "capstone": 1}),
    (10, {"foundation": 2, "core": 4, "advanced": 3, "observability": 0, "security": 0, "projects": 0, "revision": 0, "capstone": 1}),
    (20, {"foundation": 3, "core": 6, "advanced": 6, "observability": 1, "security": 1, "projects": 1, "revision": 0, "capstone": 2}),
    (30, {"foundation": 4, "core": 8, "advanced": 9, "observability": 2, "security": 1, "projects": 3, "revision": 1, "capstone": 2}),
    (50, {"foundation": 6, "core": 12, "advanced": 15, "observability": 4, "security": 2, "projects": 6, "revision": 1, "capstone": 4}),
    (100, {"foundation": 10, "core": 20, "advanced": 30, "observability": 8, "security": 4, "projects": 18, "revision": 5, "capstone": 5}),
]


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


def _ordered_unique_topics(domain: dict) -> list:
    level_map = domain.get("level_map") or {}
    selected = []
    seen = set()
    for group in ("foundation", "core", "advanced", "observability", "security", "projects"):
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


def _select_topics(domain: dict, duration: int) -> list:
    duration = max(1, min(int(duration or 1), 100))
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
    ordered = _ordered_unique_topics(domain)
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


def _day_entry(domain: dict, item: dict, day_number: int, total_days: int, notes: str) -> dict:
    topic_name = item.get("topic") or f"Day {day_number} Topic"
    subtopics = list(item.get("subtopics") or [])
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
    lab = item.get("lab") or f"Lab: apply {topic_name} in a practical exercise"
    jira_focus = _jira_activity(domain, day_number, topic_name, notes)
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
        "tools": " + ".join(tools),
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
        "learning_objectives": [
            f"Understand {topic_name} concepts and terminology",
            f"Use {', '.join(tools)} to complete guided exercises",
            f"Apply {topic_name} in a real-world delivery scenario",
            "Connect the technical work to Agile/Jira delivery tracking",
        ],
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


def generate_toc_from_dataset(domain_name: str, duration_days: int, level: str = "intermediate", mode: str = "Online", notes: str = "", domain_override: dict = None) -> dict:
    duration = max(1, min(int(duration_days or 1), 100))
    domain = deepcopy(domain_override) if domain_override else (get_domain(domain_name) or _generic_domain(domain_name))
    topics = _select_topics(domain, duration)
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
    return {
        "title": f"{domain.get('name')} Mastery",
        "subtitle": f"{duration}-Day Intensive Training Program",
        "overview": (
            f"This {duration}-day {domain.get('name')} program is generated by the Training TOC Agent using a structured domain curriculum. "
            f"It combines concepts, daily labs, Agile/Jira practice, milestone reviews, and a final capstone for {level} learners in {mode} mode."
        ),
        "overview_table": overview_table,
        "prerequisites": [
            "Laptop with required software access",
            "Basic computer and internet usage",
            f"Interest in learning {domain.get('name')} through practical labs",
        ],
        "learning_outcomes": [
            f"Understand {domain.get('name')} concepts from foundation to implementation",
            "Complete daily hands-on labs and milestone assignments",
            "Use industry tools in realistic project workflows",
            "Track delivery using Agile/Jira practices",
            "Complete final capstone and certification roadmap review",
        ],
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
            "domain_found": bool(domain_override or get_domain(domain_name)),
            "requested_days": duration,
            "mode": mode,
            "level": level,
        },
    }


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
    return toc
