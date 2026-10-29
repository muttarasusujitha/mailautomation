from app.curriculum_reasoning import builtin_records
from app.reference_planner import reference_draft
from app.routes.toc import TocRequest


def test_all_five_reference_sources_are_loaded_without_claiming_approval():
    records = [r for r in builtin_records() if r["version"] == "reference-import-v2"]
    assert len(records) == 64
    assert len({r["source_file"] for r in records}) == 5
    assert all(r["source_locator"] and r["review_status"] == "unreviewed" for r in records)
    assert any(r["scenarios"] and r["deliverable"] and r["minutes"] for r in records)
    assert any(r["review_warnings"] for r in records)
    assert all(r["subtopics"] and r["lab"] and r["deliverable"] and r["assessment"] for r in records)
    assert all(r["delivery_steps"] and "delivery_steps" in r["proposed_fields"] for r in records)
    assert all(step["minutes"] is None for r in records if r["content_quality_stage"] != "authored_pilot_pending_lab_validation" for step in r["delivery_steps"])
    aws = [r for r in records if r["domain"] == "AWS Cloud Security, DevOps & SRE"]
    assert all("On a trainer-prepared sample" not in r["lab"] for r in aws)
    assert any("IaC starter" in r["lab"] for r in aws)


def test_manual_execution_plan_retains_eight_modules_and_twelve_hours():
    toc = reference_draft(TocRequest(domain="Engineering Security Product", duration_days=2, hours_per_day=6))
    assert len(toc["days"]) == 2
    assert sum(len(d["modules"]) for d in toc["days"]) == 8
    assert sum(d["minutes"] for d in toc["days"]) == 720
    assert toc["quality"]["status"] == "requires_review"


def test_reference_duration_conflict_is_not_silently_compressed():
    toc = reference_draft(TocRequest(domain="Enterprise AI Readiness", duration_days=2, hours_per_day=6))
    assert len(toc["days"]) > 2
    assert all(day["minutes"] <= 360 for day in toc["days"])
    assert toc["quality"]["status"] == "requires_regeneration"
    assert toc["quality"]["validation_errors"]


def test_quality_engineer_core_preserves_hours_and_excludes_leadership():
    toc = reference_draft(TocRequest(domain="Quality Engineering", duration_days=18, hours_per_day=4))
    assert sum(d["minutes"] for d in toc["days"]) == 72 * 60
    assert all(m.get("track") == "core" for d in toc["days"] for m in d["modules"])


def test_codex_times_are_explicit_proposals_that_fit_client_budget():
    toc = reference_draft(TocRequest(domain="Codex", duration_days=3, hours_per_day=8))
    assert len(toc["days"]) == 3
    assert sum(d["minutes"] for d in toc["days"]) == 1440
    assert all("Proposed" in m["duration_basis"] for d in toc["days"] for m in d["modules"])
    assert toc["quality"]["status"] == "requires_review"


def test_explicit_topics_select_relevant_reference_modules():
    toc = reference_draft(TocRequest(domain="Quality Engineering", duration_days=3, hours_per_day=4, custom_topics="Python"))
    modules = [m for d in toc["days"] for m in d["modules"]]
    assert len(toc["days"]) == 3
    assert all("Python" in m["topic"] for m in modules)
    topics = [t for m in modules for t in m["subtopics"]]
    assert len(topics) == len(set(topics))


def test_offline_completion_populates_real_review_fields_without_model():
    from app.offline_programme import complete_offline_programme
    request = TocRequest(domain="AWS Security", duration_days=10, hours_per_day=4, training_dates="2026-11-02")
    toc = complete_offline_programme(reference_draft(request), request)
    assert toc["days"][0]["date"] == "02-Nov-2026"
    for day in toc["days"]:
        for module in day["modules"]:
            assert all(module.get(key) for key in ("lab", "deliverable", "assessment", "learning_objectives", "scenario"))
            assert module["proposed_fields"]
    assert toc["quality"]["status"] == "requires_review"


def test_unknown_requested_topic_is_reported():
    toc = reference_draft(TocRequest(domain="Quality Engineering", custom_topics="Unlisted product", hours_per_day=4))
    assert any("Unlisted product" in e for e in toc["quality"]["validation_errors"])


def test_unrelated_domain_still_uses_existing_dataset_generator():
    assert reference_draft(TocRequest(domain="Java")) is None


def test_ai_off_never_calls_model_even_with_legacy_enrichment_flag(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock
    from app.routes import toc
    from test_toc_generation_modes import _Db
    generate, enrich = AsyncMock(), AsyncMock()
    monkeypatch.setattr(toc, "_generate_ai_toc", generate)
    monkeypatch.setattr(toc, "_enrich_manual_toc_if_available", enrich)
    result = asyncio.run(toc.generate_toc(TocRequest(domain="Python", generation_mode="template",
        duration_days=2, hours_per_day=4, allow_ai_enrichment=True), _Db()))
    generate.assert_not_awaited()
    enrich.assert_not_awaited()
    assert all(day["modules"] for day in result["toc_data"]["days"])
