import asyncio
from datetime import datetime, timedelta

from app.tasks import no_show_notices


class Cursor:
    def __init__(self, items): self.items = items
    def limit(self, _size): return self
    def __aiter__(self):
        async def iterate():
            for item in self.items: yield item
        return iterate()


class Collection:
    def __init__(self, items): self.items, self.updates = items, []
    def find(self, _query): return Cursor(self.items)
    async def find_one_and_update(self, _query, _update): return self.items[0]
    async def update_one(self, query, update): self.updates.append((query, update))
    async def update_many(self, query, update): self.updates.append((query, update))


def test_no_show_notice_is_ten_minutes_after_start_and_only_reaches_missing_trainer(monkeypatch):
    now = datetime.utcnow()
    log = {
        "email_id": "EML-NOSHOW", "direction": "outbound", "mail_type": "mail4", "status": "sent",
        "interview_scheduled": True, "interview_at": now - timedelta(minutes=10),
        "meet_bot_status": "joined", "meet_attendance_source": "meet_bot_visible_participants",
        "meet_participant_view_available": True, "meet_attendance_observed_at": now,
        "trainer_email": "trainer@example.com", "trainer_name": "Trainer",
        "trainer_attendance_identity_available": True, "trainer_joined": False,
        "client_email": "client@example.com", "client_name": "Client",
        "client_attendance_identity_available": True, "client_joined": True,
        "interview_link": "https://meet.google.com/example", "technology": "DevOps",
    }
    emails = Collection([log])
    monkeypatch.setattr(no_show_notices, "get_db", lambda: {"email_logs": emails, "shortlists": Collection([])})
    sent = []

    class Response:
        status_code = 200
        @staticmethod
        def json(): return {"success": True, "email_id": "NOTICE"}

    monkeypatch.setattr(no_show_notices.httpx, "post", lambda _url, json, timeout: (sent.append(json) or Response()))
    result = asyncio.run(no_show_notices._send_due_no_show_notices())
    assert result["sent"] == 1
    assert {item["to"] for item in sent} == {"trainer@example.com"}
    assert all("10 minutes ago" in item["body"] for item in sent)
    assert all(item["mail_type"] == "meet_no_show_notice" for item in sent)
    assert any(update.get("$set", {}).get("followup_suppressed") is True for _, update in emails.updates)


def test_joined_trainer_gets_no_alert_when_only_client_is_missing(monkeypatch):
    now = datetime.utcnow()
    log = {
        "email_id": "EML-CLIENT-NOSHOW", "direction": "outbound", "mail_type": "mail4", "status": "sent",
        "interview_scheduled": True, "interview_at": now - timedelta(minutes=10),
        "meet_bot_status": "joined", "meet_attendance_source": "meet_bot_visible_participants",
        "meet_participant_view_available": True, "meet_attendance_observed_at": now,
        "trainer_email": "trainer@example.com", "trainer_name": "Trainer",
        "trainer_attendance_identity_available": True, "trainer_joined": True,
        "client_email": "client@example.com", "client_name": "Client",
        "client_attendance_identity_available": True, "client_joined": False,
        "interview_link": "https://meet.google.com/example", "technology": "DevOps",
    }
    emails = Collection([log])
    monkeypatch.setattr(no_show_notices, "get_db", lambda: {"email_logs": emails, "shortlists": Collection([])})
    monkeypatch.setattr(no_show_notices.httpx, "post", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("no email should be sent when the trainer joined")
    ))

    result = asyncio.run(no_show_notices._send_due_no_show_notices())

    assert result["sent"] == 0
    assert result["skipped"] == 1
    assert emails.updates[-1][1]["$set"]["no_show_check_result"] == "client_missing_trainer_joined"
