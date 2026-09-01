from app.routes.inbox import (
    _build_toc_recheck_state,
    _trainer_detail_evidence_doc,
    _trainer_missing_requested_details,
    _trainer_reply_has_requested_details,
    _validate_trainer_attachments_against_requirement,
)


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
