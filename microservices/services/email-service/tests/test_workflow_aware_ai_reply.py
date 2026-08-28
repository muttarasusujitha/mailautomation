import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.agents.email_classifier import SCENARIO_KEYWORDS, classify_email
from app.agents.reply_templates import build_auto_reply
from app.routes.inbox_actions import (
    _build_lab_reference_reply,
    _client_document_delivery_context,
    _clean_incoming_email,
    _lab_request_context,
    _normalise_item_status,
    _load_reply_workflow_context,
)


class FakeCollection:
    def __init__(self, document=None):
        self.document = document

    async def find_one(self, *_args, **_kwargs):
        return self.document


class FakeDb(dict):
    pass


LAB_ONLY_EMAIL = """
Dear Clahan Technologies Team,

We have a requirement for DevOps & AWS lab access only.
Duration: 10 days
Lab Access: 3 hours per day
Total Lab Usage: 30 hours

Please share the total lab cost.

Regards,\nSneha
"""


def test_lab_only_request_is_classified_as_lab_setup_not_training_requirement():
    classification = classify_email(
        subject="DevOps and AWS lab access",
        body=LAB_ONLY_EMAIL,
        sender_email="sneha@example.com",
        sender_name="Sneha",
    )

    assert classification["person_type"] == "corporate_client"
    assert classification["scenario"] == "client_asks_lab_setup"


def test_lab_context_extracts_quote_inputs_and_only_asks_for_missing_participants():
    context = _lab_request_context(LAB_ONLY_EMAIL, {"technology_needed": "DevOps & AWS"})

    assert context["request_type"] == "lab_access_only"
    assert context["known_inputs"]["cloud_provider"] == "aws"
    assert context["known_inputs"]["duration_days"] == 10
    assert context["known_inputs"]["hours_per_day"] == 3
    assert context["known_inputs"]["total_hours"] == 30
    assert context["missing_quote_inputs"] == ["participant_count"]

    reply = _build_lab_reference_reply(
        context,
        {"client_name": "Sneha", "technology_needed": "DevOps & AWS"},
        "Sneha",
        "DevOps and AWS lab access",
    )
    assert "number of participants/users requiring access" in reply["body"]
    assert "preferred training dates" not in reply["body"].lower()
    assert "trainer shortlist" not in reply["body"].lower()
    assert "lab-access-only" in reply["body"]
    assert reply["auto_send_safe"] is False


def test_html_and_literal_escape_artifacts_are_removed_before_drafting():
    cleaned = _clean_incoming_email("Hello&lt;br&gt;Sneha\\n&amp; team&#x20;<div>Thanks</div>")

    assert "&lt;" not in cleaned
    assert "&#x20;" not in cleaned
    assert "\\n" not in cleaned
    assert "Sneha" in cleaned


def test_inbox_response_cleans_entities_from_original_and_generated_text():
    item = _normalise_item_status({
        "status": "pending_review",
        "raw_body": "Sneha&#x20;Kerel&lt;br&gt;Solutions",
        "generated_reply": {"body": "Hello&#x20;Sneha\\nThanks"},
    })

    assert "&#x20;" not in item["raw_body"]
    assert "&lt;" not in item["raw_body"]
    assert "&#x20;" not in item["generated_reply"]["body"]
    assert "\\n" not in item["generated_reply"]["body"]


def test_existing_deterministic_feature_reply_remains_available_as_grounding():
    classification = classify_email(
        subject="Invoice copy",
        body="Please share the invoice copy for this engagement.",
        sender_email="client@example.com",
        sender_name="Client",
    )
    reply = build_auto_reply(classification, {}, "Invoice copy", "Client")

    assert classification["scenario"] == "client_asks_invoice"
    assert reply["template_key"] == "client_invoice_request_ack"
    assert "invoice" in reply["body"].lower()


def test_client_reference_format_and_single_email_rules_are_grounded():
    context = _client_document_delivery_context(
        {"attachment_names": ["Client Course Agenda.xlsx"]},
        {"toc_requested": True, "toc_action": "generate_by_clahan", "requested_details": ["ToC", "Trainer Profile"]},
    )

    assert context["preferred_toc_output"] == "xlsx"
    assert context["toc_action"] == "generate_by_clahan"
    assert "actually includes it" in context["single_email_rule"]
    assert "unapproved rates" in context["lab_cost_rule"]


def test_word_toc_reference_selects_detailed_document_output():
    context = _client_document_delivery_context(
        {"attachments": [{"filename": "Five Day TOC.docx"}]},
        {"toc_requested": True},
    )
    assert context["preferred_toc_output"] == "detailed_pdf"


def test_every_declared_client_feature_has_a_deterministic_grounding_reply():
    scenarios = {name for name, _ in SCENARIO_KEYWORDS if name.startswith("client_")}
    scenarios.update({"new_training_requirement", "quote_request", "reschedule"})

    for scenario in sorted(scenarios):
        reply = build_auto_reply(
            {
                "person_type": "corporate_client",
                "scenario": scenario,
                "requires_human": False,
                "auto_reply_allowed": True,
            },
            {"client_name": "Client", "technology_needed": "Python"},
            "Client enquiry",
            "Client",
        )
        assert reply["body"].strip(), scenario
        assert reply["template_key"] != "human_review_ack", scenario
        assert "Clahan Technologies" in reply["body"], scenario


def test_workflow_context_loads_toc_profile_po_invoice_and_document_state():
    import asyncio

    db = FakeDb({
        "requirements": FakeCollection({"requirement_id": "REQ-1", "status": "active"}),
        "shortlists": FakeCollection({
            "selected_trainer_id": "TR-1",
            "top_trainers": [{"trainer_id": "TR-1", "name": "Anita", "status": "shortlisted"}],
        }),
        "toc_generations": FakeCollection({"toc_id": "TOC-1", "status": "generated"}),
        "purchase_orders": FakeCollection({"po_id": "PO-1", "status": "sent"}),
        "invoices": FakeCollection({"invoice_id": "INV-1", "invoice_number": "INV-001", "status": "sent"}),
    })

    context = asyncio.run(_load_reply_workflow_context(
        db,
        {"requirement_id": "REQ-1", "status": "pending_review"},
        {"person_type": "corporate_client", "scenario": "client_asks_invoice"},
        {"technology_needed": "Python"},
        "Please share the invoice and TOC PDF.",
    ))

    features = context["business_features"]
    assert features["training_requirement"]["exists"] is True
    assert features["trainer_profiles"]["available_count"] == 1
    assert features["toc"]["toc_id"] == "TOC-1"
    assert features["purchase_order"]["status"] == "sent"
    assert features["invoice"]["invoice_number"] == "INV-001"
    assert features["documents_and_pdfs"]["generation_available"] is True
