from datetime import datetime, timedelta

from app.tasks.meet_start_notices import _notice_body, _notice_window


def test_notice_window_targets_ten_minutes_before_interview():
    now = datetime(2026, 9, 3, 10, 0)
    start, end = _notice_window(now)
    assert start == now + timedelta(minutes=9)
    assert end == now + timedelta(minutes=11)
    assert start <= now + timedelta(minutes=10) <= end


def test_notice_body_asks_recipient_to_join_early():
    body = _notice_body(
        name="Asha",
        technology="DevOps",
        interview_link="https://meet.google.com/example",
        interview_date="03 September 2026, 10:10 AM IST",
    )
    assert "starts in 10 minutes" in body
    assert "join a few minutes before" in body
    assert "https://meet.google.com/example" in body
