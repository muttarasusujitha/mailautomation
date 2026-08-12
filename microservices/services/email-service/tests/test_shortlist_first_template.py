import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.routes.templates import ShortlistEmailRequest, compose_shortlist_first


@pytest.mark.asyncio
async def test_shortlist_first_uses_client_request_text_with_trainer_commercials():
    reply = await compose_shortlist_first(
        ShortlistEmailRequest(
            trainer_name="Shivam Das",
            domain="DevOps",
            budget="INR 35,000 per day/session, inclusive of TDS",
            client_request=(
                "From: client@example.com\n"
                "Need DevOps trainer from 2 Sep to 20 Sep.\n"
                "Delivery online. Budget INR 50,000 per day."
            ),
        )
    )

    assert "Client Requirement Details:" in reply["body"]
    assert "Need DevOps trainer from 2 Sep to 20 Sep." in reply["body"]
    assert "Delivery online. Budget INR 50,000 per day." in reply["body"]
    assert "Commercials: INR 35,000 per day/session, inclusive of TDS" in reply["body"]
    assert "From: client@example.com" not in reply["body"]
