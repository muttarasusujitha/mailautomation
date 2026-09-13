from datetime import datetime
from zoneinfo import ZoneInfo

from app.main import _welcome_message


def test_welcome_message_uses_names_and_time_of_day():
    log = {"client_name": "Client Team", "trainer_name": "Asha Trainer"}
    assert _welcome_message(log, datetime(2026, 9, 11, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))).startswith("Good morning")
    afternoon = _welcome_message(log, datetime(2026, 9, 11, 14, 0, tzinfo=ZoneInfo("Asia/Kolkata")))
    assert "Hi Client Team" in afternoon and "hi Asha Trainer" in afternoon
    assert "microphone" in afternoon and "internet" in afternoon
    assert "stay in the meeting until the interview ends" in afternoon


def test_welcome_message_has_evening_greeting():
    assert _welcome_message({}, datetime(2026, 9, 11, 19, 0, tzinfo=ZoneInfo("Asia/Kolkata"))).startswith("Good evening")
