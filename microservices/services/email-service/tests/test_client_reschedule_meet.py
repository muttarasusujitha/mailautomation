import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.routes import inbox


OLD_LINK = "https://meet.google.com/old-meet-link"
NEW_LINK = "https://meet.google.com/new-meet-link"
REVISED_SLOTS = (
    "06 November 2026, 10:00 AM IST\n"
    "06 November 2026, 02:15 PM IST\n"
    "06 November 2026, 04:30 PM IST"
)


def _collection(value=None):
    return SimpleNamespace(
        find_one=AsyncMock(return_value=value),
        update_one=AsyncMock(),
        update_many=AsyncMock(),
        insert_one=AsyncMock(),
    )


def _trainer(**extra):
    trainer = {
        "trainer_id": "TR-1",
        "email": "trainer@example.com",
        "name": "Divya",
        "pipeline_status": "interview_scheduled",
        "meet_link": OLD_LINK,
        "interview_link": OLD_LINK,
        "interview_date": "01 October 2026, 10:00 AM IST",
        "calendar_event_id": "OLD-EVENT",
        "interview_scheduled_at": "2026-10-01T04:30:00",
        "client_email_sent": True,
        "trainer_email_sent": True,
        "client_slots_sent": True,
        "client_slots_email_id": "EML-HANDOFF",
    }
    trainer.update(extra)
    return trainer


def _database(trainer):
    return {
        "shortlists": _collection({"top_trainers": [trainer], "client_name": "Priya"}),
        "requirements": _collection({
            "requirement_id": "REQ-1",
            "client_email": "client@example.com",
            "client_name": "Priya",
            "technology_needed": "DevOps",
        }),
        "automation_settings": _collection({"key": "generation_mode", "value": "template"}),
        "admin_settings": _collection({}),
        "email_logs": _collection(None),
        "trainers": _collection(None),
    }


def _patch_sends(monkeypatch):
    monkeypatch.setattr(inbox, "_load_admin_settings", AsyncMock(return_value={}))
    monkeypatch.setattr(inbox, "_post_with_local_fallback", AsyncMock(side_effect=AssertionError("profile handoff must not run")))
    send = AsyncMock(return_value=(True, ""))
    monkeypatch.setattr(inbox, "_send_verified_workflow_email", send)
    return send


def test_client_reschedule_asks_trainer_for_three_slots_and_retires_old_meet(monkeypatch):
    trainer = _trainer()
    db = _database(trainer)
    send = _patch_sends(monkeypatch)
    create_event = AsyncMock()
    monkeypatch.setattr(inbox, "create_google_meet_event", create_event)

    result = asyncio.run(inbox._handle_interview_reschedule_reply(db, {
        "email_id": "IN-CLIENT",
        "requirement_id": "REQ-1",
        "trainer_id": "TR-1",
        "from_email": "client@example.com",
        "source_outbound_mail_type": "client_interview_schedule",
        "subject": "Re: Interview Schedule Confirmation - DevOps",
        "body": "I cannot attend the scheduled meeting. Please reschedule to 15 October 2026.",
    }))

    assert result["success"] is True
    assert result["requested_by"] == "client"
    assert result["to"] == "trainer@example.com"
    assert send.await_count == 1
    sent = send.await_args.kwargs
    assert sent["to"] == "trainer@example.com"
    assert "exactly three" in sent["body"].lower()
    assert "15 October 2026" in sent["body"]
    assert "Annapurna" in sent["body"]
    assert "Murali" not in sent["body"]
    assert "commercial" not in sent["body"].lower()
    assert "linkedin" not in sent["body"].lower()
    assert "meet.google.com" not in sent["body"].lower()
    stored = db["shortlists"].update_one.await_args.args[1]["$set"]
    assert stored["top_trainers.$.pipeline_status"] == "interview_reschedule_requested"
    assert stored["top_trainers.$.reschedule_requested"] is True
    assert stored["top_trainers.$.meet_link"] == ""
    assert stored["top_trainers.$.interview_link"] == ""
    assert stored["top_trainers.$.previous_meet_link"] == OLD_LINK
    assert stored["top_trainers.$.previous_calendar_event_id"] == "OLD-EVENT"
    db["email_logs"].update_many.assert_awaited()
    create_event.assert_not_awaited()


def test_trainer_reschedule_slots_go_to_client_without_profile_package(monkeypatch):
    trainer = _trainer(reschedule_requested=True, pipeline_status="interview_reschedule_requested", meet_link="", interview_link="")
    db = _database(trainer)
    send = _patch_sends(monkeypatch)

    result = asyncio.run(inbox._handle_trainer_slot_reply(db, {
        "email_id": "IN-TRAINER-SLOTS",
        "requirement_id": "REQ-1",
        "trainer_id": "TR-1",
        "from_email": "trainer@example.com",
        "source_outbound_mail_type": "mail4_reschedule_request",
        "subject": "Re: Interview Reschedule Request - DevOps",
        "body": (
            "15 October 2026, 10:00 AM - 10:30 AM IST\n"
            "15 October 2026, 02:15 PM - 02:45 PM IST\n"
            "15 October 2026, 04:30 PM - 05:00 PM IST"
        ),
    }))

    assert result["success"] is True
    assert result["mail_type"] == "client_reschedule_slots"
    assert result["to"] == "client@example.com"
    assert send.await_count == 1
    sent = send.await_args.kwargs
    assert sent["to"] == "client@example.com"
    assert "Revised Interview Slots" in sent["subject"]
    for line in (
        "15 October 2026, 10:00 AM IST",
        "15 October 2026, 02:15 PM IST",
        "15 October 2026, 04:30 PM IST",
    ):
        assert line in sent["body"]
    assert "Annapurna" in sent["body"]
    assert "Murali" not in sent["body"]
    assert "commercial" not in sent["body"].lower()
    assert "linkedin" not in sent["body"].lower()
    assert "attached" not in sent["body"].lower()
    logged = db["email_logs"].insert_one.await_args.args[0]
    assert logged["mail_type"] == "client_reschedule_slots"
    assert logged["slot_text"].count("15 October 2026") == 3
    stored = db["shortlists"].update_one.await_args.args[1]["$set"]
    assert stored["top_trainers.$.pipeline_status"] == "interview_reschedule_requested"
    assert stored["top_trainers.$.reschedule_requested"] is True


def _confirmation_db(trainer, slots):
    db = _database(trainer)

    async def find_email(query, *args, **kwargs):
        mail_type = query.get("mail_type")
        if mail_type == "client_reschedule_slots" or query.get("email_id") == "EML-SLOTS":
            return {"email_id": "EML-SLOTS", "slot_text": slots, "status": "sent"}
        if mail_type == "client_slots":
            return {"email_id": "EML-HANDOFF", "slot_text": "01 January 2026, 09:00 AM IST", "status": "sent"}
        if mail_type == "mail4":
            return {
                "email_id": "EML-OLD",
                "status": "sent",
                "meet_link": OLD_LINK,
                "interview_link": OLD_LINK,
                "calendar_event_id": "OLD-EVENT",
                "reschedule_retired_at": "2026-10-02T00:00:00",
            }
        return None

    db["email_logs"].find_one.side_effect = find_email
    return db


def test_client_slot_choice_creates_new_meet_for_both_people(monkeypatch):
    trainer = _trainer(
        reschedule_requested=True,
        pipeline_status="interview_reschedule_requested",
        meet_link="",
        interview_link="",
        previous_meet_link=OLD_LINK,
        previous_calendar_event_id="OLD-EVENT",
        reschedule_slots_email_id="EML-SLOTS",
    )
    db = _confirmation_db(trainer, REVISED_SLOTS)
    send = _patch_sends(monkeypatch)
    create_event = AsyncMock(return_value={"success": True, "event_id": "NEW-EVENT", "meet_link": NEW_LINK})
    cancel_event = AsyncMock(return_value={"success": True})
    client_mail = AsyncMock(return_value={"success": True, "email_id": "EML-CLIENT"})
    monkeypatch.setattr(inbox, "create_google_meet_event", create_event)
    monkeypatch.setattr(inbox, "cancel_google_calendar_event", cancel_event)
    monkeypatch.setattr(inbox, "_send_client_interview_schedule_email", client_mail)

    result = asyncio.run(inbox._handle_client_slot_confirmation_reply(db, {
        "email_id": "IN-CHOICE",
        "requirement_id": "REQ-1",
        "trainer_id": "TR-1",
        "from_email": "client@example.com",
        "source_outbound_mail_type": "client_reschedule_slots",
        "source_outbound_email_id": "EML-SLOTS",
        "subject": "Re: Revised Interview Slots - DevOps",
        "in_reply_to": "<slots@example.com>",
        "body": "I select slot 2.",
    }))

    assert result["success"] is True
    assert result["interview_link"] == NEW_LINK
    args = create_event.await_args.kwargs
    assert args["attendees"] == ["trainer@example.com", "client@example.com"]
    assert args["start"].strftime("%Y-%m-%d %H:%M") == "2026-11-06 14:15"
    assert send.await_args.kwargs["to"] == "trainer@example.com"
    assert NEW_LINK in send.await_args.kwargs["body"]
    assert OLD_LINK not in send.await_args.kwargs["body"]
    assert client_mail.await_args.kwargs["client_email"] == "client@example.com"
    assert client_mail.await_args.kwargs["meeting_link"] == NEW_LINK
    assert cancel_event.await_args.args[0] == "OLD-EVENT"


def test_client_supplied_time_after_trainer_reschedule_books_both(monkeypatch):
    trainer = _trainer(
        reschedule_requested=True,
        reschedule_requested_by="trainer",
        pipeline_status="interview_reschedule_requested",
        previous_meet_link=OLD_LINK,
        previous_calendar_event_id="OLD-EVENT",
        meet_link="",
        interview_link="",
    )
    db = _confirmation_db(trainer, REVISED_SLOTS)
    send = _patch_sends(monkeypatch)
    create_event = AsyncMock(return_value={"success": True, "event_id": "NEW-EVENT", "meet_link": NEW_LINK})
    cancel_event = AsyncMock(return_value={"success": True})
    client_mail = AsyncMock(return_value={"success": True, "email_id": "EML-CLIENT"})
    monkeypatch.setattr(inbox, "create_google_meet_event", create_event)
    monkeypatch.setattr(inbox, "cancel_google_calendar_event", cancel_event)
    monkeypatch.setattr(inbox, "_send_client_interview_schedule_email", client_mail)

    result = asyncio.run(inbox._handle_client_slot_confirmation_reply(db, {
        "email_id": "IN-TIME",
        "requirement_id": "REQ-1",
        "trainer_id": "TR-1",
        "from_email": "client@example.com",
        "source_outbound_mail_type": "client_interview_reschedule_request",
        "subject": "Re: Interview Reschedule Request - DevOps | Divya",
        "body": "15 October 2026, 3:00 PM - 3:30 PM IST works for me.",
    }))

    assert result["success"] is True
    assert result["interview_link"] == NEW_LINK
    assert create_event.await_args.kwargs["start"].strftime("%Y-%m-%d %H:%M") == "2026-10-15 15:00"
    assert send.await_args.kwargs["to"] == "trainer@example.com"
    assert client_mail.await_args.kwargs["meeting_link"] == NEW_LINK
    assert client_mail.await_count == 1
    assert send.await_count == 1


def test_missing_client_time_does_not_send_a_generic_ack(monkeypatch):
    trainer = _trainer(reschedule_requested=True, reschedule_requested_by="trainer", pipeline_status="interview_reschedule_requested")
    db = _database(trainer)
    send = _patch_sends(monkeypatch)
    create_event = AsyncMock()
    monkeypatch.setattr(inbox, "create_google_meet_event", create_event)

    result = asyncio.run(inbox._handle_client_slot_confirmation_reply(db, {
        "requirement_id": "REQ-1",
        "trainer_id": "TR-1",
        "from_email": "client@example.com",
        "source_outbound_mail_type": "client_interview_reschedule_request",
        "subject": "Re: Interview Reschedule Request - DevOps",
        "body": "Thanks, I will check and reply later.",
    }))

    assert result["attempted"] is True
    assert result["success"] is False
    assert result["reason"] == "client_reschedule_time_missing"
    send.assert_not_awaited()
    create_event.assert_not_awaited()


def test_meet_failure_does_not_claim_a_booking_or_send_a_link(monkeypatch):
    trainer = _trainer(
        reschedule_requested=True,
        pipeline_status="interview_reschedule_requested",
        meet_link="",
        interview_link="",
        previous_meet_link=OLD_LINK,
        previous_calendar_event_id="OLD-EVENT",
        reschedule_slots_email_id="EML-SLOTS",
    )
    db = _confirmation_db(trainer, REVISED_SLOTS)
    send = _patch_sends(monkeypatch)
    create_event = AsyncMock(return_value={"success": False, "error": "Google OAuth token not found."})
    client_mail = AsyncMock()
    monkeypatch.setattr(inbox, "create_google_meet_event", create_event)
    monkeypatch.setattr(inbox, "_send_client_interview_schedule_email", client_mail)

    result = asyncio.run(inbox._handle_client_slot_confirmation_reply(db, {
        "requirement_id": "REQ-1",
        "trainer_id": "TR-1",
        "from_email": "client@example.com",
        "source_outbound_mail_type": "client_reschedule_slots",
        "source_outbound_email_id": "EML-SLOTS",
        "subject": "Re: Revised Interview Slots - DevOps",
        "body": "Slot 2 works.",
    }))

    assert result["success"] is False
    assert result["reason"] == "calendar_failed_no_mail_sent"
    assert result["interview_link"] == ""
    send.assert_not_awaited()
    client_mail.assert_not_awaited()
    logged = db["email_logs"].insert_one.await_args.args[0]
    assert logged["mail_type"] == "calendar_failure_report"
    assert "old-meet-link" not in logged["body"]
    assert "booked" not in logged["body"].lower()


def test_ai_meet_link_change_and_commercial_request_fall_back(monkeypatch):
    async def changed_link(**kwargs):
        return "Hi Priya,\n\nPlease join https://meet.google.com/fake-room\n\nThanks,\nAnnapurna U.\nClahan Technologies"

    async def asks_commercial(**kwargs):
        return "Hi Divya,\n\nPlease share your commercial and three slots.\n\nThanks,\nAnnapurna U.\nClahan Technologies"

    reference = (
        "Hi Priya,\n\nMeeting Link: https://meet.google.com/real-room\n\n"
        "Thanks,\nAnnapurna U.\nClahan Technologies"
    )
    db = {"automation_settings": _collection({"value": "ai"})}
    monkeypatch.setattr("app.routes.inbox_actions._ai_draft_reply", changed_link)
    body, source = asyncio.run(inbox._client_pipeline_email_body(
        db,
        requirement={"requirement_id": "REQ-1"},
        workflow="client_interview_confirmation",
        subject="Interview Schedule Confirmation - DevOps",
        reference_body=reference,
        context={"meeting_link": "https://meet.google.com/real-room"},
    ))
    assert source == "template_fallback"
    assert body == reference

    trainer_reference = (
        "Hi Divya,\n\nPlease share exactly three convenient slots on 15 October 2026, "
        "including the date, time, and time zone.\n\nThanks,\nAnnapurna U.\nClahan Technologies"
    )
    monkeypatch.setattr("app.routes.inbox_actions._ai_draft_reply", asks_commercial)
    body, source = asyncio.run(inbox._reschedule_mail_body(
        db=db,
        requirement={"requirement_id": "REQ-1", "technology_needed": "DevOps"},
        recipient_kind="trainer",
        subject="Interview Reschedule Request - DevOps",
        inbound_text="Please reschedule to 15 October 2026.",
        reference_body=trainer_reference,
        requested_date="15 October 2026",
    ))
    assert source == "template_fallback"
    assert body == trainer_reference
    assert "commercial" not in body.lower()


def test_ai_slot_rewrite_that_drops_a_time_uses_the_template(monkeypatch):
    trainer = _trainer(reschedule_requested=True, pipeline_status="interview_reschedule_requested", meet_link="", interview_link="")
    db = _database(trainer)
    db["automation_settings"].find_one.return_value = {"value": "ai"}
    send = _patch_sends(monkeypatch)

    async def dropped_slot(**kwargs):
        return "Hi Priya,\n\nOnly 15 October 2026, 10:00 AM IST remains.\n\nThanks,\nAnnapurna U.\nClahan Technologies"

    monkeypatch.setattr("app.routes.inbox_actions._ai_draft_reply", dropped_slot)
    result = asyncio.run(inbox._handle_trainer_slot_reply(db, {
        "email_id": "IN-AI",
        "requirement_id": "REQ-1",
        "trainer_id": "TR-1",
        "from_email": "trainer@example.com",
        "source_outbound_mail_type": "mail4_reschedule_request",
        "body": (
            "15 October 2026, 10:00 AM - 10:30 AM IST\n"
            "15 October 2026, 02:15 PM - 02:45 PM IST\n"
            "15 October 2026, 04:30 PM - 05:00 PM IST"
        ),
    }))

    assert result["success"] is True
    assert result["generation_source"] == "template_fallback"
    sent = send.await_args.kwargs["body"]
    assert "02:15 PM IST" in sent
    assert "04:30 PM IST" in sent
    assert "Only 15 October" not in sent
