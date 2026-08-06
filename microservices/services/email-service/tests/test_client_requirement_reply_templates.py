import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.routes.inbox import _client_proceed_ack_reply, _extract_requirement_from_email


def test_partial_client_requirement_reply_asks_only_missing_details():
    body = (
        "Dear clahan,\n\n"
        "We have a requirement for a FullStack trainer\n\n"
        "Training Dates: 22 august to 30 august\n\n"
        "Kindly confirm your availability.\n\n"
        "Best regards,\n"
        "shob"
    )

    extracted = _extract_requirement_from_email(
        "FullStack trainer requirement",
        body,
        sender_email="shob@example.com",
        sender_name="shob",
    )
    reply = _client_proceed_ack_reply(extracted)

    assert "Thank you for sharing your training requirement." in reply["body"]
    assert "To help us refine the shortlist" in reply["body"]
    assert "- Training duration" in reply["body"]
    assert "- Training mode/location" in reply["body"]
    assert "- Participant count" in reply["body"]
    assert "- Budget or expected commercial range, if available" in reply["body"]
    assert "Thank you for sharing the required details for your training requirement." not in reply["body"]
