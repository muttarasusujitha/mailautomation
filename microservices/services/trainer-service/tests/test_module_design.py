import json
from copy import deepcopy
from pathlib import Path

from app.apply_authored_outlines import design_problems, run as apply_authored
from app.toc_generation_agent import generate_toc_from_dataset, validate_toc

APP = Path(__file__).resolve().parents[1] / "app"


def _docker_design():
    source = json.loads((APP / "authored_outlines.json").read_text(encoding="utf-8"))
    entry = next(day for day in source["courses"][0]["days"] if day["topic"] == "Docker Fundamentals")
    return entry["design"]


def test_docker_sample_module_meets_the_design_rules():
    design = _docker_design()
    assert design_problems(design, 420) == []
    assert 3 <= len(design["outcomes"]) <= 5
    assert sum(topic["minutes"] for topic in design["topics"]) == 420
    assert {topic["mode"] for topic in design["topics"]} == {"discussion", "demo", "lab"}
    assert len(design["quiz"]) >= 5


def test_design_rules_reject_incomplete_modules():
    design = deepcopy(_docker_design())
    design["topics"][0]["minutes"] += 10
    design["seeded_failure"]["fix"] = ""
    design["quiz"] = design["quiz"][:3]
    design["outcomes"] = design["outcomes"][:2]
    problems = " | ".join(design_problems(design, 420))
    assert "add up to the module's 420 minutes" in problems
    assert "seeded lab failure" in problems
    assert "at least 5 knowledge-check questions" in problems
    assert "3 to 5 outcomes" in problems


def test_docker_design_is_applied_and_reaches_the_generated_toc():
    assert all(count == 0 for count in apply_authored(APP, write=False).values())  # committed and idempotent
    toc = validate_toc(generate_toc_from_dataset("DevOps", 10), 10)
    docker = next(day for day in toc["days"] if day.get("focus_area") == "Docker Fundamentals")
    design = (docker.get("outline") or {}).get("design") or {}
    assert design.get("seeded_failure", {}).get("symptom")
    assert sum(topic["minutes"] for topic in design["topics"]) == 420
    assert toc["quality"]["status"] == "approved"
