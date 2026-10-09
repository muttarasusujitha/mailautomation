from app.routes.shortlists import _apply_interview_schedule, _merge_pipeline_state


def test_scheduled_sync_does_not_restore_a_meet_during_reschedule():
    trainer = {
        "pipeline_status": "interview_reschedule_requested",
        "reschedule_requested": True,
        "meet_link": "",
        "interview_link": "",
        "previous_meet_link": "https://meet.google.com/old-meet-link",
    }

    changed = _apply_interview_schedule(trainer, {
        "interview_link": "https://meet.google.com/old-meet-link",
        "interview_date": "06 November 2026, 10:00 AM IST",
        "interview_scheduled": True,
    })

    assert changed is False
    assert trainer["pipeline_status"] == "interview_reschedule_requested"
    assert trainer["meet_link"] == ""
    assert trainer["interview_link"] == ""


def test_ranking_merge_keeps_the_reschedule_request():
    merged = _merge_pipeline_state(
        {"trainer_id": "TR-1", "name": "Divya", "pipeline_status": "shortlisted"},
        {
            "pipeline_status": "interview_reschedule_requested",
            "reschedule_requested": True,
            "reschedule_requested_by": "client",
            "previous_meet_link": "https://meet.google.com/old-meet-link",
            "previous_calendar_event_id": "OLD-EVENT",
            "meet_link": "",
            "interview_link": "",
        },
    )

    assert merged["pipeline_status"] == "interview_reschedule_requested"
    assert merged["reschedule_requested"] is True
    assert merged["reschedule_requested_by"] == "client"
    assert merged["previous_meet_link"] == "https://meet.google.com/old-meet-link"
    assert merged["previous_calendar_event_id"] == "OLD-EVENT"
    assert merged["meet_link"] == ""
