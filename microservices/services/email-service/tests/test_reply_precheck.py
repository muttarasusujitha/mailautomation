"""Personalization engine: one plan per client email, no LLM needed for checks."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.reply_precheck import (
    build_reply_plan,
    check_reply,
    finalize_plan_reply,
    plan_prompt,
    render_plan_reply,
)

# Gmail renders list markers on their own line; keep that shape on purpose.
UJITHA = """Dear clahan,

We have a confirmed requirement for a 20-day offline DevOps training batch
starting from 20 September 2026.

Training Details:

   -

   Domain: DevOps
   -

   Duration: 20 Days
   -

   Start Date: 20 november 2026
   -

   Mode: Offline
   -

   Commercial: \u20b98,80,000
   -

   Training: Conceptual sessions along with extensive hands-on activities
   -

   Hands-on Lab: 3 hours per day

Please share the following at the earliest:

   1.

   Trainer Profile / Updated CV
   2.

   Detailed Day-wise ToC (Table of Contents)
   3.

   10-day lab cost separately for 3 hours of hands-on lab per day

Please share the above details so that we can proceed with the trainer
confirmation and next steps.

Regards,
ujitha
"""
UJITHA_EXTRACTED = {
    "technology_needed": "DevOps", "duration_days": 20, "mode": "offline",
    "training_dates": "20 September 2026", "budget_total": 880000, "lab_hours_per_day": 3,
}

PROPOSAL = """Hello,

We\u2019re exploring a DevOps training program for our team and would like a proposal. Please share suitable trainer profiles and your commercial rate.

The duration, dates, delivery mode, and budget are still to be confirmed. Please include a proposed course outline and your availability.

Regards,
Client
"""

CONFIRMED = """Hello,

We confirm the DevOps corporate training for our team.

- **Topics:** Docker, Kubernetes, and CI/CD
- **Dates:** 10\u201314 December 2026
- **Duration:** 5 training days
- **Mode:** Online
- **Participants:** 20
- **Commercial:** INR 250,000 total

Please proceed with trainer allocation and share the final course outline.

Regards,
Client
"""
CONFIRMED_EXTRACTED = {
    "technology_needed": "DevOps", "duration_days": 5, "mode": "online",
    "training_dates": "10-14 December 2026", "participant_count": 20, "budget_total": 250000,
}


def _ujitha_plan():
    return build_reply_plan(UJITHA, UJITHA_EXTRACTED, "confirmed", "Shahini <shahini@example.com>")


def test_confirmed_plan_puts_trainer_first_and_keeps_client_order():
    plan = _ujitha_plan()
    assert plan["batch_type"] == "confirmed"
    assert [item["kind"] for item in plan["items"]] == ["trainer", "toc", "lab"]
    assert plan["cv_requested"] is True
    assert plan["lab"] == {"requested": True, "days": 10, "hours": "3", "cloud": ""}


def test_greeting_mirrors_client_and_uses_signed_name_over_display_name():
    plan = _ujitha_plan()
    assert plan["greeting"] == "Dear Ujitha,"


def test_facts_under_neutral_header_are_not_treated_as_requests():
    kinds = [item["kind"] for item in _ujitha_plan()["items"]]
    assert "commercials" not in kinds


def test_confirmed_plan_asks_only_blocking_details_and_flags_conflicts():
    plan = _ujitha_plan()
    assert [entry["key"] for entry in plan["missing"]] == ["cloud", "participants"]
    questions = [entry["question"] for entry in plan["conflicts"]]
    assert questions == [
        "The start date, as the email mentions both 20 September 2026 and 20 November 2026",
        "Whether the lab cost should cover 10 days or the full 20-day program",
    ]


def test_confirmed_reply_leads_with_trainer_and_passes_its_own_check():
    plan = _ujitha_plan()
    body = render_plan_reply(plan)
    assert body.startswith("Dear Ujitha,\n\nThank you for sharing the confirmed requirement for the "
                           "20-day offline DevOps training batch.")
    trainer_at = body.index("suitable DevOps trainer")
    assert trainer_at < body.index("day-wise ToC") < body.index("lab cost for 10 days")
    assert "trainer profile and updated CV with you as soon as possible" in body
    assert "AWS, Azure, or GCP" in body and "number of participants" in body
    assert body.endswith("Best regards,\nAnnapurna U.\nClahan Technologies")
    assert check_reply(body, plan) == []


def test_confirmed_sample_needs_no_questions():
    plan = build_reply_plan(CONFIRMED, CONFIRMED_EXTRACTED, "confirmed", "Meera Iyer <meera@example.com>")
    assert [item["kind"] for item in plan["items"]] == ["trainer", "toc"]
    assert plan["missing"] == [] and plan["conflicts"] == []
    assert plan["greeting"] == "Hello Meera,"
    body = render_plan_reply(plan)
    assert "could you please confirm" not in body
    assert "A detailed day-wise ToC for the 5-day program" in body
    assert check_reply(body, plan) == []


def test_proposal_reply_offers_a_proposal_and_does_not_ask_for_tentative_details():
    plan = build_reply_plan(PROPOSAL, {"technology_needed": "DevOps"}, "proposal", "Priya Sharma <priya@example.com>")
    assert plan["batch_type"] == "proposal"
    assert plan["greeting"] == "Hello Priya,"
    assert plan["availability_requested"] is True
    assert plan["tentative"] == ["duration", "dates", "delivery mode", "budget"]
    assert [entry["key"] for entry in plan["missing"]] == ["participants", "audience"]
    body = render_plan_reply(plan)
    assert "Thank you for considering Clahan Technologies for your DevOps training program." in body
    assert "1. Suitable DevOps trainer profiles with their availability" in body
    assert "A proposed course outline" in body and "The commercials for the program" in body
    assert "still to be confirmed" in body
    assert "preferred training dates" not in body and "expected duration" not in body
    assert check_reply(body, plan) == []


def test_check_rejects_missing_trainer_internal_details_and_deadlines():
    plan = _ujitha_plan()
    short = "Dear Ujitha,\n\nThanks for sharing the DevOps requirement. I'm preparing the ToC and lab cost.\n\nThanks"
    problems = check_reply(short, plan)
    assert "trainer_missing" in problems and "question_missing:cloud" in problems
    assert "conflict_missing:start_date" in problems and "too_short" in problems

    leaky = render_plan_reply(plan).replace(
        "as soon as possible.", "by Friday. The trainer rate includes our 30% margin, please find attached."
    )
    problems = check_reply(leaky, plan)
    assert {"internal_detail_leak", "attachment_claim", "deadline_promise"} <= set(problems)


def test_finalize_replaces_model_greeting_and_signature():
    plan = _ujitha_plan()
    generated = "Subject: Re: DevOps\n\nHi Shahini,\n\nThank you for the details.\n\nThanks,\nAnnapurna U.\nClahan Technologies"
    assert finalize_plan_reply(generated, plan) == (
        "Dear Ujitha,\n\nThank you for the details.\n\nBest regards,\nAnnapurna U.\nClahan Technologies"
    )


def test_prompt_contains_checklist_and_reference_reply():
    prompt = plan_prompt(_ujitha_plan())
    assert "Open with exactly: Dear Ujitha," in prompt
    assert "Whether the lab cost should cover 10 days or the full 20-day program" in prompt
    assert "A correct reference reply follows" in prompt


def test_quoted_history_is_ignored():
    message = "Hi,\n\nPlease share the trainer profile.\n\nThanks,\nAsha\n\nOn Mon, 1 Dec 2026, Clahan wrote:\n> lab cost for 5 days"
    plan = build_reply_plan(message, {"technology_needed": "Python"}, "confirmed")
    assert [item["kind"] for item in plan["items"]] == ["trainer"]
    assert plan["greeting"] == "Hi Asha,"
