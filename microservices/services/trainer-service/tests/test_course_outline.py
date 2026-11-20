"""Course outlines: reference parsing, dataset cleanup and template-text suppression."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.course_outline import (
    GOLD_EXAMPLE,
    clean_subtopics,
    is_filler_subtopic,
    is_template_text,
    outline_from_flat,
    outline_from_reference,
    outline_problems,
    repeated_items,
    subtopics_from_outline,
)
from app.toc_pdf_template import build_toc_html
from app.upgrade_curriculum_outlines import clean_document, run

APP = Path(__file__).resolve().parents[1] / "app"

REFERENCE = """Topics
Engineering Task Contracts
Every professional request should define:
Business objective
Scope boundaries
Evidence-First Prompting
Asking Codex to inspect before concluding
Separating:
o Confirmed facts
o Assumptions
Engineering Principle
A professional workflow starts with:
1. Understanding the repository.
2. Establishing the baseline.
Lab 2: Convert an Ambiguous Issue
Original requirement:
\u201cPayments sometimes fail and customers retry. Fix the system.\u201d
Participants transform it into a task contract covering:
Failure symptoms
Retry ownership
Lab Deliverable
A production-quality task specification that another engineer could execute without
guessing.
Day 1 Assessment
Participants independently diagnose and fix one unseen defect.
Day 2 \u2013 Secure Customization
"""


def test_reference_text_keeps_groups_sub_bullets_principle_and_lab():
    outline = outline_from_reference(REFERENCE)
    groups = outline["topic_groups"]
    assert [group["heading"] for group in groups] == ["Engineering Task Contracts", "Evidence-First Prompting"]
    assert groups[0]["lead"] == "Every professional request should define:"
    assert {"text": "Separating:", "children": ["Confirmed facts", "Assumptions"]} in groups[1]["items"]
    assert outline["principle"]["points"] == ["Understanding the repository.", "Establishing the baseline."]
    lab = outline["lab"]
    assert lab["title"] == "Convert an Ambiguous Issue"
    assert lab["scenario"].startswith("Original requirement: \u201cPayments")
    assert lab["lead"] == "Participants transform it into a task contract covering:"
    assert lab["tasks"] == ["Failure symptoms", "Retry ownership"]
    assert lab["deliverables"] == ["A production-quality task specification that another engineer could execute without guessing."]
    assert outline["assessment"] == "Participants independently diagnose and fix one unseen defect."
    assert outline_problems(outline) == []


def test_template_and_padding_text_is_recognised():
    assert is_template_text("Demonstrate 'Integration' on a prepared training sample through this task: x.")
    assert is_template_text("Participant submission for 'Integration': x. Include the resulting artefact")
    assert is_template_text("Explain the Integration concepts in the context of Azure DevOps.")
    assert not is_template_text("Deploy the service to EKS behind an ALB.")
    assert is_filler_subtopic("Azure DevOps terminology and feature mapping for this topic")
    assert is_filler_subtopic("Terminology and scope")
    assert not is_filler_subtopic("Branch policies")


def test_cleanup_removes_filler_and_course_wide_repeats_but_keeps_first_use():
    days = [{"topic": f"Day {n}", "subtopics": [f"Topic {n}a", f"Topic {n}b", f"Topic {n}c", "Azure Boards",
                                                "Azure DevOps best practices and common mistakes for this topic"]}
            for n in range(1, 6)]
    days.append({"topic": "Authored", "content_quality_stage": "manually_authored_pending_lab_validation",
                 "subtopics": ["Azure Boards", "Terminology and scope"]})
    document = {"days": days}
    assert "azure boards" in repeated_items(days)
    stats = clean_document(document)
    assert days[0]["subtopics"] == ["Topic 1a", "Topic 1b", "Topic 1c", "Azure Boards"]
    assert days[1]["subtopics"] == ["Topic 2a", "Topic 2b", "Topic 2c"]
    assert days[5]["subtopics"] == ["Azure Boards", "Terminology and scope"]  # authored content untouched
    assert stats["days_changed"] == 5
    assert clean_document(document)["days_changed"] == 0  # idempotent


def test_committed_datasets_are_clean_and_references_have_outlines():
    report = run(APP, write=False)
    assert report["compact_files_changed"] == 0 and report["reference_outlines"] == 0
    for path in sorted((APP / "datasets_compact").glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8-sig"))
        for day in document["days"]:
            if day.get("content_quality_stage"):
                continue
            assert not any(is_filler_subtopic(item) for item in day.get("subtopics") or []), (path.name, day["topic"])
    codex = json.loads((APP / "reference_curricula" / "codex_for_developers.json").read_text(encoding="utf-8"))
    assert all(module.get("outline", {}).get("source") == "reference" for module in codex["modules"])


def test_flat_rows_get_an_outline_without_template_text():
    outline = outline_from_flat({
        "subtopics": ["Triggers", "Terminology and scope", "Stages: build, test, deploy"],
        "lab_task": "Build an automated workflow using Azure DevOps.",
        "scenario": "Demonstrate 'Automation' on a prepared training sample through this task: x.",
        "deliverable": "Participant submission for 'Automation': x.",
        "checks": [["Run the pipeline", "It passes", "Run log"]],
    })
    items = outline["topic_groups"][0]["items"]
    assert items == [{"text": "Triggers", "children": []}, {"text": "Stages:", "children": ["build", "test", "deploy"]}]
    assert outline["lab"]["title"] == "Build an automated workflow using Azure DevOps"
    assert outline["lab"]["scenario"] == "" and outline["lab"]["deliverables"] == []
    assert outline["lab"]["verify"] == ["Run the pipeline: It passes."]
    assert subtopics_from_outline(outline) == ["Triggers", "Stages: build, test, deploy"]


def test_pdf_renders_stored_outlines_and_hides_template_text():
    module = {"title": GOLD_EXAMPLE["title"], "outline": GOLD_EXAMPLE["outline"],
              "scenario": "Demonstrate 'x' on a prepared training sample through this task: y."}
    html = build_toc_html({"title": "Codex", "days": [
        {"day": 1, "focus_area": "Foundations", "modules": [module]},
        {"day": 2, "focus_area": "Pipelines", "subtopics": ["Triggers"], "lab_task": "Build a pipeline",
         "deliverable": "Participant submission for 'Pipelines': Build a pipeline."},
    ]})
    for marker in ("Engineering Task Contracts", "Every professional request should define:", "<li>Hypotheses</li>",
                   "Engineering Principle", "<ol class=\"list\">", "Lab 1: Repository X-Ray", "Participants must identify:",
                   "Participants verify that:", "Lab Deliverable", "Lab 2: Build a pipeline"):
        assert marker in html
    assert "prepared training sample" not in html and "Participant submission" not in html
