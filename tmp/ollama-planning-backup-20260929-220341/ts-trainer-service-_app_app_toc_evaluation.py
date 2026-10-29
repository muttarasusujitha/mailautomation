"""Evidence-based TOC evaluation for manual and LLM-generated programmes.

This is a quality gate/report, not a content generator. A populated field does
not pass unless it has enough specific evidence for a client-facing TOC.
"""
from collections import Counter
import math
import re
from shared.toc_quality import topic_is_covered


QUALITY_STAGES = {"authored_pilot_pending_lab_validation", "manually_authored_pending_lab_validation"}


def _items(value):
    return value if isinstance(value, list) else []


def _minutes(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def concrete_acceptance_check(check):
    """Reject known boilerplate; this is a quality gate, not technical review."""
    if isinstance(check, str):
        return bool(check.strip())
    if not isinstance(check, dict):
        return False
    values = [str(check.get(key) or "").strip() for key in
              ("input_or_condition", "expected_result", "evidence")]
    if not all(values):
        return False
    generic = (
        r"\bmeets? (?:the |stated )?(?:learning )?objectives\b",
        r"\bparticipant completes the lab\b",
        r"\bdescribes an appropriate correction\b",
        r"\bapplies the same method to the new example\b",
        r"\b(?:standard exercise|a failure case) (?:for|in)\b",
        r"\b(?:recorded assessment results|independent output reviewed against the objectives)\b",
        r"\bcompleted lab output for\b",
    )
    return not any(re.search(pattern, value, re.I) for pattern in generic for value in values)


def evaluate_toc(toc, required_topics=(), requested_days=None, excluded_topics=(), hours_per_day=None):
    days = toc.get("days") or []
    modules = [module for day in days for module in (day.get("modules") or [day])]
    issues, strengths, blocking = [], [], []
    if requested_days is not None and len(days) != requested_days:
        issues.append(f"Requested {requested_days} days; generated {len(days)} days")
        blocking.append(issues[-1])
    if not modules:
        return {"status": "fail", "score": 0, "issues": ["No modules were generated"], "strengths": []}

    topic_text = " ".join(" ".join(str(value) for value in [m.get("title"), m.get("topic"), m.get("focus_area"), *(_items(m.get("subtopics")))]) for m in modules).lower()
    missing = [topic for topic in required_topics if not topic_is_covered(topic, topic_text)]
    if missing:
        issues.append("Missing requested topics: " + ", ".join(missing))
        blocking.append(issues[-1])
    excluded = [topic for topic in excluded_topics if topic_is_covered(topic, topic_text)]
    if excluded:
        blocking.append("Excluded topics present: " + ", ".join(excluded))
        issues.append(blocking[-1])

    detailed, assessable, timed, reviewed = 0, 0, 0, 0
    for index, module in enumerate(modules, 1):
        label = module.get("title") or module.get("topic") or f"Module {index}"
        if len(_items(module.get("subtopics"))) < 3:
            issues.append(f"{label}: fewer than three specific subtopics")
        if not str(module.get("lab") or module.get("lab_task") or "").strip():
            issues.append(f"{label}: no practical lab")
            blocking.append(issues[-1])
        if not str(module.get("deliverable") or "").strip():
            issues.append(f"{label}: no participant deliverable")
            blocking.append(issues[-1])
        checks = _items(module.get("acceptance_checks"))
        assessment = str(module.get("assessment") or "").strip()
        valid_checks = [c for c in checks if concrete_acceptance_check(c)]
        # Changing the input label must not make three identical tests pass.
        signatures = [str((c.get("expected_result", "").strip().lower(),
                           c.get("evidence", "").strip().lower())) if isinstance(c, dict)
                      else c.strip().lower() for c in valid_checks]
        if (module.get("content_quality_stage") in QUALITY_STAGES
                and str(module.get("review_status") or "").lower() != "reviewed"):
            # Manually authored material remains valuable but cannot count as
            # approved assessment evidence until its technical review is done.
            valid_checks = []
        # Length is not proof of specificity: generic enrichment produces long
        # paragraphs too. A prose assessment remains an item for human review.
        if len(valid_checks) >= 3 and len(set(signatures)) == len(valid_checks):
            assessable += 1
        else:
            issues.append(f"{label}: no concrete acceptance evidence")
        steps = _items(module.get("delivery_steps"))
        if len(steps) >= 3 and all(isinstance(step, dict) and str(step.get("activity") or "").strip() and str(step.get("evidence") or "").strip() for step in steps):
            detailed += 1
            minutes = [step.get("minutes") for step in steps if isinstance(step, dict)]
            if minutes and all(_minutes(value) for value in minutes):
                if module.get("minutes") is not None and (not _minutes(module["minutes"]) or abs(sum(minutes) - module["minutes"]) > 0.01):
                    blocking.append(f"{label}: activity durations do not equal module duration")
                    issues.append(blocking[-1])
                else:
                    timed += 1
            else:
                issues.append(f"{label}: activity durations need confirmation")
        else:
            issues.append(f"{label}: delivery sequence lacks activity/evidence")
        if _items(module.get("prerequisites")) and _items(module.get("preparation_requirements")):
            reviewed += 1
        else:
            issues.append(f"{label}: prerequisites or trainer preparation missing")

    for day in days:
        budget = day.get("hours_per_day") or hours_per_day or toc.get("hours_per_day")
        entries = day.get("modules") or [day]
        durations = [m.get("minutes") for m in entries]
        if _minutes(budget) and all(_minutes(v) for v in durations) and sum(durations) > budget * 60:
            blocking.append(f"Day {day.get('day', '?')}: planned modules exceed daily hours")
            issues.append(blocking[-1])

    total = len(modules)
    score = round(100 * (0.30 * detailed / total + 0.30 * assessable / total + 0.20 * reviewed / total + 0.20 * timed / total))
    if detailed == total: strengths.append("Every module has a delivery sequence with participant activity and evidence")
    if assessable == total: strengths.append("Every module has assessment evidence")
    if timed == total: strengths.append("Every module has a timed delivery plan")
    status = "fail" if blocking or score < 50 else "pass" if score >= 85 and not issues else "review"
    return {"status": status, "score": score, "issues": list(dict.fromkeys(issues)), "strengths": strengths,
            "module_count": total, "detailed_modules": detailed, "assessable_modules": assessable,
            "timed_modules": timed, "ready_modules": reviewed, "blocking_issues": blocking,
            "technical_accuracy_verified": False, "score_meaning": "Completeness of assessable delivery evidence, not technical accuracy"}


def catalog_summary(records):
    stages = Counter(record.get("content_quality_stage") or "generic_or_unreviewed_source" for record in records)
    return {"records": len(records), "stages": dict(stages),
            "manually_authored_records": sum(stages[stage] for stage in QUALITY_STAGES),
            "technical_review_complete": False}
