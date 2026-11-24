import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agents import email_agent


def test_resolve_gmail_sender_email_prefers_configured_address():
    smtp_config = {
        "smtpUser": "sender@example.com",
        "fromEmail": "reply@example.com",
        "fromName": "Clahan",
    }

    assert email_agent._resolve_gmail_sender_email(smtp_config, "fallback@example.com") == "reply@example.com"


def test_resolve_gmail_sender_email_falls_back_to_configured_user():
    smtp_config = {"smtpUser": "sender@example.com"}

    assert email_agent._resolve_gmail_sender_email(smtp_config, "") == "sender@example.com"
