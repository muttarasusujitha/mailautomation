import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.routes.inbox import _handle_trainer_slot_reply


def test_client_requirement_in_slot_thread_is_not_trainer_reply():
    result = asyncio.run(_handle_trainer_slot_reply({}, {
        "source_outbound_mail_type": "client_slots",
        "subject": "Devops requirement",
        "body": "Confirmed training from 10 September to 7 October 2026, 3 hours per day",
    }))
    assert result == {"attempted": False, "reason": "client_thread_not_trainer_slot_reply"}


def test_other_sender_cannot_update_linked_trainer_slots():
    db = {
        "shortlists": SimpleNamespace(find_one=AsyncMock(return_value={"top_trainers": [
            {"trainer_id": "TR-1", "email": "trainer@example.com"}
        ]})),
        "requirements": SimpleNamespace(find_one=AsyncMock(return_value={})),
    }
    result = asyncio.run(_handle_trainer_slot_reply(db, {
        "source_outbound_mail_type": "mail3", "requirement_id": "REQ-1", "trainer_id": "TR-1",
        "from_email": "client@example.com", "body": "10 September 2026 at 10 AM",
    }))
    assert result == {"attempted": False, "reason": "sender_not_linked_trainer"}
