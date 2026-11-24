from app.routes.shortlists import _clean_confirmed_mail1_body, _trainer_missing_followup_details


def _proposal(**overrides):
    return {
        "batch_flow": "proposal",
        "pipeline_target": "shortlist1",
        "technology_needed": "SailPoint IdentityIQ",
        "requested_details": ["Updated profile/CV", "LinkedIn profile", "Availability"],
        **overrides,
    }


def test_proposal_mail1_does_not_request_slots_without_client_slot_request():
    body = _clean_confirmed_mail1_body("Trainer", _proposal(), "SailPoint IdentityIQ", {})
    assert "three convenient interview/discussion slots" not in body
    assert "tentative availability" in body


def test_proposal_mail1_requests_three_slots_when_client_asks():
    requirement = _proposal(client_requirement_text="Please share three interview slots with the trainer profile.")
    body = _clean_confirmed_mail1_body("Trainer", requirement, "SailPoint IdentityIQ", {})
    assert "three convenient interview/discussion slots" in body


def test_slot_follow_up_is_not_created_without_a_client_slot_request():
    trainer = {
        "mail1_reply_text": "I am interested and can deliver this training.",
        "pipeline_status": "mail1_replied",
    }
    assert _trainer_missing_followup_details(trainer, _proposal()) == [
        "Updated trainer profile/CV",
        "LinkedIn profile",
        "Tentative availability for the proposed engagement",
    ]
