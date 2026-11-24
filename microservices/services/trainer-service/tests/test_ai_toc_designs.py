import app.module_design_store as store
from app.toc_generation_agent import generate_toc_from_dataset


def _ai_toc(*titles):
    return {"days": [{"day": index, "focus_area": title, "modules": [{"title": title}]}
                     for index, title in enumerate(titles, 1)]}


def test_ai_days_get_the_design_of_the_module_they_teach():
    toc = _ai_toc("Docker Fundamentals", "Docker Fundamentals for Developers", "Containers in Practice")
    assert store.attach_to_ai_toc(toc, "DevOps") == 2
    first, second, third = toc["days"]
    assert first["design"]["seeded_failure"]["symptom"]  # the authored Docker design
    assert first["design_link"]["dataset_module"] == "docker fundamentals"
    assert second["design"] == first["design"]
    assert "design" not in third  # a similar title is not enough


def test_linking_uses_the_stored_design_of_a_level_course(tmp_path, monkeypatch):
    import app.level_curriculum as lc
    monkeypatch.setattr(store, "DIR", tmp_path)
    store.clear_cache()
    course = lc.get_level_course("SAP")
    day = course["levels"]["beginner"]["days"][0]
    design = {"outcomes": [], "topics": [], "quiz": ["Q?"], "origin": "test"}
    store.write(day["design_ref"]["file"], {store.place_key("beginner", day["topic"]): design}, tmp_path)
    toc = _ai_toc(day["topic"], "Something Else Entirely")
    assert store.attach_to_ai_toc(toc, "SAP") == 1
    assert toc["days"][0]["design"]["origin"] == "test" and "design" not in toc["days"][1]
    store.clear_cache()


def test_longest_module_title_wins_and_existing_designs_are_kept():
    toc = _ai_toc("Docker Compose and Multi-Container Apps")
    toc["days"].append({"day": 2, "focus_area": "Docker Fundamentals", "design": {"origin": "kept"}})
    store.attach_to_ai_toc(toc, "DevOps")
    linked = toc["days"][0].get("design_link")
    assert linked is None or linked["dataset_module"] == "docker compose and multi container apps"
    assert toc["days"][1]["design"] == {"origin": "kept"}


def test_dataset_toc_is_unchanged_by_linking():
    toc = generate_toc_from_dataset("DevOps", 10)
    before = [day.get("design") for day in toc["days"]]
    store.attach_to_ai_toc(toc, "DevOps")
    assert [day.get("design") for day in toc["days"]] == before
