"""Select explicit manual topic requests from existing source modules.

No inference of free-text intent or invention of missing curriculum. The caller
continues to flag missing scope and timing for review.
"""
from copy import deepcopy
import re
from shared.toc_quality import topic_is_covered, normalize_topic


def select_requested_curriculum(domain, topics, knowledge=None):
    requested = [value.strip() for value in re.split(r"[;,\n]+", topics or "") if value.strip()]
    if not requested:
        return knowledge
    from app.curriculum_reasoning import builtin_records
    if knowledge:
        from app.curriculum_reasoning import prepare_records
        records = prepare_records(knowledge, "client_knowledge")
    else:
        records = [r for r in builtin_records() if normalize_topic(r["domain"]) == normalize_topic(domain)]
    selected, seen = [], set()
    for record in records:
        coverage = " ".join([record["title"], *record.get("subtopics", [])])
        if not any(topic_is_covered(topic, coverage) for topic in requested):
            continue
        key = normalize_topic(record["title"])
        if key in seen:
            continue
        seen.add(key)
        module = deepcopy(record)
        module.update(topic=record["title"], learning_objectives=record.get("objectives") or [],
                      content_enrichment_version=record.get("content_enrichment_version") or "selected-source")
        selected.append(module)
    if not selected:
        return knowledge
    # Place modules in request order, retaining source order within each topic.
    selected.sort(key=lambda m: next(i for i, topic in enumerate(requested)
        if topic_is_covered(topic, " ".join([m["topic"], *m.get("subtopics", [])]))))
    return {"name": domain, "days": selected, "explicit_topic_selection": True}
