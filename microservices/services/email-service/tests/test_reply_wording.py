import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.agents.reply_wording import (
    WORDING_BANKS, ai_wording_examples, recent_sent_replies, repeats_recent, vary_template,
)

SITUATIONS = [
    "Thank you for sharing your availability.",
    "Thank you for confirming the slot.",
    "Thank you for the update.",
    "To help us refine the shortlist, please share:",
    "We will check this against the client schedule and update you on the next step.",
    "Please share 2-3 alternate slots if not already shared.",
    "We will review it and share it with the client for confirmation.",
    "We will review internally and update you if there is scope for revision.",
    "You're welcome.",
    "We will check the invoice status and share the invoice copy/update shortly.",
    "Check your microphone, speakers, and internet connection before joining.",
    "Please join now if you are available. If you need to reschedule, reply with your preferred date and time zone.",
]


@pytest.mark.parametrize("reference", SITUATIONS)
def test_ten_options_before_reuse_and_locked_facts_preserved(reference):
    facts = "\n\n12 October 2026, 3:00 PM IST\nINR 12,500 per day\nhttps://meet.google.com/abc-defg-hij"
    history = []
    for _ in range(10):
        generated = vary_template(reference + facts, history, seed="same-recipient")
        assert generated not in history
        assert generated.endswith(facts)
        history.insert(0, generated)
    assert len(set(history)) == 10
    # When the bank is exhausted, the least recently sent alternative is used.
    assert vary_template(reference + facts, history, seed="same-recipient") == history[-1]


def test_every_bank_has_ten_unique_options():
    assert len(WORDING_BANKS) == len(SITUATIONS)
    for _, variants in WORDING_BANKS.values():
        assert len(variants) == len(set(variants)) == 10


def test_professional_requirement_thanks_is_not_varied():
    body = "Thank you for sharing the DevOps requirement. We have noted the topics, 7 training days, Offline delivery mode, and 3 lab hours per day."
    assert vary_template(body, [], seed="x") == body
    with_us = "Thank you for sharing the DevOps requirement with us. We have noted the topics."
    assert vary_template(with_us, [], seed="x") == with_us
    for opening in (
        "Thank you for sending over the Python training requirement.",
        "Thank you for providing the DevOps training requirements.",
        "Thank you for sending us the DevOps requirement.",
        "Thank you for sharing the DevOps training details.",
        "Thank you for sharing your DevOps training requirements.",
    ):
        assert vary_template(opening, [], seed="x") == opening


def test_unmatched_answers_and_quoted_messages_are_not_rewritten():
    text = "The confirmed amount is INR 20,000.\n> Thank you for the update.\nNo discount is approved."
    assert vary_template(text, [], seed="x") == text


def test_examples_are_relevant_and_avoid_last_wording():
    body = "Thank you for sharing the Azure syllabus."
    previous = vary_template(body, seed="x")
    examples = ai_wording_examples(body, [previous], seed="x")
    assert len(examples) == 1
    assert examples[0]["situation"] == "details_received"
    assert "Azure syllabus" in examples[0]["alternative"]
    assert examples[0]["alternative"] != previous
    assert ai_wording_examples("The approved invoice amount is INR 20,000.") == []


def test_repetition_check_ignores_greeting_and_signature_changes():
    content = "We will review the trainer availability against your proposed schedule and share an update once confirmed."
    assert repeats_recent("Hi Mira,\n\n" + content + "\n\nRegards,\nClahan Technologies",
                          ["Dear Mira,\n\n" + content + "\n\nBest Regards,\nRecruitment Team\nClahan Technologies"])
    assert not repeats_recent("You're welcome.", ["You're welcome."])
    assert not repeats_recent("The invoice has been approved and the attached copy includes your corrected billing address.", [content])


def test_history_only_loads_sent_mail_for_exact_recipient():
    class Cursor:
        def sort(self, field, order):
            assert (field, order) == ("sent_at", -1)
            return self
        def limit(self, count):
            assert count == 10
            return self
        def __aiter__(self):
            async def rows():
                yield {"body": "An actual sent reply."}
            return rows()
    class Collection:
        def find(self, query, projection):
            assert query["direction"] == "outbound"
            assert query["status"] == "sent"
            assert query["$or"][0]["to_email"] == {"$regex": r"^mira@example\.com$", "$options": "i"}
            return Cursor()
    assert asyncio.run(recent_sent_replies({"email_logs": Collection()}, "Mira <MIRA@example.com>")) == ["An actual sent reply."]
