import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.routes.inbox import (
    _build_toc_recheck_state,
    _attachment_type_from_extracted_text,
    _document_readability,
    _send_missing_trainer_details_followup,
    _trainer_detail_evidence_doc,
    _trainer_mail2_details_reply,
    _trainer_missing_requested_details,
    _persist_trainer_requirement_fit,
    _trainer_reply_has_requested_details,
    _validate_trainer_attachments_against_requirement,
)


def test_missing_trainer_details_followup_is_never_sent_to_client_address():
    result = asyncio.run(
        _send_missing_trainer_details_followup(
            None,
            email_doc={
                "requirement_id": "REQ-1",
                "trainer_id": "TR-1",
                "from_email": "client@example.com",
            },
            requirement={"client_email": "client@example.com"},
            trainer_state={"email": "trainer@example.com"},
            missing_details=["Exactly three interview/discussion slots (date, time, and time zone)"],
            now=None,
        )
    )

    assert result["success"] is False
    assert result["blocked"] is True
    assert result["reason"] == "trainer_followup_recipient_is_client"


def test_missing_trainer_details_followup_blocks_unknown_recipient_mismatch():
    result = asyncio.run(
        _send_missing_trainer_details_followup(
            None,
            email_doc={
                "requirement_id": "REQ-1",
                "trainer_id": "TR-1",
                "from_email": "other@example.com",
            },
            requirement={"client_email": "client@example.com"},
            trainer_state={"email": "trainer@example.com"},
            missing_details=["Current Location"],
            now=None,
        )
    )

    assert result["success"] is False
    assert result["blocked"] is True
    assert result["reason"] == "trainer_followup_recipient_mismatch"


def test_cv_attachment_supplies_profile_and_experience_for_slot_mail():
    reply = (
        "linkedin: https://www.linkedin.com/in/john-doe/\n"
        "Availability: yes"
    )
    requirement = {
        "technology_needed": "DevOps",
        "client_request": (
            "Updated CV / Trainer Profile, devops implementation and training "
            "experience, Availability"
        ),
    }
    email_doc = {"attachments": [{"filename": "Megha Menon Profile.pdf", "safe_client_scope": True}]}

    assert _trainer_missing_requested_details(reply, requirement, email_doc) == []
    assert _trainer_reply_has_requested_details(reply, requirement, email_doc) is True


def test_non_document_attachment_does_not_count_as_cv_or_experience():
    reply = (
        "linkedin: https://www.linkedin.com/in/john-doe/\n"
        "Availability: yes"
    )
    requirement = {
        "technology_needed": "DevOps",
        "client_request": (
            "Updated CV / Trainer Profile, devops implementation and training "
            "experience, Availability"
        ),
    }
    email_doc = {"attachments": [{"filename": "photo.png"}]}

    missing = _trainer_missing_requested_details(reply, requirement, email_doc)
    assert "Updated CV / Trainer Profile" in missing
    assert "DevOps implementation and training experience" in missing


def test_interested_with_safe_cv_and_linkedin_advances_when_client_did_not_request_experience():
    reply = "i am interested\nlinkedin: https://www.linkedin.com/in/karthik-menon/"
    requirement = {
        "technology_needed": "DevOps",
        "requested_details": ["Availability", "Commercials (per hour/day)", "LinkedIn Profile", "ToC"],
        "budget_total": 90000,
        "source_attachments": [{
            "filename": "DevOps_20_Day_ToC.xlsx",
            "safe_client_scope": True,
        }],
    }
    email_doc = {
        "attachments": [{
            "filename": "Karthik_Menon_DevOps_Trainer_CV.pdf",
            "safe_client_scope": True,
            "size_bytes": 26880,
        }],
        "attachment_profiles": [],
    }

    assert _trainer_missing_requested_details(reply, requirement, email_doc) == []
    assert _trainer_reply_has_requested_details(reply, requirement, email_doc) is True


def test_explicit_client_requested_details_are_the_only_required_checklist():
    reply = (
        "I am interested.\n"
        "LinkedIn: https://www.linkedin.com/in/karthik-menon/\n"
        "Current location: Chennai\n"
        "Commercials: INR 12000 per day\n"
    )
    requirement = {
        "technology_needed": "DevOps",
        "requested_details": [
            "LinkedIn Profile",
            "Current Location",
            "Commercials (per day)",
        ],
    }
    email_doc = {"attachments": []}

    assert _trainer_missing_requested_details(reply, requirement, email_doc) == []
    assert _trainer_reply_has_requested_details(reply, requirement, email_doc) is True


def test_explicit_client_requested_details_do_not_add_cv_or_availability_automatically():
    reply = "LinkedIn: https://www.linkedin.com/in/karthik-menon/"
    requirement = {
        "technology_needed": "DevOps",
        "requested_details": ["LinkedIn Profile"],
        "client_request": "Also share LinkedIn Profile.",
    }
    email_doc = {"attachments": []}

    assert _trainer_missing_requested_details(reply, requirement, email_doc) == []
    assert _trainer_reply_has_requested_details(reply, requirement, email_doc) is True


def test_linkedin_profile_request_does_not_require_cv_profile_document():
    reply = (
        "LinkedIn Profile: https://www.linkedin.com/in/karthik-menon/\n"
        "Current location: Chennai\n"
        "Commercials: INR 12000 per day"
    )
    requirement = {
        "technology_needed": "DevOps",
        "requested_details": [
            "LinkedIn Profile",
            "Current Location",
            "Commercials (per day)",
        ],
    }
    email_doc = {"attachments": []}

    assert _trainer_missing_requested_details(reply, requirement, email_doc) == []


def test_explicit_client_requested_detail_stays_missing_until_trainer_supplies_it():
    reply = "I am interested.\nLinkedIn: https://www.linkedin.com/in/karthik-menon/"
    requirement = {
        "technology_needed": "DevOps",
        "requested_details": ["LinkedIn Profile", "Current Location"],
    }
    email_doc = {"attachments": []}

    assert _trainer_missing_requested_details(reply, requirement, email_doc) == ["Current Location"]
    assert _trainer_reply_has_requested_details(reply, requirement, email_doc) is False


def test_three_valid_slots_are_preserved_while_only_missing_linkedin_is_requested():
    reply = """I am interested.
- 10 September 2026, 10:30 AM IST
- 10 September 2026, 2:00 PM IST
- 10 September 2026, 4:00 PM IST"""
    requirement = {
        "technology_needed": "Advanced DevOps with AWS & Azure",
        "requested_details": ["Updated CV / Trainer Profile", "LinkedIn Profile", "ToC"],
        "request_interview_slots": True,
    }
    email_doc = {
        "attachments": [{"filename": "Trainer_Profile.pdf", "safe_client_scope": True}],
    }

    assert _trainer_missing_requested_details(reply, requirement, email_doc) == ["LinkedIn Profile"]
    followup = _trainer_mail2_details_reply({
        "trainer_name": "Suresh",
        "requirement": requirement,
        "missing_requested_details": ["LinkedIn Profile"],
    })
    assert "* LinkedIn Profile" in followup["body"]
    assert "interview/discussion slots" not in followup["body"]


def test_linkedin_mention_or_unavailability_does_not_count_as_a_profile_url():
    requirement = {
        "technology_needed": "DevOps",
        "requested_details": ["LinkedIn Profile"],
    }

    assert _trainer_missing_requested_details(
        "I am interested, but my LinkedIn profile is not available.", requirement, {}
    ) == ["LinkedIn Profile"]
    assert _trainer_missing_requested_details(
        "LinkedIn: https://www.linkedin.com/in/karthik-menon/", requirement, {}
    ) == []


def test_document_reader_classifies_generic_toc_and_lab_files_from_content():
    toc_text = "Module 1: CI/CD\nDay 1: Docker\nDay 2: Kubernetes"
    lab_text = "Lab Cost Estimate\nPer participant: INR 1200\nAWS lab sandbox access"

    assert _attachment_type_from_extracted_text("other", toc_text) == "toc"
    assert _attachment_type_from_extracted_text("other", lab_text) == "lab_cost"


def test_readability_gate_distinguishes_unreadable_and_readable_profile_text():
    assert _document_readability("blurred scan", "cv")["status"] == "unreadable"
    readable = _document_readability("DevOps AWS Azure Kubernetes CI CD delivery experience. " * 20, "cv")
    assert readable["status"] == "readable"
    assert readable["confidence"] >= 70


def test_profile_document_is_rated_against_its_requirement_skills_seniority_and_projects():
    email_doc = {
        "requirement_id": "REQ-DEVOPS-1",
        "trainer_id": "TR-1",
        "attachments": [{
            "filename": "trainer-document.pdf",
            "analysis": {
                "filename": "trainer-document.pdf",
                "attachment_type": "cv",
                "text_extracted": True,
                "ocr_used": False,
                "extracted_text": (
                    "8 years DevOps, AWS, Azure, Kubernetes, CI/CD and infrastructure automation. "
                    "Delivered AWS and Azure Kubernetes implementation projects for enterprise clients."
                ) * 8,
                "evidence": {"projects": [{"page": 1, "line": 1, "text": "Delivered AWS Azure Kubernetes implementation projects."}]},
            },
        }],
        "attachment_profiles": [{
            "filename": "trainer-document.pdf",
            "experience_years": 8,
            "skills": ["DevOps", "AWS", "Azure", "Kubernetes", "CI/CD"],
            "summary": "Senior DevOps trainer",
        }],
    }
    requirement = {
        "requirement_id": "REQ-DEVOPS-1",
        "technology_needed": "Advanced DevOps with AWS & Azure",
        "required_skills": ["DevOps", "AWS", "Azure", "Kubernetes", "CI/CD"],
        "min_experience_years": 6,
        "requirement_source_text": "Advanced DevOps training covering AWS, Azure, Kubernetes and CI/CD.",
    }

    validation = _validate_trainer_attachments_against_requirement(email_doc, requirement)
    fit = validation["requirement_fit"]
    assert validation["document_inventory"][0]["filename"] == "trainer-document.pdf"
    assert validation["document_inventory"][0]["type"] == "cv"
    assert validation["document_inventory"][0]["readability"]["status"] == "readable"
    assert fit["requirement_id"] == "REQ-DEVOPS-1"
    assert fit["skills"]["coverage_percent"] >= 80
    assert fit["seniority"] == {"required_years": 6.0, "evidenced_years": 8.0, "status": "met"}
    assert fit["projects"]["status"] == "relevant_project_found"
    assert fit["readability"]["status"] == "readable"
    assert fit["status"] == "strong_fit"


def test_requirement_fit_is_saved_on_the_exact_shortlisted_trainer():
    shortlist = SimpleNamespace(update_one=AsyncMock())
    db = {"shortlists": shortlist}
    email_doc = {"requirement_id": "REQ-1", "trainer_id": "TR-1", "body": "I am interested."}
    requirement = {"requirement_id": "REQ-1", "technology_needed": "DevOps"}

    validation = asyncio.run(_persist_trainer_requirement_fit(db, email_doc, requirement, {}))

    assert shortlist.update_one.await_args.args[0] == {
        "requirement_id": "REQ-1", "top_trainers.trainer_id": "TR-1",
    }
    stored = shortlist.update_one.await_args.args[1]["$set"]
    assert stored["top_trainers.$.requirement_fit"] == validation["requirement_fit"]


def test_previous_trainer_state_satisfies_requested_details_without_reasking():
    latest_reply = "I can proceed."
    previous_state = {
        "details_reply_text": (
            "LinkedIn: https://www.linkedin.com/in/karthik-menon/\n"
            "Current location: Chennai\n"
            "Commercials: INR 12000 per day"
        ),
        "resume_filename": "Karthik_Menon_DevOps_Trainer_CV.pdf",
    }
    requirement = {
        "technology_needed": "DevOps",
        "requested_details": [
            "Updated CV / Trainer Profile",
            "LinkedIn Profile",
            "Current Location",
            "Commercials (per day)",
        ],
    }
    evidence_doc = _trainer_detail_evidence_doc({"body": latest_reply}, previous_state)

    assert _trainer_missing_requested_details(evidence_doc["classification_body"], requirement, evidence_doc) == []


def test_previous_state_missing_only_one_detail_asks_only_that_detail():
    latest_reply = "I can proceed."
    previous_state = {
        "details_reply_text": "LinkedIn: https://www.linkedin.com/in/karthik-menon/",
        "resume_filename": "Karthik_Menon_DevOps_Trainer_CV.pdf",
    }
    requirement = {
        "technology_needed": "DevOps",
        "requested_details": [
            "Updated CV / Trainer Profile",
            "LinkedIn Profile",
            "Current Location",
        ],
    }
    evidence_doc = _trainer_detail_evidence_doc({"body": latest_reply}, previous_state)

    assert _trainer_missing_requested_details(evidence_doc["classification_body"], requirement, evidence_doc) == ["Current Location"]


def test_generated_toc_satisfies_toc_evidence_without_trainer_toc_attachment():
    email_doc = {
        "attachments": [{
            "filename": "Trainer_Profile.pdf",
            "analysis": {
                "attachment_type": "cv",
                "extracted_text": "DevOps trainer with AWS, Docker, Kubernetes and Jenkins delivery experience.",
                "evidence": {"projects": [{"text": "Delivered Kubernetes and Jenkins DevOps workshops."}]},
            },
        }],
        "attachment_profiles": [{
            "filename": "Trainer_Profile.pdf",
            "skills": ["DevOps", "AWS", "Docker", "Kubernetes", "Jenkins"],
            "summary": "DevOps trainer",
            "technology_category": "DevOps",
            "experience_years": 8,
        }],
    }
    extracted = {
        "technology_needed": "DevOps",
        "toc_action": "generate_by_clahan",
        "topics": "AWS\nDocker\nKubernetes\nJenkins",
    }

    validation = _validate_trainer_attachments_against_requirement(email_doc, extracted)
    recheck = _build_toc_recheck_state(email_doc, validation)

    assert validation["generated_toc_evidence"] is True
    assert validation["toc_evidence_source"] == "generated_or_saved"
    assert "Ask the trainer for a day-wise TOC/agenda." not in validation["recommended_actions"]
    assert recheck["status"] == "resolved"


def test_generated_toc_does_not_fake_profile_evidence():
    email_doc = {
        "attachments": [],
        "attachment_profiles": [],
    }
    extracted = {
        "technology_needed": "DevOps",
        "toc_action": "generate_by_clahan",
        "topics": "AWS\nDocker\nKubernetes\nJenkins",
    }

    validation = _validate_trainer_attachments_against_requirement(email_doc, extracted)

    assert validation["generated_toc_evidence"] is True
    assert validation["profile_attachment_count"] == 0
    assert "Ask the trainer to attach a readable PDF/DOCX CV or trainer profile." in validation["recommended_actions"]
