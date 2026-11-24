"""Complete offline delivery plans from curriculum content, without model calls."""
from copy import deepcopy


def complete_offline_programme(toc, request):
    """Add concrete proposed training activities; never assert they were approved."""
    from app.toc_generation_agent import _business_dates, _training_start_date
    days = toc.get("days") or []
    dates = _business_dates(_training_start_date(request.training_dates or ""), len(days))
    derived = False
    for index, day in enumerate(days):
        if request.training_dates and index < len(dates):
            day["date"] = dates[index]
        modules = day.get("modules") or [deepcopy({k: v for k, v in day.items() if k != "modules"})]
        for module in modules:
            preserve_authored = bool(module.get("content_quality_stage") or module.get("content_enrichment_version"))
            title = module.get("title") or module.get("topic") or module.get("focus_area") or "Training"
            module["title"] = title
            topics = module.get("subtopics") or []
            original_topics = deepcopy(topics)
            objectives = module.get("learning_objectives") or []
            scenarios = module.get("scenarios") or []
            suggested = list(module.get("proposed_fields") or [])
            if not topics:
                # Source execution plans specify demonstrable outcomes rather
                # than a separate topic list. Preserve those exact statements.
                topics = list(objectives) or [title]
                module["subtopics"] = topics
            scope = "; ".join(str(t) for t in topics[:3])
            if not module.get("lab"):
                module["lab"] = ("\n".join(s["activity"] for s in scenarios if s.get("activity"))
                    or f"Using a trainer-provided sample, complete {title}: {scope}. Record the initial state, implementation steps and validation result.")
                suggested.append("lab")
            if not objectives:
                module["learning_objectives"] = [f"Demonstrate {topic} using the training sample." for topic in topics[:3]]
                suggested.append("learning_objectives")
            if not module.get("deliverable"):
                module["deliverable"] = f"{title}: completed lab artefact, execution notes and validation evidence."
                suggested.append("deliverable")
            if not module.get("assessment"):
                module["assessment"] = ("\n".join(s["evidence"] for s in scenarios if s.get("evidence"))
                    or f"Review the submitted {title} artefact against: {scope}. Require a reproducible demonstration, one failure-case check and an explanation of the result.")
                suggested.append("assessment")
            if not module.get("scenario") and not scenarios:
                module["scenario"] = f"A team must demonstrate {title} on a representative sample before applying it to its own environment."
                suggested.append("scenario")
            if not preserve_authored and module.get("minutes") is None and len(modules) == 1 and request.hours_per_day:
                module["minutes"] = round(request.hours_per_day * 60)
                module["duration_basis"] = "Client-specified daily training budget"
            if preserve_authored:
                module["subtopics"] = original_topics
            if suggested:
                module["proposed_fields"] = suggested
                derived = True
        day["modules"] = modules
        day["subtopics"] = list(dict.fromkeys(str(t) for m in modules for t in m.get("subtopics", [])))
        day["learning_objectives"] = [v for m in modules for v in m.get("learning_objectives", [])]
        day["lab"] = "\n".join(m["lab"] for m in modules)
        if all(m.get("minutes") is not None for m in modules):
            day["minutes"] = sum(m["minutes"] for m in modules)
    toc["learning_outcomes"] = list(dict.fromkeys(o for d in days for o in d.get("learning_objectives", [])))
    toc.setdefault("requirement_brief", {})["audience"] = request.audience_level or "To be confirmed"
    if derived:
        quality = toc.setdefault("quality", {})
        quality.setdefault("review_warnings", []).append("Review proposed offline lab activities and assessment criteria with the trainer")
        if quality.get("status") != "requires_regeneration":
            quality["status"] = "requires_review"
    return toc
