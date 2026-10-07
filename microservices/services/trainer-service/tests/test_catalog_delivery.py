from copy import deepcopy
from app.enrich_curriculum_catalog import enrich_entry, VERSION
from app.curriculum_reasoning import builtin_records
from app.toc_generation_agent import generate_toc_from_dataset


def test_enrichment_preserves_source_and_is_idempotent():
    source = {"topic": "SQL joins", "subtopics": ["LEFT JOIN", "NULL"],
              "lab_task": "Find customers without orders", "deliverable": "Reviewed SQL query"}
    enriched = enrich_entry(deepcopy(source))
    assert all(enriched[key] == value for key, value in source.items())
    assert "deliverable" not in enriched["proposed_fields"]
    assert enrich_entry(deepcopy(enriched)) == enriched
    assert all(step["minutes"] is None for step in enriched["delivery_steps"])


def test_entire_compact_catalog_has_delivery_content():
    records = [r for r in builtin_records() if r["source_file"].endswith(".json") and not r["version"].startswith("reference-import")]
    assert len(records) >= 2950
    assert all(r["lab"] and r["deliverable"] and r["assessment"] and r["delivery_steps"] for r in records)
    assert all(r["review_status"] == "unreviewed" for r in records)


def test_template_generation_preserves_dataset_delivery():
    toc = generate_toc_from_dataset("Python", 2)
    first = toc["days"][0]
    assert first["delivery_steps"]
    assert first["deliverable"]
    assert first["assessment"]
    assert "delivery_steps" in first["proposed_fields"]
