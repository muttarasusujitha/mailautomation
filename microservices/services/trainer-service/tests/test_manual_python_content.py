import json
from app.apply_manual_python_content import ROOT, STAGE
from app.curriculum_reasoning import builtin_records
from app.toc_generation_agent import _day_entry


def test_manual_python_batch_is_distinct_and_reaches_reasoning():
    authored = json.loads((ROOT / "manual_python_content.json").read_text(encoding="utf-8"))
    assert len(authored) == len({row[0] for row in authored}) == 29
    assert len({row[2] for row in authored}) == 29
    records = [record for record in builtin_records() if record["content_quality_stage"] == STAGE and record["domain"] == "Python"]
    assert len(records) >= 58
    assert all(len(record["acceptance_checks"]) == 3 for record in records)
    assert all(record["review_status"] == "unreviewed" for record in records)


def test_every_authored_module_survives_manual_final_day_generation():
    for path in (ROOT / "datasets_compact").glob("python*.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        for source in document.get("days", []):
            if source.get("content_quality_stage") != STAGE:
                continue
            result = _day_entry(document, source, 5, 5, "")
            assert result["focus_area"] == source["topic"]
            for key in ("lab", "deliverable", "assessment", "learning_objectives", "acceptance_checks", "delivery_steps"):
                assert result[key] == source[key]
            assert source["content_before_manual_rewrite"]
