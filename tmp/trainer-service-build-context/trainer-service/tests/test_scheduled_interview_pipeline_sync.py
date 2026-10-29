import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from app.routes import shortlists


class ScheduleCursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *_args):
        return self

    def __aiter__(self):
        async def rows():
            for row in self.rows:
                yield row
        return rows()


def test_persisted_interview_schedule_advances_stale_slots_received_stage():
    trainer = {
        "trainer_id": "T-1",
        "email": "trainer@example.com",
        "pipeline_status": "slot_booked",
        "slot_status": "sent_to_client",
    }
    schedule = {
        "trainer_id": "T-1",
        "interview_scheduled": True,
        "interview_date": "2026-09-30 10:00 AM IST",
        "interview_link": "https://meet.example/room",
    }

    assert shortlists._apply_interview_schedule(trainer, schedule) is True
    assert trainer["pipeline_status"] == "interview_scheduled"
    assert trainer["slot_status"] == "interview_link_sent"
    assert trainer["interview_scheduled"] is True
    assert trainer["interview_date"] == schedule["interview_date"]
    assert trainer["interview_link"] == schedule["interview_link"]


def test_schedule_sync_matches_email_and_preserves_later_pipeline_stages():
    trainer = {
        "trainer_id": "T-2",
        "email": "trainer@example.com",
        "pipeline_status": "selected",
    }
    doc = {"top_trainers": [trainer]}
    db = {
        "email_logs": SimpleNamespace(find=Mock(return_value=ScheduleCursor([{
            "trainer_email": "TRAINER@example.com",
            "interview_scheduled": True,
            "interview_at": "2026-09-30T10:00:00+05:30",
            "meet_link": "https://meet.example/room",
        }]))),
        "shortlists": SimpleNamespace(update_one=AsyncMock()),
    }

    result = asyncio.run(shortlists._sync_scheduled_interviews(db, "REQ-1", doc))

    assert result is doc
    assert trainer["interview_scheduled"] is True
    assert trainer["pipeline_status"] == "selected"
    db["shortlists"].update_one.assert_awaited_once()
