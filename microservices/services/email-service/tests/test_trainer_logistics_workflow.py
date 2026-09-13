import asyncio

from app.routes import inbox
from app.routes.inbox import (
    _is_trainer_logistics_question,
    _logistics_ai_output_is_grounded,
    _verified_logistics_details,
)


class _Collection:
    def __init__(self, document):
        self.document = document
        self.updated = None

    async def find_one(self, *args, **kwargs):
        return self.document

    async def update_one(self, *args, **kwargs):
        self.updated = (args, kwargs)


class _Database:
    def __init__(self):
        self.collections = {
            "trainer_logistics_queries": _Collection({
                "query_id": "LQ-001",
                "requirement_id": "REQ-001",
                "trainer_id": "TR-001",
                "trainer_name": "Asha",
                "trainer_email": "asha@example.com",
                "client_email": "client@example.com",
                "clarification_subject": "Travel / Stay Clarification Required - DevOps",
                "status": "client_asked",
            }),
            "requirements": _Collection({"requirement_id": "REQ-001", "batch_flow": "proposal", "client_email": "client@example.com"}),
            "shortlists": _Collection({"top_trainers": [{"trainer_id": "TR-001", "email": "asha@example.com"}]}),
        }

    def __getitem__(self, name):
        return self.collections[name]


def test_travel_terms_are_detected_for_both_batch_types():
    # Detection is intentionally workflow-neutral; requirement linkage makes
    # it available to both confirmed and proposal batches.
    assert _is_trainer_logistics_question("Will local transport be reimbursed?")
    assert _is_trainer_logistics_question("Do you arrange hotel stay for onsite delivery?")


def test_food_and_meal_questions_are_detected():
    for question in ('Who provides food?', 'Are meals covered?', 'Lunch charges?', 'Per diem allowance?'):
        assert _is_trainer_logistics_question(question)


def test_location_does_not_answer_expense_question():
    assert inbox._logistics_missing_topics({'location': 'Bengaluru'}, 'Who covers travel and food?') == [
        'travel arrangements and reimbursement terms', 'food provision and meal reimbursement terms']


def test_partial_answer_still_requests_missing_topic():
    req = {'travel_policy': 'Client arranges flights', 'food_policy': 'To be confirmed'}
    assert inbox._logistics_missing_topics(req, 'Travel and meals?') == ['food provision and meal reimbursement terms']
    req['food_policy'] = 'Trainer pays for meals; no reimbursement'
    assert inbox._logistics_missing_topics(req, 'Travel and meals?') == []


def test_only_stored_logistics_are_used_for_confirmed_and_proposal_batches():
    confirmed = {
        "batch_flow": "confirmed",
        "travel_policy": "Air travel is reimbursed against receipts.",
        "location": "Bengaluru",
    }
    proposal = {
        "batch_flow": "proposal",
        "accommodation_policy": "Hotel stay is arranged by the client.",
    }

    assert _verified_logistics_details(confirmed) == [
        "Air travel is reimbursed against receipts.", "Bengaluru",
    ]
    assert _verified_logistics_details(proposal) == [
        "Hotel stay is arranged by the client.",
    ]


def test_ai_logistics_wording_cannot_add_expense_approval_or_amount():
    clarification = "Please confirm the travel policy and reimbursement terms."
    assert not _logistics_ai_output_is_grounded(
        "All travel expenses will be covered up to INR 10,000.", clarification
    )


def test_ai_logistics_wording_can_restate_verified_commitment():
    reference = "Travel expenses will be reimbursed against submitted receipts."
    assert _logistics_ai_output_is_grounded(
        "Your travel expenses will be reimbursed against submitted receipts.", reference
    )


def test_client_reply_without_logistics_keyword_is_relayed(monkeypatch):
    database = _Database()
    delivered = {}

    async def body(*args, **kwargs):
        return kwargs["reference_body"], "template"

    async def settings(*args, **kwargs):
        return {}

    async def send(**kwargs):
        delivered.update(kwargs)
        return True, ""

    monkeypatch.setattr(inbox, "_client_pipeline_email_body", body)
    monkeypatch.setattr(inbox, "_load_admin_settings", settings)
    monkeypatch.setattr(inbox, "send_email_async", send)

    result = asyncio.run(inbox._relay_client_logistics_answer(database, {
        "from_email": "client@example.com",
        "subject": "Re: Travel / Stay Clarification Required - DevOps",
        "body": "Yes, that is included.",
    }))

    assert result["success"] is True
    assert delivered["to"] == "asha@example.com"


def test_unrelated_client_email_is_not_relayed_as_logistics_answer(monkeypatch):
    database = _Database()

    async def should_not_send(**kwargs):
        raise AssertionError("Unrelated client email must not be relayed")

    monkeypatch.setattr(inbox, "send_email_async", should_not_send)
    result = asyncio.run(inbox._relay_client_logistics_answer(database, {
        "from_email": "client@example.com",
        "subject": "Re: Invoice request",
        "body": "Please share the invoice.",
    }))

    assert result == {"attempted": False}
