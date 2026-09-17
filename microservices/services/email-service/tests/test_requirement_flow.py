import asyncio

from app.routes.inbox import (
    _requirement_flow_from_email,
    _update_existing_requirement_from_extracted,
)


class _FakeRequirementsCollection:
    def __init__(self, existing):
        self.existing = existing
        self.update = None

    async def find_one(self, _query, _projection):
        return self.existing

    async def update_one(self, _query, update):
        self.update = update


class _FakeDatabase:
    def __init__(self, existing):
        self.requirements = _FakeRequirementsCollection(existing)

    def __getitem__(self, name):
        assert name == "requirements"
        return self.requirements


def test_unconfirmed_sourcing_requirement_uses_proposal_flow():
    text = """We have an immediate requirement for an experienced DevOps trainer.
Mode: To be confirmed (Online/Offline)
Duration: To be confirmed
Location: To be confirmed
If you have a suitable trainer available, kindly share the following details:
- Updated trainer profile (CV)
- Commercials (per hour/day)
"""

    assert _requirement_flow_from_email({}, text) == "proposal"


def test_explicit_confirmed_training_stays_confirmed():
    text = """We are pleased to confirm the 20-day Advanced DevOps offline training program.
Dates: 10 September 2026 to 7 October 2026
Mode: Offline / classroom
Participants: 20
"""

    assert _requirement_flow_from_email({}, text) == "confirmed"


def test_unknown_training_request_defaults_to_proposal_not_confirmed():
    text = """Please help us source a Python trainer for a future corporate program.
We will share the final dates and delivery details shortly.
"""

    assert _requirement_flow_from_email({}, text) == "proposal"


def test_extractor_confirmed_label_cannot_override_client_message():
    text = """We need to identify suitable AWS trainers and compare commercials.
The schedule and delivery mode will be finalized later.
"""

    assert _requirement_flow_from_email({"training_status": "confirmed"}, text) == "proposal"


def test_complete_upcoming_batch_is_confirmed():
    text = """We have a requirement for an experienced DevOps Trainer for an upcoming corporate training batch.
Training Start Date: 01 November 2026
Duration: 20 Training Days
Participants: 34
Commercial Budget: ₹5,40,000
"""
    from app.routes.inbox import _extract_requirement_from_email
    extracted = _extract_requirement_from_email("DevOps requirement", text, "swayoraalbum3@gmail.com", "Swayora Album3")
    assert extracted["training_dates"] == "01 November 2026"
    assert extracted["budget_total"] == 540000
    assert _requirement_flow_from_email(extracted, text) == "confirmed"


def test_three_of_four_batch_details_remain_proposal():
    extracted = {
        "technology_needed": "DevOps",
        "training_dates": "01 November 2026",
        "duration_days": 20,
        "participant_count": 34,
    }
    assert _requirement_flow_from_email(extracted, "Upcoming DevOps corporate batch") == "proposal"


def test_parser_accepts_common_email_separators_and_bullets():
    from app.routes.inbox import _extract_requirement_from_email
    text = """Technology = DevOps
- Training Start Date – 01 November 2026
Duration - 20 Training Days
Participants: 34
Commercial Budget = ₹5,40,000
"""
    extracted = _extract_requirement_from_email("DevOps requirement", text, "client@example.com", "Client")
    assert extracted["training_dates"] == "01 November 2026"
    assert extracted["duration_days"] == 20
    assert extracted["participant_count"] == 34
    assert extracted["budget_total"] == 540000


def test_confirmation_must_come_from_client_text():
    assert _requirement_flow_from_email({"batch_type": "confirmed batch"}, "Please share commercials") == "proposal"


def test_reply_cannot_downgrade_a_confirmed_requirement_to_proposal():
    db = _FakeDatabase({
        "batch_flow": "confirmed",
        "batch_type": "confirmed",
        "pipeline_page": "shortlist1",
    })

    asyncio.run(_update_existing_requirement_from_extracted(
        db,
        "REQ-TEST",
        {"client_requirement_text": "He is selected."},
    ))

    update = db.requirements.update["$set"]
    assert update["batch_flow"] == "confirmed"
    assert update["pipeline_page"] == "shortlist1"


def test_confirmation_examples_and_non_confirmation():
    for text in (
        "Client confirmed a 20-day Advanced DevOps training starting November 1 for 34 participants. Please share commercials.",
        "We have a confirmed requirement. Please share profiles and proposed TOC.",
    ):
        assert _requirement_flow_from_email({}, text) == "confirmed"
    for text in (
        "Please share commercials, profiles and proposed TOC.",
        "This is not a confirmed batch.",
        "If the client confirms the training, we will send a purchase order.",
        "Please confirm the training.",
        "We are pleased to confirm receipt of your trainer profile.",
        "Please share your purchase order format.",
    ):
        assert _requirement_flow_from_email({}, text) == "proposal"


import pytest


@pytest.mark.parametrize("body, expected", [
    ("""We have a requirement for an upcoming DevOps training program.
Technology: DevOps
Mode: Online
Duration: 20 days
Participants: 30
Start Date: 10 November 2026
Level: Advanced
Commercial: 4,80,000
Please share the trainer profile, LinkedIn profile, and detailed ToC.""", "confirmed"),
    ("""We are looking for an experienced AWS trainer for our upcoming corporate batch.
Technology: AWS
Duration: 10 days
Participants: 25
Mode: Online
Training Dates: 5?16 October 2026
Level: Advanced
Commercial: 2,50,000
Please share a suitable trainer profile along with LinkedIn details and ToC.""", "confirmed"),
    ("""We need an Azure DevOps trainer for a corporate training engagement.
Technology: Azure DevOps
Duration: 15 days
Participants: 35
Mode: Offline
Location: Bangalore
Start Date: 12 October 2026
Commercial: 3,75,000
Kindly share the trainer CV, LinkedIn profile and course outline.""", "confirmed"),
    ("""We are exploring trainers for a possible DevOps training requirement.
Technology: DevOps
Expected Duration: 15?20 days
Participants: Around 30
Mode: Online/Offline
Tentative Timeline: November 2026
Level: Advanced
Please share suitable trainer profiles along with expected commercials and ToC.""", "proposal"),
    ("""We have an upcoming AWS training requirement and would like to understand trainer availability.
Technology: AWS
Participants: Approximately 25
Duration: To be discussed
Mode: Online
Tentative Month: October 2026
Please share available trainer profiles, LinkedIn details, ToC and commercials.""", "proposal"),
])
def test_user_examples_through_parser(body, expected):
    from app.routes.inbox import _extract_requirement_from_email
    extracted = _extract_requirement_from_email("Training requirement", body, "client@example.com", "Client")
    assert _requirement_flow_from_email(extracted, body) == expected


@pytest.mark.parametrize("message", [
    "We are exploring a possible AWS batch.",
    "Tentative dates: 5 October 2026",
    "Please send a proposal for this training.",
    "Duration: To be discussed",
    "Participants: Approximately 25",
    "Mode: Online/Offline",
])
def test_tentative_language_overrides_complete_extracted_fields(message):
    extracted = dict(technology_needed="AWS", duration_days=10, participant_count=25,
                     training_dates="5 October 2026", budget_total=250000)
    assert _requirement_flow_from_email(extracted, message) == "proposal"


@pytest.mark.parametrize("updates", [
    {"training_dates": "October 2026"}, {"duration_days": 0},
    {"participant_count": 0}, {"budget_total": 0},
    {"training_dates": "Tentative 5 October 2026"},
])
def test_incomplete_or_tentative_fields_do_not_confirm(updates):
    extracted = dict(technology_needed="AWS", duration_days=10, participant_count=25,
                     training_dates="5 October 2026", budget_total=250000)
    extracted.update(updates)
    assert _requirement_flow_from_email(extracted, "Upcoming AWS batch") == "proposal"
