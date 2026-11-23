from app.toc_generation_agent import generate_toc_from_dataset
from shared.toc_quality import topic_is_covered


def _curriculum(toc):
    return " ".join(" ".join([day["focus_area"], *day.get("subtopics", [])]) for day in toc["days"]).lower()


def test_requested_topics_drive_the_plan_at_the_requested_level():
    toc = generate_toc_from_dataset("Kubernetes", 5, level="intermediate",
                                    requested_topics="Helm, RBAC, Network Policies, Ingress")
    assert toc["agent"]["source"] == "requested_topics"
    assert len(toc["days"]) == 5
    assert all(topic_is_covered(topic, _curriculum(toc)) for topic in ("Helm", "RBAC", "Network Policies", "Ingress"))
    assert toc["days"][-1]["focus_area"] == "Intermediate Capstone: GitOps Platform for Three Teams"
    assert toc["topic_plan"]["missing"] == []


def test_without_topics_the_level_course_is_used_unchanged():
    plain = generate_toc_from_dataset("Kubernetes", 5, level="intermediate")
    assert plain["agent"]["source"] == "level_dataset"
    assert "topic_plan" not in plain


def test_topics_taught_at_another_level_are_explained():
    toc = generate_toc_from_dataset("Docker", 3, level="intermediate",
                                    requested_topics="Docker Compose, Multi-stage builds, Docker Swarm")
    # Docker Compose has its own level course, so its intermediate day is borrowed and needs no
    # level note; the other two topics only exist as beginner Docker days.
    assert [day["focus_area"] for day in toc["days"]] == [
        "Multi-Stage Builds and Smaller Images", "Docker Swarm and Moving to Orchestration",
        "Single-Host Production with Docker Compose"]
    assert len(toc["topic_plan"]["level_notes"]) == 2
    assert all("more depth" in note for note in toc["topic_plan"]["level_notes"])


def test_unknown_topics_are_reported_not_invented():
    toc = generate_toc_from_dataset("Kubernetes", 5, level="intermediate", requested_topics="Quantum entanglement, Helm")
    assert toc["topic_plan"]["missing"] == ["Quantum entanglement"]
    assert toc["quality"]["status"] == "requires_review"
    assert "quantum" not in _curriculum(toc)


def test_extra_days_go_to_the_level_plan_and_long_requests_are_filled():
    toc = generate_toc_from_dataset("Kubernetes", 10, level="intermediate",
                                    requested_topics="Helm, RBAC, Network Policies, Ingress")
    titles = [day["focus_area"] for day in toc["days"]]
    assert len(titles) == len(set(titles)) == 10
    assert "Cluster Installation with kubeadm" in titles
    long = generate_toc_from_dataset("Kotlin", 30, level="intermediate", requested_topics="Coroutines, Flow")
    assert len(long["days"]) == 30 and len({d["focus_area"] for d in long["days"]}) == 30
    assert all(topic_is_covered(topic, _curriculum(long)) for topic in ("Coroutines", "Flow"))


def test_a_technology_inside_a_broader_request_comes_from_its_own_course():
    toc = generate_toc_from_dataset("DevOps", 10, level="intermediate",
                                    requested_topics="Jenkins, Docker, Kubernetes, Terraform, Ansible")
    curriculum = _curriculum(toc)
    assert all(topic_is_covered(topic, curriculum) for topic in ("Jenkins", "Docker", "Kubernetes", "Terraform", "Ansible"))
    assert toc["topic_plan"]["missing"] == []


def test_the_technology_name_is_not_a_topic_and_compound_phrases_split():
    from app.topic_planner import requested_topic_list
    assert requested_topic_list("DevOps; Jenkins; Docker", "DevOps") == ["Jenkins", "Docker"]
    assert requested_topic_list("Jenkins and Monitoring, Docker", "DevOps") == ["Jenkins", "Monitoring", "Docker"]
    plain = generate_toc_from_dataset("Kubernetes", 5, level="intermediate", requested_topics="Kubernetes")
    assert plain["agent"]["source"] == "level_dataset"


def test_one_topic_does_not_take_over_the_programme():
    toc = generate_toc_from_dataset("DevOps", 10, level="intermediate", requested_topics="Docker")
    docker_days = [day for day in toc["days"] if "docker" in day["focus_area"].lower()]
    assert 1 <= len(docker_days) <= 5


def test_topics_that_did_not_fit_are_reported_separately():
    toc = generate_toc_from_dataset("AWS", 3, level="intermediate", requested_topics="EC2, S3, IAM, VPC, Lambda")
    plan = toc["topic_plan"]
    assert plan["missing"] == []
    assert plan["not_scheduled"]
    assert any("did not fit" in warning for warning in toc["quality"]["review_warnings"])


def test_model_draft_modules_need_review(monkeypatch):
    from app import level_curriculum as lc
    toc = generate_toc_from_dataset("Generative AI", 5, level="intermediate")
    assert not any("model drafts" in w for w in toc["quality"].get("review_warnings", []))
    course = lc.get_level_course("Generative AI")
    day = next(d for d in course["levels"]["intermediate"]["days"] if d.get("modules"))
    monkeypatch.setitem(day["modules"][0], "content_origin", "model_draft_pending_technical_review")
    drafted = generate_toc_from_dataset("Generative AI", 5, level="intermediate")
    assert drafted["quality"]["status"] == "requires_review"
    assert any("model drafts" in w for w in drafted["quality"]["review_warnings"])


def test_the_standard_plan_is_kept_when_it_already_covers_the_topics():
    toc = generate_toc_from_dataset("DevOps", 10, level="intermediate", requested_topics="DevOps; Jenkins; Docker; Kubernetes")
    titles = [day["focus_area"] for day in toc["days"]]
    assert titles[:3] == ["DevOps Orientation, SDLC and Agile Delivery", "Linux Fundamentals for DevOps", "Git and GitHub Collaboration"]
    assert toc["topic_plan"]["missing"] == []
    assert "standard plan" in toc["topic_plan"]["basis"]


def test_known_phrases_with_and_stay_whole():
    from app.topic_planner import requested_topic_list
    assert requested_topic_list("Continuous Integration and Continuous Delivery", "DevOps") == [
        "Continuous Integration and Continuous Delivery"]


def test_combined_programmes_have_unique_practice_titles():
    from app.toc_generation_agent import generate_combined_toc_from_datasets
    toc = generate_combined_toc_from_datasets([{"technology": "SAP", "days": 30}, {"technology": "Java", "days": 30}],
                                              level="intermediate")
    titles = [day["focus_area"] for day in toc["days"]]
    assert len(titles) == len(set(titles)) == 60
    assert toc["quality"]["status"] != "requires_regeneration"
    assert max(len(title) for title in titles) < 120


def test_a_topic_gets_a_day_about_it_when_one_exists():
    toc = generate_toc_from_dataset("AWS", 5, level="intermediate", requested_topics="IAM, VPC, Lambda, CloudWatch")
    titles = " ".join(day["focus_area"] for day in toc["days"])
    assert "Lambda" in titles and "CloudWatch" in titles
    assert toc["agent"]["source"] == "requested_topics"


def test_and_splits_unless_the_known_name_uses_it():
    from app.topic_planner import requested_topic_list
    assert requested_topic_list("Terraform and Infrastructure as Code", "DevOps") == ["Terraform", "Infrastructure as Code"]
