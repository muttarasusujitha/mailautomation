from app.routes.inbox import _requirement_flow_from_email


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
