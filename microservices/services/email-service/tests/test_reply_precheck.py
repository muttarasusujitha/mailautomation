"""Personalization engine: one plan per client email, no LLM needed for checks."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.reply_precheck import (
    build_reply_plan,
    check_reply,
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
    assert body.startswith("Dear Ujitha,\n\nThank you for ")
    assert "the 20-day offline DevOps training batch" in body.split("\n\n")[1]
    # "at the earliest" makes this a priority request.
    assert "priority" in body.split("\n\n")[1]
    trainer_at = body.index("suitable DevOps trainer")
    assert trainer_at < body.index("day-wise ToC") < body.index("lab cost for 10 days")
    assert "trainer profile and updated CV with you on priority" in body
    assert "AWS, Azure, or GCP" in body and "number of participants" in body
    assert body.endswith("Best regards,\nAnnapurna U.\nClahan Technologies")
    assert check_reply(body, plan) == []


def test_confirmed_sample_needs_no_questions():
    plan = build_reply_plan(CONFIRMED, CONFIRMED_EXTRACTED, "confirmed", "Meera Iyer <meera@example.com>")
    assert [item["kind"] for item in plan["items"]] == ["trainer", "toc"]
    assert plan["missing"] == [] and plan["conflicts"] == []
    assert plan["greeting"] == "Hello Meera,"
    body = render_plan_reply(plan)
    assert "could you please confirm" not in body and "priority" not in body
    assert "trainer profile with you as soon as possible" in body
    assert "A detailed day-wise ToC for the 5-day program" in body
    assert check_reply(body, plan) == []


def test_proposal_reply_leads_with_trainer_and_does_not_ask_for_tentative_details():
    plan = build_reply_plan(PROPOSAL, {"technology_needed": "DevOps"}, "proposal", "Priya Sharma <priya@example.com>")
    assert plan["batch_type"] == "proposal"
    assert plan["greeting"] == "Hello Priya,"
    assert plan["availability_requested"] is True
    assert plan["tentative"] == ["duration", "dates", "delivery mode", "budget"]
    assert [entry["key"] for entry in plan["missing"]] == ["participants"]
    body = render_plan_reply(plan)
    assert "We are identifying a suitable DevOps trainer" in body
    assert "along with the trainer's availability" in body
    assert "A proposed course outline" in body and "The commercials for the program" in body
    assert "still to be confirmed" in body
    assert "preferred training dates" not in body and "expected duration" not in body
    assert "complete proposal for your review" in body
    assert check_reply(body, plan) == []


def test_check_rejects_missing_trainer_internal_details_and_deadlines():
    plan = _ujitha_plan()
    short = "Dear Ujitha,\n\nThanks for sharing the DevOps requirement. I'm preparing the ToC and lab cost.\n\nThanks"
    problems = check_reply(short, plan)
    assert "trainer_missing" in problems and "question_missing:cloud" in problems
    assert "conflict_missing:start_date" in problems and "too_short" in problems

    leaky = render_plan_reply(plan).replace(
        "on priority.", "by Friday. The trainer rate includes our 30% margin, please find attached."
    )
    problems = check_reply(leaky, plan)
    assert {"internal_detail_leak", "attachment_claim", "deadline_promise"} <= set(problems)


def test_quoted_history_is_ignored():
    message = "Hi,\n\nPlease share the trainer profile.\n\nThanks,\nAsha\n\nOn Mon, 1 Dec 2026, Clahan wrote:\n> lab cost for 5 days"
    plan = build_reply_plan(message, {"technology_needed": "Python"}, "confirmed")
    assert [item["kind"] for item in plan["items"]] == ["trainer"]
    assert plan["greeting"] == "Hi Asha,"


# Patterns from real partner requirements (names and companies anonymized).
PARTNER_ONSITE = """Dear Team,

Please refer to the below requirement and assist us with suitable trainer profiles at the earliest.

We are currently looking for 2 Trainers for a duration of 6 months, starting from 1st March 2026, who can work from the client location in Bellandur, Bangalore (3-4 days per week).

Position: GenAI & Agentic AI Trainer
Location: Client Site \u2013 Bellandur, Bangalore
Duration: 6 Months
Experience Required: 5+ Years

What We\u2019re Looking For:

  *
Strong expertise in Generative AI (LLMs, Prompt Engineering, AI tools)
  *
Hands-on experience with Agentic AI frameworks and AI automation workflows
  *
Ability to work from the client location 3\u20134 days per week

Kindly share:

  *
Updated trainer profiles
  *
Relevant project/training experience
  *
Confirmation on onsite availability (3\u20134 days/week)
  *
Commercial confirmation within the mentioned budget
  *
Availability for an internal screening call

This is a priority requirement, and we would appreciate your earliest response.

Regards,

Kavya Rao
Training Operations Manager
"""

PARTNER_FORM = """Dear Team,

We have a critical learning requirement for a trainer-led PIM (Product Information Management) training program.

Requirement Details:

  *   Topic: PIM (Product Information Management)
  *   Participants: 10
  *   Timeline: Immediate / ASAP

Scope of Training:

  *   PIM data model fundamentals
  *   Data Modelling & Configuration
  *   Import, Export & ETL Integration

Request you to share the following at the earliest:

  *   Trainer profile(s) with relevant PIM experience
  *   Detailed course outline (TOC)
  *   Recommended training duration (days & hours per day)
  *   Commercials (per day / per batch cost)
  *   Any prerequisites or lab requirements

Regards,

Kavya Rao
"""

VENDOR_PITCH = """Dear Annapurna,

I recently came across your LinkedIn post regarding the upcoming SAP training requirements.
We offer end-to-end training support including trainer deployment and lab infrastructure.

Request you to share:
  *   Number of participants
  *   Tentative training dates

Regards,
Rohit
"""


def _partner_plan():
    return build_reply_plan(PARTNER_ONSITE, {"technology_needed": "someone who can deliver"}, "proposal",
                            "Kavya Rao <kavya@partner.example>",
                            subject="Urgent Requirement \u2013 GenAI & Agentic AI Trainers (6 Months | Bangalore | Onsite)")


def test_partner_requirement_reads_trainer_needs_count_location_and_urgency():
    plan = _partner_plan()
    assert plan["greeting"] == "Dear Kavya,"
    assert plan["technology"] == "GenAI & Agentic AI"
    assert plan["trainer_count"] == 2 and plan["experience_years"] == "5+"
    assert plan["urgent"] and plan["end_client"] and plan["onsite"]
    assert plan["location"] == "Bellandur, Bangalore"
    assert plan["call_requested"] and plan["availability_requested"]
    # Skills and responsibilities describe the trainer; they are not documents to send.
    assert [item["kind"] for item in plan["items"]] == ["trainer", "commercials"]
    # Duration and dates are already in the email, so only the headcount is asked.
    assert [entry["key"] for entry in plan["missing"]] == ["participants"]


def test_partner_reply_is_specific_to_their_request():
    plan = _partner_plan()
    body = render_plan_reply(plan)
    assert "your client's GenAI & Agentic AI training requirement" in body
    assert "priority" in body.split("\n\n")[1]
    assert "two suitable GenAI & Agentic AI trainers with 5+ years of experience" in body
    assert "who can deliver onsite at Bellandur, Bangalore for your client's 6-month engagement" in body
    assert "Their profiles will highlight hands-on experience in Generative AI" in body
    assert "along with their availability and suitable slots for the screening call" in body
    assert "within your stated budget" in body
    assert "Ability to work" not in body and "Strong expertise" not in body
    assert check_reply(body, plan) == []


def test_partner_form_uses_scope_and_does_not_ask_back_what_they_want_recommended():
    plan = build_reply_plan(PARTNER_FORM, {}, "proposal", "Kavya Rao <kavya@partner.example>",
                            subject="Urgent Trainer Requirement \u2013 PIM Training")
    assert plan["technology"] == "PIM"
    assert plan["scope"] == ["PIM data model fundamentals", "Data Modelling & Configuration",
                             "Import, Export & ETL Integration"]
    body = render_plan_reply(plan)
    assert "A proposed course outline covering PIM data model fundamentals" in body
    assert "Recommended training duration (days & hours per day)" in body
    # They asked us to recommend the duration and lab setup: never ask those back.
    assert "expected duration" not in body and "cloud platform" not in body
    assert "number of participants" not in body
    assert check_reply(body, plan) == []


def test_vendor_pitch_is_not_treated_as_a_client_requirement():
    from app.agents.reply_precheck import is_vendor_pitch

    assert is_vendor_pitch(VENDOR_PITCH)
    assert not is_vendor_pitch(PARTNER_ONSITE)
    assert not is_vendor_pitch(UJITHA)


def test_check_allows_client_wording_about_internal_calls():
    plan = _partner_plan()
    body = render_plan_reply(plan).replace("screening call", "internal screening call")
    assert "internal_detail_leak" not in check_reply(body, plan)
