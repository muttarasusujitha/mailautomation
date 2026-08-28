from app.routes.shortlists import _workflow_summary


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
