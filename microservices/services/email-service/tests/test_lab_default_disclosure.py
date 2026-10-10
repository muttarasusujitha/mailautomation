from app.routes.inbox import _client_short_requirement_ack


def test_client_ack_discloses_lab_defaults_and_requests_real_inputs():
    message = _client_short_requirement_ack({
        "technology_needed": "DevOps",
        "clahan_managed_details": ["Lab availability and cost"],
        "requested_details": ["CV"],
    })

    body = message["body"]
    assert "Please share the participant count, lab hours per day, and preferred cloud provider (AWS, Azure, or GCP) so we can prepare the lab estimate." in body
    assert "not treated as the participant count" not in body
    assert "confirmed batch scope" not in body


def test_partial_devops_ack_reads_like_a_short_note():
    message = _client_short_requirement_ack({
        "technology_needed": "DevOps",
        "duration_days": 7,
        "mode": "Offline",
        "lab_hours_per_day": 3,
        "clahan_managed_details": ["Lab availability and cost"],
        "requested_details": ["CV", "ToC"],
        "needs_clarification": [],
    })

    body = message["body"]
    assert body.startswith("Hi,")
    assert "Greetings of the day! Thanks for sharing the DevOps training requirement." in body
    assert "We have noted 7 training days, Offline, and 3 lab hours per day." in body
    assert "We will share the CV and ToC for your review." in body
    assert "Please share the participant count and preferred cloud provider (AWS, Azure, or GCP) so we can prepare the lab estimate." in body
    assert "confirmed batch scope" not in body
    assert "not treated as the participant count" not in body
    assert "region can be finalized" not in body
    assert "suitable trainer profiles" not in body
