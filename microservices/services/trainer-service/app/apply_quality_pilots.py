"""Apply authored pilot modules and emit a reviewable content preview.

Durations are proposed teaching budgets. Source URLs support concepts, not
claims that the proposed exercises were executed or reviewed by a trainer.
"""
import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).parent


def apply_document(document, relative_path):
    pilots = json.loads((ROOT / "quality_pilots.json").read_text(encoding="utf-8"))
    for pilot in pilots:
        if pilot["file"] != relative_path:
            continue
        matches = [row for row in document.get("modules", document.get("days", []))
                   if all(row.get(key) == pilot[key] for key in ("topic", "code", "reference_day") if key in pilot)
                   and (not pilot.get("topic_prefix") or row.get("topic", "").startswith(pilot["topic_prefix"]))]
        if len(matches) != 1:
            raise ValueError(f"Pilot needs exactly one source module: {relative_path}")
        row = matches[0]
        fields = ("subtopics", "scenario", "lab", "deliverable", "learning_objectives", "assessment",
                  "prerequisites", "preparation_requirements", "source_urls")
        row.setdefault("original_reference_content", {key: deepcopy(row.get(key)) for key in fields})
        row.update({key: deepcopy(pilot[key]) for key in fields})
        row["delivery_steps"] = [dict(zip(("minutes", "method", "activity", "evidence"), step)) for step in pilot["schedule"]]
        row["minutes"] = sum(step[0] for step in pilot["schedule"])
        row["duration_basis"] = "Proposed pilot teaching budget; trainer feasibility review required"
        row["delivery_basis"] = "Authored scenario and acceptance checks; sample assets must be prepared before delivery"
        row["content_quality_stage"] = "authored_pilot_pending_lab_validation"
        row["review_status"] = "unreviewed"
        row["proposed_fields"] = list(dict.fromkeys([*row.get("proposed_fields", []), *fields, "delivery_steps", "minutes"]))
    return document


def run():
    pilots = json.loads((ROOT / "quality_pilots.json").read_text(encoding="utf-8"))
    preview = ["# Curriculum content quality pilots", "", "Five authored module previews, not complete course rewrites. Timings are proposals; training assets and technical review remain required. Original reference content is retained in each dataset. These previews show stored curriculum content, not live AI output.", ""]
    for pilot in pilots:
        path = ROOT / pilot["file"]
        document = apply_document(json.loads(path.read_text(encoding="utf-8")), pilot["file"])
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        preview.extend(["## " + document.get("name", document.get("domain", path.stem)), "",
                        "**Scenario:** " + pilot["scenario"], "", "**Topics:** " + "; ".join(pilot["subtopics"]), "",
                        "**Prerequisites:** " + "; ".join(pilot["prerequisites"]), "",
                        "**Lab:** " + pilot["lab"], "", "**Participant output:** " + pilot["deliverable"], "",
                        "**Acceptance checks:** " + pilot["assessment"], "", "**Delivery:**", ""])
        preview.extend(f"- {minutes} minutes — {method}: {activity}. Evidence: {evidence}." for minutes, method, activity, evidence in pilot["schedule"])
        preview.extend(["", "**Preparation:** " + "; ".join(pilot["preparation_requirements"]), "", "**Sources:** " + ", ".join(pilot["source_urls"]), ""])
    output = ROOT.parents[4] / "CONTENT_QUALITY_PILOTS.md"
    output.write_text("\n".join(preview), encoding="utf-8")
    print(f"Updated {len(pilots)} modules; review: {output}")


if __name__ == "__main__":
    run()
