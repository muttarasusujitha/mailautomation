import json
from copy import deepcopy
from app.apply_quality_pilots import ROOT, apply_document
from app.curriculum_reasoning import builtin_records
from app.reference_planner import reference_draft
from app.routes.toc import TocRequest


def test_authored_pilots_reach_reasoning_with_evidence_and_provenance():
    records = [r for r in builtin_records() if r["content_quality_stage"] == "authored_pilot_pending_lab_validation"]
    assert len(records) == 5
    for record in records:
        assert record["source_urls"] and record["prerequisites"] and record["preparation_requirements"]
        assert record["review_status"] == "unreviewed"
        assert record["scenario"] and record["assessment"]
        assert sum(s["minutes"] for s in record["delivery_steps"]) == record["minutes"]
        assert all(s["minutes"] > 0 and s["evidence"] for s in record["delivery_steps"])


def test_reapplication_preserves_original_reference_and_authored_content():
    for pilot in json.loads((ROOT / "quality_pilots.json").read_text(encoding="utf-8")):
        document = json.loads((ROOT / pilot["file"]).read_text(encoding="utf-8"))
        assert apply_document(deepcopy(document), pilot["file"]) == document


def test_template_keeps_specific_scenario_and_acceptance_checks():
    toc = reference_draft(TocRequest(domain="AWS Security", duration_days=10, hours_per_day=4))
    module = toc["days"][5]["modules"][0]
    pilot = next(p for p in json.loads((ROOT / "quality_pilots.json").read_text(encoding="utf-8")) if p.get("reference_day") == 6)
    assert module["scenario"] == pilot["scenario"]
    assert "Count mode" in module["assessment"]
    assert sum(s["minutes"] for s in module["delivery_steps"]) == 240
