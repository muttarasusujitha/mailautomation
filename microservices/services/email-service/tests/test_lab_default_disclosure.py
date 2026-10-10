from app.agents.natural_voice import apply_voice
from app.routes.inbox import _ACK_VERSIONS, _client_short_requirement_ack, _render_professional_ack


_CLOSES = tuple(version["close"] for version in _ACK_VERSIONS)
_OLD_ACK_SENTENCE = "We will share the CV and ToC for your review."
_OLD_PREPARE_SENTENCE = (
    "We will put together the ToC and the lab cost from the topics and the details you shared."
)


def _work_paragraph(body: str) -> str:
    for paragraph in body.split("\n\n"):
        text = paragraph.strip()
        lowered = text.lower()
        if lowered.startswith("looking forward") or lowered.startswith("we look forward"):
            continue
        if "lab estimate for" in lowered:
            continue
        if text.startswith("Please share"):
            continue
        if "toc" in lowered or "lab cost" in lowered:
            return text
    return ""


def _close(body: str) -> str:
    for paragraph in body.split("\n\n"):
        text = paragraph.strip()
        if text.startswith("Looking forward") or text.startswith("We look forward"):
            return text
    return ""


def _thanks_sentence(body: str) -> str:
    paragraphs = [paragraph.strip() for paragraph in body.split("\n\n") if paragraph.strip()]
    opening = paragraphs[1]
    return opening.split(". ")[0] + "."


def _chosen_wording(body: str) -> tuple[str, str, str]:
    return _thanks_sentence(body), _work_paragraph(body), _close(body)


def _ack(technology: str, client_email: str = "asha@example.com", client_name: str = "Asha", **facts) -> str:
    payload = {
        "client_email": client_email,
        "client_name": client_name,
        "technology_needed": technology,
        "clahan_managed_details": ["Lab availability and cost"],
        "requested_details": ["CV", "ToC", "lab cost"],
        "needs_clarification": [],
    }
    payload.update(facts)
    return _client_short_requirement_ack(payload)["body"]


def _assert_professional_ack(body: str, *, topics: bool, toc: bool = True, lab: bool = True, cv: bool = True) -> None:
    assert "Greetings of the day" not in body
    assert _OLD_ACK_SENTENCE not in body
    assert _OLD_PREPARE_SENTENCE not in body
    assert "Looking forward to sending this across." not in body
    assert _close(body) in _CLOSES
    assert "Please share the participant count" not in body
    assert "preferred cloud provider" not in body
    assert "1 participant" not in body
    assert "confirmed batch scope" not in body
    assert "revert" not in body.lower()
    assert "as applicable" not in body.lower()
    assert "to proceed further" not in body.lower()
    assert body.endswith("Thanks,\nAnnapurna U.\nClahan Technologies")
    work = _work_paragraph(body)
    if toc or lab or cv:
        assert work
    if toc:
        assert "toc" in work.lower()
    if lab:
        assert "lab cost" in work.lower()
    if cv:
        assert "cv" in work.lower()
    assert ("topics" in body.lower()) is topics


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
    assert "Greetings of the day" not in body
    assert _OLD_ACK_SENTENCE not in body
    assert "topics" not in body.lower()
    assert _close(body) in _CLOSES
    assert "cv" in body.lower()


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
    assert "DevOps" in body.split("\n\n")[1]
    assert "7" in body
    assert "Offline" in body
    assert "3" in body
    _assert_professional_ack(body, topics=False)
    assert "so we can prepare the ToC and the lab cost." not in body
    assert "not treated as the participant count" not in body
    assert "region can be finalized" not in body
    assert "suitable trainer profiles" not in body


def test_topics_and_partial_details_prepare_toc_and_lab_cost():
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
    assert "topics" in body.lower()
    assert "7" in body
    assert "Offline" in body
    assert "3" in body
    _assert_professional_ack(body, topics=True)


def test_profile_items_stay_grammatical_when_topics_were_shared():
    message = _client_short_requirement_ack({
        "technology_needed": "DevOps",
        "duration_days": 7,
        "topics": ["Docker", "Kubernetes"],
        "clahan_managed_details": ["Lab availability and cost"],
        "requested_details": ["CV", "LinkedIn profile", "ToC", "relevant experience"],
        "needs_clarification": [],
    })

    body = message["body"]
    assert "topics" in body.lower()
    assert "7" in body
    assert "CV, LinkedIn profile, and relevant experience" in body
    assert "ToC" in body
    _assert_professional_ack(body, topics=True)
    assert "Please share the participant count" not in body


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
    assert "topics" in body.lower()
    assert "CV" in body and "LinkedIn" in body
    assert "We will prepare the lab estimate for 12 participants, 7 days, and 3 hours per day." in body
    _assert_professional_ack(body, topics=True)
    assert "Please share the participant count" not in body


def test_same_client_different_requirements_use_different_professional_versions():
    python_body = _ack(
        "Python",
        duration_days=5,
        mode="Online",
        lab_hours_per_day=2,
        topics="Pandas and FastAPI",
    )
    devops_body = _ack(
        "DevOps",
        duration_days=7,
        mode="Offline",
        lab_hours_per_day=3,
        topics="Docker, Kubernetes, and CI/CD",
    )
    devops_other = _ack(
        "DevOps",
        duration_days=10,
        mode="Online",
        lab_hours_per_day=4,
        topics="Terraform and Jenkins",
    )
    repeated = _ack(
        "DevOps",
        duration_days=7,
        mode="Offline",
        lab_hours_per_day=3,
        topics="Docker, Kubernetes, and CI/CD",
    )

    assert python_body != devops_body
    assert devops_body != devops_other
    assert devops_body == repeated
    assert _chosen_wording(python_body) != _chosen_wording(devops_body)
    assert _chosen_wording(devops_body) != _chosen_wording(devops_other)

    for body in (python_body, devops_body, devops_other):
        _assert_professional_ack(body, topics=True)
        assert "Greetings of the day" not in body
        assert _OLD_ACK_SENTENCE not in body
        assert _close(body) in _CLOSES

    assert "Python" in python_body.split("\n\n")[1]
    assert "5" in python_body
    assert "Online" in python_body
    assert "2" in python_body
    assert "DevOps" in devops_body.split("\n\n")[1]
    assert "7" in devops_body
    assert "Offline" in devops_body
    assert "3" in devops_body


def test_repeated_devops_requirements_do_not_reuse_one_sentence():
    openings = set()
    prepares = set()
    closes = set()
    samples = (
        (5, "Online", 2, "Docker"),
        (6, "Offline", 3, "Kubernetes"),
        (7, "Online", 4, "CI/CD"),
        (8, "Hybrid", 2, "Jenkins"),
        (9, "Offline", 3, "Terraform"),
        (10, "Online", 2, "Ansible"),
        (12, "Offline", 5, "Helm"),
        (15, "Hybrid", 3, "GitOps"),
        (4, "Online", 2, "Prometheus"),
        (11, "Offline", 4, "Argo CD"),
    )
    for days, mode, hours, topics in samples:
        body = _ack("DevOps", duration_days=days, mode=mode, lab_hours_per_day=hours, topics=topics)
        opening, prepare, close = _chosen_wording(body)
        openings.add(opening)
        prepares.add(prepare)
        closes.add(close)
        _assert_professional_ack(body, topics=True)
    assert len(openings) > 1
    assert len(prepares) > 1
    assert len(closes) > 1


def test_acknowledgement_recognises_the_client():
    facts = {
        "duration_days": 7,
        "mode": "Offline",
        "lab_hours_per_day": 3,
        "topics": "Docker, Kubernetes, and CI/CD",
    }
    by_email = {
        _chosen_wording(_ack("DevOps", client_email=email, client_name=name, **facts))
        for email, name in (
            ("asha@example.com", "Asha"),
            ("meera@example.com", "Meera"),
            ("ravi@example.com", "Ravi"),
            ("neha@example.com", "Neha"),
            ("kiran@example.com", "Kiran"),
            ("pooja@example.com", "Pooja"),
        )
    }
    by_name = {
        _chosen_wording(_ack("DevOps", client_email="", client_name=name, **facts))
        for name in ("Asha", "Meera", "Ravi", "Neha", "Kiran", "Pooja")
    }
    assert len(by_email) > 1
    assert len(by_name) > 1
    same_email = _chosen_wording(_ack("DevOps", client_email="asha@example.com", client_name="Asha", **facts))
    renamed = _chosen_wording(_ack("DevOps", client_email="asha@example.com", client_name="Meera", **facts))
    assert same_email == renamed


def test_version_one_and_ten_use_the_reference_tone():
    payload = {
        "client_name": "Asha",
        "client_email": "asha@example.com",
        "technology_needed": "DevOps",
        "duration_days": 7,
        "mode": "Offline",
        "lab_hours_per_day": 3,
        "topics": "Docker, Kubernetes, and CI/CD",
        "clahan_managed_details": ["Lab availability and cost"],
        "requested_details": ["CV", "ToC", "lab cost"],
        "needs_clarification": [],
    }
    version_one = (
        "Hi Asha,\n\n"
        "Thank you for sharing the DevOps requirement. We have noted the topics, "
        "7 training days, Offline delivery mode, and 3 lab hours per day.\n\n"
        "We will prepare the ToC and lab cost based on the details provided and "
        "share the relevant CV for your review.\n\n"
        "Looking forward to sharing the documents with you.\n\n"
        "Thanks,\nAnnapurna U.\nClahan Technologies"
    )
    version_ten = (
        "Hi Asha,\n\n"
        "Thank you for sharing the DevOps requirement. We have noted the topics, "
        "the 7-day training duration, Offline mode, and 3 lab hours per day.\n\n"
        "We will put together the ToC and lab cost based on the details you provided and "
        "share the trainer's CV for your review.\n\n"
        "Looking forward to sending these over to you.\n\n"
        "Thanks,\nAnnapurna U.\nClahan Technologies"
    )
    assert _render_professional_ack(payload, 0) == version_one
    assert _render_professional_ack(payload, 9) == version_ten
    assert apply_voice(version_one) == version_one
    assert apply_voice(version_ten) == version_ten
    rendered = {_render_professional_ack(payload, index) for index in range(10)}
    assert len(rendered) == 10
