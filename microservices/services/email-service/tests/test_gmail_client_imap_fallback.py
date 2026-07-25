import imaplib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import gmail_client


class FakeIMAPMailbox:
    def __init__(self, *args, **kwargs):
        self.login_calls = []
        self.closed = False

    def login(self, user, pwd):
        self.login_calls.append((user, pwd))
        if user == "primary@gmail.com":
            raise imaplib.IMAP4.error(b"[AUTHENTICATIONFAILED] Invalid credentials (Failure)")
        return "OK", b""

    def select(self, *args, **kwargs):
        return "OK", []

    def search(self, *args, **kwargs):
        return "OK", [b""]

    def fetch(self, *args, **kwargs):
        return "OK", []

    def close(self):
        self.closed = True

    def logout(self):
        self.closed = True


def test_check_imap_replies_uses_fallback_credentials(monkeypatch):
    created_mailboxes = []

    def fake_imap4_ssl(host, port, timeout=20):
        mailbox = FakeIMAPMailbox()
        created_mailboxes.append(mailbox)
        return mailbox

    monkeypatch.setattr(gmail_client.imaplib, "IMAP4_SSL", fake_imap4_ssl)
    monkeypatch.setattr(gmail_client.settings, "GMAIL_USER", "primary@gmail.com")
    monkeypatch.setattr(gmail_client.settings, "GMAIL_APP_PASSWORD", "primary-pass")
    monkeypatch.setattr(gmail_client.settings, "GMAIL_PASS", "")
    monkeypatch.setattr(gmail_client.settings, "GMAIL_FALLBACK_USER", "fallback@gmail.com")
    monkeypatch.setattr(gmail_client.settings, "GMAIL_FALLBACK_APP_PASSWORD", "fallback-pass")
    monkeypatch.setattr(gmail_client.settings, "GMAIL_FALLBACK_PASS", "")

    replies = gmail_client.check_imap_replies(since_days=3, max_messages=5)

    assert replies == []
    assert len(created_mailboxes) == 1
    assert created_mailboxes[0].login_calls == [
        ("primary@gmail.com", "primary-pass"),
        ("fallback@gmail.com", "fallback-pass"),
    ]
