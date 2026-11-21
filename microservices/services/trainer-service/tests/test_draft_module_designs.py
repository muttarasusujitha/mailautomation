import asyncio
import json
import shutil
from copy import deepcopy
from pathlib import Path

import app.draft_module_designs as drafts
import app.module_design_store as store

APP = Path(__file__).resolve().parents[1] / "app"


def _copy_courses(tmp_path, monkeypatch):
    level, compact, designs = tmp_path / "levels", tmp_path / "compact", tmp_path / "designs"
    level.mkdir()
    compact.mkdir()
    shutil.copy(APP / "datasets_levels" / "sap.json", level / "sap.json")
    shutil.copy(APP / "datasets_compact" / "devops_30.json", compact / "devops_30.json")
    shutil.copy(APP / "datasets_compact" / "cloud_60.json", compact / "cloud_60.json")
    monkeypatch.setattr(drafts, "LEVEL_DIR", level)
    monkeypatch.setattr(drafts, "COMPACT_DIR", compact)
    monkeypatch.setattr(drafts, "DESIGN_DIR", designs)
    monkeypatch.setattr(store, "DIR", designs)
    store.clear_cache()
    return level, compact, designs


def _good_design():
    return deepcopy(drafts.example_design()["design"])


def _fake_post(bad_topics=(), always_bad=()):
    calls = []

    async def post(system, user):
        payload = json.loads(user)
        calls.append(payload)
        modules = []
        for source in payload["modules"]:
            design = _good_design()
            retry = "fix_these_problems_in_your_previous_draft" in payload
            if source["topic"] in always_bad or (source["topic"] in bad_topics and not retry):
                design["quiz"] = ["Not a question"]
            modules.append({"key": source["key"], "design": design})
        return json.dumps({"modules": modules})
    post.calls = calls
    return post


def _quiet(*args, **kwargs):
    pass


def test_inventory_skips_designed_and_placeholder_modules(tmp_path, monkeypatch):
    _copy_courses(tmp_path, monkeypatch)
    skipped = []
    pending = drafts.inventory(["sap", "devops_30", "cloud_60"], skipped)
    topics = {entry["source"]["topic"] for entry in pending.values()}
    assert "Docker Fundamentals" not in topics  # authored design in its outline
    assert sum(entry["course"] == "devops_30" for entry in pending.values()) == 29
    # cloud_60 days 31-60 are generic "<topic> concepts / configuration" placeholders.
    assert len([s for s in skipped if s["course"] == "cloud_60"]) == 30
    assert not any(entry["course"] == "cloud_60" and "Deep Dive" in entry["source"]["topic"] for entry in pending.values())


def test_valid_drafts_go_to_the_design_store_and_course_files_never_change(tmp_path, monkeypatch):
    level, compact, designs = _copy_courses(tmp_path, monkeypatch)
    before = {path.name: path.read_bytes() for path in list(level.iterdir()) + list(compact.iterdir())}
    pending = drafts.inventory(["sap", "devops_30"])
    summary = asyncio.run(drafts.run(pending, post=_fake_post(), model="fake", per_course=2, log=_quiet))
    assert summary["accepted"] == 4 and summary["rejected"] == []
    assert {path.name: path.read_bytes() for path in list(level.iterdir()) + list(compact.iterdir())} == before
    saved = json.loads((designs / "sap.json").read_text(encoding="utf-8"))["designs"]
    assert len(saved) == 2 and all(d["origin"] == drafts.ORIGIN for d in saved.values())
    assert len(drafts.inventory(["sap", "devops_30"])) == len(pending) - 4  # a rerun skips saved modules


def test_failing_draft_is_retried_once_then_rejected_and_not_saved(tmp_path, monkeypatch):
    _, _, designs = _copy_courses(tmp_path, monkeypatch)
    pending = drafts.inventory(["sap"])
    first, second = [entry["source"]["topic"] for entry in list(pending.values())[:2]]
    post = _fake_post(bad_topics=[first], always_bad=[second])
    summary = asyncio.run(drafts.run(pending, post=post, model="fake", limit=2, batch_size=2, log=_quiet))
    assert summary["accepted"] == 1
    assert [item["topic"] for item in summary["rejected"]] == [second]
    assert "knowledge-check questions" in " ".join(summary["rejected"][0]["issues"])
    assert len([call for call in post.calls if "fix_these_problems_in_your_previous_draft" in call]) == 2
    saved = json.loads((designs / "sap.json").read_text(encoding="utf-8"))["designs"]
    topics = {key.split("::", 1)[1] for key in saved}
    assert store.place_key(None, first).split("::", 1)[1] in topics
    assert store.place_key(None, second).split("::", 1)[1] not in topics


def test_normalise_fixes_minutes_and_shapes_and_strips_prices():
    source = {"minutes": 420, "topic": "X"}
    design = _good_design()
    for topic in design["topics"]:
        topic["minutes"] += 3  # model arithmetic is off
    normalised = drafts.normalise(design, 420)
    assert sum(t["minutes"] for t in normalised["topics"]) == 420
    assert all(len(row) == 5 for row in normalised["lab_rubric"])
    assert drafts.problems(normalised, source) == []
    design["lab_environment"][0]["cost"] = "About $25 per participant"
    design["lab_environment"][1]["version"] = ""
    design["topics"][0]["mode"] = "Hands-on"
    cleaned = drafts.normalise(design, 420)
    assert cleaned["lab_environment"][0]["cost"] == "Priced in the Lab Cost Estimate"
    assert cleaned["lab_environment"][1]["version"] == drafts.TBC
    assert cleaned["topics"][0]["mode"] == "lab"
    assert drafts.problems(cleaned, source) == []


def test_fatal_provider_error_stops_the_run_and_keeps_saved_work(tmp_path, monkeypatch):
    _copy_courses(tmp_path, monkeypatch)
    pending = drafts.inventory(["sap"])
    good = _fake_post()
    calls = {"n": 0}

    async def post(system, user):
        calls["n"] += 1
        if calls["n"] > 1:
            raise drafts.FatalProviderError("Provider rejected the request (404): model not found")
        return await good(system, user)
    summary = asyncio.run(drafts.run(pending, post=post, model="fake", limit=6, batch_size=3, concurrency=1, log=_quiet))
    assert summary["accepted"] == 3 and "404" in summary["error"]
    assert len(drafts.inventory(["sap"])) == len(pending) - 3


def test_model_choice_prefers_current_flash_over_lite_preview_and_pro():
    names = ["gemini-2.0-flash-lite", "gemini-3.0-pro", "gemini-3.0-flash-preview", "gemini-2.5-flash", "gemini-3.0-flash"]
    assert sorted(names, key=drafts._model_rank)[0] == "gemini-3.0-flash"


def test_model_resolution_follows_the_suggested_replacement_model():
    class Response:
        def __init__(self, status, body):
            self.status_code, self._body = status, body
            self.is_error = status >= 400

        def json(self):
            return self._body

    class Client:
        def __init__(self):
            self.generated = []

        async def get(self, url, headers=None, params=None):
            return Response(200, {"models": [
                {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-2.0-flash-lite", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]}]})

        async def post(self, url, headers=None, json=None):
            model = url.split("/models/")[1].split(":")[0]
            self.generated.append(model)
            if model == "gemini-2.5-flash":
                return Response(404, {"error": {"message": "This model models/gemini-2.5-flash is no longer available to "
                                                           "new users. Please use models/gemini-3.8-flash instead."}})
            return Response(200, {"candidates": []})

    client = Client()
    settings = {"provider": "gemini", "key": "secret", "model": "gemini-2.5-flash"}
    assert asyncio.run(drafts.resolve_model(client, settings)) == "gemini-3.8-flash"
    assert client.generated == ["gemini-2.5-flash", "gemini-3.8-flash"]


def test_course_selection_covers_every_course_once():
    every = drafts.select_courses("all")
    assert set(drafts.DEFAULT_COURSES) <= set(every)
    assert sorted(drafts.select_courses("rest") + list(drafts.DEFAULT_COURSES)) == sorted(every)
    assert "categories" not in every and "combined" not in every


def test_stored_design_reaches_the_generated_toc(tmp_path, monkeypatch):
    level, compact, _ = _copy_courses(tmp_path, monkeypatch)
    pending = drafts.inventory(["sap", "devops_30"])
    asyncio.run(drafts.run(pending, post=_fake_post(), model="fake", log=_quiet))
    import app.level_curriculum as lc
    import app.toc_domain_dataset as tdd
    from app.toc_generation_agent import generate_toc_from_dataset, validate_toc
    monkeypatch.setattr(lc, "_DIR", level)
    monkeypatch.setattr(lc, "_COURSES", None)
    sap = validate_toc(generate_toc_from_dataset("SAP", 5), 5)
    assert all((day.get("design") or {}).get("origin") == drafts.ORIGIN for day in sap["days"])
    assert sap["quality"]["status"] == "approved"
    monkeypatch.setattr(tdd, "COMPACT_DOMAINS", {})
    monkeypatch.setattr(tdd, "COMPACT_DOMAIN_VARIANTS", {})
    monkeypatch.setattr(tdd, "_COMPACT_DATASET_PATH", str(compact))
    devops = validate_toc(generate_toc_from_dataset("DevOps", 10), 10)
    origins = {(day.get("design") or {}).get("origin") for day in devops["days"]}
    assert drafts.ORIGIN in origins
    docker = next(day for day in devops["days"] if day.get("focus_area") == "Docker Fundamentals")
    assert (docker.get("outline") or {}).get("design")  # the authored design stays on the outline


def test_inline_designs_from_earlier_runs_move_to_the_store(tmp_path, monkeypatch):
    level, _, designs = _copy_courses(tmp_path, monkeypatch)
    original = (level / "sap.json").read_text(encoding="utf-8")
    document = json.loads(original)
    day = document["levels"]["beginner"]["days"][0]
    lines = original.split("\n")
    marker = '"topic": ' + json.dumps(day["topic"], ensure_ascii=False)
    topic_line = next(i for i, line in enumerate(lines) if line.strip().startswith(marker))
    closing = next(i for i in range(topic_line, len(lines)) if lines[i].strip() in ("}", "},"))
    lines[closing - 1] += ","
    lines.insert(closing, "          " + '"design": ' + json.dumps({**_good_design(), "origin": drafts.ORIGIN}))
    (level / "sap.json").write_text("\n".join(lines), encoding="utf-8")

    assert drafts.migrate_inline(["sap"]) == 1
    assert (level / "sap.json").read_text(encoding="utf-8") == original
    saved = json.loads((designs / "sap.json").read_text(encoding="utf-8"))["designs"]
    assert list(saved) == [store.place_key("beginner", day["topic"])]


def test_time_limit_stops_new_batches_and_keeps_finished_ones(tmp_path, monkeypatch):
    _copy_courses(tmp_path, monkeypatch)
    import time
    clock = {"now": 0.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["now"])
    good = _fake_post()

    async def post(system, user):
        clock["now"] += 120  # each request takes two minutes
        return await good(system, user)
    pending = drafts.inventory(["sap"])
    summary = asyncio.run(drafts.run(pending, post=post, model="fake", limit=9, batch_size=3, concurrency=1,
                                     max_minutes=3, log=_quiet))
    assert summary["accepted"] == 6 and summary["stopped_at_time_limit"]
