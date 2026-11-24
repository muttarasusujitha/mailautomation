from app.routes.send import CalendarInvite, _build_calendar_invite_ics


def test_calendar_invite_contains_native_ten_minute_popup_alarm():
    ics = _build_calendar_invite_ics(CalendarInvite(
        summary="DevOps Interview",
        start="2026-09-11T16:00:00",
        end="2026-09-11T17:00:00",
        meeting_url="https://meet.google.com/example",
    ), "client@example.com")
    assert "BEGIN:VALARM" in ics
    assert "ACTION:DISPLAY" in ics
    assert "TRIGGER:-PT10M" not in ics
    assert "DESCRIPTION:Interview starts in 5 minutes" in ics
    assert "TRIGGER:-PT5M" in ics
