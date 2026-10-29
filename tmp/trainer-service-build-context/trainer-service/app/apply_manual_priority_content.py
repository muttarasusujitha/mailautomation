"""Apply authored high-use domain exercises without model calls."""
import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).parent
STAGE = "manually_authored_pending_lab_validation"


def run():
    entries = json.loads((ROOT / "manual_priority_content.json").read_text(encoding="utf-8"))
    updated = 0
    for entry in entries:
        path = ROOT / "datasets_compact" / entry["file"]
        document = json.loads(path.read_text(encoding="utf-8"))
        rows = [row for row in document.get("days", []) if row.get("topic") == entry["topic"]]
        if len(rows) != 1:
            raise ValueError(f"Expected one module for {entry['file']} / {entry['topic']}")
        row = rows[0]
        row.setdefault("content_before_manual_rewrite", deepcopy(row))
        row.update(scenario=entry["scenario"], lab=entry["lab"], lab_task=entry["lab"],
                   deliverable=entry["output"], learning_objectives=entry["outcomes"],
                   assessment="\n".join(entry["checks"]), prerequisites=[entry["prerequisites"]],
                   acceptance_checks=entry["checks"], content_quality_stage=STAGE,
                   review_status="unreviewed", content_enrichment_version="manual-priority-v1",
                   source_verification="Exercise is manually authored; technical and lab validation remain pending")
        row["preparation_requirements"] = ["Prepare the stated lab fixture or training environment", "Verify expected results: " + "; ".join(entry["checks"])]
        row["delivery_steps"] = [
            {"method":"Demonstration", "minutes":None, "activity":entry["scenario"], "evidence":"Baseline example and first expected result"},
            {"method":"Guided lab", "minutes":None, "activity":entry["lab"], "evidence":entry["output"]},
            {"method":"Independent validation", "minutes":None, "activity":entry["checks"][1], "evidence":"Recorded result"},
            {"method":"Assessment", "minutes":None, "activity":entry["checks"][2], "evidence":"Participant explanation and evidence"},
        ]
        row["proposed_fields"] = ["scenario", "lab", "deliverable", "learning_objectives", "assessment", "acceptance_checks", "prerequisites", "preparation_requirements", "delivery_steps"]
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        updated += 1
    print(json.dumps({"authored_modules": len(entries), "updated_entries": updated}))


if __name__ == "__main__":
    run()
