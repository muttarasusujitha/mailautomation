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
