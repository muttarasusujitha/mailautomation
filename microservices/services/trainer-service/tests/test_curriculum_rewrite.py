from copy import deepcopy
import pytest
from app import rewrite_curriculum_content as rewrite


def module():
    return rewrite.Module(key="sample", subtopics=["CSV parsing", "Duplicate IDs", "Rejection reasons"],
        scenario="Sales import contains duplicate IDs", lab="Partition ten rows into accepted and rejected CSV files",
        deliverable="Two CSV files and a validation script", learning_objectives=["Detect repeated IDs", "Reconcile input and output counts"],
        assessment="Every input row appears once across accepted and rejected files",
        acceptance_checks=[rewrite.Check(input_or_condition=value, expected_result=result, evidence="CSV row and reason")
            for value, result in [("Unique ID", "Accepted"), ("Duplicate ID", "Rejected"), ("Repeated run", "Identical output")]],
        prerequisites=["Python functions"], preparation_requirements=["Ten-row CSV fixture"], minutes=90,
        delivery_steps=[rewrite.Step(method="Practice", minutes=90, activity="Validate CSV", evidence="Partitioned CSV files")],
        unresolved_questions=[])


def test_validation_rejects_duplicate_cases_and_wrong_time():
    value = module()
    rewrite.validate(value, {"key": "sample", "minutes": 90})
    value.acceptance_checks[1].input_or_condition = "Unique ID"
    with pytest.raises(ValueError, match="Duplicated"):
        rewrite.validate(value, {"key": "sample"})
    value = module()
    value.delivery_steps[0].minutes = 60
    with pytest.raises(ValueError, match="budget"):
        rewrite.validate(value, {"key": "sample"})


def test_cached_candidate_cannot_change_source_duration(tmp_path, monkeypatch):
    monkeypatch.setattr(rewrite, "CACHE", tmp_path)
    rewrite.write_json(tmp_path / "candidates/sample.json", {"module": module().model_dump()})
    with pytest.raises(ValueError, match="duration"):
        rewrite.cached("sample", {"key": "sample", "minutes": 120})


def test_resume_uses_original_source_after_application():
    source = {"topic": "CSV", "subtopics": ["Parsing"], "lab_task": "Load sales", "minutes": 90}
    doc = {"name": "Python"}
    edited = deepcopy(source)
    edited["content_before_rewrite"] = deepcopy(source)
    edited["subtopics"] = ["New detail"]
    assert rewrite.source_input(doc, source) == rewrite.source_input(doc, edited)


def test_inventory_preserves_pilots_and_deduplicates_variants(tmp_path):
    source = {"name": "Python", "days": [{"topic": "CSV", "lab_task": "Load rows"},
        {"topic": "Pilot", "content_quality_stage": "authored_pilot_pending_lab_validation"}]}
    for name in ("a", "b"):
        rewrite.write_json(tmp_path / "datasets_compact" / (name + ".json"), source)
    documents, pending = rewrite.inventory(tmp_path)
    assert len(documents) == 2
    assert len(pending) == 1
