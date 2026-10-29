"""Build a renderer-compatible program payload from a master topic bank.

build_program.py
-----------------
Reads ONE master file (master_topic_banks.json) containing topic banks for
ALL domains, picks the requested domain, and slices its unlimited topic pool
down to the requested number of days -- outputting the EXACT payload shape
your renderer expects.

Usage:
    python build_program.py master_topic_banks.json DevOps 10   > devops_10day.json
    python build_program.py master_topic_banks.json Python 5    > python_5day.json
    python build_program.py master_topic_banks.json "Full Stack Development" 20 > fullstack_20day.json

List available domains:
    python build_program.py master_topic_banks.json --list
"""

import json
import sys

JIRA_POOL = [
    "Update sprint board",
    "Log time on stories",
    "Move cards to In Progress/Done",
    "Add comments with build links",
    "Sprint planning; review progress for {topic}",
]
CAPSTONE_JIRA = "Final sprint review, retrospective, release notes, and stakeholder demo"
LEVEL_ORDER = ["foundation", "intermediate", "advanced", "expert"]

DOMAIN_TOPIC_ORDER = {
    "DevOps": [
        "Linux Basics",
        "Networking Basics",
        "Docker Basics",
        "Jenkins CI/CD Basics",
        "Terraform IaC Basics",
        "Kubernetes Fundamentals",
        "AWS Core Services",
        "Logging - ELK Stack",
        "DevSecOps",
    ],
}

TOPIC_TITLE_OVERRIDES = {
    "Jenkins CI/CD Basics": "Jenkins CI/CD",
    "Terraform IaC Basics": "Terraform IaC",
    "AWS Core Services": "AWS Core",
    "Logging - ELK Stack": "ELK Stack",
}


def _normalize_topic_title(title):
    if not isinstance(title, str):
        return title
    return TOPIC_TITLE_OVERRIDES.get(title, title)


def select_topics(bank, requested_days, domain=None):
    """
    Build the topic selection list for a program.
    Uses a domain-specific preferred ordering when available, otherwise
    falls back to level-based selection.
    """
    slots = max(requested_days - 1, 1)
    if domain in DOMAIN_TOPIC_ORDER:
        ordered_names = DOMAIN_TOPIC_ORDER[domain]
        selected = []
        for name in ordered_names:
            if len(selected) >= slots:
                break
            for t in bank:
                if t.get("topic") == name:
                    selected.append(t)
                    break
        for t in bank:
            if len(selected) >= slots:
                break
            if t not in selected:
                selected.append(t)
        return selected[:slots]

    by_level = {lvl: [t for t in bank if t.get("level", "foundation") == lvl] for lvl in LEVEL_ORDER}

    selected = []
    for lvl in LEVEL_ORDER:
        if len(selected) >= slots:
            break
        pool = by_level.get(lvl, [])
        needed = slots - len(selected)
        selected.extend(pool[:needed])

    return selected[:slots]


def _covered(subtopics, *indexes):
    selected = [subtopics[index] for index in indexes if index < len(subtopics)]
    return ", ".join(selected) if selected else "Guided practice and concept review"


def _afternoon_lecture(subtopics, topic_name):
    remaining = [subtopics[index] for index in range(5, 8) if index < len(subtopics)]
    if remaining:
        return ", ".join(remaining)
    return f"{topic_name} hands-on implementation, {topic_name} troubleshooting scenarios, {topic_name} best practices and review"


def _build_day_entry(day_number, topic_name, tools, jira, subtopics, lab_task):
    morning_1 = _covered(subtopics, 0, 1, 2)
    morning_2 = _covered(subtopics, 3, 4)
    afternoon_1 = _afternoon_lecture(subtopics, topic_name)

    return {
        "day": day_number,
        "topic": topic_name,
        "tools": tools,
        "jira_focus": jira,
        "subtopics": subtopics,
        "lab_task": lab_task,
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
                {"time": "2:45 - 4:00", "topic": f"Lab: {lab_task}", "type": "lab"},
                {"time": "4:00 - 5:00", "topic": f"Jira: {jira}", "type": "jira"},
            ],
        },
        "learning_objectives": [
            f"Understand {topic_name} concepts and terminology",
            f"Use {', '.join(tools)} to complete guided exercises" if tools else f"Use {topic_name} to complete guided exercises",
            f"Apply {topic_name} in a real-world delivery scenario",
            "Connect the technical work to Agile/Jira delivery tracking",
        ],
        "jira_practice": [
            jira,
            "Create/update Epics, Stories, Tasks, Subtasks, acceptance criteria, and story points",
            "Move tasks across the sprint board and review progress with comments/time logs",
        ],
    }


def build_days(bank, requested_days, domain):
    chosen = select_topics(bank, requested_days, domain)
    days = []

    for i, t in enumerate(chosen, start=1):
        topic_name = _normalize_topic_title(t["topic"])
        jira = JIRA_POOL[(i - 1) % len(JIRA_POOL)].format(topic=topic_name)
        days.append(_build_day_entry(
            i,
            topic_name,
            t.get("tools", []),
            jira,
            t.get("subtopics", []),
            t.get("lab_task", f"Hands-on exercise applying {topic_name} concepts"),
        ))

    days.append(_build_day_entry(
        requested_days,
        "Capstone Project + Certification Roadmap",
        [f"All {domain} Tools"],
        CAPSTONE_JIRA,
        ["Requirements", "End-to-end Implementation", "Review & Demo", "Certification Planning"],
        "Final project implementation, demo, retrospective, and certification roadmap review",
    ))

    return days


def main():
    if len(sys.argv) < 2:
        print("Usage: python build_program.py master_topic_banks.json <Domain> <duration_days>", file=sys.stderr)
        sys.exit(1)

    master_path = sys.argv[1]
    with open(master_path) as f:
        master = json.load(f)

    if len(sys.argv) == 3 and sys.argv[2] == "--list":
        for d in master.get("domains", {}):
            print(d)
        return

    if len(sys.argv) != 4:
        print("Usage: python build_program.py master_topic_banks.json <Domain> <duration_days>", file=sys.stderr)
        print("       python build_program.py master_topic_banks.json --list", file=sys.stderr)
        sys.exit(1)

    domain = sys.argv[2]
    duration_days = int(sys.argv[3])

    if domain not in master.get("domains", {}):
        print(f"Domain '{domain}' not found. Available domains:", file=sys.stderr)
        for d in master.get("domains", {}):
            print(" -", d, file=sys.stderr)
        sys.exit(1)

    bank = master["domains"][domain]
    days = build_days(bank, duration_days, domain)

    payload = {
        "title": f"{domain} Mastery",
        "program_title": f"{domain} Mastery",
        "subtitle": f"{duration_days}-Day Intensive Training Program",
        "domain": domain,
        "duration_days": duration_days,
        "mode": "Online",
        "trainer_name": "Vikram Chauhan",
        "overview": (
            f"This {duration_days}-day {domain} program is generated by the Training TOC Agent "
            f"using a structured domain curriculum. It combines concepts, daily labs, Agile/Jira "
            f"practice, milestone reviews, and a final capstone for Intermediate learners in Online mode."
        ),
        "days": days,
    }

    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
