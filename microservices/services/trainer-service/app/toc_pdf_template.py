"""Course-outline PDF template for training ToCs (rendered by WeasyPrint).

Layout:
  1. Cover page: "COURSE OUTLINE" and the course title on a branded background.
  2. Course details: Course Name, Duration, Delivery, Level, Learning Objectives,
     Prerequisites.
  3. Course Outline: one heading per day, then numbered modules. Each module
     shows Topics (with nested sub-topics), Tools, Scenario, a numbered Lab,
     "Participants verify that", and the Lab Deliverable. Each day ends with
     its assessment.

Only client-facing curriculum content is rendered. Internal planning data
(sources, quality flags, trainer preparation, delivery steps, trainer notes)
is never printed, and nothing is invented when a field is missing.
"""

from html import escape
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.course_outline import is_template_text, outline_from_flat, real_text

BRAND = "Clahan Technologies"
BRAND_SITE = "CLAHANTECHNOLOGIES.COM"


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ", ".join(_text(item) for item in value if _text(item))
    if isinstance(value, dict):
        return _text(value.get("topic") or value.get("title") or value.get("name") or value.get("text"))
    return re.sub(r"\s+", " ", str(value)).strip()


def _html(value: Any) -> str:
    return escape(_text(value), quote=True)


def _list_items(value: Any) -> List[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    return [value]


def _unique(items: Iterable[str], limit: int = 0) -> List[str]:
    seen, result = set(), []
    for item in items:
        text = _text(item)
        key = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
        if limit and len(result) >= limit:
            break
    return result


def _domain(toc: Dict[str, Any], title: str) -> str:
    direct = _text(toc.get("technology") or toc.get("domain") or toc.get("training_domain"))
    return direct or re.sub(r"\s+Mastery\s*$", "", title, flags=re.IGNORECASE).strip() or "Training"


def _days(toc: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [day for day in _list_items(toc.get("days")) if isinstance(day, dict)]


def _number(value: Any) -> Optional[float]:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _plain_number(number: float) -> str:
    return str(int(number)) if float(number).is_integer() else f"{number:g}"


def _duration(toc: Dict[str, Any]) -> str:
    days = _days(toc)
    agent = toc.get("agent") or {}
    count = _number(toc.get("duration_days") or toc.get("duration") or toc.get("days_count")
                    or agent.get("requested_days")) or (len(days) or None)
    # Show total hours only when every day states its minutes.
    day_minutes = [_number(day.get("minutes")) for day in days]
    hours = sum(day_minutes) / 60 if day_minutes and all(day_minutes) else None
    if not hours and count and _number(toc.get("hours_per_day")):
        hours = count * _number(toc.get("hours_per_day"))
    parts = []
    if count:
        parts.append(f"{_plain_number(count)} {'day' if count == 1 else 'days'}")
    if hours:
        hours = round(hours * 2) / 2
        parts.append(f"{_plain_number(hours)} hours")
    if len(parts) == 2:
        return f"{parts[0]} ({parts[1]})"
    return parts[0] if parts else ""


def _clean_day_title(day: Dict[str, Any]) -> str:
    raw = _text(day.get("focus_area") or day.get("title") or day.get("topic"))
    return re.sub(r"^\s*day\s+\d+\s*[:\-\u2013]\s*", "", raw, flags=re.IGNORECASE) or "Training Topic"


# --------------------------------------------------------------------------- topics

def _split_topic(item: Any) -> Tuple[str, List[str]]:
    """Return (label, children). "Surfaces: CLI, IDE, Cloud" becomes a nested list."""
    if isinstance(item, dict):
        label = _text(item.get("text") or item.get("topic") or item.get("title") or item.get("name"))
        children = [_text(child) for child in _list_items(item.get("items") or item.get("subtopics") or item.get("children"))]
        return label, [child for child in children if child]
    text = _text(item)
    match = re.match(r"^([^:]{3,60}):\s*(.+)$", text)
    if match:
        children = [part.strip(" .") for part in re.split(r",\s*|;\s*|\s+\u2022\s+", match.group(2)) if part.strip(" .")]
        if len(children) >= 3 and all(len(child) <= 60 for child in children):
            return match.group(1).strip() + ":", children
    return text, []


def _bullets(items: Iterable[Any], numbered: bool = False) -> str:
    rows = []
    for item in items:
        label, children = _split_topic(item)
        if not label:
            continue
        nested = ""
        if children:
            nested = '<ul class="sub">' + "".join(f"<li>{escape(child)}</li>" for child in children) + "</ul>"
        rows.append(f"<li>{escape(label)}{nested}</li>")
    if not rows:
        return ""
    tag = "ol" if numbered else "ul"
    return f'<{tag} class="list">{"".join(rows)}</{tag}>'


def _block(label: str, body: str) -> str:
    return f'<div class="block"><div class="label">{escape(label)}</div>{body}</div>' if body else ""


def _para(value: Any) -> str:
    text = _text(value)
    return f"<p>{escape(text)}</p>" if text else ""


# --------------------------------------------------------------------------- modules

def _modules(day: Dict[str, Any]) -> List[Dict[str, Any]]:
    modules = [module for module in _list_items(day.get("modules")) if isinstance(module, dict)]
    if modules:
        return modules
    # Older ToCs have one topic list and one lab per day.
    topics = _list_items(day.get("subtopics"))
    if not topics:
        morning = (day.get("morning_session") or {}).get("topics")
        topics = [topic for topic in _list_items(morning)
                  if not isinstance(topic, dict) or str(topic.get("type") or "") not in {"break", "jira", "qa"}]
    return [{
        "title": _clean_day_title(day),
        "subtopics": topics,
        "tools": day.get("tools") or day.get("primary_tools"),
        "scenario": day.get("scenario"),
        "lab": day.get("lab") or day.get("lab_task"),
        "deliverable": day.get("deliverable"),
        "acceptance_checks": day.get("acceptance_checks"),
        "outline": day.get("outline"),
        "learning_objectives": day.get("learning_objectives"),
    }]


def _render_groups(groups: List[Dict[str, Any]]) -> str:
    parts = []
    for index, group in enumerate(groups):
        heading = _text(group.get("heading")) or ("Topics" if index == 0 else "")
        body = _para(group.get("lead")) + _bullets(_list_items(group.get("items")))
        parts.append(_block(heading, body) if heading else body)
    return "".join(parts)


def _render_principle(principle: Dict[str, Any]) -> str:
    points = [_text(point) for point in _list_items((principle or {}).get("points")) if _text(point)]
    if not points:
        return ""
    title = _text(principle.get("title")) or "Key Principle"
    return _block(title, _para(principle.get("lead")) + _bullets(points, numbered=True))


def _render_lab(lab: Dict[str, Any], lab_no: int, fallback_title: str) -> str:
    title = _text(lab.get("title"))
    tasks = [_text(task) for task in _list_items(lab.get("tasks")) if _text(task)]
    verify = _unique(_list_items(lab.get("verify")), 8)
    deliverables = [_text(item) for item in _list_items(lab.get("deliverables")) if _text(item)]
    scenario = _text(lab.get("scenario"))
    heading = f"Lab {lab_no}: {title}" if title else f"Lab {lab_no}: {fallback_title}"
    parts = [f'<div class="lab"><div class="lab-title">{escape(heading)}</div>', _para(scenario)]
    if tasks:
        parts.append((_para(lab.get("lead")) if _text(lab.get("lead")) else "") + _bullets(tasks))
    if verify:
        parts.append('<p class="lead">Participants verify that:</p>' + _bullets(verify))
    if deliverables:
        body = _para(deliverables[0]) if len(deliverables) == 1 else _bullets(deliverables)
        parts.append(f'<div class="label">Lab Deliverable</div>{body}')
    parts.append("</div>")
    return "".join(part for part in parts if part)


def _render_module(module: Dict[str, Any], module_no: int, lab_no: int) -> Tuple[str, int]:
    title = re.sub(r"^\s*day\s+\d+\s*[:\-\u2013]\s*", "", _text(module.get("title") or module.get("topic")),
                   flags=re.IGNORECASE) or f"Module {module_no}"
    outline = outline_from_flat(module)
    parts = [f'<h3 class="module">Module {module_no}: {escape(title)}</h3>']
    parts.append(_render_groups(_list_items(outline.get("topic_groups"))))
    # Dataset days store tools as "Jira + Git"; print them as a comma-separated list.
    tools = _unique(part for item in _list_items(module.get("tools")) for part in re.split(r"\s+\+\s+", _text(item)))
    if tools:
        parts.append(f'<p class="tools"><span class="label-inline">Tools:</span> {escape(", ".join(tools))}</p>')
    parts.append(_render_principle(outline.get("principle") or {}))
    lab = outline.get("lab") or {}
    if any(_list_items(lab.get(key)) or _text(lab.get(key)) for key in ("title", "scenario", "tasks", "verify", "deliverables")):
        lab_no += 1
        parts.append(_render_lab(lab, lab_no, title))
    return "\n".join(part for part in parts if part), lab_no


def _render_day(day: Dict[str, Any], index: int, show_day: bool, counters: Dict[str, int]) -> str:
    parts = []
    if show_day:
        number = _text(day.get("day")) or str(index)
        date = _text(day.get("date"))
        meta = f'<span class="day-date">{escape(date)}</span>' if date else ""
        parts.append(f'<h2 class="day">Day {escape(number)} \u2013 {escape(_clean_day_title(day))}{meta}</h2>')
    modules = _modules(day)
    for module in modules:
        counters["module"] += 1
        html, counters["lab"] = _render_module(module, counters["module"], counters["lab"])
        parts.append(html)
    # An authored outline assessment wins; then the day's; then the modules'.
    assessment = " ".join(_unique((real_text((module.get("outline") or {}).get("assessment")) for module in modules), 3))
    if not assessment:
        assessment = real_text(day.get("assessment"))
    if not assessment:
        assessment = " ".join(_unique((real_text(module.get("assessment")) for module in modules), 3))
    verified = " ".join(_text(check) for module in modules
                        for check in (outline_from_flat(module).get("lab") or {}).get("verify") or [])
    def words(value: str) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", value.lower()))
    if assessment and words(assessment) and words(assessment) in words(verified):
        assessment = ""  # the day assessment only repeats the lab checks shown above
    if assessment:
        label = f"Day {_text(day.get('day')) or index} Assessment" if show_day else "Assessment"
        parts.append(f'<div class="assessment"><div class="label">{escape(label)}</div>{_para(assessment)}</div>')
    return f'<section class="day-section">{"".join(parts)}</section>'


# --------------------------------------------------------------------------- document

def _learning_objectives(toc: Dict[str, Any]) -> List[str]:
    direct = _unique((item for item in _list_items(toc.get("learning_outcomes") or toc.get("learning_objectives"))
                      if not is_template_text(item)), 20)
    if direct:
        return direct
    collected = []
    for day in _days(toc):
        for module in _modules(day):
            collected.extend(item for item in _list_items(module.get("learning_objectives"))[:2]
                             if not is_template_text(item))
    return _unique(collected, 20)


_CSS = """
@page {
  size: A4; margin: 26mm 20mm 22mm 20mm;
  @top-right { content: "CLAHAN TECHNOLOGIES"; font: 700 10.5pt Poppins, "Segoe UI", Arial, sans-serif;
               letter-spacing: 1.6pt; color: #2E1065; vertical-align: bottom; padding-bottom: 6mm; }
  @bottom-left { content: "%(site)s"; font: 8.5pt Poppins, "Segoe UI", Arial, sans-serif; color: #111827; }
  @bottom-right { content: counter(page); font: 9pt Poppins, "Segoe UI", Arial, sans-serif; color: #111827; }
}
@page cover { margin: 0; @top-right { content: none; } @bottom-left { content: none; } @bottom-right { content: none; } }
* { box-sizing: border-box; }
body { margin: 0; font-family: Calibri, Carlito, "Segoe UI", Arial, sans-serif; font-size: 10.5pt;
       line-height: 1.42; color: #111827; }

.cover { page: cover; width: 210mm; height: 297mm; position: relative; overflow: hidden; color: #fff;
         background: linear-gradient(160deg, #13073A 0%%, #2A0A6B 45%%, #4C1D95 75%%, #5B21B6 100%%);
         break-after: page; }
.cover .eyebrow { position: absolute; top: 34mm; left: 22mm; font: 500 14pt Poppins, "Segoe UI", Arial, sans-serif;
                  letter-spacing: 1pt; }
.cover h1 { position: absolute; top: 46mm; left: 22mm; right: 22mm; margin: 0; font: 400 26pt Poppins,
            "Segoe UI", Arial, sans-serif; line-height: 1.2; }
.cover .facts { position: absolute; top: 74mm; left: 22mm; right: 22mm; font: 11pt Poppins, "Segoe UI", Arial,
                sans-serif; color: #DDD6FE; }
.cover .orb { position: absolute; left: 112mm; top: 112mm; width: 135mm; height: 135mm; border-radius: 50%%;
              background: radial-gradient(circle, rgba(124,58,237,.45) 0%%, rgba(91,33,182,.25) 60%%, rgba(76,29,149,0) 72%%); }
.cover .bar { position: absolute; bottom: 70mm; width: 30mm; border-radius: 3mm;
              box-shadow: 4mm 0 0 rgba(30,10,80,.55); }
.cover .b1 { left: 118mm; height: 52mm; background: linear-gradient(180deg, #C4B5FD, #A78BFA); }
.cover .b2 { left: 154mm; height: 84mm; background: linear-gradient(180deg, #A855F7, #7C3AED); }
.cover .b3 { left: 190mm; height: 114mm; background: linear-gradient(180deg, #9333EA, #6D28D9); }
.cover .brand { position: absolute; bottom: 20mm; left: 22mm; font: 700 12pt Poppins, "Segoe UI", Arial, sans-serif;
                letter-spacing: 2pt; }

h2.section { font: 400 22pt Poppins, "Segoe UI", Arial, sans-serif; color: #9333EA; margin: 10mm 0 3mm; }
h2.section:first-child { margin-top: 0; }
.value { font-weight: 700; margin: 0 0 2mm; }
.details { margin: 0 0 2mm; }
.details div { margin: 0 0 1mm; }
.details b { display: inline-block; min-width: 26mm; }
.list { margin: 1.5mm 0 3mm; padding-left: 7mm; }
.list li { margin: 0 0 1.1mm; }
.list .sub { list-style-type: circle; margin: 1mm 0 1.5mm; padding-left: 7mm; }
h2.day { font: 700 13pt Poppins, "Segoe UI", Arial, sans-serif; color: #2E1065; margin: 8mm 0 2mm;
         padding-bottom: 1.5mm; border-bottom: 1.2pt solid #DDD6FE; break-after: avoid; }
.day-date { float: right; font: 400 9.5pt Calibri, Arial, sans-serif; color: #6B7280; padding-top: 1mm; }
h3.module { font-size: 11pt; font-weight: 700; margin: 6mm 0 2mm; break-after: avoid; }
.label { font-weight: 700; margin: 3mm 0 1mm; break-after: avoid; }
.label-inline { font-weight: 700; }
.tools { margin: 1mm 0 2mm; }
p { margin: 0 0 2mm; }
.lead { margin: 1.5mm 0 0; }
.lab { margin: 3mm 0 2mm; }
.lab-title { font-weight: 700; margin: 0 0 1.5mm; break-after: avoid; }
.assessment { margin: 4mm 0 0; }
.closing { margin-top: 8mm; }
"""


def build_toc_html(toc_data: Dict[str, Any]) -> str:
    """Build the course-outline HTML used by every trainer ToC PDF path."""
    toc = dict(toc_data or {})
    title = _text(toc.get("title") or toc.get("program_title") or "Training Programme")
    title = re.sub(r"^\s*(?:draft\s*[-:]\s*)", "", title, flags=re.IGNORECASE)
    days = _days(toc)
    duration = _duration(toc)
    mode = _text(toc.get("mode") or toc.get("delivery_mode") or (toc.get("agent") or {}).get("mode"))
    level = _text(toc.get("level") or toc.get("audience_level"))
    facts = " \u2022 ".join(part for part in (duration, mode.title() if mode.islower() else mode, level) if part)

    html = [f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>{escape(title)}</title>
<style>{_CSS % {"site": BRAND_SITE}}</style></head><body>
<div class="cover">
  <div class="eyebrow">COURSE OUTLINE</div>
  <h1>{escape(title)}</h1>
  {f'<div class="facts">{escape(facts)}</div>' if facts else ''}
  <div class="orb"></div><div class="bar b1"></div><div class="bar b2"></div><div class="bar b3"></div>
  <div class="brand">{escape(BRAND.upper())}</div>
</div>"""]

    html.append(f'<h2 class="section">Course Name</h2><p class="value">{escape(title)}</p>')
    if duration:
        html.append(f'<h2 class="section">Duration</h2><p class="value">{escape(duration)}</p>')
    details = []
    if mode:
        details.append(f"<div><b>Delivery:</b> {_html(mode.title() if mode.islower() else mode)}</div>")
    if level:
        details.append(f"<div><b>Level:</b> {_html(level)}</div>")
    if _text(toc.get("audience")):
        details.append(f"<div><b>Audience:</b> {_html(toc.get('audience'))}</div>")
    if details:
        html.append(f'<div class="details">{"".join(details)}</div>')
    overview = real_text(toc.get("overview"))
    if overview:
        html.append(f'<h2 class="section">Overview</h2>{_para(overview)}')
    objectives = _learning_objectives(toc)
    if objectives:
        html.append(f'<h2 class="section">Learning Objectives</h2>{_bullets(objectives)}')
    prerequisites = _unique((item for item in _list_items(toc.get("prerequisites")) if not is_template_text(item)), 12)
    if prerequisites:
        html.append(f'<h2 class="section">Prerequisites</h2>{_bullets(prerequisites)}')

    if days:
        html.append('<h2 class="section" style="break-before: page; margin-top: 0">Course Outline</h2>')
        counters = {"module": 0, "lab": 0}
        show_day = len(days) > 1
        for index, day in enumerate(days, 1):
            html.append(_render_day(day, index, show_day, counters))

    closing = []
    tools = _unique(_list_items(toc.get("tools_software")), 20)
    if tools:
        closing.append(f'<h2 class="section">Tools &amp; Software</h2>{_bullets(tools)}')
    capstone = toc.get("capstone_plan") or {}
    if isinstance(capstone, dict) and capstone:
        items = [capstone.get("approach"), *_list_items(capstone.get("checkpoints")), capstone.get("finale")]
        closing.append(f'<h2 class="section">Capstone</h2>{_bullets(item for item in items if _text(item))}')
    certifications = _unique(_list_items(toc.get("certification_roadmap")), 10)
    guidance = _text(toc.get("certification_guidance"))
    if certifications or guidance:
        closing.append(f'<h2 class="section">Certification Guidance</h2>{_bullets(certifications)}{_para(guidance)}')
    if closing:
        html.append(f'<div class="closing">{"".join(closing)}</div>')

    html.append("</body></html>")
    return "\n".join(html)
