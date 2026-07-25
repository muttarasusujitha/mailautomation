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

    def fake_oauth(*, to, subject, body, from_name, from_email, tracking_url, attachments=None):
        called["invoked"] = True
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
