import asyncio

from app.routes import shortlists


class Collection:
    def __init__(self, document=None):
        self.document = document or {}
        self.update = None
        self.inserted = None

    async def find_one(self, *args, **kwargs):
        return self.document

    async def update_one(self, *args, **kwargs):
        self.update = (args, kwargs)

    async def insert_one(self, document):
        self.inserted = document


class Database(dict):
    pass


class BookingTaskCollection(Collection):
    async def find_one(self, query, *args, **kwargs):
        if not self.inserted:
            return {}
        if query.get("booking_task_id") and query["booking_task_id"] != self.inserted.get("booking_task_id"):
            return {}
        return self.inserted


def logistics_db():
    return Database({
        "requirements": Collection({
            "requirement_id": "REQ-1",
            "selected_trainer_id": "TR-1",
            "selected_trainer_name": "Asha",
            "client_email": "client@example.com",
            "client_name": "Acme",
            "technology_needed": "DevOps",
            "delivery_mode": "Offline",
        }),
        "shortlists": Collection({
            "requirement_id": "REQ-1",
            "selected_trainer_id": "TR-1",
            "top_trainers": [{
                "trainer_id": "TR-1", "name": "Asha", "email": "asha@example.com",
                "pipeline_status": "selected",
            }],
        }),
        "trainer_logistics_queries": Collection(),
        "admin_settings": Collection(),
    })


def test_post_selection_logistics_only_targets_selected_trainer():
    db = logistics_db()
    payload = shortlists.PostSelectionLogisticsRequest(
        venue_address="42 Main Road, Bengaluru",
        venue_maps_url="https://www.google.com/maps/search/?api=1&query=42",
        trainer_origin="Chennai",
    )

    result = asyncio.run(shortlists.save_post_selection_logistics("REQ-1", "TR-1", payload, db))

    assert result["success"] is True
    assert db["shortlists"].update[0][0]["top_trainers.trainer_id"] == "TR-1"
    assert result["logistics"]["venue_address"] == "42 Main Road, Bengaluru"


def test_client_logistics_request_creates_reply_link_for_selected_trainer(monkeypatch):
    db = logistics_db()

    async def sent(**kwargs):
        return {"success": True, "email_id": "EMAIL-1"}

    monkeypatch.setattr(shortlists, "_send_post_selection_logistics_email", sent)
    payload = shortlists.PostSelectionLogisticsRequest(
        venue_address="42 Main Road, Bengaluru",
        venue_maps_url="https://www.google.com/maps/search/?api=1&query=42",
        trainer_origin="Chennai",
        preferred_travel_mode="Train",
    )

    result = asyncio.run(shortlists.request_client_logistics_confirmation("REQ-1", "TR-1", payload, db))

    assert result["success"] is True
    assert result["sent_to"] == "client@example.com"
    query = db["trainer_logistics_queries"].inserted
    assert query["status"] == "client_asked"
    assert query["trainer_id"] == "TR-1"
    assert query["logistics_snapshot"]["venue_maps_url"].startswith("https://www.google.com/maps/")


def booking_db():
    db = logistics_db()
    db["shortlists"].document["top_trainers"][0]["post_interview_logistics"] = {
        "delivery_mode": "Offline",
        "client_confirmed_venue": "42 Main Road, Bengaluru",
        "client_confirmed_maps_url": "https://www.google.com/maps/search/?api=1&query=42",
        "client_confirmed_travel_terms": "Clahan will arrange and book the train ticket up to INR 12,000.",
        "training_dates": "10-12 December 2026",
        "trainer_origin": "Chennai",
    }
    db["travel_booking_tasks"] = BookingTaskCollection()
    return db


def test_client_authorized_booking_creates_finance_approval_task_only():
    db = booking_db()
    payload = shortlists.CreateTravelBookingTaskRequest(
        client_authorization_text="Please ask Clahan to book the trainer's train ticket.",
        ticket_required=True,
    )

    result = asyncio.run(shortlists.create_travel_booking_task("REQ-1", "TR-1", payload, db))

    assert result["success"] is True
    task = db["travel_booking_tasks"].inserted
    assert task["status"] == "awaiting_finance_approval"
    assert task["final_purchase_requires_confirmation"] is True
    assert task["venue_maps_url"].startswith("https://www.google.com/maps/")
    assert db["shortlists"].update[0][1]["$set"]["top_trainers.$.post_interview_logistics.booking_status"] == "awaiting_finance_approval"


def test_booking_task_rejects_unverified_or_unclear_client_instruction():
    db = booking_db()
    payload = shortlists.CreateTravelBookingTaskRequest(
        client_authorization_text="The trainer may travel by train.",
        ticket_required=True,
    )

    try:
        asyncio.run(shortlists.create_travel_booking_task("REQ-1", "TR-1", payload, db))
        assert False, "Expected client authorization validation to fail"
    except shortlists.HTTPException as error:
        assert error.status_code == 422


def test_finance_approval_notifies_booking_agent_and_makes_task_ready(monkeypatch):
    db = booking_db()
    created = asyncio.run(shortlists.create_travel_booking_task(
        "REQ-1", "TR-1",
        shortlists.CreateTravelBookingTaskRequest(
            client_authorization_text="Clahan should arrange and book the trainer ticket.",
        ),
        db,
    ))
    task_id = created["booking_task"]["booking_task_id"]

    async def notified(task, database):
        assert task["booking_task_id"] == task_id
        return {"status": "sent", "email": "travel-agent@example.com", "email_id": "EMAIL-1"}

    monkeypatch.setattr(shortlists, "_notify_travel_booking_agent", notified)

    result = asyncio.run(shortlists.approve_travel_booking_task(
        "REQ-1", "TR-1", task_id,
        shortlists.ApproveTravelBookingTaskRequest(approved_by="Finance Team"),
        db,
    ))

    assert result["status"] == "ready_to_book"
    assert result["booking_agent"]["status"] == "sent"
    assert db["travel_booking_tasks"].update[0][1]["$set"]["status"] == "ready_to_book"
