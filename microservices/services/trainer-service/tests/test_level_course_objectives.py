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


TOP_COURSES = ("generative_ai", "azure", "testing_qa", "sap", "devops", "csharp", "java", "cybersecurity", "aws",
               "react", "oracle_database", "data_engineering", "sre", "python", "salesforce")


def test_top_courses_map_their_course_outcomes_to_every_day():
    for name in TOP_COURSES:
        course = json.loads((LEVELS / f"{name}.json").read_text(encoding="utf-8-sig"))
        for level, track in course["levels"].items():
            topics = [day["topic"] for day in track["days"]]
            items = track["course_outcomes"]
            assert (8 if len(topics) <= 10 else 12) <= len(items) <= 15, (name, level, len(items))
            mapped = [topic for item in items for topic in item["topics"]]
            assert set(mapped) <= set(topics), (name, level)  # every mapping names a real day
            assert set(topics) <= set(mapped), (name, level)  # every day delivers an outcome
            assert not any(re.match(r"(?i)^(understand|know|learn)\b", item["outcome"]) for item in items)


def test_a_toc_only_promises_outcomes_its_days_teach():
    from app.level_curriculum import level_outcomes
    track = {
        "outcomes": ["Summary outcome A", "Summary outcome B"],
        "days": [{"topic": f"Day {n}", "objectives": [f"Objective {n}"]} for n in range(1, 5)],
        "course_outcomes": [{"outcome": "Covers days 1 and 2", "topics": ["Day 1", "Day 2"]},
                            {"outcome": "Covers day 3", "topics": ["Day 3"]},
                            {"outcome": "Covers days 3 and 4", "topics": ["Day 3", "Day 4"]}],
    }
    days = [{"topic": "Day 1"}, {"topic": "Day 3"}]
    # Day 1's mapped outcome also needs day 2, so the ToC states day 1's own objective instead.
    assert level_outcomes(track, days) == ["Objective 1", "Covers day 3"]
    assert level_outcomes(track, track["days"]) == ["Covers days 1 and 2", "Covers day 3", "Covers days 3 and 4"]
    unmapped = {key: value for key, value in track.items() if key != "course_outcomes"}
    assert level_outcomes(unmapped, unmapped["days"]) == ["Summary outcome A", "Summary outcome B"]
    assert level_outcomes(unmapped, days) == ["Objective 1", "Objective 3"]  # a partial level never uses the summary


def test_top_course_tocs_carry_their_official_references():
    from app.toc_generation_agent import generate_toc_from_dataset
    toc = generate_toc_from_dataset("Python", 5, level="beginner")
    assert toc["references"] and all(item["url"].startswith("https://") and item["title"] for item in toc["references"])
    for name in TOP_COURSES:
        course = json.loads((LEVELS / f"{name}.json").read_text(encoding="utf-8-sig"))
        assert course["sources"] and all(source["url"].startswith("https://") for source in course["sources"]), name
