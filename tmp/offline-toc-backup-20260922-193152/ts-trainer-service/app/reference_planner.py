"""Offline reference drafts preserve source scope and time; never imply approval."""
import json
from pathlib import Path

from shared.toc_quality import normalize_topic


def reference_draft(request):
    key = normalize_topic(request.domain)
    aliases = {
        "codex": "codex_for_developers", "codex for developers": "codex_for_developers",
        "enterprise ai readiness": "enterprise_ai_readiness_genai_for_bi_capstone_track",
        "engineering security product": "engineering_security_product",
        "aws security devops sre": "aws_cloud_security_devops_sre",
        "quality engineering": "training_for_quality_engineers",
        "training for quality engineers": "training_for_quality_engineers",
    }
    root = Path(__file__).parent / "reference_curricula"
    paths = list(root.glob("*.json"))
    source = next((json.loads(p.read_text(encoding="utf-8")) for p in paths
                   if p.stem == aliases.get(key) or normalize_topic(p.stem.replace("_", " ")) == key), None)
    if not source:
        return None
    warnings = list(source.get("review_warnings") or [])
    warnings.append("Reference draft requires client-scope and subject-matter review before delivery")
    modules = [dict(m) for m in source["modules"] if m.get("track") != "advanced_leadership"
               or "leadership" in (request.custom_topics or "").lower()]
    count = int(request.duration_days)
    budget = int(request.hours_per_day * 60) if request.hours_per_day else None
    days = []
    if all(m.get("reference_day") for m in modules):
        for number in sorted({m["reference_day"] for m in modules}):
            days.append({"day": number, "modules": [m for m in modules if m["reference_day"] == number]})
    elif budget and all(m.get("minutes") for m in modules):
        for module in modules:
            # A long module can span days; preserve every minute and label its
            # continuation, rather than silently treating it as a short class.
            remaining = module["minutes"]
            part = 0
            while remaining:
                if not days or sum(m["minutes"] for m in days[-1]["modules"]) >= budget:
                    days.append({"day": len(days)+1, "modules": []})
                available = budget - sum(m["minutes"] for m in days[-1]["modules"])
                allocated = min(remaining, available)
                part += 1
                item = {**module, "minutes": allocated}
                if module["minutes"] > allocated:
                    item["topic"] += f" (part {part})"
                    warnings.append("Split modules require trainer review of topic distribution across sessions")
                days[-1]["modules"].append(item)
                remaining -= allocated
    else:
        # Keep unknown module durations unknown; do not fabricate a schedule.
        days = [{"day": 1, "modules": modules}]
        warnings.append("Module durations must be confirmed before allocating the requested days")
    errors = []
    if len(days) != count:
        errors.append(f"Reference requires {len(days)} planned days; client requested {count}. Adapt scope before delivery.")
    for day in days:
        items = day["modules"]
        for item in items:
            item["title"] = item["topic"]
            item["scenario"] = "\n".join(s["situation"] for s in item.get("scenarios", []))
        day.update({
            "focus_area": " / ".join(m["topic"] for m in items),
            "subtopics": [t for m in items for t in m.get("subtopics", [])],
            "learning_objectives": [t for m in items for t in m.get("learning_objectives", [])],
            "lab": "\n".join(m.get("lab", "") for m in items),
            "minutes": sum(m["minutes"] for m in items) if all(m.get("minutes") for m in items) else None,
        })
        if budget and day["minutes"] and day["minutes"] > budget:
            errors.append(f"Day {day['day']} exceeds the requested daily hours")
    return {"title": source["name"], "overview": "Reference curriculum draft for client adaptation",
        "days": days, "planning_method": "offline_reference_draft", "source_file": source["source_file"],
        "requirement_brief": {"audience": request.audience_level or "To be confirmed"},
        "quality": {"status": "requires_regeneration" if errors else "requires_review",
                    "validation_errors": errors, "review_warnings": list(dict.fromkeys(warnings))}}
