import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.routes import inbox


def test_trainer_decision_delivery_uses_composed_body_and_returns_result(monkeypatch):
    shortlist = SimpleNamespace(find_one=AsyncMock(return_value={
        "top_trainers": [{"trainer_id": "TR-1", "email": "trainer@example.com", "name": "Asha"}],
    }))
    email_logs = SimpleNamespace(insert_one=AsyncMock())
    db = {"shortlists": shortlist, "email_logs": email_logs}
    sent = {}

    async def compose(_payload):
        return {"subject": "Trainer selected", "body": "Congratulations, Asha."}

    async def send(_db, _requirement_id, _trainer_id, _kind, **kwargs):
        sent.update(kwargs)
        return True, ""

    monkeypatch.setattr(inbox, "compose_mail5_selection", compose)
    monkeypatch.setattr(inbox, "_load_admin_settings", AsyncMock(return_value={}))
    monkeypatch.setattr(inbox, "_send_verified_workflow_email", send)

    result = asyncio.run(inbox._send_trainer_decision_mail(
        db,
        email_doc={"email_id": "IN-1", "technology": "DevOps"},
        requirement_id="REQ-1",
        trainer_id="TR-1",
        decision="selected",
        now=datetime(2026, 9, 8),
    ))

    assert result["success"] is True
    assert sent["body"] == "Congratulations, Asha."
    assert email_logs.insert_one.await_args.args[0]["body"] == "Congratulations, Asha."
