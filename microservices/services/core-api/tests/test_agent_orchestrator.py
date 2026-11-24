import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.routes import agent_orchestrator
from app.routes.agent_orchestrator import _client_decision, agent_summary
from app.routes.agent_orchestrator import _matching_decision, _outreach_decision, _exception_decision, _log_decision
from pymongo.errors import DuplicateKeyError


def client_email(**overrides):
    return {
        "email_id": "test-client",
        "extracted": {"technology_needed": "Python", "duration_days": 5, "budget_total": 10000},
        **overrides,
    }


@pytest.mark.parametrize("score", [0, 0.2, 0.69])
def test_complete_requirements_do_not_override_low_confidence(score):
    decision = _client_decision(client_email(auto_send_confidence=score, confidence=0.95))
    assert decision.confidence == score
    assert decision.requires_human


@pytest.mark.parametrize("score", ["invalid", "NaN", float("inf"), -1, 2, {}])
def test_invalid_confidence_requires_review_instead_of_crashing(score):
    decision = _client_decision(client_email(confidence=score))
    assert decision.confidence == 0
    assert decision.requires_human


def test_missing_confidence_uses_uncertain_default():
    decision = _client_decision(client_email())
    assert decision.confidence == 0.65
    assert decision.requires_human


def test_valid_confidence_and_malformed_extraction():
    assert _client_decision(client_email(confidence="0.9")).confidence == 0.9
    decision = _client_decision(client_email(extracted="bad data"))
    assert decision.metadata["missing_fields"] == ["technology", "duration", "budget"]


def test_matching_ranks_eligible_trainers_and_excludes_rejections():
    decision = _matching_decision({"requirement_id": "R1"}, {"top_trainers": [
        {"trainer_id": "A", "match_score": 70},
        {"trainer_id": "B", "match_score": 95, "pipeline_status": "rejected"},
        {"trainer_id": "C", "match_score": 90},
        {"trainer_id": "D", "match_score": "NaN"},
    ]})
    assert [row["trainer_id"] for row in decision.metadata["ranked_trainers"]] == ["C", "A", "D"]
    assert decision.confidence == 0.9


def test_missing_matches_require_review():
    decision = _matching_decision({"requirement_id": "R1"}, {})
    assert decision.requires_human
    assert decision.metadata["ranked_trainers"] == []


def test_outreach_and_exception_do_not_send_emails():
    decision = _outreach_decision(client_email(extracted={}))
    assert decision.action == "recommend"
    assert decision.requires_human
    assert "clarification" in decision.decision
    exception = _exception_decision(decision)
    assert exception.agent_role == "exception_review_agent"
    assert exception.metadata["source_role"] == "outreach_agent"
    assert _exception_decision(_client_decision(client_email(confidence=0.9))) is None


def test_concurrent_identical_decisions_are_saved_once_and_changes_are_retained():
    class Collection:
        def __init__(self):
            self.docs = {}

        async def insert_one(self, doc):
            await asyncio.sleep(0)
            if doc["_id"] in self.docs:
                raise DuplicateKeyError("duplicate")
            self.docs[doc["_id"]] = dict(doc)

    async def run():
        collection = Collection()
        db = {"agent_decisions": collection}
        candidate = _client_decision(client_email(confidence=0.9))
        results = await asyncio.gather(*[_log_decision(db, candidate, True) for _ in range(20)])
        assert sum(result is not None for result in results) == 1
        assert len(collection.docs) == 1
        candidate.confidence = 0.2
        changed = await _log_decision(db, candidate, True)
        assert changed["requires_human"]
        assert len(collection.docs) == 2
    asyncio.run(run())


@pytest.mark.parametrize("rows,total,review", [([], 0, 0), ([
    {"_id": "client_requirement_agent", "count": 7, "review": 3},
    {"_id": "commercial_agent", "count": 4, "review": 1},
], 11, 4)])
def test_summary_totals_match_role_counts_without_extra_count_queries(rows, total, review):
    class Collection:
        async def aggregate(self, pipeline):
            for row in rows:
                yield row

        def find(self, *args):
            return self

        def sort(self, *args):
            return self

        def limit(self, *args):
            return self

        async def to_list(self, *args):
            return []

    result = asyncio.run(agent_summary({"agent_decisions": Collection()}))
    assert result["total"] == total
    assert result["requires_human"] == review


def test_client_agent_accepts_duration_text():
    decision = _client_decision(client_email(extracted={
        "technology_needed": "DevOps", "duration_text": "20 Training Days", "budget_total": 10000,
    }, confidence=0.9))
    assert "missing_fields" not in decision.metadata
    assert "Proceed" in decision.decision


def test_template_mode_does_not_call_the_agent_llm(monkeypatch):
    called = {}

    async def wording(decisions):
        called["yes"] = True
        return {}

    monkeypatch.setattr(agent_orchestrator, "_fetch_agentic_wording", wording)
    db = {"automation_settings": SimpleNamespace(find_one=AsyncMock(return_value={"value": "template"}))}
    decisions = [{"agent_role": "client_requirement_agent", "entity_id": "E1", "metadata": {}}]
    asyncio.run(agent_orchestrator._attach_agentic_wording(db, decisions, True))
    assert "yes" not in called
    assert "llm" not in decisions[0]["metadata"]


def test_ai_mode_stores_client_shortlist_and_toc_notes(monkeypatch):
    async def wording(decisions):
        return {("client_requirement_agent", "E1"): {
            "client_text": "Please confirm the Python dates.",
            "shortlist_note": "Two trainers match the Python scope.",
            "toc_note": "Draft a Python TOC from the known scope.",
            "provider": "llm",
        }}

    monkeypatch.setattr(agent_orchestrator, "_fetch_agentic_wording", wording)
    updates = []

    class Decisions:
        async def update_one(self, query, update):
            updates.append((query, update))

        def find(self, *args, **kwargs):
            return self

        def sort(self, *args, **kwargs):
            return self

        def limit(self, *args, **kwargs):
            return self

        async def to_list(self, *args, **kwargs):
            return []

    db = {
        "automation_settings": SimpleNamespace(find_one=AsyncMock(return_value={"value": "ai"})),
        "agent_decisions": Decisions(),
    }
    decisions = [{
        "agent_role": "client_requirement_agent",
        "entity_id": "E1",
        "decision_id": "AGD-1",
        "metadata": {},
    }]
    asyncio.run(agent_orchestrator._attach_agentic_wording(db, decisions, False))
    note = decisions[0]["metadata"]["llm"]
    assert note["client_text"] == "Please confirm the Python dates."
    assert note["shortlist_note"].startswith("Two trainers")
    assert "TOC" in note["toc_note"]
    assert updates[0][0] == {"decision_id": "AGD-1"}


def test_ai_mode_includes_every_application_agent(monkeypatch):
    seen = {}

    async def wording(decisions):
        seen["roles"] = [item["agent_role"] for item in decisions]
        return {}

    monkeypatch.setattr(agent_orchestrator, "_fetch_agentic_wording", wording)

    class Decisions:
        def find(self, *args, **kwargs):
            return self

        def sort(self, *args, **kwargs):
            return self

        def limit(self, *args, **kwargs):
            return self

        async def to_list(self, *args, **kwargs):
            return []

    db = {
        "automation_settings": SimpleNamespace(find_one=AsyncMock(return_value={"value": "ai"})),
        "agent_decisions": Decisions(),
    }
    decisions = [
        {"agent_role": role, "entity_id": role, "metadata": {}}
        for role in agent_orchestrator.AGENT_ROLES
    ]
    asyncio.run(agent_orchestrator._attach_agentic_wording(db, decisions, True))
    assert set(seen["roles"]) == set(agent_orchestrator.AGENT_ROLES)
