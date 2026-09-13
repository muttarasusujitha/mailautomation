from datetime import datetime, timedelta

from app.tasks.meet_start_notices import (
    _notice_body,
    _notice_idempotency_key,
    _notice_recipients,
    _notice_window,
    _due_notice_query,
)


def test_notice_window_targets_five_minutes_before_interview():
    now = datetime(2026, 9, 3, 10, 0)
    start, end = _notice_window(now)
    assert start == now + timedelta(minutes=4)
    assert end == now + timedelta(minutes=6)
    assert start <= now + timedelta(minutes=5) <= end


def test_failed_notice_is_eligible_for_bounded_retry():
    now = datetime(2026, 9, 3, 10, 0)
    query = _due_notice_query(now)
    retry = query["$and"][-1]["$or"][1]

    assert retry["interview_at"]["$gte"] == now - timedelta(minutes=30)
    assert retry["interview_at"]["$lt"] == now + timedelta(minutes=4)
    assert query["$and"][1]["$or"][1]["meet_start_notice_retry_count"]["$lt"] == 3


def test_notice_body_asks_recipient_to_join_early():
    body = _notice_body(
        name="Asha",
        technology="DevOps",
        interview_link="https://meet.google.com/example",
        interview_date="03 September 2026, 10:10 AM IST",
    )
    assert "starts in 5 minutes" in body
    assert "join a few minutes before" in body
    assert "https://meet.google.com/example" in body


def test_duplicate_invitation_logs_share_one_reminder_key():
    meeting = {
        "requirement_id": "REQ-1",
        "trainer_id": "TRN-1",
        "trainer_name": "Asha",
        "interview_at": datetime(2026, 9, 8, 4, 30),
    }
    trainer_invite = {**meeting, "email_id": "EML-TRAINER", "mail_type": "mail4"}
    client_invite = {
        **meeting,
        "email_id": "EML-CLIENT",
        "mail_type": "client_interview_schedule",
        "interview_at": "2026-09-08T04:30:00Z",
    }

    assert _notice_idempotency_key(trainer_invite, "POOJA@example.com") == _notice_idempotency_key(
        client_invite, "pooja@example.com"
    )


def test_rescheduled_interview_gets_a_new_reminder_key():
    original = {"requirement_id": "REQ-1", "trainer_id": "TRN-1", "interview_at": "2026-09-08T10:00:00"}
    rescheduled = {**original, "interview_at": "2026-09-08T11:00:00"}

    assert _notice_idempotency_key(original, "pooja@example.com") != _notice_idempotency_key(
        rescheduled, "pooja@example.com"
    )


def test_client_invite_does_not_use_client_address_as_trainer_address():
    recipients = _notice_recipients(
        {
            "mail_type": "client_interview_schedule",
            "to_email": "client@example.com",
            "client_email": "client@example.com",
            "client_name": "Deepika",
            "trainer_name": "Pooja",
        }
    )

    assert recipients == [
        {"email": "client@example.com", "name": "Deepika", "role": "client"},
        {"email": "sujithaofficial784@gmail.com", "name": "Clahan Technologies", "role": "clahan"},
    ]


def test_same_address_is_only_notified_once_per_source_log():
    recipients = _notice_recipients(
        {
            "mail_type": "mail4",
            "trainer_email": "shared@example.com",
            "client_email": "SHARED@example.com",
            "trainer_name": "Pooja",
            "client_name": "Deepika",
        }
    )

    assert len(recipients) == 2
    assert recipients[0]["email"] == "shared@example.com"
    assert recipients[1]["role"] == "clahan"


def test_ten_minute_notice_includes_trainer_client_and_clahan():
    recipients = _notice_recipients(
        {
            "mail_type": "mail4",
            "trainer_email": "trainer@example.com",
            "client_email": "client@example.com",
            "client_name": "Client Team",
        }
    )
    assert [(item["email"], item["role"]) for item in recipients] == [
        ("trainer@example.com", "trainer"),
        ("client@example.com", "client"),
        ("sujithaofficial784@gmail.com", "clahan"),
    ]
