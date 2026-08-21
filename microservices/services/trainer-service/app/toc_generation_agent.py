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


def _standardize_compact_day_item(day_item: dict, domain_name: str) -> dict:
    item = {k: v for k, v in day_item.items() if k != "day"}
    if "lab_task" in item and "lab" not in item:
        item["lab"] = item.pop("lab_task")
    if "tools" not in item or not item.get("tools"):
        item["tools"] = [domain_name]
    return item


def _select_topics(domain: dict, duration: int) -> list:
    duration = max(1, min(int(duration or 1), 100))
    compact_days = list(domain.get("days") or [])
    if compact_days:
        compact_source = compact_days
        if len(compact_days) > duration:
            compact_source = _sample_progressive(compact_days, duration)
        selected = [_standardize_compact_day_item(day, domain.get("name", "Training")) for day in compact_source[:duration]]
        if len(selected) >= duration:
            return selected[:duration]
        fallback_domain = deepcopy(domain)
        fallback_domain.pop("days", None)
        selected.extend(_select_topics(fallback_domain, duration - len(selected)))
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
    source_subtopics = list(item.get("subtopics") or [])
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
    lab = item.get("lab") or item.get("lab_task") or f"Lab: apply {topic_name} in a practical exercise"
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
        if current.weekday() < 5:
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


def generate_toc_from_dataset(domain_name: str, duration_days: int, level: str = "intermediate", mode: str = "Online", notes: str = "", domain_override: dict = None, audience_level: str = "", training_dates: str = "") -> dict:
    duration = max(1, min(int(duration_days or 1), 100))
    domain = deepcopy(domain_override) if domain_override else (get_domain(domain_name, duration) or _generic_domain(domain_name))
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
            "domain_found": bool(domain_override or get_domain(domain_name, duration)),
            "requested_days": duration,
            "mode": mode,
            "level": level,
        },
    }
    return _enrich_programme_pack(toc, audience_level, training_dates)


def generate_combined_toc_from_datasets(allocations: list[dict], level: str = "intermediate", mode: str = "Online", notes: str = "", audience_level: str = "", training_dates: str = "") -> dict:
    """Create one delivery-ready TOC from explicit per-technology day allocations."""
    normalized = []
    for allocation in allocations or []:
        name = str(allocation.get("technology") or allocation.get("domain") or "").strip()
        days = int(allocation.get("days") or 0)
        if name and days > 0:
            normalized.append({"technology": name, "days": days})
    if not normalized:
        raise ValueError("At least one technology allocation is required")

    duration = sum(item["days"] for item in normalized)
    domains = []
    combined_days = []
    allocation_reasoning = []
    day_number = 1
    for allocation in normalized:
        domain = get_domain(allocation["technology"], allocation["days"]) or _generic_domain(allocation["technology"])
        domains.append(domain)
        source_days = list(domain.get("days") or [])
        # In an allocated multi-technology program, teach each module from its
        # beginning. Sampling across a full course can otherwise pull a capstone
        # into a short two or three-day allocation.
        if source_days and len(source_days) >= allocation["days"]:
            selected_items = [_standardize_compact_day_item(item, domain.get("name", allocation["technology"])) for item in source_days[:allocation["days"]]]
        else:
            selected_items = _select_topics(domain, allocation["days"])
        if allocation["technology"].lower() != str(domain.get("name") or "").lower():
            for item in selected_items:
                item["topic"] = f"{allocation['technology']}: {item.get('topic') or 'Core Concepts'}"
        selected_topics = [str(item.get("topic") or "Training topic") for item in selected_items]
        allocation_reasoning.append({
            "technology": allocation["technology"],
            "allocated_days": allocation["days"],
            "selection_rule": "Selected in progressive curriculum order: foundations and setup before core implementation, then applied practice.",
            "selected_topics": selected_topics,
            "day_range": f"Day {day_number}-Day {day_number + allocation['days'] - 1}",
        })
        for item in selected_items:
            combined_days.append(_day_entry(domain, item, day_number, duration, notes))
            day_number += 1

    if duration >= 5 and combined_days:
        final_day = combined_days[-1]
        final_day["title"] = f"Day {duration}: Integrated Capstone - {combined_name if 'combined_name' in locals() else 'Combined Technologies'}"
        final_day["focus_area"] = "Integrated Cloud, DevOps, Python and Agentic AI Capstone"
        final_day["subtopics"] = [
            "Integrate cloud deployment, CI/CD automation, Python scripting and AI agent workflow",
            "Validate logs, deployment status, alerts and remediation recommendations",
            "Demonstrate the solution and explain operational decisions",
        ]
        final_day["morning_session"]["title"] = "Integrated Capstone - Design and Demonstration"
        final_day["afternoon_session"]["title"] = "Integrated Capstone - Hands-on"
        final_day["afternoon_session"]["topics"][2]["topic"] = "Lab: Build and demonstrate the integrated automation and AI-agent solution"

    names = [item["technology"] for item in normalized]
    combined_name = " + ".join(names)
    tools = []
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
    return _enrich_programme_pack(toc, audience_level, training_dates)


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
