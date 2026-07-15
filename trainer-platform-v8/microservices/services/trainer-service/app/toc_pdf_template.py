"""Shared HTML template for training TOC PDF exports."""

from html import escape
import re
from typing import Any, Dict, Iterable, List


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return " + ".join(_text(item) for item in value if _text(item))
    return str(value).strip()


def _html(value: Any) -> str:
    return escape(_text(value), quote=True)


def _list_items(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    return [value]


def _domain_from_toc(toc: Dict[str, Any], title: str) -> str:
    direct = _text(
        toc.get("technology")
        or toc.get("domain")
        or toc.get("training_domain")
        or toc.get("program_domain")
    )
    if direct:
        return direct
    return re.sub(r"\s+Mastery\s*$", "", title, flags=re.IGNORECASE).strip() or "Training"


def _duration_from_toc(toc: Dict[str, Any]) -> str:
    agent = toc.get("agent") or {}
    duration = (
        toc.get("duration_days")
        or toc.get("duration")
        or toc.get("days_count")
        or agent.get("requested_days")
    )
    if duration in (None, ""):
        day_count = len(toc.get("days") or [])
        duration = day_count or ""
    if duration in (None, ""):
        return ""
    try:
        number = float(duration)
        if number.is_integer():
            duration = int(number)
    except (TypeError, ValueError):
        pass
    return f"{duration} day(s)"


def _mode_from_toc(toc: Dict[str, Any]) -> str:
    agent = toc.get("agent") or {}
    return _text(toc.get("mode") or toc.get("delivery_mode") or agent.get("mode"))


def _trainer_from_toc(toc: Dict[str, Any]) -> str:
    return _text(toc.get("trainer_name") or toc.get("trainer") or toc.get("facilitator"))


def _clean_day_topic(day: Dict[str, Any]) -> str:
    raw = _text(day.get("title") or day.get("topic") or day.get("focus_area"))
    day_number = _text(day.get("day"))
    if day_number:
        raw = re.sub(rf"^\s*day\s+{re.escape(day_number)}\s*:\s*", "", raw, flags=re.IGNORECASE)
    else:
        raw = re.sub(r"^\s*day\s+\d+\s*:\s*", "", raw, flags=re.IGNORECASE)
    return raw or "Training Topic"


def _tools_text(value: Any) -> str:
    return _text(value)


def _line_list(items: Iterable[Any]) -> str:
    lines = []
    for item in items:
        text = _text(item)
        if text:
            lines.append(f'<div class="list-line">- {_html(text)}</div>')
    return "\n".join(lines)


def _render_section(title: str, lines: Iterable[Any]) -> str:
    body = _line_list(lines)
    if not body:
        return ""
    return f"""
    <section class="section">
        <h2>{_html(title)}</h2>
        {body}
    </section>
"""


def _render_roadmap(toc: Dict[str, Any]) -> str:
    days = _list_items(toc.get("days"))
    if not days:
        rows = []
        for row in _list_items(toc.get("overview_table")):
            if not isinstance(row, dict):
                continue
            parts = [
                f"Day {_text(row.get('day'))}: {_text(row.get('focus_area') or row.get('topic'))}",
                f"Tools: {_tools_text(row.get('primary_tools') or row.get('tools'))}",
                f"Jira: {_text(row.get('jira_focus'))}",
            ]
            rows.append(" | ".join(part for part in parts if part and not part.endswith(": ")))
        if not rows:
            return ""
        body = "\n".join(f'<div class="roadmap-line">{_html(row)}</div>' for row in rows)
        return f"""
    <section class="section">
        <h2>Program Roadmap</h2>
        {body}
    </section>
"""

    rows = []
    for day in days:
        if not isinstance(day, dict):
            continue
        day_number = _text(day.get("day"))
        topic = _clean_day_topic(day)
        tools = _tools_text(day.get("tools") or day.get("primary_tools"))
        jira = _text(day.get("jira_focus"))
        parts = [f"Day {day_number}: {topic}" if day_number else topic]
        if tools:
            parts.append(f"Tools: {tools}")
        if jira:
            parts.append(f"Jira: {jira}")
        rows.append(" | ".join(parts))
    if not rows:
        return ""
    body = "\n".join(f'<div class="roadmap-line">{_html(row)}</div>' for row in rows)
    return f"""
    <section class="section">
        <h2>Program Roadmap</h2>
        {body}
    </section>
"""


def _render_session(session: Dict[str, Any], fallback_title: str) -> str:
    if not isinstance(session, dict) or not session:
        return ""
    title = _text(session.get("title") or fallback_title)
    time_slot = _text(session.get("time"))
    if title and not title.lower().startswith(fallback_title.lower()):
        heading = f"{fallback_title}: {title}"
    else:
        heading = title or fallback_title
    if time_slot:
        heading = f"{heading} ({time_slot})"
    lines = []
    for topic in _list_items(session.get("topics")):
        if isinstance(topic, dict):
            slot = _text(topic.get("time"))
            topic_text = _text(topic.get("topic"))
            topic_type = _text(topic.get("type"))
            parts = [slot, topic_text]
            line = " - ".join(part for part in parts if part)
            if topic_type:
                line = f"{line} [{topic_type}]" if line else f"[{topic_type}]"
        else:
            line = _text(topic)
        if line:
            lines.append(f'<div class="session-line">{_html(line)}</div>')
    body = "\n".join(lines)
    return f"""
        <h3>{_html(heading)}</h3>
        {body}
"""


def _render_day(day: Dict[str, Any]) -> str:
    day_number = _text(day.get("day"))
    topic = _clean_day_topic(day)
    tools = _tools_text(day.get("tools") or day.get("primary_tools"))
    jira = _text(day.get("jira_focus"))
    meta_parts = []
    if tools:
        meta_parts.append(f"Tools: {tools}")
    if jira:
        meta_parts.append(f"Jira Focus: {jira}")

    def build_default_session(title: str, topics: list[str], is_morning: bool) -> Dict[str, Any]:
        topics = [str(item) for item in topics if item]
        if is_morning:
            lecture_topics = topics[:3]
            demo_topics = topics[3:5]
            lecture_text = ", ".join(lecture_topics) if lecture_topics else f"{topic} concepts review"
            demo_text = ", ".join(demo_topics) if demo_topics else f"{topic} practical walkthrough"
            return {
                "time": "9:00 AM - 1:00 PM",
                "title": title,
                "topics": [
                    {"time": "9:00 - 10:30", "topic": lecture_text, "type": "lecture"},
                    {"time": "10:30 - 10:45", "topic": "Break", "type": "break"},
                    {"time": "10:45 - 12:15", "topic": demo_text, "type": "demo"},
                    {"time": "12:15 - 1:00", "topic": f"Knowledge check, use cases, and Q&A for {topic}", "type": "qa"},
                ],
            }
        afternoon_topics = topics[:3]
        lecture_text = ", ".join(afternoon_topics) if afternoon_topics else f"{topic} hands-on implementation"
        lab_text = day.get("lab_task") or day.get("lab") or f"Apply {topic} in a practical exercise"
        return {
            "time": "1:00 PM - 5:00 PM",
            "title": title,
            "topics": [
                {"time": "1:00 - 2:30", "topic": lecture_text, "type": "lecture"},
                {"time": "2:30 - 2:45", "topic": "Break", "type": "break"},
                {"time": "2:45 - 4:00", "topic": f"Lab: {lab_text}", "type": "lab"},
                {"time": "4:00 - 5:00", "topic": f"Jira: {jira or 'Update sprint board'}", "type": "jira"},
            ],
        }

    morning = day.get("morning_session") or {}
    afternoon = day.get("afternoon_session") or {}
    if not morning and not afternoon and day.get("subtopics"):
        subtopics = [_text(item) for item in _list_items(day.get("subtopics")) if _text(item)]
        morning_topics = subtopics[:5]
        afternoon_topics = subtopics[5:8]
        morning = build_default_session(f"{topic} - Concepts", morning_topics, True)
        afternoon = build_default_session(f"{topic} - Hands-on", afternoon_topics, False)

    if not morning:
        morning = {"title": f"{topic} - Concepts", "time": "9:00 AM - 1:00 PM", "topics": []}
    if not afternoon:
        afternoon = {"title": f"{topic} - Hands-on", "time": "1:00 PM - 5:00 PM", "topics": []}

    lab = day.get("lab_task") or day.get("lab")
    lab_section = _render_section("Lab Task", [lab]) if lab else ""

    learning_objectives = _list_items(day.get("learning_objectives"))
    if not learning_objectives and topic:
        learning_objectives = [
            f"Understand {topic} concepts and terminology",
            f"Use {tools or topic} to complete guided exercises",
            f"Apply {topic} in a real-world delivery scenario",
            "Connect the technical work to Agile/Jira delivery tracking",
        ]
    objectives = _render_section("Learning Objectives", learning_objectives)

    jira_practice_items = _list_items(day.get("jira_practice"))
    if not jira_practice_items:
        jira_practice_items = [
            jira or "Update sprint board",
            "Create/update Epics, Stories, Tasks, Subtasks, acceptance criteria, and story points",
            "Move tasks across the sprint board and review progress with comments/time logs",
        ]
    jira_practice = _render_section("Jira Practice", jira_practice_items)

    return f"""
    <section class="day-section">
        <h2 class="day-title">Day {_html(day_number)}: {_html(topic)}</h2>
        {f'<div class="day-meta">{_html(" | ".join(meta_parts))}</div>' if meta_parts else ''}
        {_render_session(morning, "Morning Session")}
        {_render_session(afternoon, "Afternoon Session")}
        {lab_section}
        {objectives}
        {jira_practice}
    </section>
"""


def _render_tools_reference(toc: Dict[str, Any]) -> str:
    blocks = []
    for block in _list_items(toc.get("tools_reference")):
        if not isinstance(block, dict):
            continue
        title = _text(block.get("category") or block.get("title"))
        items = _list_items(block.get("items"))
        body = _line_list(items)
        if title and body:
            blocks.append(f"""
    <section class="section">
        <h2>{_html(title)}</h2>
        {body}
    </section>
""")
    return "\n".join(blocks)


def build_toc_html(toc_data: Dict[str, Any]) -> str:
    """Build sample-style TOC HTML used by all trainer TOC PDF paths."""
    toc = dict(toc_data or {})
    title = _text(toc.get("title") or toc.get("program_title") or "Training Programme")
    default_subtitle = f"{_duration_from_toc(toc).replace(' day(s)','')}-Day Intensive Training Program"
    subtitle = _text(toc.get("subtitle") or default_subtitle)
    if subtitle.strip().lower() == "training program":
        subtitle = default_subtitle
    domain = _domain_from_toc(toc, title)
    duration = _duration_from_toc(toc)
    mode = _mode_from_toc(toc)
    trainer_name = _trainer_from_toc(toc)
    overview = _text(toc.get("overview"))
    if not overview:
        overview = (
            f"This {duration} {domain} program is generated by the Training TOC Agent using a structured domain curriculum. "
            "It combines concepts, daily labs, Agile/Jira practice, milestone reviews, and a final capstone for "
            f"{_text(toc.get('level') or 'Intermediate')} learners in {mode or 'Online'} mode."
        )

    metadata = [f"Technology: {domain}"]
    if duration:
        metadata.append(f"Duration: {duration}")
    if mode:
        metadata.append(f"Mode: {mode}")
    if trainer_name:
        metadata.append(f"Trainer: {trainer_name}")

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        @page {{ size: A4; margin: 42pt; }}
        * {{ box-sizing: border-box; }}
        body {{
            margin: 0;
            font-family: Arial, Helvetica, sans-serif;
            color: #111827;
            background: #ffffff;
            font-size: 12px;
            line-height: 1.45;
        }}
        .brand {{
            color: #0b57ff;
            font-size: 12px;
            margin: 0 0 24px;
        }}
        h1 {{
            color: #111827;
            font-size: 28px;
            line-height: 1.1;
            font-weight: 400;
            margin: 0 0 4px;
        }}
        .subtitle {{
            color: #475569;
            font-size: 16px;
            margin: 0 0 24px;
        }}
        .metadata {{
            color: #111827;
            font-size: 12px;
            margin: 0 0 24px;
        }}
        .section {{
            margin: 0 0 18px;
            page-break-inside: auto;
        }}
        h2 {{
            color: #111827;
            font-size: 19px;
            line-height: 1.2;
            font-weight: 400;
            margin: 0 0 8px;
        }}
        .section p {{
            margin: 0;
            max-width: 100%;
        }}
        .roadmap-row,
        .roadmap-line,
        .list-line,
        .session-line {{
            margin: 0 0 10px;
            overflow-wrap: anywhere;
        }}
        .roadmap-line {{
            margin-bottom: 12px;
        }}
        .list-line {{
            margin-bottom: 9px;
        }}
        .day-section {{
            margin: 22px 0 20px;
            page-break-inside: auto;
        }}
        .day-title {{
            color: #0b57ff;
            font-size: 20px;
            line-height: 1.2;
            font-weight: 400;
            margin: 0 0 8px;
        }}
        .day-meta {{
            color: #111827;
            font-size: 12px;
            margin: 0 0 16px;
        }}
        h3 {{
            color: #111827;
            font-size: 16px;
            line-height: 1.2;
            font-weight: 400;
            margin: 18px 0 10px;
        }}
        .day-section .section {{
            margin-top: 18px;
            margin-bottom: 18px;
        }}
        .day-section .section h2 {{
            font-size: 19px;
            margin-bottom: 8px;
        }}
    </style>
</head>
<body>
    <div class="brand">Clahan Technologies | TrainerSync</div>
    <h1>{_html(title)}</h1>
    <div class="subtitle">{_html(subtitle)}</div>
    <div class="metadata">{_html(" | ".join(metadata))}</div>
"""

    if overview:
        html += f"""
    <section class="section">
        <h2>Program Overview</h2>
        <p>{_html(overview)}</p>
    </section>
"""

    html += _render_roadmap(toc)
    html += _render_section("Prerequisites", _list_items(toc.get("prerequisites")))
    html += _render_section("Learning Outcomes", _list_items(toc.get("learning_outcomes")))

    for day in _list_items(toc.get("days")):
        if isinstance(day, dict):
            html += _render_day(day)

    html += _render_section("Tools & Software", _list_items(toc.get("tools_software")))
    html += _render_section("Hiring & Test Preparation", _list_items(toc.get("hiring_preparation")))
    html += _render_section("Assessment Plan", _list_items(toc.get("assessment_plan")))
    html += _render_tools_reference(toc)
    html += _render_section("Certification Roadmap", _list_items(toc.get("certification_roadmap")))

    cert_guidance = _text(toc.get("certification_guidance"))
    if cert_guidance:
        html += f"""
    <section class="section">
        <h2>Certification Guidance</h2>
        <p>{_html(cert_guidance)}</p>
    </section>
"""

    trainer_notes = _text(toc.get("trainer_notes"))
    if trainer_notes:
        html += f"""
    <section class="section">
        <h2>Trainer Notes</h2>
        <p>{_html(trainer_notes)}</p>
    </section>
"""

    html += """
</body>
</html>
"""
    return html
