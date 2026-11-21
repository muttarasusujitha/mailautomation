"""Detailed module designs kept outside the course files and read only when a ToC needs them.

Each course file ``datasets_levels/<course>.json`` or ``datasets_compact/<course>.json``
can have ``module_designs/<course>.json``: one design per module, keyed by level and
topic. Keeping them separate means the trainer service does not load thousands of
designs at start-up, and a ToC reads only the designs of the course it uses.

Generation marks every dataset day with a ``design_ref`` ({file, level, topic});
``design_for`` turns that reference into the design, or ``None``.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

DIR = Path(__file__).parent / "module_designs"


def place_key(level, topic):
    return f"{level or ''}::{re.sub(r'[^a-z0-9]+', ' ', str(topic or '').lower()).strip()}"


@lru_cache(maxsize=32)
def _load(course, directory=None):
    path = Path(directory or DIR) / f"{course}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("designs") or {}
    except (OSError, ValueError):
        return {}  # a damaged design file must never break ToC generation


def load(course, directory=None):
    return _load(course, str(directory) if directory else None)


def design_for(ref, directory=None):
    if not isinstance(ref, dict) or not ref.get("file"):
        return None
    design = load(ref["file"], directory).get(place_key(ref.get("level"), ref.get("topic")))
    return json.loads(json.dumps(design)) if isinstance(design, dict) else None  # a private copy


def clear_cache():
    _load.cache_clear()


def _day_design(day):
    """The design a dataset day carries: authored on its outline, inline, or in the store."""
    outline = day.get("outline") if isinstance(day.get("outline"), dict) else {}
    for value in (outline.get("design"), day.get("design")):
        if isinstance(value, dict) and value:
            return json.loads(json.dumps(value))
    return design_for(day.get("design_ref"))


def _course_days(domain):
    """Dataset days for a course name: its level course (all levels) and its compact course."""
    from app.level_curriculum import get_level_course
    from app.toc_domain_dataset import get_domain
    days = []
    course = get_level_course(domain)
    if course:
        days += [day for track in course["levels"].values() for day in track["days"]]
    compact = get_domain(domain, 30) or {}
    days += [day for day in compact.get("days") or [] if isinstance(day, dict) and day.get("design_ref")]
    return days


def attach_to_ai_toc(toc, domain):
    """Give AI-planned days the stored design of the course module they teach; returns the count.

    A day is linked only when its title is the module's title or contains it word for word
    (``shared.toc_quality.topic_is_covered``); the longest such module title wins, and a tie
    between different designs links nothing. Partial or similar titles are never linked, so a
    design always describes the module the day actually teaches.
    """
    from shared.toc_quality import normalize_topic, topic_is_covered
    candidates = {}
    for day in _course_days(domain):
        title = normalize_topic(day.get("topic"))
        if title and title not in candidates:
            design = _day_design(day)
            if design:
                candidates[title] = design
    linked = 0
    for day in toc.get("days") or []:
        if not isinstance(day, dict):
            continue
        outline = day.get("outline") if isinstance(day.get("outline"), dict) else {}
        if outline.get("design") or day.get("design") or day.get("design_ref"):
            continue  # the day already has its own design (authored, inline or from the dataset)
        title = str(day.get("focus_area") or day.get("topic") or "")
        matches = [(len(name), name) for name in candidates if topic_is_covered(name, title)]
        if not matches:
            continue
        best = max(length for length, _ in matches)
        names = [name for length, name in matches if length == best]
        designs = {json.dumps(candidates[name], sort_keys=True) for name in names}
        if len(designs) != 1:
            continue
        day["design"] = json.loads(json.dumps(candidates[names[0]]))
        day["design_link"] = {"dataset_module": names[0], "domain": domain}
        linked += 1
    return linked


def write(course, designs, directory=None):
    """Merge designs into the course's design file, one module per line, via a temporary file."""
    directory = Path(directory or DIR)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{course}.json"
    current = {}
    if path.exists():
        current = json.loads(path.read_text(encoding="utf-8")).get("designs") or {}
    current.update(designs)
    lines = ["{", f'  "course": {json.dumps(course)},', '  "review_status": "unreviewed",', '  "designs": {']
    items = sorted(current.items())
    for index, (key, design) in enumerate(items):
        comma = "," if index < len(items) - 1 else ""
        lines.append(f"    {json.dumps(key, ensure_ascii=False)}: {json.dumps(design, ensure_ascii=False)}{comma}")
    lines += ["  }", "}", ""]
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text("\n".join(lines), encoding="utf-8")
    temporary.replace(path)
    clear_cache()
    return len(current)
