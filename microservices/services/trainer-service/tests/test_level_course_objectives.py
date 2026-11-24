import json
import re
from pathlib import Path

LEVELS = Path(__file__).resolve().parents[1] / "app" / "datasets_levels"


def test_level_course_objectives_use_measurable_verbs():
    """Outcomes are things a participant can do and be checked on, never "understand", "know" or "learn"."""
    vague = []
    for path in sorted(LEVELS.glob("*.json")):
        course = json.loads(path.read_text(encoding="utf-8-sig"))
        for level, track in (course.get("levels") or {}).items():
            for day in track["days"]:
                vague += [f"{path.stem}/{level}/{day['topic']}: {objective}"
                          for objective in day.get("objectives") or []
                          if re.match(r"(?i)^(understand|know|learn|be aware)\b", str(objective))]
    assert vague == []
