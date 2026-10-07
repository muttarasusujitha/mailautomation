"""Annapurna signs coordination mail. Murali signs finance mail."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.agents.natural_voice import choose_voice, voice_for_situation
from app.agents.reply_templates import build_auto_reply, render_delivery_reply
from app.routes.inbox import _client_interview_schedule_message
from app.routes.inbox_actions import _build_lab_reference_reply, _structure_email_draft, writing_guidance


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


def test_toc_and_lab_cost_is_one_annapurna_reply():
    reply = render_delivery_reply(
        client_name="Asha",
        subject="Kubernetes ToC and lab cost",
        technology="Kubernetes",
        toc_requested=True,
        lab_requested=True,
        toc_attached=True,
        lab_attached=True,
        lab_sentence="Please find the lab-cost estimate attached for 20 participant(s), with 3 hours of lab access per day.",
    )
    assert choose_voice(reply["template_key"]) == "annapurna"
    assert reply["body"].startswith("Hi Asha,")
    assert "Greetings of the day! Thanks for sharing the ToC and lab-cost request" in reply["body"]
    assert "day-wise ToC" in reply["body"]
    assert "lab-cost estimate" in reply["body"]
    assert reply["body"].count("Annapurna U.") == 1
    assert "Murali Mohan M" not in reply["body"]
    assert "Recruitment Team" not in reply["body"]
    assert "Dear" not in reply["body"]


def test_toc_only_stays_with_annapurna():
    reply = render_delivery_reply(
        client_name="Asha",
        subject="Need the ToC",
        technology="DevOps",
        toc_requested=True,
        toc_attached=True,
    )
    assert reply["template_key"] == "client_toc_only"
    assert reply["body"].endswith("Thanks,\nAnnapurna U.\nClahan Technologies")
    assert "trainer shortlisting will not start" in reply["body"].lower()


def test_purchase_order_template_uses_murali():
    reply = build_auto_reply(
        {
            "person_type": "corporate_client",
            "scenario": "client_sends_po",
            "auto_reply_allowed": True,
            "requires_human": False,
        },
        {"client_name": "Asha", "technology_needed": "DevOps"},
        subject="Purchase order",
        sender_name="Asha",
    )
    assert choose_voice("client_po_received_ack") == "murali"
    assert reply["body"].startswith("Hello Asha,")
    assert reply["body"].endswith("Thanks and Regards,\nMurali Mohan M\nClahan Technologies")
    assert "Annapurna U." not in reply["body"]
    assert "purchase order" in reply["body"].lower()


def test_lab_reference_uses_annapurna_and_keeps_the_missing_input():
    reply = _build_lab_reference_reply(
        {
            "known_inputs": {"cloud_provider": "aws", "duration_days": 5, "hours_per_day": 3},
            "missing_quote_inputs": ["participant_count"],
            "request_type": "lab_access_only",
        },
        {"client_name": "Sneha", "technology_needed": "DevOps"},
        "Sneha",
        "Lab cost",
        also_toc=True,
        toc_attached=True,
    )
    assert reply["template_key"] == "client_toc_and_lab_cost"
    assert reply["body"].startswith("Hi Sneha,")
    assert "number of participants/users requiring access" in reply["body"]
    assert "day-wise ToC" in reply["body"]
    assert reply["body"].endswith("Thanks,\nAnnapurna U.\nClahan Technologies")
    assert "Murali Mohan M" not in reply["body"]
    assert "Recruitment Team" not in reply["body"]


def test_interview_confirmation_carries_lab_cost_in_the_same_note():
    message = _client_interview_schedule_message(
        client_name="Asha",
        trainer_name="Ravi",
        technology="Kubernetes",
        requirement_id="REQ-1",
        interview_date="10 Oct, 10:00 AM",
        meeting_link="https://meet.google.com/abc-defg-hij",
        extra_paragraph="Please find the day-wise ToC and the lab-cost estimate attached with this interview confirmation.",
    )
    assert message["body"].count("Annapurna U.") == 1
    assert "Murali Mohan M" not in message["body"]
    assert message["body"].count("lab-cost estimate") == 1
    assert "https://meet.google.com/abc-defg-hij" in message["body"]


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
    assert "exactly one person" in writing_guidance("annapurna")
    assert "exactly one email" in writing_guidance("murali")
    assert "both a ToC and a lab cost" in writing_guidance("annapurna")


def test_ai_voice_follows_the_situation_rather_than_a_mixed_subject():
    assert voice_for_situation("client_toc_and_lab_cost", "client_asks_toc_and_lab_cost", subject="Invoice and PO") == "annapurna"
    assert voice_for_situation("client_invoice_request_ack", subject="ToC and lab cost") == "murali"
    assert voice_for_situation("client_po_received_ack") == "murali"
    assert voice_for_situation(subject="Please share the invoice") == "murali"
