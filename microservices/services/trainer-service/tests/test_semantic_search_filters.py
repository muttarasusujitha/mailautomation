import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.routes import trainers as trainer_routes


class EmptyCursor:
    def sort(self, *_args, **_kwargs):
        return self

    def limit(self, _limit):
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


class TrainerCollection:
    query = None

    def find(self, query, _projection=None):
        self.query = query
        return EmptyCursor()


class FakeDatabase:
    def __init__(self):
        self.trainers = TrainerCollection()


def test_semantic_search_applies_domain_and_location_as_required_filters(monkeypatch):
    async def domain_clauses(_db, value):
        assert value == "DevOps"
        return [{"technology_category": {"$regex": "DevOps", "$options": "i"}}]

    monkeypatch.setattr(trainer_routes, "_domain_search_clauses", domain_clauses)

    db = FakeDatabase()
    result = asyncio.run(trainer_routes.semantic_trainer_search(
        q="Python trainer",
        limit=15,
        domain="DevOps",
        location="Pune",
        db=db,
    ))

    assert result["items"] == []
    query = db.trainers.query
    assert query["$or"]  # The natural-language query is still used for retrieval.
    filters = query["$and"]
    assert len(filters) == 2
    assert any("technology_category" in clause for clause in filters[0]["$or"])
    location_clause = filters[1]["$or"]
    assert any(
        field == "location" and condition["$regex"] == "Pune"
        for clause in location_clause
        for field, condition in clause.items()
    )
