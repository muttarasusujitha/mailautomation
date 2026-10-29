import json
from app.apply_manual_priority_content import ROOT, STAGE
from app.curriculum_reasoning import builtin_records
from app.toc_generation_agent import _day_entry


def test_priority_content_is_specific_and_survives_manual_generation():
    entries = json.loads((ROOT / "manual_priority_content.json").read_text(encoding="utf-8"))
    assert len(entries) == 10
    records = [r for r in builtin_records() if r["content_enrichment_version"] == "manual-priority-v1"]
    assert len(records) == 10
    assert all(len(r["acceptance_checks"]) == 3 and r["review_status"] == "unreviewed" for r in records)
    for record in records:
        item = {**record, "topic": record["title"]}
        day = _day_entry({"name": record["domain"]}, item, 5, 5, "")
        assert day["lab"] == record["lab"]
        assert day["acceptance_checks"] == record["acceptance_checks"]
