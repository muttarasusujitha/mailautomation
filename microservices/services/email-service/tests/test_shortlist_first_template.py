import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.routes.templates import ShortlistEmailRequest, compose_shortlist_first


def test_shortlist_first_uses_structured_snapshot_not_raw_client_text():
    reply = asyncio.run(compose_shortlist_first(
        ShortlistEmailRequest(
            trainer_name="Shivam Das",
            domain="DevOps",
            duration="5 Days",
            mode="Online",
            dates="15 September 2026 to 19 September 2026",
            audience_level="IT/Software Professionals",
            budget="INR 35,000 per day/session, inclusive of TDS",
            requirement_kind="confirmed_batch",
            client_request=(
                "From: client@example.com\n"
                "Hi Team,\n"
                "We have a confirmed requirement for DevOps training. Please find the details below:\n"
                "- Domain: DevOps\n"
                "- Training Dates: 15 September 2026 to 19 September 2026\n"
                "- Duration: 5 Days\n"
                "- Mode: Online\n"
                "- Audience: IT/Software Professionals\n"
                "Please share the trainer's LinkedIn profile, updated resume, and trainer profile for client review."
            ),
        )
    ))

    assert "Training Details:" in reply["body"]
    assert "We have received a training requirement for DevOps" in reply["body"]
    assert "- Domain/Technology: DevOps" in reply["body"]
    assert "- Training dates: 15 September 2026 to 19 September 2026" in reply["body"]
    assert "- Duration: 5 Days" in reply["body"]
    assert "- Mode: Online" in reply["body"]
    assert "- Audience/Participants: IT/Software Professionals" in reply["body"]
    assert "- Commercials/Budget: INR 35,000 per day/session, inclusive of TDS" in reply["body"]
    assert "- Updated CV / Trainer Profile" in reply["body"]
    assert "- LinkedIn Profile" in reply["body"]
    assert "Kindly share the details below" in reply["body"]
    assert "Requirement Snapshot" not in reply["body"]
    assert "Client Requirement Details:" not in reply["body"]
    assert "Hi Team" not in reply["body"]
    assert "client review" not in reply["body"].lower()
    assert "From: client@example.com" not in reply["body"]


def test_shortlist_first_skips_experience_when_resume_already_confirms_it():
    reply = asyncio.run(compose_shortlist_first(
        ShortlistEmailRequest(
            trainer_name="Shivam Das",
            domain="DevOps",
            requirement_kind="proposal_requirement",
            resume_verified_experience=True,
            client_request="Please share relevant DevOps implementation and training experience along with LinkedIn profile.",
        )
    ))

    assert "DevOps implementation and training experience" not in reply["body"]
    assert "LinkedIn Profile" in reply["body"]


def test_proposal_template_shows_clahan_fixed_commercials_without_requesting_a_rate():
    reply = asyncio.run(compose_shortlist_first(
        ShortlistEmailRequest(
            trainer_name="Megha Menon",
            domain="DevOps",
            requirement_kind="proposal_requirement",
            client_request="Please share trainer commercials and a suitable profile.",
        )
    ))

    assert "Commercials: INR 12,000-15,000 per day/session" in reply["body"]
    assert "Commercials (per hour/day)" not in reply["body"]
