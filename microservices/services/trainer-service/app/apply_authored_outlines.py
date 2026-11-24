"""Apply hand-written course outlines from authored_outlines.json to the datasets.

    python -m app.apply_authored_outlines            # report only
    python -m app.apply_authored_outlines --write    # update the dataset files

An entry matches a dataset day by ``topic``; ``rename_to`` replaces a generic
topic name with a specific one. Each authored day becomes the day's ``outline`` (used by the PDF course outline)
and its flat fields (subtopics, lab, scenario, deliverable, objectives,
assessment, acceptance checks), so the Excel ToC and AI-off generation use the
same content. ``tools`` on a course (or on one day) sets the day's tools; without
it the day keeps its own. An optional ``design`` block (outcomes, timed topics with
failure scenarios and best practices, a seeded lab failure, quiz, lab rubric and
lab environment) is copied to ``outline.design`` for the course workbook. Days that were already manually authored keep their flat fields
and only gain the outline. Original content is kept once in
``content_before_outline_authoring``. Review status stays "unreviewed".
"""

import argparse
import json
from copy import deepcopy
from pathlib import Path

from app.course_outline import OUTLINE_VERSION, _split_item, check_statement, outline_problems, subtopics_from_outline

ROOT = Path(__file__).parent
SOURCE = ROOT / "authored_outlines.json"
STAGE = "outline_authored_pending_review"
_FLAT_FIELDS = ("subtopics", "lab_task", "lab", "scenario", "deliverable", "learning_objectives", "assessment",
                "acceptance_checks", "delivery_steps", "minutes", "duration_basis", "tools")


def build_outline(entry: dict) -> dict:
    lab = entry["lab"]
    principle = entry.get("principle") or {}
    return {
        "topic_groups": [{"heading": group.get("heading", ""), "lead": group.get("lead", ""),
                          "items": [_split_item(item) for item in group["items"]]} for group in entry["groups"]],
        "principle": {"title": principle.get("title", ""), "lead": principle.get("lead", ""),
                      "points": list(principle.get("points") or [])},
        "lab": {"title": lab["title"], "scenario": lab.get("scenario", ""), "lead": lab.get("lead", ""),
                "tasks": list(lab["tasks"]), "verify": [check_statement(check[0], check[1]) for check in entry["checks"]],
                "deliverables": list(lab["deliverables"])},
        "assessment": entry.get("assessment", ""),
        "source": "authored",
        "version": OUTLINE_VERSION,
        **({"design": deepcopy(entry["design"])} if entry.get("design") else {}),
    }


_DESIGN_MODES = {"demo", "lab", "discussion"}


def design_problems(design: dict, module_minutes: int) -> list:
    """Checks for an optional fully detailed module design (the course-workbook sample format)."""
    problems = []
    outcomes = design.get("outcomes") or []
    if not 3 <= len(outcomes) <= 5 or not all(o.get("outcome") and o.get("assessed_by") for o in outcomes):
        problems.append("design needs 3 to 5 outcomes, each with an outcome and how it is assessed")
    topics = design.get("topics") or []
    if not topics or not all(t.get("topic") and int(t.get("minutes") or 0) > 0 for t in topics):
        problems.append("design topics need a name and positive minutes")
    elif sum(int(t["minutes"]) for t in topics) != module_minutes:
        problems.append(f"design topic minutes must add up to the module's {module_minutes} minutes")
    if any(t.get("mode") not in _DESIGN_MODES for t in topics):
        problems.append("design topic mode must be demo, lab or discussion")
    seeded = design.get("seeded_failure") or {}
    if not all(seeded.get(key) for key in ("symptom", "cause", "fix")):
        problems.append("design needs a seeded lab failure with a symptom, cause and fix")
    if len(design.get("quiz") or []) < 5:
        problems.append("design needs at least 5 knowledge-check questions")
    if any(len(row) != 5 for row in design.get("lab_rubric") or []) or not design.get("lab_rubric"):
        problems.append("design lab rubric rows need a criterion and four score descriptions")
    if not all(all(item.get(key) for key in ("tool", "version", "access", "setup_owner", "cost"))
               for item in design.get("lab_environment") or [{}]):
        problems.append("design lab environment rows need tool, version, access, setup owner and cost")
    return problems


def _flat_fields(entry: dict, outline: dict, had_lab_key: bool) -> dict:
    lab = outline["lab"]
    fields = {
        "subtopics": subtopics_from_outline(outline),
        "lab_task": f"{lab['title']}: " + "; ".join(lab["tasks"]) + ".",
        "scenario": lab["scenario"],
        "deliverable": "; ".join(lab["deliverables"]),
        "learning_objectives": list(entry["objectives"]),
        "assessment": entry["assessment"],
        "acceptance_checks": [{"input_or_condition": check[0], "expected_result": check[1], "evidence": check[2]}
                              for check in entry["checks"]],
        "delivery_steps": [
            {"method": "Explanation and demonstration", "minutes": 120,
             "activity": "Explain and demonstrate: " + "; ".join(group["heading"] or "Topics"
                                                                  for group in outline["topic_groups"]),
             "evidence": "Demonstrated example and participant notes"},
            {"method": "Guided lab", "minutes": 210, "activity": f"{lab['title']}: {lab['scenario']}",
             "evidence": "; ".join(lab["deliverables"])},
            {"method": "Verification and review", "minutes": 90,
             "activity": "Participants verify: " + " ".join(lab["verify"]),
             "evidence": "Recorded verification results and trainer feedback"},
        ],
        "minutes": 420,
        "duration_basis": "Proposed seven-hour day; the trainer confirms timings during review",
    }
    if had_lab_key:
        fields["lab"] = fields["lab_task"]
    return fields


def apply_course(course: dict, document: dict) -> int:
    """Update one dataset document in place; return the number of days changed."""
    entries = {}
    for entry in course["days"]:
        # A generic source topic ("Core Configuration") can be renamed to a specific one.
        entries[entry["topic"]] = entry
        if entry.get("rename_to"):
            entries[entry["rename_to"]] = entry
    changed = 0
    for day in document.get("days") or []:
        entry = entries.get(day.get("topic"))
        if not entry:
            continue
        outline = build_outline(entry)
        problems = outline_problems(outline)
        from app.toc_generation_agent import _subtopic_target  # authored days are kept as written
        target = _subtopic_target(entry.get("rename_to") or entry["topic"])
        if len(subtopics_from_outline(outline)) < target:
            problems.append(f"needs at least {target} topics so the ToC quality gate passes")
        if entry.get("design"):
            problems += design_problems(entry["design"], int(day.get("minutes") or 420))
        if problems:
            raise ValueError(f"{entry['topic']}: {'; '.join(problems)}")
        before = deepcopy(day)
        authored_elsewhere = day.get("content_quality_stage") not in (None, "", STAGE)
        if not authored_elsewhere:
            day.setdefault("content_before_outline_authoring",
                           {key: deepcopy(day[key]) for key in _FLAT_FIELDS if key in day})
            day.update(_flat_fields(entry, outline, "lab" in day))
            tools = entry.get("tools") or course.get("tools")
            if tools:
                day["tools"] = list(tools)
            day["content_quality_stage"] = STAGE
            day["content_enrichment_version"] = "authored-outline-v1"
            day["proposed_fields"] = ["delivery_steps", "minutes"]
            day["review_status"] = "unreviewed"
        day["outline"] = outline
        if entry.get("rename_to"):
            day["topic"] = entry["rename_to"]
        if day != before:
            changed += 1
    return changed


def run(root: Path = ROOT, write: bool = False) -> dict:
    source = json.loads((root / "authored_outlines.json").read_text(encoding="utf-8"))
    report = {}
    for course in source["courses"]:
        for name in course["files"]:
            path = root / "datasets_compact" / name
            document = json.loads(path.read_text(encoding="utf-8-sig"))
            changed = apply_course(course, document)
            report[name] = changed
            if changed and write:
                path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true", help="update the dataset files")
    print(json.dumps(run(write=parser.parse_args().write), indent=2))


if __name__ == "__main__":
    main()
