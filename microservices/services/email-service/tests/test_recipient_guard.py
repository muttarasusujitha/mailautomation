import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from app.recipient_guard import recipient_error


class RecipientGuardTests(unittest.TestCase):
    def check(self, email, kind):
        db = MagicMock()
        db.__getitem__.return_value.find_one = AsyncMock(side_effect=[
            {"client_email": "client@example.com"},
            {"top_trainers": [{"trainer_id": "T1", "email": "trainer@example.com"}]},
        ])
        return asyncio.run(recipient_error(db, email, "R1", "T1", kind))

    def test_trainer_followup_cannot_go_to_client(self):
        for kind in ("mail2_followup", "mail2followup", "trainer_auto_reply"):
            self.assertEqual(self.check("client@example.com", kind), "trainer_mail_recipient_is_client")

    def test_client_handoff_cannot_go_to_trainer(self):
        self.assertEqual(self.check("trainer@example.com", "client_slots"), "client_mail_recipient_is_trainer")

    def test_correct_recipients_are_allowed(self):
        self.assertEqual(self.check("Trainer <TRAINER@example.com>", "mail2_followup"), "")
        self.assertEqual(self.check("client@example.com", "client_slots"), "")

    def test_unknown_address_requires_review(self):
        self.assertEqual(self.check("unknown@example.com", "mail4"), "workflow_recipient_unverified")

    def test_legacy_requirement_without_client_email_allows_client_reply(self):
        db = MagicMock()
        db.__getitem__.return_value.find_one = AsyncMock(side_effect=[
            {}, {"top_trainers": [{"trainer_id": "T1", "email": "trainer@example.com"}]},
        ])
        result = asyncio.run(recipient_error(db, "client@example.com", "R1", "T1", "client_auto_reply"))
        self.assertEqual(result, "")
