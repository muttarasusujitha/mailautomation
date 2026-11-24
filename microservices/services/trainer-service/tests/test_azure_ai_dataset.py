import json
from pathlib import Path

from app.toc_generation_agent import _subtopic_target, generate_toc_from_dataset, validate_toc

APP = Path(__file__).resolve().parents[1] / "app"


def test_azure_ai_level_dataset_loads_and_meets_subtopic_targets():
    document = json.loads((APP / "datasets_levels" / "azure_ai.json").read_text(encoding="utf-8"))
    assert set(document["levels"]) == {"beginner", "intermediate", "advanced"}
    for level in document["levels"].values():
        assert len(level["days"]) >= 12
        for day in level["days"]:
            assert len(day["subtopics"]) >= _subtopic_target(day["topic"]), day["topic"]
            assert len(day["checks"]) == 3 and all(len(ch) == 3 for ch in day["checks"])
            assert day["lab_task"] and day["deliverable"] and day["objectives"]


def test_azure_ai_generates_specific_content_from_the_level_dataset():
    toc = validate_toc(generate_toc_from_dataset("Azure AI", 10), 10)
    assert (toc.get("agent") or {}).get("source") == "level_dataset"
    assert toc["quality"]["status"] == "approved"
    labs = " ".join((day.get("lab_task") or day.get("lab") or "") for day in toc["days"]).lower()
    assert "azure basics" not in labs
    assert any(term in labs for term in ("rag", "azure ai search", "content safety", "groundedness", "azure openai", "managed-identity"))


def test_azure_ai_aliases_use_the_level_dataset():
    for alias in ("Azure OpenAI", "AI-102", "Azure AI Foundry"):
        toc = validate_toc(generate_toc_from_dataset(alias, 8), 8)
        assert (toc.get("agent") or {}).get("source") == "level_dataset", alias
