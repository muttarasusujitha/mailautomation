"""LLM understanding is verified against the email before any reply uses it."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.agents.reply_precheck import build_reply_plan, check_reply, render_plan_reply
from app.agents.requirement_understanding import apply_understanding, ground_understanding, parse_understanding
from test_reply_precheck import UJITHA, UJITHA_EXTRACTED

AZURE = """Hello Annapurna,

Greetings from Alchemy!

We have a training requirement for Azure Data Explorer for 5 participants. The client prefers online
sessions of 4 hours per day, and the training needs to start in the first week of March 2027.

Topics: KQL fundamentals, ingestion pipelines, and dashboards.

Request you to share the trainer profile and costing per day for the same.

Thanks and Regards,
Girish
"""


def _model_reading(**overrides):
    reading = {
        "is_training_requirement": True,
        "topic": "Azure Data Explorer",
        "scope_topics": ["KQL fundamentals", "ingestion pipelines", "dashboards"],
        "for_end_client": True,
        "urgent": False,
        "deadline": "",
        "trainers": {"count": 1, "experience_years": "", "skills": ["Azure Data Explorer", "KQL"], "onsite": False,
                     "location": "", "engagement_length": ""},
        "schedule": {"start": "first week of March 2027", "duration": "", "hours_per_day": "4 hours", "mode": "online"},
        "participants": {"count": "5", "level": ""},
        "requested_from_us": [
            {"kind": "trainer_profile", "client_words": "share the trainer profile"},
            {"kind": "commercials", "client_words": "costing per day"},
        ],
        "lab": {"days": "", "hours_per_day": "", "cloud": ""},
        "commercial_basis": "per day",
        "budget_mentioned": False,
        "to_be_confirmed": [],
        "asks_us_to_recommend": [],
        "conflicts": [],
    }
    reading.update(overrides)
    return reading


def _understood_reply(reading, message=AZURE, subject="Training - Azure Data Explorer (ADX) skillset"):
    understanding = ground_understanding(parse_understanding(json.dumps(reading)), subject, message)
    plan = build_reply_plan(message, {"technology_needed": "Azure"}, "proposal", "Girish <g@partner.example>",
                            subject=subject, seed="mail-1")
    plan = apply_understanding(plan, understanding)
    return understanding, plan, render_plan_reply(plan)


def test_verified_understanding_drives_a_specific_reply():
    understanding, plan, body = _understood_reply(_model_reading())
    assert understanding["dropped_unsupported"] == []
    assert plan["understanding_source"] == "llm_verified"
    assert "your client's Azure Data Explorer training requirement for 5 participants, delivered online" in body
    assert "The profile will highlight hands-on experience in Azure Data Explorer and KQL." in body
    assert "The commercials on a per-day basis" in body
    # Dates, hours per day, mode, and headcount are in the email; only the number of days is open.
    assert [entry["question"] for entry in plan["missing"]] == ["The number of training days"]
    assert "number of participants" not in body and "delivery mode" not in body
    assert check_reply(body, plan) == []


def test_facts_not_in_the_email_are_dropped_before_the_reply():
    reading = _model_reading(
        topic="Microsoft Fabric",
        trainers={"count": 3, "experience_years": "10+", "skills": ["Power BI"], "onsite": True,
                  "location": "Hyderabad", "engagement_length": "3 months"},
        participants={"count": "40", "level": "advanced"},
        conflicts=[{"about": "start date", "values": ["5 March", "9 April"]}],
    )
    understanding, plan, body = _understood_reply(reading)
    dropped = set(understanding["dropped_unsupported"])
    assert {"topic", "skill", "location", "engagement", "participants", "level", "conflict"} <= dropped
    assert understanding["trainers"]["count"] == 1 and understanding["trainers"]["experience_years"] == ""
    for invented in ("Fabric", "Power BI", "Hyderabad", "40", "10+", "advanced", "April"):
        assert invented not in body


def test_conflicts_from_the_model_are_kept_only_with_both_values_in_the_email():
    reading = _model_reading(
        requested_from_us=[{"kind": "trainer_profile", "client_words": "Trainer Profile / Updated CV"},
                           {"kind": "toc", "client_words": "Detailed Day-wise ToC"},
                           {"kind": "lab_cost", "client_words": "10-day lab cost separately"}],
        conflicts=[{"about": "start date", "values": ["20 September 2026", "20 november 2026"]}],
        topic="DevOps", scope_topics=[], for_end_client=False, urgent=True,
        schedule={"start": "", "duration": "20 Days", "hours_per_day": "", "mode": "offline"},
        participants={"count": "", "level": ""},
        lab={"days": "10", "hours_per_day": "3", "cloud": ""},
        trainers={"count": 1, "experience_years": "", "skills": [], "onsite": False, "location": "", "engagement_length": ""},
        commercial_basis="",
    )
    understanding = ground_understanding(reading, "DevOps requirement", UJITHA)
    plan = apply_understanding(build_reply_plan(UJITHA, UJITHA_EXTRACTED, "confirmed", "Shahini <s@x.com>"), understanding)
    body = render_plan_reply(plan)
    assert [item["kind"] for item in plan["items"]] == ["trainer", "toc", "lab"]
    assert body.count("20 September 2026") == 1  # the rule conflict and the model conflict are merged
    assert "Whether the lab cost should cover 10 days or the full 20-day program" in body
    assert "AWS, Azure, or GCP" in body
    assert check_reply(body, plan) == []


def test_unusable_model_output_is_rejected():
    assert parse_understanding("Sorry, I cannot help with that.") is None
    assert parse_understanding('```json\n{"topic": "SAP"}\n```') == {"topic": "SAP"}
    assert ground_understanding(None, "s", "b") is None


def test_model_can_mark_a_pitch_as_not_a_requirement():
    understanding = ground_understanding(_model_reading(is_training_requirement=False), "Partnership", AZURE)
    assert understanding["is_training_requirement"] is False
