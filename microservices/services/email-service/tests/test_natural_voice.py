"""Annapurna signs coordination mail. Murali signs finance mail."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.agents.natural_voice import choose_voice
from app.agents.reply_templates import build_auto_reply
from app.routes.inbox_actions import _structure_email_draft, writing_guidance


def _reply(scenario):
    return build_auto_reply(
        {
            "person_type": "corporate_client",
            "scenario": scenario,
            "auto_reply_allowed": True,
            "requires_human": False,
        },
        {"client_name": "Asha", "technology_needed": "DevOps", "needs_clarification": []},
        subject="DevOps Trainer Requirement",
        sender_name="Asha",
    )


def test_coordination_template_uses_annapurna():
    reply = _reply("client_sent_details")
    assert reply["body"].startswith("Hi Asha,")
    assert "Greetings of the day! Thanks for sharing" in reply["body"]
    assert reply["body"].endswith("Thanks,\nAnnapurna U.\nClahan Technologies")
    assert "Dear" not in reply["body"]
    assert "Recruitment Team" not in reply["body"]


def test_invoice_template_uses_murali():
    reply = build_auto_reply(
        {
            "person_type": "corporate_client",
            "scenario": "client_asks_invoice",
            "auto_reply_allowed": True,
            "requires_human": False,
        },
        {"client_name": "Asha", "technology_needed": "DevOps"},
        subject="Invoice copy",
        sender_name="Asha",
    )
    assert choose_voice("client_invoice_request_ack") == "murali"
    assert reply["body"].startswith("Hello Asha,")
    assert reply["body"].endswith("Thanks and Regards,\nMurali Mohan M\nClahan Technologies")
    assert "invoice" in reply["body"].lower()


def test_draft_envelope_follows_the_same_voice():
    annapurna = _structure_email_draft("The trainer is available on 15 September.", "Asha", "annapurna")
    murali = _structure_email_draft("Please find the invoice attached.", "Asha", "murali")
    assert annapurna.startswith("Hi Asha,")
    assert annapurna.endswith("Thanks,\nAnnapurna U.\nClahan Technologies")
    assert murali.startswith("Hello Asha,")
    assert murali.endswith("Thanks and Regards,\nMurali Mohan M\nClahan Technologies")
    assert "Annapurna U" in writing_guidance("annapurna")
    assert "Murali Mohan M" in writing_guidance("murali")
    assert "under 80 words" in writing_guidance("annapurna")
