import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.routes.inbox import _client_proceed_ack_reply, _extract_requirement_from_email, _requirement_payload_from_email


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


def test_natural_month_range_counts_as_preferred_dates():
    body = (
        "Good morning,\n\n"
        "Need a DevOps trainer. Sep 2 to Sep 20 works for us.\n"
        "Mode online, 20 participants, 15 days, budget INR 50000.\n"
    )

    extracted = _extract_requirement_from_email(
        "DevOps trainer requirement",
        body,
        sender_email="client@example.com",
        sender_name="Siri 2265",
    )
    reply = _client_proceed_ack_reply(extracted)

    assert extracted["preferred_dates"] == "Sep 2 to Sep 20"
    assert extracted["training_dates"] == "Sep 2 to Sep 20"
    assert "- Preferred dates or timings" not in reply["body"]


def test_requirement_payload_preserves_original_client_request_text():
    body = (
        "Hi Team,\n\n"
        "Need DevOps trainer from 2 Sep to 20 Sep.\n"
        "Commercials 50000 per day, online delivery.\n\n"
        "Regards,\nClient"
    )
    extracted = _extract_requirement_from_email("DevOps trainer", body, "client@example.com", "Client")
    payload = _requirement_payload_from_email({"email_id": "E1", "body": body, "subject": "DevOps trainer"}, extracted)

    assert "Need DevOps trainer from 2 Sep to 20 Sep." in payload["client_requirement_text"]
    assert payload["metadata"]["original_body"] == payload["client_requirement_text"]


def test_date_first_training_dates_are_extracted_from_recent_client_request():
    body = (
        "Dear clahan,\n"
        "We have a requirement for a Devops trainer\n"
        "Training Dates: 15  august to 29 august\n"
        "Kindly confirm your availability.\n\n"
        "Best regards,\n"
        "yamuna"
    )

    extracted = _extract_requirement_from_email(
        "Devops training requriment",
        body,
        sender_email="yamuna@example.com",
        sender_name="yamuna",
    )

    assert extracted["preferred_dates"] == "15 august to 29 august"
    assert extracted["training_dates"] == "15 august to 29 august"
    assert extracted["timeline_start"] == "15 august"
    assert extracted["timeline_end"] == "29 august"
    assert "Preferred dates or timings" not in extracted["needs_clarification"]


def test_preferred_dates_or_timings_label_is_extracted():
    body = (
        "- Training duration : 200 hours\n"
        "- Preferred dates or timings   :sep 15 to sep 30\n"
        "- Training mode/location : offline\n"
        "- Participant count : 28\n"
        "- Budget or expected commercial range, if available : 400000\n"
    )

    extracted = _extract_requirement_from_email(
        "Re: DevOps Trainer Requirement",
        body,
        sender_email="client@example.com",
        sender_name="Client",
    )

    assert extracted["preferred_dates"] == "sep 15 to sep 30"
    assert extracted["training_dates"] == "sep 15 to sep 30"
    assert "Preferred dates or timings" not in extracted["needs_clarification"]
