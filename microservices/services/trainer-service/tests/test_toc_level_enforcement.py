from app.toc_generation_agent import _subtopic_target, generate_toc_from_dataset
from app.toc_domain_dataset import COMPACT_DOMAINS, _load_compact_domains


def test_intermediate_toc_is_cumulative_and_keeps_foundations():
    toc = generate_toc_from_dataset("DevOps", 10, level="intermediate")

    titles = " ".join(day["focus_area"].lower() for day in toc["days"])
    assert "linux fundamentals" in titles
    assert any(marker in titles for marker in ("docker", "container", "jenkins", "kubernetes"))
    assert len(toc["days"]) == 10
    assert "working knowledge" in toc["prerequisites"][0].lower()
    assert any("production-oriented" in outcome.lower() for outcome in toc["learning_outcomes"])


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
