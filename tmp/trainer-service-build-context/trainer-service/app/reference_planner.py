"""Offline reference drafts preserve source scope and time; never imply approval."""
import json
import re
from pathlib import Path

from shared.toc_quality import normalize_topic, topic_is_covered


def _pack_modules(modules, budget, warnings):
    days = []
    for module in modules:
        remaining = module["minutes"]
        segments = []
        while remaining:
            if not days or sum(m["minutes"] for m in days[-1]["modules"]) >= budget:
                days.append({"day": len(days) + 1, "modules": []})
            available = budget - sum(m["minutes"] for m in days[-1]["modules"])
            item = {**module, "minutes": min(remaining, available)}
            days[-1]["modules"].append(item)
            segments.append(item)
            remaining -= item["minutes"]
        if len(segments) > 1:
            topics = module.get("subtopics") or module.get("learning_objectives") or [module["topic"]]
            for index, item in enumerate(segments):
                start, end = index * len(topics) // len(segments), (index + 1) * len(topics) // len(segments)
                item["topic"] += f" (part {index + 1}/{len(segments)})"
                item["subtopics"] = topics[start:end] or [f"Applied practice: {module['topic']}"]
                item["continuation_of"] = module["topic"]
            warnings.append("Split-module topic distribution is proposed for trainer review")
    return days


def reference_draft(request):
    key = normalize_topic(request.domain)
    aliases = {
        "codex": "codex_for_developers", "codex for developers": "codex_for_developers",
        "enterprise ai readiness": "enterprise_ai_readiness_genai_for_bi_capstone_track",
        "engineering security product": "engineering_security_product",
        "aws security devops sre": "aws_cloud_security_devops_sre",
        "aws security": "aws_cloud_security_devops_sre",
        "quality engineers": "training_for_quality_engineers",
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
    # Remove identities belonging to the example's client, not the new request.
    modules = json.loads(re.sub(r"\b(?:ADA|Ratings Tech|GAC Tech CoE|FinPay)\b", "sample organisation", json.dumps(modules)))
    for module in modules:
        if module.get("reference_text") and not module.get("lab"):
            prose = module["reference_text"]
            parts = re.split(r"(?m)^Lab \d+:\s*", prose, maxsplit=1)
            module["subtopics"] = [line for line in parts[0].splitlines()
                if line not in {"Topics", "o", "•"} and len(line) > 3]
            if len(parts) == 2:
                lab, *deliverable = re.split(r"(?m)^Lab Deliverable\s*", parts[1], maxsplit=1)
                module["lab"] = lab.strip()
                if deliverable:
                    module["deliverable"] = deliverable[0].strip()
    count = int(request.duration_days)
    budget = int(request.hours_per_day * 60) if request.hours_per_day else None
    if budget is not None and budget < 1:
        raise ValueError("Training budget must be at least one minute")
    # Explicit topic lists can narrow a reference. Preserve original ordering,
    # and report unknown topics rather than replacing them with unrelated ones.
    requested = [s.strip() for s in re.split(r"[;,\n]+", request.custom_topics or "") if s.strip()]
    narrow = [t for t in requested if normalize_topic(t) not in {key, normalize_topic(source["name"])}]
    missing = []
    if narrow:
        selected_ids = set()
        for topic in narrow:
            exact_modules = [i for i, m in enumerate(modules) if topic_is_covered(topic, m["topic"])]
            selected_ids.update(exact_modules or [i for i, m in enumerate(modules) if topic_is_covered(topic, json.dumps(m))])
        matched = [m for i, m in enumerate(modules) if i in selected_ids]
        missing = [t for t in narrow if not any(topic_is_covered(t, json.dumps(m)) for m in modules)]
        if matched:
            modules = matched
            warnings.append("Topic selection follows the explicit topic list; trainer must confirm prerequisite sufficiency")
    estimated = False
    if budget and modules and any(not m.get("minutes") for m in modules):
        # Estimates are scheduling proposals, not durations claimed by sources.
        fixed = sum(m.get("minutes") or 0 for m in modules)
        unknown = [m for m in modules if not m.get("minutes")]
        available = count * budget - fixed
        if available >= 30 * len(unknown):
            base, extra = divmod(available, len(unknown))
            for index, module in enumerate(unknown):
                module["minutes"] = base + (index < extra)
                module["duration_basis"] = "Proposed equal allocation of remaining client training budget"
            estimated = True
            warnings.append("Module times are proposed estimates; confirm feasibility with the trainer")
    days = []
    if not narrow and not estimated and all(m.get("reference_day") for m in modules) and (
        not budget or (max(m["reference_day"] for m in modules) == count and all(
            sum(m["minutes"] for m in modules if m["reference_day"] == n) <= budget
            for n in {m["reference_day"] for m in modules}))):
        for number in sorted({m["reference_day"] for m in modules}):
            days.append({"day": number, "modules": [m for m in modules if m["reference_day"] == number]})
    elif budget and all(m.get("minutes") for m in modules):
        days = _pack_modules(modules, budget, warnings)
    else:
        # Keep unknown module durations unknown; do not fabricate a schedule.
        days = [{"day": 1, "modules": modules}]
        warnings.append("Module durations must be confirmed before allocating the requested days")
    errors = ["Requested topic is missing from this reference: " + topic for topic in missing]
    if len(days) != count:
        errors.append(f"Reference requires {len(days)} planned days; client requested {count}. Adapt scope before delivery.")
    for day in days:
        items = day["modules"]
        for item in items:
            item["title"] = item["topic"]
            item["scenario"] = item.get("scenario") or "\n".join(s["situation"] for s in item.get("scenarios", []))
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
