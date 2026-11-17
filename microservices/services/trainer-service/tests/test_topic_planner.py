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
    assert [day["focus_area"] for day in toc["days"]] == [
        "Docker Compose for Multi-Container Apps", "Multi-Stage Builds and Smaller Images",
        "Docker Swarm and Moving to Orchestration"]
    assert len(toc["topic_plan"]["level_notes"]) == 3
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
