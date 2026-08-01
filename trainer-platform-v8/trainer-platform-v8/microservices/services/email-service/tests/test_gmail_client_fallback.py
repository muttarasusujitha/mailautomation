import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
