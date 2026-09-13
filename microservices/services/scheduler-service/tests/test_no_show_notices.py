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


def test_no_show_notice_is_eight_minutes_after_start_and_reaches_missing_party_and_clahan(monkeypatch):
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
    assert result["sent"] == 3
    assert {item["to"] for item in sent} == {"trainer@example.com", "client@example.com", "sujithaofficial784@gmail.com"}
    clahan = next(item for item in sent if item["to"] == "sujithaofficial784@gmail.com")
    assert "trainer joined" in clahan["body"]
    client = next(item for item in sent if item["to"] == "client@example.com")
    assert "trainer joined" in client["body"]
    assert all("10 minutes ago" in item["body"] for item in sent)
    assert any(update.get("$set", {}).get("followup_suppressed") is True for _, update in emails.updates)
