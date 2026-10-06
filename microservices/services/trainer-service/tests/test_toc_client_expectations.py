from copy import deepcopy
import pytest
from app.toc_evaluation import evaluate_toc
from app.scoped_curriculum import select_requested_curriculum
from app.toc_generation_agent import generate_toc_from_dataset, validate_toc


def module():
    return {"day": 1, "topic": "CSV", "subtopics": ["CSV parsing", "Duplicate IDs", "Errors"],
        "lab": "Partition ten sales rows", "deliverable": "Accepted and rejected CSV files",
        "acceptance_checks": ["Unique ID accepted", "Duplicate ID rejected", "Repeated run identical"],
        "prerequisites": ["Python"], "preparation_requirements": ["Ten-row sales fixture"], "minutes": 90,
        "delivery_steps": [{"method": "Demo", "minutes": 20, "activity": "Inspect rows", "evidence": "Baseline"},
        {"method": "Lab", "minutes": 50, "activity": "Build validator", "evidence": "CSV files"},
        {"method": "Assessment", "minutes": 20, "activity": "Run checks", "evidence": "Reconciled rows"}]}


@pytest.mark.parametrize("fault", ["days", "lab", "deliverable", "module_time", "daily_time", "malformed_steps", "empty_checks", "excluded"])
def test_evidence_score_cannot_hide_material_faults(fault):
    value = module()
    kwargs = {"requested_days": 1}
    if fault == "days": kwargs["requested_days"] = 2
    if fault in {"lab", "deliverable"}: value[fault] = ""
    if fault == "module_time": value["minutes"] = 60
    if fault == "daily_time": kwargs["hours_per_day"] = 1
    if fault == "malformed_steps": value["delivery_steps"] = ["demo", "lab", "assessment"]
    if fault == "empty_checks":
        value["acceptance_checks"] = ["", "", ""]
        value["assessment"] = "Review the results and complete the exercise. " * 20
    if fault == "excluded": kwargs["excluded_topics"] = ["CSV"]
    result = evaluate_toc({"days": [value]}, **kwargs)
    assert result["status"] != "pass"
    assert result["technical_accuracy_verified"] is False


def test_two_client_objectives_select_different_source_content():
    analytics = select_requested_curriculum("Python", "Pandas")
    api = select_requested_curriculum("Python", "FastAPI")
    assert analytics and api
    assert {m["topic"] for m in analytics["days"]} != {m["topic"] for m in api["days"]}
    for source, expected in [(analytics, "pandas"), (api, "fastapi")]:
        toc = generate_toc_from_dataset("Python", 1, domain_override=source)
        assert expected in str(toc["days"][0]).lower()


def test_validation_cannot_erase_existing_review_findings_or_pad_authored_topics():
    day = module()
    day.update(content_quality_stage="manually_authored_pending_lab_validation", focus_area="CSV")
    original = deepcopy(day["subtopics"])
    toc = validate_toc({"days": [day], "quality": {"status": "requires_regeneration", "validation_errors": ["Excluded topic"]}}, 1)
    assert toc["quality"]["status"] == "requires_regeneration"
    assert toc["quality"]["validation_errors"] == ["Excluded topic"]
    assert toc["days"][0]["subtopics"] == original
