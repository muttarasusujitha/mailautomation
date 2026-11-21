import asyncio
import json
import shutil
from copy import deepcopy
from pathlib import Path

import app.draft_module_designs as drafts

APP = Path(__file__).resolve().parents[1] / "app"


def _copy_courses(tmp_path, monkeypatch):
    level, compact = tmp_path / "levels", tmp_path / "compact"
    level.mkdir()
    compact.mkdir()
    shutil.copy(APP / "datasets_levels" / "sap.json", level / "sap.json")
    shutil.copy(APP / "datasets_compact" / "devops_30.json", compact / "devops_30.json")
    monkeypatch.setattr(drafts, "LEVEL_DIR", level)
    monkeypatch.setattr(drafts, "COMPACT_DIR", compact)
    return level, compact


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


def test_inventory_skips_modules_that_already_have_a_design(tmp_path, monkeypatch):
    _copy_courses(tmp_path, monkeypatch)
    pending = drafts.inventory(["sap", "devops_30"])
    topics = {entry["source"]["topic"] for entry in pending.values()}
    assert "Docker Fundamentals" not in topics  # authored design in its outline
    assert sum(entry["course"] == "devops_30" for entry in pending.values()) == 29


def test_valid_drafts_are_saved_into_level_and_compact_files(tmp_path, monkeypatch):
    level, compact = _copy_courses(tmp_path, monkeypatch)
    before_level = json.loads((level / "sap.json").read_text(encoding="utf-8"))
    pending = drafts.inventory(["sap", "devops_30"])
    summary = asyncio.run(drafts.run(pending, post=_fake_post(), model="fake", per_course=2, log=lambda *a, **k: None))
    assert summary["accepted"] == 4 and summary["rejected"] == []

    after_level = json.loads((level / "sap.json").read_text(encoding="utf-8"))
    designed = [day for track in after_level["levels"].values() for day in track["days"] if "design" in day]
    assert designed and all(day["design"]["origin"] == drafts.ORIGIN for day in designed)
    # Only "design" keys were added; every other value in the file is unchanged.
    for track in after_level["levels"].values():
        for day in track["days"]:
            day.pop("design", None)
    assert after_level == before_level

    compact_doc = json.loads((compact / "devops_30.json").read_text(encoding="utf-8"))
    assert sum("design" in day for day in compact_doc["days"]) == 2
    # A rerun does not redraft saved modules.
    assert len(drafts.inventory(["sap", "devops_30"])) == len(pending) - 4


def test_failing_draft_is_retried_once_then_rejected_and_not_saved(tmp_path, monkeypatch):
    level, _ = _copy_courses(tmp_path, monkeypatch)
    pending = drafts.inventory(["sap"])
    first, second = [entry["source"]["topic"] for entry in list(pending.values())[:2]]
    post = _fake_post(bad_topics=[first], always_bad=[second])
    summary = asyncio.run(drafts.run(pending, post=post, model="fake", limit=2, batch_size=2, log=lambda *a, **k: None))
    assert summary["accepted"] == 1
    assert [item["topic"] for item in summary["rejected"]] == [second]
    assert "knowledge-check questions" in " ".join(summary["rejected"][0]["issues"])
    retries = [call for call in post.calls if "fix_these_problems_in_your_previous_draft" in call]
    assert len(retries) == 2
    saved = [day["topic"] for track in json.loads((level / "sap.json").read_text(encoding="utf-8"))["levels"].values()
             for day in track["days"] if "design" in day]
    assert first in saved and second not in saved


def test_normalise_fixes_minutes_and_rubric_shape_and_rejects_prices():
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
    summary = asyncio.run(drafts.run(pending, post=post, model="fake", limit=6, batch_size=3, concurrency=1,
                                     log=lambda *a, **k: None))
    assert summary["accepted"] == 3 and "404" in summary["error"]
    assert len(drafts.inventory(["sap"])) == len(pending) - 3


def test_model_choice_prefers_current_flash_over_lite_preview_and_pro():
    names = ["gemini-2.0-flash-lite", "gemini-3.0-pro", "gemini-3.0-flash-preview", "gemini-2.5-flash", "gemini-3.0-flash"]
    assert sorted(names, key=drafts._model_rank)[0] == "gemini-3.0-flash"


def test_saved_design_reaches_the_generated_toc(tmp_path, monkeypatch):
    level, _ = _copy_courses(tmp_path, monkeypatch)
    pending = drafts.inventory(["sap"])
    asyncio.run(drafts.run(pending, post=_fake_post(), model="fake", log=lambda *a, **k: None))
    import app.level_curriculum as lc
    from app.toc_generation_agent import generate_toc_from_dataset, validate_toc
    monkeypatch.setattr(lc, "_DIR", level)
    monkeypatch.setattr(lc, "_COURSES", None)
    toc = validate_toc(generate_toc_from_dataset("SAP", 5), 5)
    assert all((day.get("design") or {}).get("origin") == drafts.ORIGIN for day in toc["days"])
    assert toc["quality"]["status"] == "approved"


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
