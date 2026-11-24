from app.toc_evaluation import evaluate_toc
from app.toc_generation_agent import generate_toc_from_dataset


SCENARIOS = [
    ("Python", 5, "beginner", ["Python"]),
    ("DevOps", 5, "intermediate", ["DevOps"]),
    ("Power BI", 5, "beginner", ["Power BI"]),
    ("Agentic AI", 5, "intermediate", ["Agentic"]),
    ("Java", 5, "beginner", ["Java"]),
]


def test_domain_scenarios_generate_requested_days_and_are_evaluated_honestly():
    for domain, duration, level, topics in SCENARIOS:
        toc = generate_toc_from_dataset(domain, duration, level=level)
        report = evaluate_toc(toc, topics, duration)
        assert report["module_count"] >= duration
        assert report["status"] in {"pass", "review", "fail"}
        assert 0 <= report["score"] <= 100


def test_evaluation_does_not_equate_populated_generic_fields_with_high_quality():
    report = evaluate_toc({"days": [{"topic": "Docker", "subtopics": ["Containers"],
        "lab": "Try Docker", "deliverable": "Notes", "assessment": "Done",
        "delivery_steps": [{"method": "Lab", "activity": "Try Docker", "evidence": "Notes"}]}]})
    assert report["status"] == "fail"
    assert report["score"] < 50


def test_evaluation_requires_a_real_timed_plan_for_pass():
    module = {"topic": "CSV validation", "subtopics": ["Parsing", "Duplicates", "Errors"],
        "lab": "Partition ten rows", "deliverable": "Accepted and rejected CSV files",
        "acceptance_checks": ["valid row accepted", "duplicate rejected", "repeatable output"],
        "prerequisites": ["Python"], "preparation_requirements": ["ten-row fixture"],
        "delivery_steps": [{"method": "Demo", "minutes": 20, "activity": "Show fixture", "evidence": "baseline"},
                           {"method": "Lab", "minutes": 50, "activity": "Build validator", "evidence": "CSV files"},
                           {"method": "Assessment", "minutes": 20, "activity": "Run checks", "evidence": "results"}]}
    report = evaluate_toc({"days": [module]})
    assert report["status"] == "pass"
    assert report["score"] == 100


def test_manual_toc_with_generic_evidence_cannot_be_approved_for_delivery():
    toc = generate_toc_from_dataset("DevOps", 5, level="intermediate")
    quality = toc["quality"]
    assert quality["content_evaluation"]["status"] in {"review", "fail"}
    assert quality["status"] in {"requires_review", "requires_regeneration"}
