from app.toc_generation_agent import generate_combined_toc_from_datasets
from app.toc_generation_agent import generate_toc_from_dataset
from app.toc_domain_dataset import get_domain, list_domains


def test_intermediate_combined_programme_keeps_requested_scope_and_specific_labs():
    allocations = [
        {"technology": "DevOps", "days": 7},
        {"technology": "AWS", "days": 3},
        {"technology": "Azure", "days": 3},
        {"technology": "Kubernetes", "days": 3},
        {"technology": "Python", "days": 2},
        {"technology": "Agentic AI", "days": 2},
    ]

    toc = generate_combined_toc_from_datasets(
        allocations,
        level="intermediate",
        training_dates="02-Nov-2026",
    )

    assert len(toc["days"]) == 20
    assert toc["technology_allocations"] == allocations
    titles = [day["focus_area"].lower() for day in toc["days"]]
    assert len(titles) == len(set(titles))
    for technology in ("aws", "azure", "kubernetes", "python", "agentic ai"):
        assert technology in " ".join(titles)
    assert all(day.get("lab") for day in toc["days"])
    assert all("guided hands-on exercise" not in day["lab"].lower() for day in toc["days"])
    assert toc["days"][0]["focus_area"] == "Source, Build and Artifact Strategy"
    assert toc["days"][-1]["focus_area"].endswith("Capstone")


def test_all_registered_domains_pass_the_universal_toc_quality_contract():
    for domain in list_domains():
        toc = generate_toc_from_dataset(domain["name"], 20, level="intermediate")
        assert len(toc["days"]) == 20, domain["name"]
        assert toc["quality"]["status"] == "approved", domain["name"]
        assert all(day.get("lab") for day in toc["days"]), domain["name"]
        assert all("guided hands-on exercise" not in day["lab"].lower() for day in toc["days"]), domain["name"]


def test_every_registered_domain_passes_the_quality_contract_at_all_levels():
    for level in ("basic", "intermediate", "advanced"):
        for domain in list_domains():
            toc = generate_toc_from_dataset(domain["name"], 20, level=level)
            assert toc["quality"]["status"] == "approved", f"{level}: {domain['name']}"
            assert len(toc["days"]) == 20, f"{level}: {domain['name']}"
            assert all(day.get("lab") for day in toc["days"]), f"{level}: {domain['name']}"
            assert all(day.get("learning_objectives") for day in toc["days"]), f"{level}: {domain['name']}"


def test_catalogue_has_unique_display_names_and_every_item_resolves_to_a_dataset():
    domains = list_domains()
    display_names = [domain["name"].strip().lower() for domain in domains]
    assert len(display_names) == len(set(display_names))
    assert all(get_domain(domain["name"], 20) for domain in domains)


def test_advanced_combined_programme_uses_expert_modules_not_intermediate_modules():
    allocations = [
        {"technology": "DevOps", "days": 7},
        {"technology": "AWS", "days": 3},
        {"technology": "Azure", "days": 3},
        {"technology": "Kubernetes", "days": 3},
        {"technology": "Python", "days": 2},
        {"technology": "Agentic AI", "days": 2},
    ]

    intermediate = generate_combined_toc_from_datasets(allocations, level="intermediate")
    advanced = generate_combined_toc_from_datasets(allocations, level="advanced")

    assert len(advanced["days"]) == 20
    assert advanced["quality"]["status"] == "approved"
    assert advanced["days"][0]["focus_area"] == "Platform Engineering and Golden Paths"
    assert advanced["days"][0]["focus_area"] != intermediate["days"][0]["focus_area"]
    content = " ".join(
        " ".join([day["focus_area"], *day["subtopics"], day["lab"]])
        for day in advanced["days"]
    ).lower()
    for marker in ("multi-account", "azure enterprise", "multi-tenancy", "python reliability", "llmops"):
        assert marker in content
