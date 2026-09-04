from app.routes.shortlists import _trainer_missing_followup_details, _workflow_summary


def test_followup_requests_only_availability_when_profile_is_already_stored():
    requirement = {"client_requirement_text": "Please confirm trainer availability for 10 October."}
    trainer = {
        "profile_summary": "DevOps corporate trainer with 12 years experience.",
        "linkedin": "https://linkedin.com/in/trainer",
        "experience_years": 12,
    }

    assert _trainer_missing_followup_details(trainer, requirement) == [
        "Availability for the specified training dates"
    ]


def test_followup_is_not_sent_when_requested_details_are_already_available():
    requirement = {"client_requirement_text": "Please confirm trainer availability for 10 October."}
    trainer = {"availability": "Available on 10 October, 10 AM to 5 PM IST."}

    assert _trainer_missing_followup_details(trainer, requirement) == []


def test_matching_completion_does_not_complete_client_workflow():
    summary = _workflow_summary({
        "pipeline_summary": {"status": "completed"},
        "top_trainers": [{
            "pipeline_status": "details_received",
            "client_slots_sent": False,
        }],
    })

    assert summary["status"] == "in_progress"
    assert summary["matching_status"] == "completed"
    assert summary["current_stage"] == "collecting_trainer_details"
    assert summary["client_handoff_completed"] is False


def test_client_handoff_requires_verified_email_delivery_fields():
    incomplete = _workflow_summary({
        "top_trainers": [{
            "pipeline_status": "slot_booked",
            "slot_status": "sent_to_client",
            "client_slots_sent": True,
            "client_slots_email_id": "",
        }],
    })
    delivered = _workflow_summary({
        "top_trainers": [{
            "pipeline_status": "slot_booked",
            "slot_status": "sent_to_client",
            "client_slots_sent": True,
            "client_slots_email_id": "EML-123",
        }],
    })

    assert incomplete["client_handoff_completed"] is False
    assert incomplete["current_stage"] == "awaiting_trainer_slots"
    assert delivered["client_handoff_completed"] is True
    assert delivered["current_stage"] == "client_handoff_sent"


def test_client_handoff_retry_is_not_reported_as_trainer_slots_missing():
    summary = _workflow_summary({
        "top_trainers": [{
            "pipeline_status": "slot_booked",
            "slot_status": "client_handoff_retry_pending",
            "client_slots_sent": False,
        }],
    })

    assert summary["status"] == "in_progress"
    assert summary["current_stage"] == "client_handoff_retry_pending"
    assert summary["client_handoff_completed"] is False
    assert summary["client_handoff_retry_pending"] is True


def test_sent_mail3_reports_awaiting_slots_even_if_details_stage_is_preserved():
    summary = _workflow_summary({
        "top_trainers": [{
            "pipeline_status": "details_received",
            "last_mail_type": "mail3",
            "client_slots_sent": False,
        }],
    })

    assert summary["status"] == "in_progress"
    assert summary["current_stage"] == "awaiting_trainer_slots"
    assert summary["client_handoff_completed"] is False


def test_only_training_confirmation_completes_workflow():
    summary = _workflow_summary({
        "top_trainers": [{"pipeline_status": "training_confirmed"}],
    })

    assert summary["status"] == "completed"
    assert summary["current_stage"] == "training_confirmed"


def test_interview_scheduled_reports_link_sent_not_completed():
    summary = _workflow_summary({
        "top_trainers": [{
            "pipeline_status": "interview_scheduled",
            "slot_status": "sent_to_client",
            "client_slots_sent": True,
            "client_slots_email_id": "EML-123",
        }],
    })

    assert summary["status"] == "in_progress"
    assert summary["current_stage"] == "interview_link_sent"
    assert summary["client_handoff_completed"] is True
