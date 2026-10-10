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
    assert "We will share the CV for your review." in body
    assert "We will share the CV and ToC" not in body
    assert "Please share the participant count and preferred cloud provider (AWS, Azure, or GCP) so we can prepare the ToC and the lab cost." in body
    assert "confirmed batch scope" not in body
    assert "not treated as the participant count" not in body
    assert "region can be finalized" not in body
    assert "suitable trainer profiles" not in body


def test_topics_keep_the_batch_moving_and_wait_to_prepare_toc_and_lab_cost():
    message = _client_short_requirement_ack({
        "technology_needed": "DevOps",
        "duration_days": 7,
        "mode": "Offline",
        "lab_hours_per_day": 3,
        "topics": "Docker, Kubernetes, and CI/CD",
        "clahan_managed_details": ["Lab availability and cost"],
        "requested_details": ["CV", "ToC", "lab cost"],
        "needs_clarification": [],
    })

    body = message["body"]
    assert "We have noted the topics you shared, 7 training days, Offline, and 3 lab hours per day." in body
    assert "We will share the CV for your review." in body
    assert "We will share the CV and ToC" not in body
    assert "Please share the participant count and preferred cloud provider (AWS, Azure, or GCP) so we can prepare the ToC and the lab cost." in body
    assert "confirmed batch scope" not in body


def test_profile_items_stay_grammatical_when_toc_waits():
    message = _client_short_requirement_ack({
        "technology_needed": "DevOps",
        "duration_days": 7,
        "topics": ["Docker", "Kubernetes"],
        "clahan_managed_details": ["Lab availability and cost"],
        "requested_details": ["CV", "LinkedIn profile", "ToC", "relevant experience"],
        "needs_clarification": [],
    })

    body = message["body"]
    assert "We have noted the topics you shared and 7 training days." in body
    assert "We will share the CV, LinkedIn profile, and relevant experience for your review." in body
    assert "ToC" not in body.split("Please share")[0]
    assert "so we can prepare the ToC and the lab cost." in body


def test_complete_lab_inputs_still_share_toc_and_prepare_the_estimate():
    message = _client_short_requirement_ack({
        "technology_needed": "DevOps",
        "duration_days": 7,
        "mode": "Offline",
        "lab_hours_per_day": 3,
        "participant_count": 12,
        "cloud_provider": "AWS",
        "topics": "Docker, Kubernetes, and CI/CD",
        "clahan_managed_details": ["Lab availability and cost"],
        "requested_details": ["CV", "LinkedIn profile", "ToC"],
        "needs_clarification": [],
    })

    body = message["body"]
    assert "We have noted the topics you shared, 7 training days, Offline, 12 participants, and AWS." in body
    assert "We will share the CV, LinkedIn profile, and ToC for your review." in body
    assert "We will prepare the lab estimate for 12 participants, 7 days, and 3 hours per day." in body
