import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.routes import inbox


class ClientClarificationNoFollowupTests(unittest.TestCase):
    def test_client_reply_to_clarification_is_processed_without_another_send(self):
        db = MagicMock()
        collection = MagicMock()
        collection.find_one = AsyncMock(return_value={
            "body": "Please share your preferred cloud platform to finalize the lab estimate.",
        })
        db.__getitem__.return_value = collection
        email_doc = {
            "email_id": "IN-2",
            "from_email": "client@example.com",
            "source_outbound_email_id": "OUT-1",
            "source_outbound_mail_type": "client_auto_reply",
            "email_classification": {"person_type": "corporate_client", "scenario": "client_requirement"},
        }

        with patch.object(inbox, "_auto_send_settings", AsyncMock(return_value={"enabled": True})), \
             patch.object(inbox, "_auto_send_risk_reason", return_value=""), \
             patch("app.recipient_guard.recipient_error", AsyncMock(return_value=None)) as recipient_guard:
            result = asyncio.run(inbox._send_client_auto_reply(
                db,
                email_doc,
                {"subject": "Re: DevOps training", "body": "Thanks for confirming AWS."},
                requirement_id="REQ-1",
                mail_type_override="client_lab_cost_revised",
            ))

        self.assertTrue(result["success"])
        self.assertTrue(result.get("suppressed"), (result, collection.find_one.call_args_list))
        self.assertEqual(result["reason"], "client_replied_to_clarification_no_followup")
        recipient_guard.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
