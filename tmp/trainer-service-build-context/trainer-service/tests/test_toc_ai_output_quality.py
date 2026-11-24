"""AI output must pass validation before replacing a curriculum day's text."""
import asyncio
from copy import deepcopy

import pytest

from app.routes import toc


def day():
    return {
        "tools": "Docker",
        "subtopics": "images and containers",
        "lab": "Build a Docker image",
        "learning_objectives": ["Original curriculum objective"],
    }


def valid_result():
    return {
        "learning_outcomes": [
            "Build a Docker image.",
            "Run a Docker container.",
            "Inspect Docker image layers.",
        ],
        "hands_on_summary": "Build a Docker image and run its container.",
    }


@pytest.mark.parametrize("result", [
    ["unexpected response"],
    {"learning_outcomes": "abc", "hands_on_summary": "Docker"},
    {"learning_outcomes": [None, 42, "Docker"], "hands_on_summary": "Docker"},
    {"learning_outcomes": ["Docker", "containers", "images"], "hands_on_summary": {"text": "Docker"}},
    {"learning_outcomes": ["Docker", "containers", "!!!"], "hands_on_summary": "Docker"},
    {"learning_outcomes": ["Docker", "containers", "images"], "hands_on_summary": "!!!"},
])
def test_malformed_output_is_rejected(result):
    assert not toc._daily_enrichment_is_specific(result, day(), [])


def test_repeated_outcome_with_different_punctuation_is_rejected():
    result = valid_result()
    result["learning_outcomes"][1] = "BUILD A DOCKER IMAGE!"
    assert not toc._daily_enrichment_is_specific(result, day(), [])


def test_specific_output_is_accepted_but_cross_day_repetition_is_rejected():
    result = valid_result()
    assert toc._daily_enrichment_is_specific(result, day(), [])
    assert not toc._daily_enrichment_is_specific(result, day(), ["build a docker image"])


def test_bad_day_preserves_curriculum_without_discarding_good_day(monkeypatch):
    original = day()
    curriculum = {"domain": "Docker", "days": [deepcopy(original), deepcopy(original)]}
    curriculum["days"][0]["day"] = 1
    curriculum["days"][1]["day"] = 2

    async def generate(client, model, domain, current_day):
        return ["malformed"] if current_day["day"] == 1 else valid_result()

    monkeypatch.setattr(toc, "_generate_ai_day_enrichment", generate)
    count = asyncio.run(toc._enrich_toc_days_with_ai(object(), "test-model", curriculum))
    assert count == curriculum["ai_enriched_days"] == 1
    assert curriculum["days"][0]["lab"] == original["lab"]
    assert curriculum["days"][0]["learning_objectives"] == original["learning_objectives"]
    assert curriculum["days"][1]["learning_objectives"] == valid_result()["learning_outcomes"]
