import pytest

from app.agents.natural_voice import apply_voice
from app.routes.inbox import (
    _ACK_ROTATION,
    _ACK_VERSIONS,
    _client_short_requirement_ack,
    _render_professional_ack,
)
import app.routes.inbox as inbox


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


def _reset_ack_clients(*clients: str) -> None:
    """Start these clients at version 1. The saved book must not pick the version."""
    inbox._load_ack_book()
    for client in clients:
        inbox._CLIENT_ACK_VERSIONS[client.lower()] = {}


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


def test_python_and_java_for_one_client_use_different_versions():
    """The version pool is not a DevOps template. Facts that are absent stay out."""
    _reset_ack_clients("asha@example.com")
    python_body = _ack(
        "Python",
        duration_days=5,
        mode="Online",
        lab_hours_per_day=2,
        topics="Pandas and FastAPI",
        requested_details=["CV"],
        clahan_managed_details=["Lab availability and cost"],
    )
    java_body = _ack(
        "Java",
        duration_days=4,
        mode="Offline",
        topics="Spring Boot",
        requested_details=["CV"],
        clahan_managed_details=[],
    )
    aws_body = _ack(
        "AWS",
        duration_days=6,
        mode="Online",
        lab_hours_per_day=3,
        topics="IAM and VPC",
        requested_details=["CV"],
        clahan_managed_details=["Lab availability and cost"],
    )

    assert "We have noted the topics, 5 training days, Online delivery mode, and 2 lab hours per day." in python_body
    assert "We will prepare the lab cost based on the details provided and share the relevant CV for your review." in python_body
    assert "Looking forward to sharing the documents with you." in python_body
    assert "toc" not in python_body.lower()
    assert "We have noted the topics, the 4-day training duration, and Offline mode." in java_body
    assert "We will share the trainer's CV for your review." in java_body
    assert "Looking forward to sending these over to you." in java_body
    assert "lab" not in java_body.lower()
    assert "This AWS batch is Online and runs for 6 days." in aws_body
    assert "The topics are included, and the lab is 3 hours per day." in aws_body
    assert "The lab cost will use those daily hours." in aws_body
    assert "We will share the CV for your review." in aws_body
    assert "Looking forward to your thoughts on the draft." in aws_body
    assert "toc" not in aws_body.lower()

    assert len({python_body, java_body, aws_body}) == 3
    assert _chosen_wording(python_body) != _chosen_wording(java_body)
    assert _chosen_wording(java_body) != _chosen_wording(aws_body)
    for body, technology in ((python_body, "Python"), (java_body, "Java"), (aws_body, "AWS")):
        assert "devops" not in body.lower()
        assert technology in body
        assert "Greetings of the day" not in body
        assert "Our team" not in body
        assert "connecting with you again soon" not in body
        assert body.endswith("Thanks,\nAnnapurna U.\nClahan Technologies")
        assert _close(body) in _CLOSES

    repeated = _ack(
        "Python",
        duration_days=5,
        mode="Online",
        lab_hours_per_day=2,
        topics="Pandas and FastAPI",
        requested_details=["CV"],
        clahan_managed_details=["Lab availability and cost"],
    )
    assert repeated == python_body

    proposal = _ack(
        "Python",
        client_email="proposal.asha@example.com",
        duration_days=3,
        mode="Online",
        topics="",
        requested_details=[],
        clahan_managed_details=[],
        batch_flow="proposal",
    )
    assert "devops" not in proposal.lower()
    assert "Python" in proposal
    assert "lab cost" not in proposal.lower()
    assert "cv" not in proposal.lower()
    assert "We have noted 3 training days and Online delivery mode." in proposal
    assert _close(proposal) in _CLOSES


def test_template_replies_use_the_same_version_pool():
    from app.agents.reply_templates import build_auto_reply

    _reset_ack_clients("template.asha@example.com")

    def reply(technology, **facts):
        payload = {
            "client_name": "Asha",
            "client_email": "template.asha@example.com",
            "technology_needed": technology,
            "needs_clarification": [],
            "requested_details": ["CV"],
            "clahan_managed_details": [],
        }
        payload.update(facts)
        return build_auto_reply(
            {
                "person_type": "corporate_client",
                "scenario": "new_training_requirement",
                "auto_reply_allowed": True,
                "requires_human": False,
            },
            payload,
            subject=f"{technology} training requirement",
            sender_name="Asha",
        )

    python = reply(
        "Python",
        duration_days=5,
        mode="Online",
        lab_hours_per_day=2,
        topics="Pandas and FastAPI",
        clahan_managed_details=["Lab availability and cost"],
    )
    java = reply("Java", duration_days=4, mode="Offline", topics="Spring Boot")
    assert python["template_key"] == "client_requirement_ack"
    assert java["template_key"] == "client_requirement_ack"
    assert "devops" not in python["body"].lower()
    assert "devops" not in java["body"].lower()
    assert "Python" in python["body"]
    assert "Java" in java["body"]
    assert _chosen_wording(python["body"]) != _chosen_wording(java["body"])
    assert "Greetings of the day" not in python["body"]
    assert "Thanks for sharing the DevOps training requirement." not in java["body"]
    assert "lab cost" in python["body"].lower()
    assert "lab" not in java["body"].lower()


def test_same_client_different_requirements_use_different_professional_versions():
    _reset_ack_clients("asha@example.com")
    devops_body = _ack(
        "DevOps",
        duration_days=7,
        mode="Offline",
        lab_hours_per_day=3,
        topics="Docker, Kubernetes, and CI/CD",
    )
    python_body = _ack(
        "Python",
        duration_days=5,
        mode="Online",
        lab_hours_per_day=2,
        topics="Pandas and FastAPI",
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

    assert "We have noted the topics, 7 training days, Offline delivery mode, and 3 lab hours per day." in devops_body
    assert "Looking forward to sharing the documents with you." in devops_body
    assert "We have noted the topics, the 5-day training duration, Online mode, and 2 lab hours per day." in python_body
    assert "share the trainer's CV for your review." in python_body
    assert "Looking forward to sending these over to you." in python_body
    assert "We have noted" not in devops_other
    assert "We have recorded" not in devops_other
    assert "taken note" not in devops_other
    assert "This DevOps batch is Online and runs for 10 days." in devops_other
    assert "The topics are included, and the lab is 4 hours per day." in devops_other
    assert "The lab cost will use those daily hours." in devops_other

    assert python_body != devops_body
    assert devops_body != devops_other
    assert devops_body == repeated
    assert _chosen_wording(python_body) != _chosen_wording(devops_body)
    assert _chosen_wording(devops_body) != _chosen_wording(devops_other)

    for body in (python_body, devops_body, devops_other):
        _assert_professional_ack(body, topics=True)
        assert "Greetings of the day" not in body
        assert "Our team" not in body
        assert "connecting with you again soon" not in body
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
    _reset_ack_clients("successive@example.com")
    openings = set()
    prepares = set()
    closes = set()
    bodies = []
    samples = (
        (5, "Online", 2, "Docker"),
        (6, "Offline", 3, "Kubernetes"),
        (7, "Online", 4, "CI/CD"),
        (8, "Hybrid", 2, "Jenkins"),
        (9, "Offline", 3, "Terraform"),
        (10, "Online", 2, "Ansible"),
        (12, "Offline", 5, "Helm"),
        (15, "Hybrid", 3, "GitOps"),
    )
    for days, mode, hours, topics in samples:
        body = _ack(
            "DevOps",
            client_email="successive@example.com",
            duration_days=days,
            mode=mode,
            lab_hours_per_day=hours,
            topics=topics,
        )
        opening, prepare, close = _chosen_wording(body)
        openings.add(opening)
        prepares.add(prepare)
        closes.add(close)
        bodies.append(body)
        _assert_professional_ack(body, topics=True)
        assert _OLD_ACK_SENTENCE not in body
        assert _OLD_PREPARE_SENTENCE not in body
        assert "Looking forward to sending this across." not in body
        assert "Greetings of the day" not in body
        assert "Our team" not in body
        assert "connecting with you again soon" not in body
    assert "We have noted the topics, 5 training days, Online delivery mode, and 2 lab hours per day." in bodies[0]
    assert "the 6-day training duration" in bodies[1]
    for body in bodies[2:]:
        assert "We have noted" not in body
    assert "We have noted" not in bodies[2]
    assert "This DevOps batch is Online and runs for 7 days." in bodies[2]
    # Version 1 and version 10 keep the same thank-you sentence.
    assert len(openings) == 7
    assert len(prepares) == 8
    assert len(closes) == 8
    assert len(set(bodies)) == 8
    repeated = _ack(
        "DevOps",
        client_email="successive@example.com",
        duration_days=5,
        mode="Online",
        lab_hours_per_day=2,
        topics="Docker",
    )
    assert repeated == bodies[0]


def test_acknowledgement_recognises_the_client():
    facts = {
        "duration_days": 7,
        "mode": "Offline",
        "lab_hours_per_day": 3,
        "topics": "Docker, Kubernetes, and CI/CD",
    }
    emails = (
        ("asha@example.com", "Asha"),
        ("meera@example.com", "Meera"),
        ("ravi@example.com", "Ravi"),
        ("neha@example.com", "Neha"),
        ("kiran@example.com", "Kiran"),
        ("pooja@example.com", "Pooja"),
    )
    _reset_ack_clients(*(email for email, _name in emails))
    email_bodies = [
        _ack("DevOps", client_email=email, client_name=name, **facts)
        for email, name in emails
    ]
    assert len({_chosen_wording(body) for body in email_bodies}) == 1
    assert [body.split("\n\n")[0] for body in email_bodies] == [f"Hi {name}," for _email, name in emails]
    assert "We have noted the topics, 7 training days, Offline delivery mode, and 3 lab hours per day." in email_bodies[0]

    names = ("Asha", "Meera", "Ravi", "Neha", "Kiran", "Pooja")
    _reset_ack_clients(*names)
    name_bodies = [_ack("DevOps", client_email="", client_name=name, **facts) for name in names]
    assert len({_chosen_wording(body) for body in name_bodies}) == 1
    assert [body.split("\n\n")[0] for body in name_bodies] == [f"Hi {name}," for name in names]

    second = _ack(
        "Python",
        client_email="meera@example.com",
        client_name="Meera",
        duration_days=5,
        mode="Online",
        lab_hours_per_day=2,
        topics="Pandas and FastAPI",
    )
    assert "We have noted the topics, the 5-day training duration, Online mode, and 2 lab hours per day." in second
    same_email = _chosen_wording(_ack("DevOps", client_email="asha@example.com", client_name="Asha", **facts))
    renamed = _ack("DevOps", client_email="asha@example.com", client_name="Meera", **facts)
    assert same_email == _chosen_wording(renamed)
    assert renamed.startswith("Hi Meera,")


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
    rendered = [_render_professional_ack(payload, index) for index in _ACK_ROTATION]
    assert len(set(rendered)) == len(_ACK_ROTATION) == 8
    assert _ACK_ROTATION == (0, 9, 1, 2, 5, 6, 7, 8)
    for body in rendered[2:]:
        assert "We have noted" not in body
        assert "We have recorded" not in body
        assert "taken note" not in body
        assert "Our team" not in body
        assert "connecting with you again soon" not in body
        assert apply_voice(body) == body
    with pytest.raises(ValueError):
        _render_professional_ack(payload, 3)
    with pytest.raises(ValueError):
        _render_professional_ack(payload, 4)

    missing_topics = {**payload, "topics": "", "requested_details": ["CV"]}
    missing_body = _render_professional_ack(missing_topics, 0)
    assert "Thank you for sharing the DevOps requirement. We have noted 7 training days, Offline delivery mode, and 3 lab hours per day." in missing_body
    assert "the topics" not in missing_body.lower()
    assert "We will prepare the lab cost based on the details provided and share the relevant CV for your review." in missing_body
    assert "Looking forward to sharing the documents with you." in missing_body
    assert _OLD_ACK_SENTENCE not in missing_body
    assert _OLD_PREPARE_SENTENCE not in missing_body

    not_lab = {**payload, "clahan_managed_details": []}
    not_lab_body = _render_professional_ack(not_lab, 9)
    assert "We have noted the topics, the 7-day training duration, Offline mode, and 3 lab hours per day." in not_lab_body
    assert "We will put together the ToC based on the details you provided and share the trainer's CV for your review." in not_lab_body
    assert "lab cost" not in not_lab_body.lower()
    assert "Looking forward to sending these over to you." in not_lab_body
    assert _OLD_ACK_SENTENCE not in not_lab_body

    linkedin = {**payload, "requested_details": ["CV", "LinkedIn profile", "ToC"]}
    linkedin_body = _render_professional_ack(linkedin, 0)
    assert "share the relevant CV and LinkedIn profile for your review." in linkedin_body
    assert linkedin_body.count("for your review") == 1
    assert _OLD_ACK_SENTENCE not in linkedin_body
