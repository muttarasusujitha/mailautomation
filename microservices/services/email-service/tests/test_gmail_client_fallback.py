import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import gmail_client
from app.gmail_client import _build_sender_candidates


def test_build_sender_candidates_includes_fallback_when_configured():
    candidates = _build_sender_candidates(
        smtp_config={
            "smtpUser": "primary@gmail.com",
            "smtpPass": "primary-pass",
            "fromName": "Primary",
            "fromEmail": "primary@gmail.com",
            "fallbackSmtpUser": "fallback@gmail.com",
            "fallbackSmtpPass": "fallback-pass",
            "fallbackFromName": "Fallback",
            "fallbackFromEmail": "fallback@gmail.com",
        }
    )

    assert len(candidates) == 2
    assert candidates[0]["smtpUser"] == "primary@gmail.com"
    assert candidates[1]["smtpUser"] == "fallback@gmail.com"
    assert candidates[1]["fromName"] == "Fallback"


def test_send_smtp_uses_oauth_when_smpt_password_missing(monkeypatch):
    called = {}

    monkeypatch.setattr(gmail_client.settings, "GMAIL_USER", "primary@gmail.com")
    monkeypatch.setattr(gmail_client.settings, "GMAIL_APP_PASSWORD", "")
    monkeypatch.setattr(gmail_client.settings, "GMAIL_PASS", "")

    def fake_oauth(*, to, subject, body, from_name, from_email, tracking_url, attachments=None, message_id_header=""):
        called["invoked"] = True
        called["message_id_header"] = message_id_header
        return True, ""

    monkeypatch.setattr(gmail_client, "send_gmail_oauth", fake_oauth)

    ok, error = gmail_client.send_smtp(
        to="trainer@example.com",
        subject="Test",
        body="Hello",
        smtp_config={"smtpUser": "primary@gmail.com", "smtpPass": ""},
    )

    assert ok is True
    assert error == ""
    assert called["invoked"] is True


def test_client_ack_template_is_not_treated_as_trainer_reply():
    body = (
        "Dear Client,\n\n"
        "Thank you for sharing the required details for your training requirement.\n\n"
        "We will proceed with the trainer search and share suitable profiles with experience, skill set, availability, and commercials for your review shortly.\n\n"
        "Best Regards,\nRecruitment Team\nClahan Technologies"
    )

    assert gmail_client._is_trainer_reply(body) is False
    assert gmail_client._normalize_trainer_reply_body(body) == body
    html = gmail_client._html_template(body, "Clahan Technologies", "team@example.com")
    assert "Trainer Matching Platform" in html
    assert "Trainer Coordination Platform" not in html
