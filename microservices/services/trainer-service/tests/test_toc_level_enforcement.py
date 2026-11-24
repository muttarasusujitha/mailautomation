from app.toc_generation_agent import _subtopic_target, generate_toc_from_dataset, resolve_content_level
from app.toc_domain_dataset import COMPACT_DOMAINS, _load_compact_domains

# A compact dataset key with no level course, used to test the catalog (non-level) path.
# Kotlin itself now has a level course, so tests that need the old path use its compact file.
CATALOG_ONLY = "kotlin_15"
# DevOps now has a level course; its curated catalog path is still reachable by dataset key.
DEVOPS_CATALOG = "devops_30"


def test_intermediate_toc_is_cumulative_and_keeps_foundations():
    toc = generate_toc_from_dataset(DEVOPS_CATALOG, 10, level="intermediate")

    titles = " ".join(day["focus_area"].lower() for day in toc["days"])
    assert "linux fundamentals" in titles
    assert any(marker in titles for marker in ("docker", "container", "jenkins", "kubernetes"))
    assert len(toc["days"]) == 10
    assert "working knowledge" in toc["prerequisites"][0].lower()
    assert any("production-oriented" in outcome.lower() for outcome in toc["learning_outcomes"])


def test_intermediate_ten_day_devops_path_is_ordered_and_does_not_add_azure():
    toc = generate_toc_from_dataset(DEVOPS_CATALOG, 10, level="intermediate")
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
    toc = generate_toc_from_dataset(DEVOPS_CATALOG, 10, level="beginner")

    titles = " ".join(day["focus_area"].lower() for day in toc["days"])
    assert any(marker in titles for marker in ("basics", "fundamentals", "orientation"))


def test_levels_use_distinct_ordered_depth_bands():
    beginner = generate_toc_from_dataset(DEVOPS_CATALOG, 10, level="beginner")
    intermediate = generate_toc_from_dataset(DEVOPS_CATALOG, 10, level="intermediate")
    advanced = generate_toc_from_dataset(DEVOPS_CATALOG, 10, level="advanced")

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
    mixed = generate_toc_from_dataset(DEVOPS_CATALOG, 10, level="mixed")
    beginner = generate_toc_from_dataset(DEVOPS_CATALOG, 10, level="beginner")
    intermediate = generate_toc_from_dataset(DEVOPS_CATALOG, 10, level="intermediate")
    advanced = generate_toc_from_dataset(DEVOPS_CATALOG, 10, level="advanced")
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


def test_short_advanced_compact_toc_skips_the_introductory_days():
    beginner = [day["focus_area"] for day in generate_toc_from_dataset(CATALOG_ONLY, 5, level="beginner")["days"]]
    advanced = [day["focus_area"] for day in generate_toc_from_dataset(CATALOG_ONLY, 5, level="advanced")["days"]]
    assert beginner[0] == "Kotlin Introduction and Environment Setup"
    assert not set(advanced[:-1]) & set(beginner[:-1])
    assert "capstone" in advanced[-1].lower()


def test_level_days_carry_scenarios_and_catalog_days_keep_their_assessment():
    level_day = generate_toc_from_dataset("Kubernetes", 5, level="intermediate")["days"][1]
    assert len(level_day["scenarios"]) == len(level_day["acceptance_checks"]) == 3
    assert level_day["scenarios"][0]["outcome"] == level_day["acceptance_checks"][0]["expected_result"]
    catalog_days = generate_toc_from_dataset(CATALOG_ONLY, 5, level="intermediate")["days"]
    assert all(not day["assessment"].startswith("Daily knowledge check") for day in catalog_days)


def test_authored_modules_reach_the_toc_with_scenarios_and_timed_steps():
    toc = generate_toc_from_dataset("Generative AI", 5, level="intermediate")
    day = toc["days"][0]
    assert [module["title"] for module in day["modules"]][0] == "Anatomy of an LLM Application"
    assert sum(module["minutes"] for module in day["modules"]) == 420
    for module in day["modules"]:
        assert len(module["scenarios"]) >= 3
        assert sum(step["minutes"] for step in module["delivery_steps"]) == module["minutes"]
    assert toc["quality"]["content_evaluation"]["status"] == "pass"


def test_incomplete_authored_modules_fail_validation():
    from app.level_curriculum import _module_problems
    good = {"title": "T", "minutes": 210, "subtopics": ["a", "b", "c"], "objective": "o", "lab": "l",
            "deliverable": "d", "success_measure": "s", "scenarios": [["a", "b", "c", "d"]] * 3}
    assert _module_problems([good, good], "Day 1") == []
    assert "add up to 420" in _module_problems([good], "Day 1")[0]
    assert "needs 3 scenarios" in _module_problems([{**good, "scenarios": [["a", "b"]]}, good], "Day 1")[0]
    assert "missing lab" in _module_problems([{**good, "lab": ""}, good], "Day 1")[0]
    assert "at least 3 subtopics" in _module_problems([{**good, "subtopics": ["a"]}, good], "Day 1")[0]
    assert "must be an object" in _module_problems(["not a module", good], "Day 1")[0]


def test_level_is_read_from_a_longer_audience_description():
    # IT company and college batches both choose the level by naming it.
    assert resolve_content_level("intermediate", "Advanced developers") == "advanced"
    assert resolve_content_level("intermediate", "IT employees, intermediate level") == "intermediate"
    assert resolve_content_level("intermediate", "College students - beginner") == "beginner"
    assert resolve_content_level("intermediate", "Engineering college students, basics") == "beginner"
    assert resolve_content_level("intermediate", "Freshers from beginner to advanced") == "mixed"
    # College and fresher batches without a named level start at beginner.
    assert resolve_content_level("intermediate", "College students") == "beginner"
    assert resolve_content_level("", "Final-year B.Tech students") == "beginner"
    assert resolve_content_level("intermediate", "Freshers joining the company") == "beginner"
    assert resolve_content_level("advanced", "College students") == "advanced"
    # Other audience words without a level keep the requested or default level.
    assert resolve_content_level("intermediate", "Senior managers") == "intermediate"
    assert resolve_content_level("intermediate", "IT employees") == "intermediate"
    assert resolve_content_level("advanced", "Corporate employees") == "advanced"
    # An explicitly chosen non-default level still wins over the audience text.
    assert resolve_content_level("beginner", "Advanced developers") == "beginner"


def test_long_programmes_use_all_course_content_before_practice_days():
    for name, duration in (("Kubernetes", 60), ("Kubernetes", 100), ("Kotlin", 30), ("Kotlin", 5)):
        toc = generate_toc_from_dataset(name, duration, level="intermediate")
        titles = [day["focus_area"] for day in toc["days"]]
        assert len(titles) == duration == len(set(titles)), name
        assert "capstone" in titles[-1].lower(), name
        assert not any(title.startswith(("Real-Time Project Sprint", "Revision, Assessment")) for title in titles), name
    # All three Kubernetes levels together fill most of a 60-day programme.
    sixty = generate_toc_from_dataset("Kubernetes", 60, level="intermediate")
    assert sixty["agent"]["levels_used"] == ["beginner", "intermediate", "advanced"]
    assert sixty["practice_days"] <= 3


def test_practice_days_build_on_taught_topics_and_are_disclosed():
    toc = generate_toc_from_dataset(CATALOG_ONLY, 30, level="intermediate")
    practice = [day for day in toc["days"] if day["focus_area"].startswith("Project Sprint")]
    assert practice and len(practice) == toc["practice_days"]
    taught = [day["focus_area"] for day in toc["days"] if not day["focus_area"].startswith("Project Sprint")]
    assert all(any(topic in day["focus_area"] for topic in taught) for day in practice)
    # Practice days are spread through the programme, not stacked before the capstone.
    positions = [toc["days"].index(day) for day in practice]
    assert positions[0] < len(toc["days"]) // 2
    assert any("project practice days" in note for note in toc["review_warnings"])


def test_long_advanced_requests_keep_the_advanced_end_and_capstone():
    for name, duration in (("Kubernetes", 40), ("SAP", 20), ("Cloud", 24)):
        toc = generate_toc_from_dataset(name, duration, level="advanced")
        titles = [day["focus_area"] for day in toc["days"]]
        assert len(titles) == duration == len(set(titles)), name
        assert titles[-1].startswith("Advanced Capstone"), name
        assert toc["agent"]["levels_used"][-1] == "advanced", name


def test_audience_sentences_are_not_read_as_college_or_level_words():
    assert resolve_content_level("intermediate", "Developers who will be working on AWS") == "intermediate"
    assert resolve_content_level("intermediate", "B.E. final year students") == "beginner"
    assert resolve_content_level("intermediate", "Intermediate to advanced developers") == "intermediate"
    assert resolve_content_level("intermediate", "Please share the plan in advance") == "intermediate"
    assert resolve_content_level("intermediate", "advance level") == "advanced"


def test_long_programmes_do_not_return_to_basics_after_advanced_content():
    toc = generate_toc_from_dataset("Python", 80, level="advanced")
    titles = [day["focus_area"] for day in toc["days"]]
    assert "Python Basics" not in titles[len(titles) // 2:]


def test_saved_client_knowledge_is_not_padded_with_catalog_days():
    knowledge = {"name": "Client Kotlin", "days": [
        {"topic": f"Client topic {index}", "subtopics": ["one", "two", "three"], "lab": f"Client lab {index}"}
        for index in range(1, 7)]}
    toc = generate_toc_from_dataset("Kotlin", 12, level="intermediate", domain_override=knowledge)
    titles = [day["focus_area"] for day in toc["days"]]
    assert all(title.startswith(("Client topic", "Project Sprint")) or "Capstone" in title for title in titles)
    short = generate_toc_from_dataset("Kotlin", 5, level="advanced", domain_override=knowledge)
    assert short["days"][0]["focus_area"] == "Client topic 1"


def test_advanced_check_ignores_fundamentals_of_a_subject():
    toc = generate_toc_from_dataset("DSA & Algorithms Mastery", 5, level="advanced")
    assert not any("introductory topics" in warning for warning in toc["quality"].get("review_warnings", []))


def test_mostly_practice_long_programmes_need_review():
    toc = generate_toc_from_dataset(CATALOG_ONLY, 60, level="intermediate")
    assert toc["practice_days"] * 2 > 60
    assert toc["quality"]["status"] == "requires_review"


def test_prerequisite_phrases_and_verbs_do_not_set_the_level():
    assert resolve_content_level("intermediate", "Intermediate developers with basic Kubernetes knowledge") == "intermediate"
    assert resolve_content_level("intermediate", "Engineers looking to advance their skills") == "intermediate"
    assert resolve_content_level("intermediate", "Advance course for testers") == "advanced"


def test_borrowed_courses_keep_their_own_order():
    titles = [day["focus_area"] for day in generate_toc_from_dataset("Java", 90, level="intermediate")["days"]]
    spring_core = [index for index, title in enumerate(titles) if title.startswith("Spring Core")]
    spring_mvc = [index for index, title in enumerate(titles) if title.startswith("Spring MVC")]
    assert spring_core and spring_mvc and spring_core[0] < spring_mvc[0]


def test_module_validation_rejects_tiny_modules_and_bad_scenarios():
    from app.level_curriculum import _module_problems
    good = {"title": "T", "minutes": 210, "subtopics": ["a", "b", "c"], "objective": "o", "lab": "l",
            "deliverable": "d", "success_measure": "s", "scenarios": [["a", "b", "c", "d"]] * 3}
    assert "at least 30" in _module_problems([{**good, "minutes": 5}, good], "Day 1")[0]
    assert "needs 3 scenarios" in _module_problems([{**good, "scenarios": "not a list"}, good], "Day 1")[0]


def test_beginner_audiences_and_level_spellings():
    assert resolve_content_level("intermediate", "Beginner with no prior experience") == "beginner"
    assert resolve_content_level("intermediate", "Beginner with basic knowledge of Python") == "beginner"
    assert resolve_content_level("intermediate", "Mid-level engineers with basic Python") == "intermediate"
    assert resolve_content_level("intermediate", "Advance Java developers") == "advanced"


def test_long_programmes_keep_borrowed_days_before_the_advanced_end():
    import re
    titles = [day["focus_area"] for day in generate_toc_from_dataset("Java", 90, level="intermediate")["days"]]
    assert not any(re.search(r"\b(basics|fundamentals)\b", title, re.I) for title in titles[len(titles) // 2:])
    assert titles[-1].startswith("Advanced Capstone")


def test_devops_uses_its_level_course_with_timed_modules():
    for level, first in (("beginner", "DevOps Culture and the CALMS Model"),
                         ("intermediate", "Trunk-Based Development with Short-Lived Branches"),
                         ("advanced", "From Ticket Queues to Self-Service Delivery")):
        toc = generate_toc_from_dataset("DevOps", 10, level=level)
        assert toc["days"][0]["focus_area"] == first, level
        assert "capstone" in toc["days"][-1]["focus_area"].lower(), level
        assert toc["quality"]["status"] == "approved", level
        for day in toc["days"]:
            assert 3 <= len(day["modules"]) <= 4, day["focus_area"]
            assert sum(module["minutes"] for module in day["modules"]) == 420, day["focus_area"]
            assert all(len(module["scenarios"]) >= 3 for module in day["modules"]), day["focus_area"]


def test_devops_days_carry_an_ordered_subtopic_roadmap():
    from app.level_curriculum import ROADMAP_STAGES
    from app.toc_pdf_template import build_toc_html
    toc = generate_toc_from_dataset("DevOps", 5, level="beginner")
    for day in toc["days"]:
        stages = [step["stage"] for step in day["roadmap"]]
        assert 3 <= len(stages) <= 5, day["focus_area"]
        assert [ROADMAP_STAGES.index(s) for s in stages] == sorted(ROADMAP_STAGES.index(s) for s in stages)
        # The flat subtopics follow the roadmap order, so every export reads the same way.
        assert day["subtopics"] == [item for step in day["roadmap"] for item in step["subtopics"]]
    html = build_toc_html(toc)
    assert html.count("Learning Roadmap") == 5
    assert "Step 1: Understand" in html


def test_roadmap_validation_rejects_missing_subtopics_and_bad_order():
    from app.level_curriculum import _roadmap_problems
    day = {"subtopics": ["a", "b", "c"]}
    good = [{"stage": "Understand", "subtopics": ["a"]}, {"stage": "Build", "subtopics": ["b"]},
            {"stage": "Verify", "subtopics": ["c"]}]
    assert _roadmap_problems({**day, "roadmap": good}, "Day 1") == []
    assert "exactly once" in _roadmap_problems({**day, "roadmap": good[:2] + [{"stage": "Verify", "subtopics": ["x"]}]}, "Day 1")[0]
    assert "follow" in _roadmap_problems({**day, "roadmap": list(reversed(good))}, "Day 1")[0]
    assert "3 to 5" in _roadmap_problems({**day, "roadmap": good[:2]}, "Day 1")[0]


def test_days_without_modules_show_their_roadmap_as_topic_groups():
    from app.course_outline import outline_from_flat
    outline = outline_from_flat({"subtopics": ["a", "b", "c"], "roadmap": [
        {"stage": "Understand", "subtopics": ["a"]}, {"stage": "Build", "subtopics": ["b"]},
        {"stage": "Verify", "subtopics": ["c"]}]})
    assert [group["heading"] for group in outline["topic_groups"]] == [
        "Step 1: Understand", "Step 2: Build", "Step 3: Verify"]
