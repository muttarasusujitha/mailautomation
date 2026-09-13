"""Check Calendar request payloads without sending real invitations."""
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from app import calendar_client


class CalendarGuestPrivacyTests(unittest.TestCase):
    def assert_private_invitation(self, request):
        body = request["body"]
        self.assertIs(body["guestsCanSeeOtherGuests"], False)
        self.assertIs(body["guestsCanInviteOthers"], False)
        self.assertIs(body["guestsCanModify"], False)
        self.assertEqual(request["sendUpdates"], "all")
        self.assertEqual(
            {item["email"] for item in body["attendees"]},
            {"trainer@example.com", "client@example.com"},
        )

    def test_new_event_hides_guest_addresses(self):
        service = MagicMock()
        service.events.return_value.insert.return_value.execute.return_value = {
            "id": "event-1", "hangoutLink": "https://meet.google.com/example",
        }
        with patch.object(calendar_client, "_load_calendar_service", return_value=(service, "")):
            result = calendar_client._create_google_meet_event_sync(
                summary="Interview", description="Interview coordination",
                start=datetime(2026, 9, 10, 16), end=datetime(2026, 9, 10, 16, 30),
                attendees=["trainer@example.com", "client@example.com"],
            )
        self.assertTrue(result["success"])
        self.assert_private_invitation(service.events.return_value.insert.call_args.kwargs)

    def test_adding_guest_to_existing_event_hides_guest_addresses(self):
        service = MagicMock()
        service.events.return_value.get.return_value.execute.return_value = {
            "attendees": [{"email": "trainer@example.com"}],
            "guestsCanSeeOtherGuests": True,
        }
        service.events.return_value.patch.return_value.execute.return_value = {
            "id": "event-1", "hangoutLink": "https://meet.google.com/example",
        }
        with patch.object(calendar_client, "_load_calendar_service", return_value=(service, "")):
            result = calendar_client._add_calendar_attendees_sync("event-1", ["client@example.com"])
        self.assertTrue(result["success"])
        self.assert_private_invitation(service.events.return_value.patch.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
