import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.routes.inbox import _find_outbound_log_for_reply


class FakeCursor:
    def __init__(self, docs):
        self.docs = list(docs)

    def sort(self, *args, **kwargs):
        return self

    def limit(self, count):
        self.docs = self.docs[:count]
        return self

    async def to_list(self, count):
        return self.docs[:count]

    def __aiter__(self):
        self._index = 0
        return self

    async def __anext__(self):
        if self._index >= len(self.docs):
            raise StopAsyncIteration
        doc = self.docs[self._index]
        self._index += 1
        return doc


class FakeEmailLogs:
    def __init__(self, exact=None, ref_docs=None, subject_docs=None):
        self.exact = exact
        self.ref_docs = ref_docs or []
        self.subject_docs = subject_docs or []
        self.find_one_queries = []
        self.find_queries = []

    async def find_one(self, query, *args, **kwargs):
        self.find_one_queries.append(query)
        return self.exact

    def find(self, query, *args, **kwargs):
        self.find_queries.append(query)
        if query.get("trainer_id"):
            return FakeCursor(self.ref_docs)
        return FakeCursor(self.subject_docs)


class FakeDb(dict):
    def __init__(self, email_logs):
        super().__init__()
        self["email_logs"] = email_logs


def test_outbound_reply_match_uses_gmail_headers_before_ref():
    exact_log = {
        "email_id": "EML-MAIL2",
        "gmail_message_id": "<mail2@example.com>",
        "mail_type": "mail2",
    }
    ref_log = {
        "email_id": "EML-MAIL3",
        "gmail_message_id": "<mail3@example.com>",
        "mail_type": "mail3",
        "subject": "Trainer availability Ref: REQ-123 / TR-999",
    }
    email_logs = FakeEmailLogs(exact=exact_log, ref_docs=[ref_log])

    match = asyncio.run(
        _find_outbound_log_for_reply(
            FakeDb(email_logs),
            from_email="trainer@example.com",
            subject="Re: Trainer availability Ref: REQ-123 / TR-999",
            message_ids=["<mail2@example.com>"],
            body="Ref: REQ-123 / TR-999",
        )
    )

    assert match["email_id"] == "EML-MAIL2"
    assert email_logs.find_queries == []
    assert email_logs.find_one_queries[0]["gmail_message_id"] == {"$in": ["<mail2@example.com>"]}


def test_outbound_reply_ref_fallback_uses_stage_order():
    ref_docs = [
        {
            "email_id": "EML-MAIL1",
            "mail_type": "mail1",
            "subject": "Different subject Ref: REQ-123 / TR-999",
            "created_at": "2026-07-25T10:00:00",
        },
        {
            "email_id": "EML-MAIL3",
            "mail_type": "mail3",
            "subject": "Different subject Ref: REQ-123 / TR-999",
            "created_at": "2026-07-24T10:00:00",
        },
    ]
    email_logs = FakeEmailLogs(exact=None, ref_docs=ref_docs)

    match = asyncio.run(
        _find_outbound_log_for_reply(
            FakeDb(email_logs),
            from_email="trainer@example.com",
            subject="Re: unrelated Ref: REQ-123 / TR-999",
            message_ids=[],
            body="Ref: REQ-123 / TR-999",
        )
    )

    assert match["email_id"] == "EML-MAIL3"
