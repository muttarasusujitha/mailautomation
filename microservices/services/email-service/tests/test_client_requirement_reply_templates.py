import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.routes.inbox import _client_email_status_for_reply, _client_proceed_ack_reply, _extract_requirement_from_email, _requirement_payload_from_email, _trainer_mail_for_requirement, _trainer_rate_from_client_budget
from app.agents.email_classifier import classify_email
from app.agents.reply_templates import build_auto_reply


def test_partial_client_requirement_reply_asks_only_missing_details():
    body = (
        "Dear clahan,\n\n"
        "We have a requirement for a FullStack trainer\n\n"
        "Training Dates: 22 august to 30 august\n\n"
        "Kindly confirm your availability.\n\n"
        "Best regards,\n"
        "shob"
    )

    extracted = _extract_requirement_from_email(
        "FullStack trainer requirement",
        body,
        sender_email="shob@example.com",
        sender_name="shob",
    )
    reply = _client_proceed_ack_reply(extracted)

    assert "Thank you for sharing your training requirement." in reply["body"]
    assert "To help us refine the shortlist" in reply["body"]
    assert "- Training duration" in reply["body"]
    assert "- Training mode/location" in reply["body"]
    assert "- Participant count" in reply["body"]
    assert "- Budget or expected commercial range, if available" in reply["body"]
    assert "Thank you for sharing the required details for your training requirement." not in reply["body"]


def test_saved_client_requirement_has_its_extracted_confidence_immediately():
    status = _client_email_status_for_reply({
        "subject": "DevOps Trainer Requirement",
        "body": "Please share suitable DevOps trainer profiles and commercials for our review.",
        "from_email": "client@example.com",
        "from_name": "Client Team",
    })

    assert status["confidence"] >= 0.9
    assert status["auto_send_confidence"] == status["confidence"]
    assert status["extracted"]["technology"] == "DevOps"


def test_first_time_proposal_requirement_is_eligible_for_acknowledgement():
    status = _client_email_status_for_reply({
        "subject": "DevOps training requirement",
        "body": "We need a proposal for a DevOps training batch.",
        "from_email": "client@example.com",
        "from_name": "Client Team",
    })

    assert status["extracted"]["is_training_request"] is True
    assert status["confidence"] >= 0.9
    assert status["auto_send_confidence"] == status["confidence"]


def test_initial_proposal_request_with_toc_is_not_a_toc_revision():
    extracted = _extract_requirement_from_email(
        "DevOps training requirement",
        "We need a proposal for a DevOps training batch. Please share a trainer profile and TOC / Course Agenda.",
        sender_email="client@example.com",
        sender_name="Client Team",
    )

    assert extracted["is_training_request"] is True
    assert extracted["latest_coordination_intent"] == ""
    assert extracted["toc_requested"] is True
    assert extracted["toc_action"] == "generate_by_clahan"


def test_new_proposal_request_with_review_wording_is_not_a_toc_revision():
    extracted = _extract_requirement_from_email(
        "DevOps training requirement",
        "We have a proposed DevOps training requirement. Please share a suitable trainer profile and TOC for our review.",
        sender_email="client@example.com",
        sender_name="Client Team",
    )

    assert extracted["latest_coordination_intent"] == ""


def test_attached_client_scope_requests_trainer_aligned_daywise_toc():
    extracted = _extract_requirement_from_email(
        "Trainer Requirement for Azure Track",
        (
            "We have a confirmed corporate training requirement. Scope of the delivery attached. "
            "Please share day wise content from your end, updated profile, commercials, similar batches, "
            "lab charges per pax, lab setup, system requirements and software required."
        ),
        sender_email="client@example.com",
        sender_name="Client Team",
    )

    assert extracted["toc_requested"] is True
    assert extracted["scope_attached"] is True
    assert extracted["toc_action"] == "trainer_validate_scope"


def test_lab_cost_is_recorded_for_clahan_without_requesting_it_from_trainers():
    extracted = _extract_requirement_from_email(
        "DevOps training requirement",
        "We need a DevOps training batch. Please confirm lab support availability and lab cost.",
        sender_email="client@example.com",
        sender_name="Client Team",
    )

    assert extracted["clahan_managed_details"] == ["Lab availability and cost"]
    assert not {
        "Lab charges per pax, if any",
        "Lab support availability and cost, if applicable",
        "Lab setup details",
    }.intersection(extracted["requested_details"])
    assert "We will confirm lab availability and cost separately." in _client_proceed_ack_reply(extracted)["body"]


def test_training_requirement_with_lab_cost_still_creates_requirement():
    extracted = _extract_requirement_from_email(
        "DevOps Training Requirement - 15 Days",
        (
            "We have a corporate training requirement for DevOps including AWS and Azure.\n"
            "Duration: 15 Days\n"
            "Training Dates: November 1, 2026 to November 15, 2026\n"
            "Please share trainer CV, day-wise TOC and lab cost for 15 days."
        ),
        sender_email="client@example.com",
        sender_name="Client Team",
    )

    assert extracted["is_training_request"] is True
    assert extracted["direct_request_language"] is True
    assert extracted["toc_action"] == "generate_by_clahan"
    assert extracted["clahan_managed_details"] == ["Lab availability and cost"]


def test_proposal_word_alone_does_not_trigger_toc_request_before_slots():
    from app.routes.inbox import _client_requested_toc_or_proposal

    requirement = {
        "requirement_type": "proposal_batch",
        "requested_details": ["Trainer Profile", "Commercials"],
        "client_requirement_text": "Please share proposal commercials for DevOps training.",
    }

    assert _client_requested_toc_or_proposal(requirement, {}) is False


def test_explicit_toc_word_triggers_toc_request_before_slots():
    from app.routes.inbox import _client_requested_toc_or_proposal

    requirement = {
        "requirement_type": "proposal_batch",
        "requested_details": ["Trainer Profile", "ToC"],
    }

    assert _client_requested_toc_or_proposal(requirement, {}) is True


def test_natural_month_range_counts_as_preferred_dates():
    body = (
        "Good morning,\n\n"
        "Need a DevOps trainer. Sep 2 to Sep 20 works for us.\n"
        "Mode online, 20 participants, 15 days, budget INR 50000.\n"
    )

    extracted = _extract_requirement_from_email(
        "DevOps trainer requirement",
        body,
        sender_email="client@example.com",
        sender_name="Siri 2265",
    )
    reply = _client_proceed_ack_reply(extracted)

    assert extracted["preferred_dates"] == "Sep 2 to Sep 20"
    assert extracted["training_dates"] == "Sep 2 to Sep 20"
    assert "- Preferred dates or timings" not in reply["body"]


def test_requirement_payload_preserves_original_client_request_text():
    body = (
        "Hi Team,\n\n"
        "Need DevOps trainer from 2 Sep to 20 Sep.\n"
        "Commercials 50000 per day, online delivery.\n\n"
        "Regards,\nClient"
    )
    extracted = _extract_requirement_from_email("DevOps trainer", body, "client@example.com", "Client")
    payload = _requirement_payload_from_email({"email_id": "E1", "body": body, "subject": "DevOps trainer"}, extracted)

    assert "Need DevOps trainer from 2 Sep to 20 Sep." in payload["client_requirement_text"]
    assert payload["metadata"]["original_body"] == payload["client_requirement_text"]


def test_total_client_commercial_uses_duration_without_fifteen_thousand_cap():
    body = (
        "Technology: DevOps\n"
        "Training Duration: 15 days\n"
        "Training Dates: Sep 2 to Sep 20\n"
        "Mode: Online\n"
        "Participants: 20\n"
        "Commercials: INR 650000 for 15 days\n"
    )

    extracted = _extract_requirement_from_email("DevOps trainer requirement", body, "client@example.com", "Client")
    payload = _requirement_payload_from_email({"email_id": "E2", "body": body}, extracted)

    assert extracted["budget_total"] == 650000
    assert "Budget or expected commercial range, if available" not in extracted["needs_clarification"]
    assert round(payload["client_budget_per_day"], 2) == 43333.33
    assert payload["trainer_visible_budget_per_session"] == 31000
    assert _trainer_rate_from_client_budget(43333.33) == 31000


def test_first_trainer_mail_requests_three_dated_interview_slots():
    mail = _trainer_mail_for_requirement({"technology_needed": "DevOps"}, "REQ-1")

    assert "3 convenient interview/discussion slots" in mail["body"]
    assert "date, time, and time zone" in mail["body"]


def test_date_first_training_dates_are_extracted_from_recent_client_request():
    body = (
        "Dear clahan,\n"
        "We have a requirement for a Devops trainer\n"
        "Training Dates: 15  august to 29 august\n"
        "Kindly confirm your availability.\n\n"
        "Best regards,\n"
        "yamuna"
    )

    extracted = _extract_requirement_from_email(
        "Devops training requriment",
        body,
        sender_email="yamuna@example.com",
        sender_name="yamuna",
    )

    assert extracted["preferred_dates"] == "15 august to 29 august"
    assert extracted["training_dates"] == "15 august to 29 august"
    assert extracted["timeline_start"] == "15 august"
    assert extracted["timeline_end"] == "29 august"
    assert extracted["duration_days"] > 0
    assert extracted["duration_inferred_from_dates"] is True
    assert "Training duration" not in extracted["needs_clarification"]
    assert "Preferred dates or timings" not in extracted["needs_clarification"]


def test_client_requirement_with_only_date_range_loads_with_inferred_duration():
    body = (
        "Dear clahan,\n"
        "We have a requirement for a Devops trainer\n\n"
        "Training Dates: 20 august to 29 august\n\n"
        "Kindly confirm your availability.\n\n"
        "Best regards,\n"
        "sllv"
    )

    extracted = _extract_requirement_from_email(
        "Devops trainer requirement",
        body,
        sender_email="sllv@example.com",
        sender_name="sllv",
    )

    assert extracted["is_training_request"] is True
    assert extracted["technology_needed"] == "Devops"
    assert extracted["preferred_dates"] == "20 august to 29 august"
    assert extracted["training_dates"] == "20 august to 29 august"
    assert extracted["duration_days"] > 0
    assert extracted["duration_inferred_from_dates"] is True
    assert "Training duration" not in extracted["needs_clarification"]


def test_preferred_dates_or_timings_label_is_extracted():
    body = (
        "- Training duration : 200 hours\n"
        "- Preferred dates or timings   :sep 15 to sep 30\n"
        "- Training mode/location : offline\n"
        "- Participant count : 28\n"
        "- Budget or expected commercial range, if available : 400000\n"
    )

    extracted = _extract_requirement_from_email(
        "Re: DevOps Trainer Requirement",
        body,
        sender_email="client@example.com",
        sender_name="Client",
    )

    assert extracted["preferred_dates"] == "sep 15 to sep 30"
    assert extracted["training_dates"] == "sep 15 to sep 30"
    assert "Preferred dates or timings" not in extracted["needs_clarification"]


def test_client_provided_all_details_reply_thanks_naturally():
    body = (
        "- Technology: DevOps\n"
        "- Training duration: 5 days\n"
        "- Preferred dates or timings: Sep 15 to Sep 20\n"
        "- Training mode/location: Online\n"
        "- Participant count: 20\n"
        "- Budget or expected commercial range, if available: INR 50000\n"
    )

    extracted = _extract_requirement_from_email(
        "Re: DevOps Trainer Requirement",
        body,
        sender_email="client@example.com",
        sender_name="Client",
    )
    reply = _client_proceed_ack_reply(extracted)

    assert "Thank you for sharing the required details for your training requirement." in reply["body"]
    assert "share suitable trainer profiles" in reply["body"]
    assert "To help us refine the shortlist" not in reply["body"]


def test_client_sent_details_template_uses_details_ack_intro():
    reply = build_auto_reply(
        {
            "person_type": "corporate_client",
            "scenario": "client_sent_details",
            "auto_reply_allowed": True,
            "requires_human": False,
        },
        {
            "client_name": "Asha",
            "technology_needed": "DevOps",
            "duration_text": "5 days",
            "training_dates": "Sep 15 to Sep 20",
            "mode": "Online",
            "participant_count": 20,
            "budget_total": 50000,
            "needs_clarification": [],
        },
        subject="Re: DevOps Trainer Requirement",
        sender_name="Asha",
    )

    assert reply["template_key"] == "client_details_ack"
    assert "Dear Asha" in reply["body"]
    assert "Thank you for sharing the required details." in reply["body"]
    assert "Thank you for sharing the DevOps training requirement." not in reply["body"]


def test_auto_reply_partial_requirement_lists_only_missing_details():
    reply = build_auto_reply(
        {
            "person_type": "corporate_client",
            "scenario": "client_sent_details",
            "auto_reply_allowed": True,
            "requires_human": False,
        },
        {
            "client_name": "Asha",
            "technology_needed": "DevOps",
            "requested_details": [],
            "needs_clarification": ["Training mode/location", "Participant count"],
        },
        subject="DevOps Trainer Requirement",
        sender_name="Asha",
    )

    assert "To help us refine the shortlist" in reply["body"]
    assert "* Training mode/location" in reply["body"]
    assert "* Participant count" in reply["body"]


def test_auto_reply_profile_request_does_not_ask_for_unrelated_fields():
    reply = build_auto_reply(
        {
            "person_type": "corporate_client",
            "scenario": "client_asks_profiles",
            "auto_reply_allowed": True,
            "requires_human": False,
        },
        {
            "client_name": "Asha",
            "technology_needed": "DevOps",
            "requested_details": ["Updated CV / Trainer Profile", "LinkedIn Profile"],
            "needs_clarification": ["Training mode/location", "Budget or expected commercial range, if available"],
        },
        subject="DevOps Trainer Requirement",
        sender_name="Asha",
    )

    assert "CV and LinkedIn profile" in reply["body"]
    assert "To help us refine the shortlist" not in reply["body"]
    assert "Budget or expected commercial range" not in reply["body"]


def test_shared_tech_call_link_uses_forward_to_trainer_template():
    body = (
        "We shared joining link for tech call.\n"
        "Please share it with trainer.\n\n"
        "On Wed, Aug 12, 2026 at 11:03 AM Likhitha wrote:\n"
        "Please share trainer slots for tech call."
    )
    classification = classify_email(
        subject="RE: Blue Yonder TMS Training Requirement",
        body=body,
        sender_email="likhitha@cloudthat.com",
        sender_name="Likhitha",
    )
    reply = build_auto_reply(
        classification,
        {
            "client_name": "Likhitha",
            "technology_needed": "Blue Yonder TMS",
        },
        subject="RE: Blue Yonder TMS Training Requirement",
        sender_name="Likhitha",
    )

    assert classification["scenario"] == "client_shared_meeting_link_to_trainer"
    assert "forward the link to the trainer" in reply["body"]
    assert "batch" not in reply["body"].lower()
    assert "lab" not in reply["body"].lower()


def test_client_ack_mentions_only_requested_profile_items():
    body = (
        "Dear Team,\n"
        "We have an upcoming requirement for DevOps corporate training.\n"
        "Please share a suitable trainer profile along with:\n"
        "- Updated Trainer CV / Profile\n"
        "- LinkedIn Profile\n"
        "- Relevant DevOps training and implementation experience\n"
    )

    extracted = _extract_requirement_from_email(
        "DevOps Trainer Requirement",
        body,
        sender_email="client@example.com",
        sender_name="Client",
    )
    reply = _client_proceed_ack_reply(extracted)

    assert "CV, LinkedIn profile, and relevant experience" in reply["body"]
    assert "availability" not in reply["body"].lower()
    assert "commercial" not in reply["body"].lower()
