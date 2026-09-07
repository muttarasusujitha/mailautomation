import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.routes import inbox


class FollowupFailureTests(unittest.TestCase):
    def run_followup(self, status):
        db = MagicMock()
        db.__getitem__.return_value.find_one = AsyncMock(return_value={"status": status, "email_id": "previous"})
        db.__getitem__.return_value.update_one = AsyncMock()
        sender = AsyncMock(return_value={"success": True})
        with patch.object(inbox, "_send_client_auto_reply", sender):
            result = asyncio.run(inbox._send_missing_trainer_details_followup(
                db, email_doc={"requirement_id": "R1", "trainer_id": "T1", "from_email": "trainer@example.com"},
                requirement={"client_email": "client@example.com"},
                trainer_state={"email": "trainer@example.com"},
                missing_details=["Current location"], now=inbox._now(),
            ))
        return result, sender

    def test_failed_attempt_can_retry(self):
        result, sender = self.run_followup("failed")
        self.assertTrue(result["success"])
        sender.assert_awaited_once()

    def test_sent_attempt_is_not_repeated(self):
        result, sender = self.run_followup("sent")
        self.assertTrue(result["success"])
        sender.assert_not_awaited()

    def test_uncertain_delivery_is_not_reported_as_success(self):
        result, sender = self.run_followup("sending")
        self.assertFalse(result["success"])
        self.assertFalse(result["already_attempted"])
        sender.assert_not_awaited()
