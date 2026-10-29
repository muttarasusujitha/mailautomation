import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app import curriculum_reasoning as cr
from app.routes.toc import TocRequest, _apply_requirement_quality
from shared.toc_quality import toc_delivery_error


def source():
    return cr.prepare_records({"name": "Python", "days": [{"topic": "Python data pipelines", "subtopics": ["pandas", "CSV"], "lab": "Clean a CSV with pandas"}]}, "python.json")[0]


def brief():
    return cr.Brief(audience="Analysts", outcomes=["Clean business data"], required_topics=["pandas"],
                    excluded_topics=["Django"], prior_knowledge=["Python"], constraints=[], clarification_questions=[])


def plan():
    module = cr.PlanModule(title="pandas data preparation", minutes=180, subtopics=["pandas", "CSV validation"],
        tools=["Python"], lab="Clean a CSV dataset with pandas and demonstrate missing-value checks",
        learning_objectives=["Load CSV records", "Validate missing values"],
        assessment="Submit cleaned CSV and validation evidence", deliverable="Cleaned CSV", scenario="Sales rows contain missing values",
        source_ids=[source()["id"]], prerequisites=["Python functions"],
        preparation_requirements=["Sales CSV with seeded missing values and expected rejected rows"],
        client_outcome_indices=[0], acceptance_checks=[
            cr.AcceptanceCheck(input_or_condition="Valid sales row", expected_result="Accepted unchanged", evidence="Cleaned CSV"),
            cr.AcceptanceCheck(input_or_condition="Missing required ID", expected_result="Rejected with reason", evidence="Rejection report"),
            cr.AcceptanceCheck(input_or_condition="Repeated input run", expected_result="Identical partition", evidence="Output comparison")], delivery_steps=[
            cr.DeliveryStep(method="Demonstration", minutes=30, activity="Inspect seeded CSV errors", evidence="List of invalid rows"),
            cr.DeliveryStep(method="Guided lab", minutes=120, activity="Build and run CSV validation", evidence="Cleaned CSV and rejected rows"),
            cr.DeliveryStep(method="Assessment", minutes=30, activity="Test against seeded missing values", evidence="All seeded errors detected")])
    return cr.CurriculumPlan(title="Python for analysts", overview="Clean business data", prerequisites=["Python"],
        learning_outcomes=["Clean CSV data"], assumptions=[], clarification_questions=[], days=[cr.PlanDay(
            day=1, focus_area="pandas data preparation", subtopics=["pandas", "CSV validation"], tools=["Python", "pandas"],
            lab="Clean a CSV dataset with pandas and demonstrate missing-value checks", learning_objectives=["Load CSV records", "Validate missing values"],
            assessment="Submit cleaned CSV and validation evidence", deliverable="Cleaned CSV and validation report", scenario="A sales export contains missing values", minutes=180, source_ids=[source()["id"]], prerequisite_days=[], requirement_topics=["pandas"], modules=[module])])


def request(**kwargs):
    return TocRequest(domain="Python", duration_days=1, hours_per_day=3, custom_topics="pandas", **kwargs)


def test_dataset_preparation_preserves_provenance_and_invalidates_changed_content():
    first = source()
    changed = cr.prepare_records({"name": "Python", "days": [{"topic": "Python data pipelines", "subtopics": ["polars"]}]}, "python.json")[0]
    assert first["review_status"] == "unreviewed"
    assert first["id"] != changed["id"]
    assert first["source"] == "python.json"


def test_valid_plan_and_coverage():
    errors, coverage = cr.validate_plan(plan(), brief(), request(), [source()])
    assert not errors
    assert coverage == {"pandas": [1]}


def test_topic_coverage_does_not_substitute_for_client_objectives():
    client = brief()
    client.outcomes.append("Reconcile financial month-end totals")
    errors, _ = cr.validate_plan(plan(), client, request(), [source()])
    assert "Missing client outcome: Reconcile financial month-end totals" in errors
    value = plan()
    value.days[0].modules[0].client_outcome_indices = [99]
    errors, _ = cr.validate_plan(value, brief(), request(), [source()])
    assert any("valid client outcome indices" in error for error in errors)


def test_missing_preparation_and_duplicate_acceptance_cases_need_repair():
    value = plan()
    module = value.days[0].modules[0]
    module.preparation_requirements = []
    module.acceptance_checks[1] = module.acceptance_checks[0]
    errors, _ = cr.validate_plan(value, brief(), request(), [source()])
    assert any("trainer preparation" in error for error in errors)
    assert any("repeats acceptance cases" in error for error in errors)


def test_delivery_cannot_hide_overbooked_or_unverifiable_activities():
    value = plan()
    value.days[0].modules[0].delivery_steps[0].minutes = 60
    value.days[0].modules[0].delivery_steps[1].evidence = " "
    errors, _ = cr.validate_plan(value, brief(), request(), [source()])
    assert any("delivery minutes" in error for error in errors)
    assert any("observable evidence" in error for error in errors)


def test_missing_delivery_sequence_requires_regeneration():
    value = plan()
    value.days[0].modules[0].delivery_steps = []
    errors, _ = cr.validate_plan(value, brief(), request(), [source()])
    assert any("delivery minutes" in error for error in errors)


def test_reviewed_knowledge_requires_provenance():
    import pytest
    from fastapi import HTTPException
    from app.routes.toc_extended import _normalise_toc_knowledge
    with pytest.raises(HTTPException):
        _normalise_toc_knowledge({"name": "Python", "review_status": "approved"})
    result = _normalise_toc_knowledge({"name": "Python", "review_status": "approved", "version": "3.12",
        "official_sources": ["https://docs.python.org/3/"], "reviewed_by": "Curriculum owner", "reviewed_at": "2026-09-22"})
    assert result["review_status"] == "approved"


def test_citing_metadata_cannot_fake_coverage_and_exclusions_are_checked():
    value = plan()
    value.days[0].focus_area = "Django services"
    value.days[0].subtopics = ["Django models"]
    value.days[0].lab = "Build and deploy a Django web service"
    value.days[0].modules[0].title = "Django services"
    value.days[0].modules[0].subtopics = ["Django models"]
    value.days[0].modules[0].lab = value.days[0].lab
    errors, _ = cr.validate_plan(value, brief(), request(), [source()])
    assert any("excluded" in error for error in errors)
    assert "Missing requested topic: pandas" in errors


def test_invalid_citations_time_and_prerequisites_are_rejected():
    value = plan()
    value.days[0].source_ids = ["invented"]
    value.days[0].minutes = 500
    value.days[0].prerequisite_days = [1]
    errors, _ = cr.validate_plan(value, brief(), request(), [source()])
    assert any("source IDs" in error for error in errors)
    assert any("prerequisite" in error for error in errors)
    assert any("time budget" in error for error in errors)
    assert any("module minutes" in error for error in errors)


def test_local_filter_does_not_query_embeddings_or_cached_index():
    record = source()
    class Collection:
        def find(self, *args): return self
        async def to_list(self, *args): return [{"record_id": record["id"], "vector": [1.0, 0.0]}]
    client = SimpleNamespace(embeddings=SimpleNamespace(create=AsyncMock(return_value=SimpleNamespace(
        data=[SimpleNamespace(index=0, embedding=[1.0, 0.0])]))))
    result, metadata = asyncio.run(cr.retrieve(client, {"curriculum_embeddings": Collection()}, [record], ["tabular cleansing"], "test"))
    assert result == []
    assert metadata["method"] == "local_dataset_filter"
    client.embeddings.create.assert_not_awaited()


def test_local_matching_works_without_embedding_provider():
    client = SimpleNamespace(embeddings=SimpleNamespace(create=AsyncMock(side_effect=RuntimeError("quota"))))
    records, metadata = asyncio.run(cr.retrieve(client, None, [source()], ["pandas"], "test"))
    assert records
    assert metadata["method"] == "local_dataset_filter"
    assert not metadata["warnings"]
    client.embeddings.create.assert_not_awaited()


def test_unreviewed_sources_block_delivery_and_warnings_survive_route_quality(monkeypatch):
    async def structured(client, model, contract, *args):
        if contract is cr.Brief: return brief()
        if contract is cr.CurriculumPlan: return plan()
        return cr.CurriculumReview(supported_by_sources=True, fits_client_scope=True, prerequisites_ordered=True, issues=[])
    monkeypatch.setattr(cr, "structured", structured)
    monkeypatch.setattr(cr, "load_records", AsyncMock(return_value=[source()]))
    monkeypatch.setattr(cr, "retrieve", AsyncMock(return_value=([source()], {"method": "hybrid_semantic", "warnings": []})))
    result = asyncio.run(cr.generate_reasoned_toc(request(), object(), SimpleNamespace(OPENAI_MODEL="test")))
    _apply_requirement_quality(result, request())
    assert result["coverage_matrix"] == {"pandas": [1]}
    assert result["quality"]["status"] == "requires_review"
    assert toc_delivery_error(result)


def test_failed_review_blocks_even_structurally_valid_plan(monkeypatch):
    async def structured(client, model, contract, *args):
        if contract is cr.Brief: return brief()
        if contract is cr.CurriculumPlan: return plan()
        return cr.CurriculumReview(supported_by_sources=False, fits_client_scope=True, prerequisites_ordered=True, issues=["Unsupported lab capability"])
    monkeypatch.setattr(cr, "structured", structured)
    monkeypatch.setattr(cr, "load_records", AsyncMock(return_value=[source()]))
    monkeypatch.setattr(cr, "retrieve", AsyncMock(return_value=([source()], {"warnings": []})))
    result = asyncio.run(cr.generate_reasoned_toc(request(), object(), SimpleNamespace(OPENAI_MODEL="test")))
    assert result["quality"]["status"] == "requires_regeneration"
    assert "Unsupported lab capability" in result["quality"]["validation_errors"]


def test_ai_unavailable_template_is_review_only(monkeypatch):
    from app.routes import toc
    from test_toc_generation_modes import _Db
    monkeypatch.setattr(toc, "_generate_ai_toc", AsyncMock(return_value=None))
    result = asyncio.run(toc.generate_toc(request(), _Db()))
    assert toc_delivery_error(result["toc_data"])


def test_different_proposals_reach_planner_as_different_briefs(monkeypatch):
    seen = []
    async def structured(client, model, contract, instructions, data, *args):
        if contract is cr.Brief:
            value = brief()
            value.audience = data["audience_level"]
            return value
        if contract is cr.CurriculumPlan:
            seen.append(data["brief"]["audience"])
            value = plan()
            value.title = "Python for " + seen[-1]
            return value
        return cr.CurriculumReview(supported_by_sources=True, fits_client_scope=True, prerequisites_ordered=True, issues=[])
    monkeypatch.setattr(cr, "structured", structured)
    monkeypatch.setattr(cr, "load_records", AsyncMock(return_value=[source()]))
    monkeypatch.setattr(cr, "retrieve", AsyncMock(return_value=([source()], {"warnings": []})))
    settings = SimpleNamespace(OPENAI_MODEL="test")
    a = asyncio.run(cr.generate_reasoned_toc(request(audience_level="finance analysts"), object(), settings))
    b = asyncio.run(cr.generate_reasoned_toc(request(audience_level="data engineers"), object(), settings))
    assert a["title"] != b["title"]
    assert seen == ["finance analysts", "data engineers"]
