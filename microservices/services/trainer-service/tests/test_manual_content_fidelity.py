from copy import deepcopy
from app.toc_generation_agent import _day_entry
from app.offline_programme import complete_offline_programme
from app.routes.toc import TocRequest


def test_manual_final_day_preserves_authored_content_and_evidence():
    source = {"topic": "CSV validation", "subtopics": ["Duplicate IDs", "Rejected-row report"],
        "lab": "Partition the ten-row fixture", "learning_objectives": ["Reconcile all ten rows"],
        "deliverable": "Accepted and rejected CSV files", "assessment": "Six accepted, four rejected",
        "acceptance_checks": [{"input_or_condition": "Repeated ID", "expected_result": "Rejected", "evidence": "Report"}],
        "content_quality_stage": "authored_pilot_pending_lab_validation", "minutes": 150,
        "prerequisites": ["Python functions"], "source_urls": ["https://docs.python.org/3/library/csv.html"],
        "delivery_steps": [{"method": "Lab", "minutes": 150, "activity": "Partition fixture", "evidence": "CSV files"}]}
    original = deepcopy(source)
    day = _day_entry({"name": "Python"}, source, 5, 5, "")
    toc = complete_offline_programme({"days": [day]}, TocRequest(domain="Python", duration_days=5, hours_per_day=4))
    module = toc["days"][0]["modules"][0]
    assert "Capstone" not in day["title"]
    for key in source:
        if key != "topic": assert module[key] == source[key]
    assert source == original
