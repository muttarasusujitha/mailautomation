import base64
from email.message import EmailMessage

from app import gmail_client


class _Request:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class _Messages:
    def __init__(self, raw):
        self.raw = raw

    def list(self, **_kwargs):
        return _Request({"messages": [{"id": "gmail-message-1"}]})

    def get(self, **_kwargs):
        return _Request({"raw": self.raw, "internalDate": "0"})


class _Users:
    def __init__(self, raw):
        self.raw = raw

    def messages(self):
        return _Messages(self.raw)


class _Service:
    def __init__(self, raw):
        self.raw = raw

    def users(self):
        return _Users(self.raw)


def test_gmail_api_captures_safe_excel_toc(monkeypatch):
    message = EmailMessage()
    message["From"] = "client@example.com"
    message["To"] = "inbox@example.com"
    message["Subject"] = "DevOps training requirement"
    message["Message-ID"] = "<client-toc@example.com>"
    message.set_content("Please use the attached day-wise TOC.")
    excel_bytes = b"test excel toc bytes"
    message.add_attachment(
        excel_bytes,
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="DevOps TOC.xlsx",
    )
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    monkeypatch.setattr(gmail_client, "_load_oauth_service", lambda: (_Service(raw), ""))

    replies = gmail_client.check_gmail_api_replies(max_messages=1)

    assert replies[0]["attachment_names"] == ["DevOps TOC.xlsx"]
    attachment = replies[0]["attachments"][0]
    assert attachment["safe_client_scope"] is True
    assert attachment["size_bytes"] == len(excel_bytes)
    assert base64.b64decode(attachment["content_base64"]) == excel_bytes
