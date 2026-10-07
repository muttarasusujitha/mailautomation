from app.routes.inbox import _client_short_requirement_ack


def test_client_ack_discloses_lab_defaults_and_requests_real_inputs():
    message = _client_short_requirement_ack({
        "technology_needed": "DevOps",
        "clahan_managed_details": ["Lab availability and cost"],
        "requested_details": ["CV"],
    })

    body = message["body"]
    assert "after confirming the participant count and required lab-access hours per day and preferred cloud provider (AWS, Azure, or GCP)" in body
    assert "not treated as the participant count" in body
