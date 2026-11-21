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
