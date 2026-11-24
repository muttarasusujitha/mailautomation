import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.routes import inbox


@pytest.mark.parametrize("answer, owner", [
    # The client writes these, so "we" is the client and "you" is Clahan.
    ("We'll book the tickets", "client"),
    ("We will provide lunch", "client"),
    ("Our team will arrange the stay", "client"),
    ("Provided by us", "client"),
    ("Lunch from our side", "client"),
    ("Client will pay for travel", "client"),
    ("You can book the hotel", "clahan"),
    ("Clahan to book", "clahan"),
    ("Please arrange accommodation", "clahan"),
    ("To be arranged by you", "clahan"),
    ("We cannot arrange the hotel", "needs_review"),
    ("Trainer to book and claim", "needs_review"),
    ("We'll book the tickets; you arrange the hotel", "needs_review"),
    ("Lunch will be provided", "needs_review"),
])
def test_owner_is_read_from_the_clients_point_of_view(answer, owner):
    assert inbox._logistics_owner(answer) == owner


def test_one_sentence_can_assign_two_items_and_leave_the_third_open():
    found = inbox._client_offline_logistics("Hi,\n\nWe'll book the tickets and provide lunch.\n\nRegards,\nAsha")

    assert {item: value["owner"] for item, value in found.items()} == {"travel": "client", "food": "client"}
    assert found["travel"]["answer"] == "We'll book the tickets"


def test_each_clause_keeps_its_own_owner():
    found = inbox._client_offline_logistics("You can book the hotel near the venue; we will cover lunch.")
    assert {item: value["owner"] for item, value in found.items()} == {"accommodation": "clahan", "food": "client"}

    found = inbox._client_offline_logistics("Travel, stay and food will be arranged by us.")
    assert {item: value["owner"] for item, value in found.items()} == {
        "travel": "client", "accommodation": "client", "food": "client"}

    found = inbox._client_offline_logistics("We will not provide accommodation, but lunch is on us.")
    assert {item: value["owner"] for item, value in found.items()} == {"accommodation": "needs_review", "food": "client"}


def test_labeled_lines_win_and_passing_mentions_or_questions_are_ignored():
    found = inbox._client_offline_logistics(
        "Travel: Clahan to book\nAccommodation: provided by us\nThe hotel is close to the office.")
    assert {item: value["owner"] for item, value in found.items()} == {"travel": "clahan", "accommodation": "client"}

    assert inbox._client_offline_logistics("Thank you, we will share the participant list.") == {}
    assert inbox._client_offline_logistics("Will you book the tickets?") == {}
    assert inbox._client_offline_logistics("The hotel is near the venue and lunch starts at 1 pm.") == {}


@pytest.mark.parametrize("text, preference", [
    ("Please create a WhatsApp group with the trainer for travel coordination.", True),
    ("We would like a whatsapp group for tickets and location.", True),
    ("No need for a WhatsApp group.", False),
    ("Is there a WhatsApp group?", None),
    ("We will share details on email.", None),
])
def test_whatsapp_group_request_is_read_without_a_model(text, preference):
    assert inbox._whatsapp_group_preference(text) is preference


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *args, **kwargs):
        return self

    def limit(self, count):
        return self

    def __aiter__(self):
        async def rows():
            for row in self.rows:
                yield row
        return rows()


def _client_emails(rows):
    return SimpleNamespace(find=lambda *args, **kwargs: _Cursor(rows))


def test_logistics_so_far_reads_every_client_email_and_later_statements_win():
    requirement = {"client_email": "asha@acme.com", "offline_logistics": {"owners": {"accommodation": "needs_review"}}}
    rows = [
        {"email_id": "E1", "from_email": "Asha <asha@acme.com>",
         "body": "Offline Kubernetes training in Pune. We'll book the tickets and provide lunch. "
                 "Please create a WhatsApp group with the trainer."},
        {"email_id": "E2", "from_email": "trainer@example.com", "body": "I will book my own hotel."},
        {"email_id": "E3", "from_email": "asha@acme.com", "body": "Accommodation: please book a hotel near the office."},
    ]
    result = asyncio.run(inbox._offline_logistics_so_far(
        {"client_emails": _client_emails(rows)}, "REQ-1", requirement,
        {"email_id": "E4", "from_email": "asha@acme.com", "body": "We have selected the trainer."},
    ))

    assert result["owners"] == {"travel": "client", "food": "client", "accommodation": "clahan"}
    assert result["whatsapp_group_requested"] is True


def test_selection_records_earlier_logistics_and_group_request_without_resetting_a_task():
    requirement = {"requirement_id": "REQ-1", "delivery_mode": "Offline", "client_email": "asha@acme.com"}
    requirements = SimpleNamespace(find_one=AsyncMock(return_value=requirement), update_one=AsyncMock())
    tasks = SimpleNamespace(update_one=AsyncMock())
    db = {
        "shortlists": SimpleNamespace(
            find_one=AsyncMock(return_value={"top_trainers": [{"trainer_id": "TR-1", "name": "Ravi", "email": "ravi@example.com"}]}),
            update_one=AsyncMock()),
        "requirements": requirements,
        "client_emails": _client_emails([
            {"email_id": "E1", "from_email": "asha@acme.com",
             "body": "We'll book the tickets and provide lunch. Please create a WhatsApp group with the trainer."},
        ]),
        "offline_coordination_tasks": tasks,
        "finance_approvals": SimpleNamespace(update_one=AsyncMock()),
        "email_logs": SimpleNamespace(find_one=AsyncMock(return_value={"email_id": "EML-5", "to_email": "ravi@example.com"}),
                                      insert_one=AsyncMock()),
    }
    asyncio.run(inbox._handle_client_selection_reply(db, {
        "email_id": "E2", "from_email": "asha@acme.com", "clean_body": "We have selected the trainer.",
        "requirement_id": "REQ-1", "trainer_id": "TR-1",
    }))

    task_update = tasks.update_one.await_args.args[1]
    assert task_update["$set"]["logistics_owners"] == {"travel": "client", "food": "client"}
    assert task_update["$set"]["whatsapp_group_requested"] is True
    assert "status" not in task_update["$set"] and task_update["$setOnInsert"]["status"] == "pending_trainer_po_approval"

    updates = [call.args for call in requirements.update_one.await_args_list]
    logistics = next(update for _, update in updates if "offline_logistics.owners.travel" in update["$set"])
    assert logistics["$set"]["offline_logistics.owners.food"] == "client"
    assert logistics["$set"]["offline_logistics.whatsapp_group_requested"] is True
    status_filter = next(query for query, update in updates if "trainer_po_approval_status" in update["$set"])
    assert status_filter["offline_coordination_task_id"] == {"$ne": "offline-coordination:REQ-1:TR-1"}
