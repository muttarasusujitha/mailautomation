from app.toc_generation_agent import _subtopic_target, generate_toc_from_dataset, resolve_content_level
from app.toc_domain_dataset import COMPACT_DOMAINS, _load_compact_domains


def test_intermediate_toc_is_cumulative_and_keeps_foundations():
    toc = generate_toc_from_dataset("DevOps", 10, level="intermediate")

    titles = " ".join(day["focus_area"].lower() for day in toc["days"])
    assert "linux fundamentals" in titles
    assert any(marker in titles for marker in ("docker", "container", "jenkins", "kubernetes"))
    assert len(toc["days"]) == 10
    assert "working knowledge" in toc["prerequisites"][0].lower()
    assert any("production-oriented" in outcome.lower() for outcome in toc["learning_outcomes"])


def test_intermediate_ten_day_devops_path_is_ordered_and_does_not_add_azure():
    toc = generate_toc_from_dataset("DevOps", 10, level="intermediate")
    titles = [day["focus_area"] for day in toc["days"]]

    assert titles == [
        "DevOps Orientation, SDLC and Agile Delivery",
        "Linux Fundamentals for DevOps",
        "Git and GitHub Collaboration",
        "Jenkins Fundamentals",
        "Docker Fundamentals",
        "Kubernetes Architecture",
        "AWS DevOps Foundations",
        "Terraform Infrastructure as Code",
        "DevSecOps and Quality Gates",
        "Capstone Demo and Certification Roadmap",
    ]
    assert all("azure" not in title.lower() for title in titles)


def test_devops_toc_supports_every_duration_from_one_to_thirty_without_azure_scope():
    for duration in (1, 2, 10, 16, 20, 30):
        toc = generate_toc_from_dataset("DevOps", duration, level="intermediate")
        curriculum = " ".join(
            " ".join([
                day["focus_area"],
                " ".join(day.get("subtopics") or []),
                day.get("lab") or "",
            ])
            for day in toc["days"]
        ).lower()
        assert len(toc["days"]) == duration
        assert "azure" not in curriculum


def test_beginner_toc_retains_progressive_foundations():
    toc = generate_toc_from_dataset("DevOps", 10, level="beginner")

    titles = " ".join(day["focus_area"].lower() for day in toc["days"])
    assert any(marker in titles for marker in ("basics", "fundamentals", "orientation"))


def test_levels_use_distinct_ordered_depth_bands():
    beginner = generate_toc_from_dataset("DevOps", 10, level="beginner")
    intermediate = generate_toc_from_dataset("DevOps", 10, level="intermediate")
    advanced = generate_toc_from_dataset("DevOps", 10, level="advanced")

    beginner_titles = [day["focus_area"] for day in beginner["days"]]
    intermediate_titles = [day["focus_area"] for day in intermediate["days"]]
    advanced_titles = [day["focus_area"] for day in advanced["days"]]
    assert beginner_titles != intermediate_titles != advanced_titles
    assert beginner_titles[0] == "DevOps Orientation, SDLC and Agile Delivery"
    assert intermediate_titles[0] == "DevOps Orientation, SDLC and Agile Delivery"
    assert "Linux Fundamentals for DevOps" in intermediate_titles
    assert "Linux Fundamentals for DevOps" in advanced_titles
    assert "End-to-End DevOps Project Sprint" in advanced_titles


def test_all_compact_courses_generate_at_every_level():
    _load_compact_domains()
    course_names = {
        domain.get("name") or domain.get("domain")
        for domain in COMPACT_DOMAINS.values()
    }
    for course_name in course_names:
        for level in ("beginner", "intermediate", "advanced"):
            toc = generate_toc_from_dataset(course_name, 10, level=level)
            assert toc["level"] == level
            assert len(toc["days"]) == 10
            assert all(day["focus_area"] for day in toc["days"])
            assert all(len(day["subtopics"]) >= _subtopic_target(day["focus_area"]) for day in toc["days"])


def _knowledge_domain():
    def topic(name):
        return {
            "topic": name,
            "subtopics": ["Terms", "Workflow", "Check"],
            "tools": ["Sample"],
            "lab": f"Configure, validate, and troubleshoot {name} in the sample workspace",
        }
    return {
        "name": "Sample",
        "level_map": {
            "foundation": [topic("Orientation")],
            "core": [topic("Core Build")],
            "advanced": [topic("Scale Architecture")],
            "security": [topic("Security Hardening")],
            "capstone": [topic("Sample Capstone")],
        },
    }


def test_knowledge_beginner_stays_in_foundation():
    toc = generate_toc_from_dataset("Sample", 4, level="beginner", domain_override=_knowledge_domain())
    titles = [day["focus_area"] for day in toc["days"]]
    assert "Orientation" in titles
    assert "Core Build" not in titles
    assert "Scale Architecture" not in titles
    assert "Security Hardening" not in titles


def test_knowledge_mixed_includes_foundation_core_and_advanced():
    domain = _knowledge_domain()
    domain["level_map"]["foundation"].append({
        "topic": "Setup Practice",
        "subtopics": ["Install", "Access", "Check"],
        "tools": ["Sample"],
        "lab": "Install the sample tools and confirm access",
    })
    toc = generate_toc_from_dataset("Sample", 7, level="mixed", domain_override=domain)
    titles = [day["focus_area"] for day in toc["days"]]
    assert toc["level"] == "mixed"
    assert "Orientation" in titles
    assert "Core Build" in titles
    assert "Scale Architecture" in titles
    assert "Security Hardening" not in titles


def test_mixed_compact_track_spans_early_and_later_days():
    mixed = generate_toc_from_dataset("DevOps", 10, level="mixed")
    beginner = generate_toc_from_dataset("DevOps", 10, level="beginner")
    intermediate = generate_toc_from_dataset("DevOps", 10, level="intermediate")
    advanced = generate_toc_from_dataset("DevOps", 10, level="advanced")
    mixed_titles = [day["focus_area"] for day in mixed["days"]]
    assert mixed["level"] == "mixed"
    assert mixed_titles[0] == "DevOps Orientation, SDLC and Agile Delivery"
    assert mixed_titles != [day["focus_area"] for day in beginner["days"]]
    assert mixed_titles != [day["focus_area"] for day in intermediate["days"]]
    assert mixed_titles != [day["focus_area"] for day in advanced["days"]]
    later = {"Kubernetes Architecture", "Terraform Infrastructure as Code", "DevSecOps and Quality Gates", "End-to-End DevOps Project Sprint"}
    assert any(title in later for title in mixed_titles)


def test_audience_band_replaces_the_default_level():
    assert resolve_content_level("intermediate", "beginner") == "beginner"
    assert resolve_content_level("intermediate", "mixed") == "mixed"
    assert resolve_content_level("intermediate", "Basic + Intermediate + Advanced Mix") == "mixed"
    assert resolve_content_level("advanced", "finance analysts") == "advanced"
    assert resolve_content_level("beginner", "advanced") == "beginner"
    assert resolve_content_level("", "expert") == "advanced"


def test_common_level_aliases_are_canonicalized():
    assert generate_toc_from_dataset("DevOps", 10, "basic")["level"] == "beginner"
    assert generate_toc_from_dataset("DevOps", 10, "intermidate")["level"] == "intermediate"
    assert generate_toc_from_dataset("DevOps", 10, "advance")["level"] == "advanced"


def test_representative_catalog_levels_use_distinct_cumulative_tracks():
    for course_name in ("DevOps", "Python", "Java", "Kubernetes", "AWS AI"):
        tracks = []
        for level in ("basic", "intermediate", "advanced"):
            toc = generate_toc_from_dataset(course_name, 10, level=level)
            tracks.append(tuple(day["focus_area"] for day in toc["days"][:-1]))
        assert len(set(tracks)) == 3, course_name


def test_python_days_have_ten_concrete_subtopics():
    for level in ("basic", "intermediate", "advanced"):
        toc = generate_toc_from_dataset("Python", 10, level=level)
        assert all(len(day["subtopics"]) >= _subtopic_target(day["focus_area"]) for day in toc["days"])
    first_day = generate_toc_from_dataset("Python", 10, level="basic")["days"][0]
    assert len(first_day["subtopics"]) >= 10
    details = " ".join(first_day["subtopics"]).lower()
    assert "variables" in details
    assert "comments" in details
