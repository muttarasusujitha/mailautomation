import asyncio
import json
import shutil
from pathlib import Path

from app import draft_level_modules as draft
from app.level_curriculum import validate_course

LEVELS_DIR = Path(__file__).resolve().parents[1] / "app" / "datasets_levels"


def _modules_for(source, drop_subtopic=False):
    topics = list(source["subtopics"])
    if drop_subtopic:
        topics = topics[1:]
    parts = [topics[0::3], topics[1::3], topics[2::3]]
    return [{
        "title": f"{source['topic']} part {index}", "minutes": minutes, "subtopics": part,
        "objective": "Do the thing", "lab": "Run the sample lab", "deliverable": "Lab output",
        "success_measure": "Output matches the expected result",
        "scenarios": [["A situation", "An activity", "An outcome", "Evidence"]] * 3,
    } for index, (part, minutes) in enumerate(zip(parts, (120, 150, 150)), 1)]


def _workspace(tmp_path):
    level_dir = tmp_path / "levels"
    level_dir.mkdir()
    for name in ("git.json", "generative_ai.json"):
        shutil.copy(LEVELS_DIR / name, level_dir / name)
    return level_dir, tmp_path / "cache"


def test_inventory_skips_days_that_already_have_modules(tmp_path):
    level_dir, _ = _workspace(tmp_path)
    genai = draft.inventory(level_dir, courses=["generative_ai"], levels=["intermediate"])
    topics = {source["topic"] for source in genai.values()}
    assert "Generative AI Application Architecture" not in topics
    assert len(genai) == 15


def test_valid_drafts_are_applied_and_invalid_ones_are_rejected(tmp_path):
    level_dir, cache = _workspace(tmp_path)
    pending = draft.inventory(level_dir, courses=["git"], levels=["beginner"])
    first, second = list(pending.values())[:2]

    async def fake_post(payload):
        return json.dumps({"days": [
            {"key": first["key"], "modules": _modules_for(first)},
            {"key": second["key"], "modules": _modules_for(second, drop_subtopic=True)},
        ]})

    accepted, rejected = asyncio.run(draft.generate(
        {first["key"]: first, second["key"]: second}, post=fake_post, cache=cache, level_dir=level_dir))
    assert (accepted, rejected) == (1, 1)
    assert "not covered" in json.loads((cache / "rejected" / f"{second['key']}.json").read_text())["issues"][0]

    before = (level_dir / "git.json").read_text(encoding="utf-8")
    assert draft.apply(pending, cache=cache, level_dir=level_dir) == 1
    after = (level_dir / "git.json").read_text(encoding="utf-8")
    course = json.loads(after)
    assert validate_course(course) == []
    day = next(d for d in course["levels"]["beginner"]["days"] if d["topic"] == first["topic"])
    assert day["modules"][0]["origin"] == draft.ORIGIN
    # Only the new block is added; every original line is kept in order.
    original = before.split("\n")
    kept = [line for line in after.split("\n") if line in original]
    assert len(kept) >= len(original) - 1
    # The applied day no longer needs a draft.
    assert first["key"] not in draft.inventory(level_dir, courses=["git"], levels=["beginner"])


def test_drafts_must_cover_each_subtopic_once():
    source = {"file": "x.json", "level": "beginner", "topic": "T", "subtopics": ["a", "b", "c"]}
    modules = _modules_for(source)
    assert draft.problems(modules, source) == []
    modules[1]["subtopics"].append("a")
    assert "more than one module" in draft.problems(modules, source)[0]
