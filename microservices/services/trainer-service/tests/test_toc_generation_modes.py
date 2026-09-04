import asyncio

from app.routes import toc as toc_route
from app.routes import toc_extended


class _Collection:
    def __init__(self, document=None):
        self.document = document
        self.inserted = []

    async def find_one(self, *args, **kwargs):
        return self.document

    async def insert_one(self, document):
        self.inserted.append(document)

    async def update_one(self, query, update, **kwargs):
        current = dict(self.document or {})
        current.update(update.get("$setOnInsert") or {})
        current.update(update.get("$set") or {})
        self.document = current


class _Db:
    def __init__(self, knowledge=None):
        self.collections = {
            "toc_knowledge": _Collection(knowledge),
            "toc_generations": _Collection(),
        }

    def __getitem__(self, name):
        return self.collections[name]

    def __getattr__(self, name):
        return self.collections[name]


def _generated(domain="New Platform"):
    return {
        "domain": domain,
        "days": [{
            "day": 1,
            "title": "Day 1: Client Knowledge Topic",
            "focus_area": "Client Knowledge Topic",
            "subtopics": ["Concept"],
            "tools": "New Platform",
            "lab": "Configure a working New Platform example",
            "learning_objectives": ["Apply the client knowledge topic"],
            "morning_session": {"topics": []},
            "afternoon_session": {"topics": [{}, {}, {}]},
        }],
    }


def test_template_mode_uses_saved_toc_knowledge(monkeypatch):
    knowledge = {
        "key": "new_platform",
        "name": "New Platform",
        "domain": "New Platform",
        "active": True,
        "aliases": ["NP"],
        "level_map": {"foundation": [{"topic": "Client Knowledge Topic"}]},
    }
    db = _Db(knowledge)
    captured = {}

    def generate(*args, **kwargs):
        captured["override"] = kwargs.get("domain_override")
        return _generated()

    monkeypatch.setattr(toc_route, "generate_toc_from_dataset", generate)
    monkeypatch.setattr(toc_route, "validate_toc", lambda value, days: value)

    result = asyncio.run(toc_route.generate_toc(toc_route.TocRequest(
        domain="NP", duration_days=1, generation_mode="template"
    ), db))

    assert captured["override"]["name"] == "New Platform"
    assert result["toc_data"]["generation_mode"] == "template_knowledge"


def test_ai_mode_uses_llm_result_without_manual_knowledge(monkeypatch):
    db = _Db({
        "key": "new_platform",
        "name": "New Platform",
        "domain": "New Platform",
        "active": True,
        "level_map": {"foundation": [{"topic": "Manual-only topic"}]},
    })
    ai_result = _generated("AI Platform")

    async def generate_ai(payload):
        return ai_result

    def manual_generator(*args, **kwargs):
        raise AssertionError("Successful AI mode must not call the manual knowledge generator")

    monkeypatch.setattr(toc_route, "_generate_ai_toc", generate_ai)
    monkeypatch.setattr(toc_route, "generate_toc_from_dataset", manual_generator)

    result = asyncio.run(toc_route.generate_toc(toc_route.TocRequest(
        domain="New Platform", duration_days=1, generation_mode="ai"
    ), db))

    assert result["toc_data"]["generation_mode"] == "ai"
    assert result["toc_data"]["domain"] == "New Platform"


def test_template_mode_falls_back_to_builtin_dataset_without_saved_knowledge(monkeypatch):
    db = _Db(None)
    captured = {}

    def generate(*args, **kwargs):
        captured["override"] = kwargs.get("domain_override")
        return _generated()

    monkeypatch.setattr(toc_route, "generate_toc_from_dataset", generate)
    monkeypatch.setattr(toc_route, "validate_toc", lambda value, days: value)

    result = asyncio.run(toc_route.generate_toc(toc_route.TocRequest(
        domain="New Platform", duration_days=1, generation_mode="template"
    ), db))

    assert captured["override"] is None
    assert result["toc_data"]["generation_mode"] == "template"


def test_new_post_deployment_technology_can_be_saved_then_used_by_manual_generation(monkeypatch):
    db = _Db()
    payload = {
        "name": "Future Quantum SDK",
        "key": "future_quantum_sdk",
        "aliases": ["FQSDK"],
        "active": True,
        "level_map": {
            "foundation": [{
                "topic": "Quantum SDK Foundations",
                "subtopics": ["Runtime model", "Qubit APIs"],
                "tools": ["Future Quantum SDK"],
                "lab": "Build and execute a verified two-qubit programme",
            }],
            "core": [], "advanced": [], "observability": [], "security": [],
            "projects": [], "revision": [], "capstone": [],
        },
    }
    asyncio.run(toc_extended.save_toc_knowledge(payload, db))
    captured = {}

    def generate(*args, **kwargs):
        captured["override"] = kwargs.get("domain_override")
        return _generated("Future Quantum SDK")

    monkeypatch.setattr(toc_route, "generate_toc_from_dataset", generate)
    monkeypatch.setattr(toc_route, "validate_toc", lambda value, days: value)

    result = asyncio.run(toc_route.generate_toc(toc_route.TocRequest(
        domain="FQSDK", duration_days=1, generation_mode="manual"
    ), db))

    assert captured["override"]["name"] == "Future Quantum SDK"
    assert captured["override"]["level_map"]["foundation"][0]["topic"] == "Quantum SDK Foundations"
    assert result["toc_data"]["generation_mode"] == "template_knowledge"
