from app.routes.inbox import (
    _trainer_missing_requested_details,
    _trainer_reply_has_requested_details,
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
    email_doc = {"attachments": [{"filename": "Megha Menon Profile.pdf"}]}

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
