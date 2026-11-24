import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from app.routes import inbox


class Cursor:
    def __init__(self, rows):
        self.rows = iter(rows)

    def sort(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.rows)
        except StopIteration:
            raise StopAsyncIteration


def test_legacy_client_handoff_retry_is_marked_after_single_attempt(monkeypatch):
    email = {
        "email_id": "EMAIL-LEGACY-1",
        "requirement_id": "REQ-1",
        "trainer_id": "TR-1",
        "source_outbound_mail_type": "mail1",
        "status": "needs_manual_review",
        "auto_send_error": "Client handoff is temporarily delayed and will retry automatically.",
    }
    client_emails = SimpleNamespace(
        find=Mock(return_value=Cursor([email])),
        update_one=AsyncMock(),
    )
    db = {"client_emails": client_emails}
    process = AsyncMock(return_value={"status": "needs_manual_review"})
    monkeypatch.setattr(inbox, "_process_client_requirement_email", process)

    result = asyncio.run(inbox._process_pending_client_emails(db))

    assert result["checked"] == 1
    process.assert_awaited_once_with(db, email)
    updates = [call.args[1]["$set"] for call in client_emails.update_one.await_args_list]
    assert any("legacy_client_handoff_retry_checked_at" in update for update in updates)
    query = client_emails.find.call_args.args[0]
    assert "legacy_client_handoff_retry_checked_at" in str(query)
