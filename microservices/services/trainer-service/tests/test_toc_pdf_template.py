"""The ToC PDF is a course outline: cover, details, then days, modules, and labs."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.toc_pdf_template import build_toc_html

SAMPLE_TOC = {
    "title": "DevOps Engineering with AWS",
    "domain": "DevOps",
    "duration_days": 2,
    "mode": "online",
    "level": "Intermediate",
    "learning_outcomes": [
        "Build a CI pipeline that tests and packages a service on every commit.",
        "Containerise an application and run it on Amazon EKS.",
    ],
    "prerequisites": ["Basic Linux commands", "Git fundamentals"],
    "quality": {"status": "approved", "review_warnings": ["internal note"]},
    "sources": [{"id": "SRC-1", "title": "internal dataset"}],
    "trainer_notes": "Internal: trainer rate agreed",
    "days": [
        {
            "day": 1, "focus_area": "Continuous Integration", "minutes": 480, "date": "2027-01-04",
            "assessment": "Participants fix a failing pipeline without trainer help.",
            "modules": [{
                "title": "Pipeline Architecture",
                "subtopics": [
                    "CI versus CD responsibilities",
                    "Pipeline stages: build, test, scan, package",
                    {"topic": "Triggers", "items": ["push", "pull request", "schedule"]},
                ],
                "tools": ["GitHub Actions", "Docker"],
                "scenario": "A payment service release fails intermittently in CI.",
                "lab": "Build a CI pipeline. Add unit tests, a container build, and an image scan.",
                "deliverable": "A passing pipeline run with a scanned image tag.",
                "acceptance_checks": [
                    {"input_or_condition": "push", "expected_result": "The pipeline runs on every push.", "evidence": "run log"},
                    {"input_or_condition": "bad test", "expected_result": "A failing test blocks packaging.", "evidence": "red run"},
                ],
                "preparation_requirements": ["Trainer creates the starter repo"],
                "delivery_steps": [{"method": "demo", "minutes": 60, "activity": "x", "evidence": "y"}],
            }],
        },
        {
            "day": 2, "focus_area": "Containers on EKS", "minutes": 480,
            "subtopics": ["EKS cluster architecture", "Deployments and Services"],
            "lab_task": "Deploy the service to EKS",
        },
    ],
}


def test_outline_has_cover_details_days_modules_and_labs_in_order():
    html = build_toc_html(SAMPLE_TOC)
    order = ["COURSE OUTLINE", "Course Name", "Duration", "Learning Objectives", "Prerequisites",
             "Course Outline", "Day 1 \u2013 Continuous Integration", "Module 1: Pipeline Architecture",
             "Lab 1: Pipeline Architecture", "<li>Build a CI pipeline</li>", "Participants verify that:", "Lab Deliverable",
             "Day 1 Assessment", "Day 2 \u2013 Containers on EKS", "Module 2: Containers on EKS",
             "Lab 2: Deploy the service to EKS"]
    positions = [html.index(marker) for marker in order]
    assert positions == sorted(positions)
    assert "2 days (16 hours)" in html


def test_colon_lists_and_item_groups_become_nested_bullets():
    html = build_toc_html(SAMPLE_TOC)
    assert "Pipeline stages:" in html and "<li>scan</li>" in html
    assert "Triggers" in html and "<li>pull request</li>" in html


def test_internal_planning_data_and_filler_are_never_printed():
    html = build_toc_html(SAMPLE_TOC)
    for internal in ("internal note", "internal dataset", "trainer rate", "Trainer creates the starter repo",
                     "Jira", "9:00 AM", "Morning Session"):
        assert internal not in html


def test_missing_fields_are_omitted_rather_than_invented():
    html = build_toc_html({"title": "Python Basics", "days": [{"day": 1, "focus_area": "Syntax",
                                                                "subtopics": ["Variables"]}]})
    assert "Learning Objectives" not in html and "Lab " not in html and "Assessment" not in html
    assert "Module 1: Syntax" in html and "1 day" in html
