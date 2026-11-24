import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.routes import inbox_actions


def _run_immediate(coroutine):
    """Drive this async unit with immediate AsyncMock dependencies, without an event loop."""
    while True:
        try:
            yielded = coroutine.send(None)
        except StopIteration as finished:
            return finished.value
        if yielded is not None:
            raise AssertionError(f"Unexpected async suspension in mocked approval flow: {yielded!r}")


def test_approve_inbox_reply_sends_the_saved_draft_and_marks_it_sent(monkeypatch):
    draft = "Hi Kavya,\n\nWe've received your message and will review it.\n\nThanks,\nAnnapurna U."
    client_doc = {
        "email_id": "CLH-1E4D03ADC0",
        "from_email": "kavya@emovur.com",
        "subject": "Whatsapp Business Api",
        "draft_reply": draft,
    }
    updates = []
    inserted_logs = []
    client_emails = SimpleNamespace(
        find_one=AsyncMock(return_value=client_doc),
        update_one=AsyncMock(side_effect=lambda *args, **kwargs: updates.append((args, kwargs))),
    )
    email_logs = SimpleNamespace(
        find_one=AsyncMock(return_value=None),
        insert_one=AsyncMock(side_effect=lambda log: inserted_logs.append(log)),
    )
    db = {"client_emails": client_emails, "email_logs": email_logs}
    send = AsyncMock(return_value=(True, ""))
    monkeypatch.setattr(inbox_actions, "send_email_async", send)
    monkeypatch.setattr(inbox_actions, "_smtp_config", AsyncMock(return_value={"smtpUser": "sender@example.com"}))
    monkeypatch.setattr(
        "app.recipient_guard.recipient_error",
        AsyncMock(return_value=""),
    )

    result = _run_immediate(inbox_actions.approve_inbox_reply(
        "CLH-1E4D03ADC0",
        inbox_actions.ApproveRequest(send_now=True),
        db,
    ))

    assert result["success"] is True
    assert result["status"] == "sent"
    send.assert_awaited_once()
    sent = send.await_args.kwargs
    assert sent["to"] == "kavya@emovur.com"
    assert sent["subject"] == "Re: Whatsapp Business Api"
    assert sent["body"] == draft
    assert inserted_logs[0]["status"] == "sent"
    assert inserted_logs[0]["source_email_id"] == "CLH-1E4D03ADC0"
    assert updates[0][0][1]["$set"]["reply_status"] == "sent"
