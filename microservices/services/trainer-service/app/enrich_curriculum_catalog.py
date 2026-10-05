"""Add source-derived delivery proposals across the compact curriculum catalog."""
import json
from pathlib import Path

VERSION = "catalog-delivery-v1"


def enrich_entry(entry):
    title = entry.get("topic") or entry.get("title") or entry.get("focus_area")
    lab = entry.get("lab") or entry.get("lab_task")
    if not title or not lab:
        raise ValueError("Each curriculum entry needs a topic and source lab")
    coverage = "; ".join(str(topic) for topic in entry.get("subtopics", []))
    proposed = list(entry.get("proposed_fields") or [])
    additions = {
        "deliverable": f"Participant submission for '{title}': {lab}. Include the resulting artefact, reproducible steps and observed results.",
        "assessment": f"Reproduce the source lab: {lab}. Compare the participant result with a trainer-prepared expected result; check applicable focus areas ({coverage}). Require one changed-input or exception case and an explanation of its result.",
        "learning_objectives": [f"Complete and demonstrate: {lab}.", f"Explain how the lab applies {title} and justify the observed result."],
        "scenario": f"Demonstrate '{title}' on a prepared training sample through this task: {lab}.",
        "preparation_requirements": [f"Prepare sample assets, expected results and an exception case for: {lab}", "Confirm participant prerequisites, tool access and activity durations before delivery"],
    }
    for key, value in additions.items():
        if not entry.get(key):
            entry[key] = value
            proposed.append(key)
    if not entry.get("delivery_steps"):
        entry["delivery_steps"] = [
            {"method": "Explanation and demonstration", "minutes": None,
             "activity": f"Explain the applicable concepts ({coverage}) and demonstrate the starting sample for: {lab}",
             "evidence": "Annotated sample with inputs and expected results"},
            {"method": "Guided practice", "minutes": None, "activity": lab, "evidence": entry["deliverable"]},
            {"method": "Independent application", "minutes": None,
             "activity": f"Repeat '{lab}' with a trainer-prepared changed input or exception case; explain differences from the demonstrated result.",
             "evidence": "Participant artefact and comparison of expected versus observed results"},
            {"method": "Assessment and feedback", "minutes": None,
             "activity": entry["assessment"], "evidence": "Recorded checks, unresolved errors and trainer feedback"},
        ]
        entry["delivery_basis"] = "Proposed sequence derived from source topic and lab; timings require trainer planning"
        proposed.append("delivery_steps")
    entry["proposed_fields"] = list(dict.fromkeys(proposed))
    entry["content_enrichment_version"] = VERSION
    return entry


def enrich_catalog(root):
    count, pending, domains = 0, [], set()
    for path in sorted(root.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8-sig"))
        rows = [*document.get("days", []), *document.get("modules", [])]
        for group in (document.get("level_map") or {}).values():
            rows.extend(group)
        for row in rows:
            enrich_entry(row)
            row["review_status"] = "unreviewed"
            count += 1
        document["content_enrichment_version"] = VERSION
        warnings = document.setdefault("review_warnings", [])
        warning = "Added delivery details are source-derived proposals; confirm technical accuracy, prerequisites, assessment cases and timing with the trainer."
        if warning not in warnings:
            warnings.append(warning)
        document["review_status"] = "unreviewed"
        domains.add(document.get("domain") or document.get("name") or path.stem)
        pending.append((path, json.dumps(document, ensure_ascii=False, indent=2) + "\n"))
    for path, content in pending:
        path.write_text(content, encoding="utf-8")
    return {"files": len(pending), "domains": len(domains), "entries": count}


if __name__ == "__main__":
    print(json.dumps(enrich_catalog(Path(__file__).parent / "datasets_compact")))
