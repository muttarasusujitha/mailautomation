import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.routes.profile_enhancements import _fallback_analysis, _keywords, _resume_text
from app.routes.shortlists import (
    _client_profile_evidence_items,
    _edit_submitted_trainer_pdf,
    _submitted_resume_suits_requirement,
)


def test_gap_analysis_separates_supported_and_missing_requirement_skills():
    requirement = {
        "technology_needed": "DevOps and AWS",
        "required_skills": ["Jenkins", "Docker", "Azure DevOps", "Prompt Engineering"],
    }
    trainer = {
        "resume": "Implemented Jenkins CI/CD pipelines with Docker on AWS.",
        "skills": ["AWS", "Jenkins", "Docker"],
    }

    analysis = _fallback_analysis(requirement, trainer)

    assert "jenkins" in analysis["confirmed_skills"]
    assert "docker" in analysis["confirmed_skills"]
    assert "prompt" in analysis["missing_skills"]
    missing = [item for item in analysis["suggestions"] if item["evidence_status"] == "missing"]
    assert missing
    assert all(item["requires_trainer_confirmation"] for item in missing)
    assert all(not item["suggested_bullet"] for item in missing)


def test_original_resume_text_is_read_without_being_replaced():
    trainer = {"resume": "Original verified resume", "summary": "Existing summary"}

    combined = _resume_text(trainer)

    assert "Original verified resume" in combined
    assert "Existing summary" in combined


def test_keyword_extraction_ignores_generic_requirement_words():
    tokens = _keywords("We need a trainer for an AWS DevOps training requirement with Kubernetes")

    assert "aws" in tokens
    assert "devops" in tokens
    assert "kubernetes" in tokens
    assert "trainer" not in tokens
    assert "requirement" not in tokens


def test_client_profile_edits_a_copy_of_the_submitted_pdf():
    import fitz

    source = fitz.open()
    page = source.new_page()
    page.insert_text((72, 72), "TRAINER ORIGINAL RESUME")
    original = source.tobytes()
    source.close()
    trainer = {
        "name": "Test Trainer",
        "profile_enhancement_status": "approved",
        "approved_profile_bullets": ["Delivered verified AWS workshops."],
    }

    edited = _edit_submitted_trainer_pdf(original, trainer, "AWS")
    result = fitz.open(stream=edited, filetype="pdf")

    assert result.page_count == 2
    assert "TRAINER ORIGINAL RESUME" in result[0].get_text()
    assert "Delivered verified AWS workshops" in result[1].get_text()
    assert original != edited


def test_submitted_pdf_is_returned_unchanged_without_approved_additions():
    original = b"%PDF-placeholder"

    assert _edit_submitted_trainer_pdf(original, {}, "AWS") == original


def test_submitted_resume_without_requirement_evidence_is_not_used_for_client_handoff():
    submitted = {"extracted_text": "Experienced Python instructor with data analytics projects."}
    trainer = {"skills": ["Python"], "summary": "Data analytics trainer"}

    assert _submitted_resume_suits_requirement(submitted, trainer, "DevOps") is False


def test_submitted_resume_with_requirement_evidence_is_used_for_client_handoff():
    submitted = {"extracted_text": "Delivered DevOps implementation workshops with CI/CD and Kubernetes."}

    assert _submitted_resume_suits_requirement(submitted, {}, "DevOps") is True


def test_approved_profile_addendum_allows_submitted_resume_copy():
    submitted = {"extracted_text": "General cloud trainer resume."}
    trainer = {
        "profile_enhancement_status": "approved",
        "approved_profile_bullets": ["Delivered DevOps implementation training for enterprise teams."],
    }

    assert _submitted_resume_suits_requirement(submitted, trainer, "DevOps") is True


def test_client_profile_evidence_marks_verified_training_and_implementation():
    trainer = {
        "summary": "Delivered DevOps training and implemented CI/CD pipeline automation projects.",
    }

    evidence = _client_profile_evidence_items(trainer, "DevOps")

    assert "Confirmed technology alignment: DevOps" in evidence
    assert "Training delivery experience: confirmed from trainer profile or reply" in evidence
    assert "Implementation/project exposure: confirmed from trainer profile or reply" in evidence
    assert not any(item.startswith("Needs confirmation") for item in evidence)


def test_client_profile_evidence_flags_missing_proof_instead_of_overclaiming():
    trainer = {
        "summary": "Corporate instructor for communication skills.",
    }

    evidence = _client_profile_evidence_items(trainer, "DevOps")

    assert "Needs confirmation: DevOps evidence not found in available trainer data" in evidence
    assert "Needs confirmation: Implementation/project proof not found" in evidence
