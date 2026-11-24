"""Run repeatable manual TOC evaluation scenarios and write a local report."""
import json
from pathlib import Path
from app.curriculum_reasoning import builtin_records
from app.toc_evaluation import catalog_summary, evaluate_toc
from app.toc_generation_agent import generate_toc_from_dataset

SCENARIOS = [
    {"domain": "Python", "days": 5, "level": "beginner", "required_topics": ["Python"]},
    {"domain": "DevOps", "days": 5, "level": "intermediate", "required_topics": ["DevOps"]},
    {"domain": "Power BI", "days": 5, "level": "beginner", "required_topics": ["Power BI"]},
    {"domain": "Agentic AI", "days": 5, "level": "intermediate", "required_topics": ["Agentic"]},
    {"domain": "Java", "days": 5, "level": "beginner", "required_topics": ["Java"]},
]


def main():
    results = []
    for scenario in SCENARIOS:
        toc = generate_toc_from_dataset(scenario["domain"], scenario["days"], level=scenario["level"])
        results.append({"scenario": scenario, "evaluation": evaluate_toc(toc, scenario["required_topics"], scenario["days"])})
    report = {"manual_toc_scenarios": results, "dataset": catalog_summary(builtin_records()),
              "limitations": ["This checks structure and evidence fields, not technical correctness of every claim.",
                              "Run generated labs with a subject-matter trainer before client delivery.",
                              "LLM evaluation requires a funded API and separate prompt/output tests."]}
    output = Path(__file__).parents[4] / "TOC_EVALUATION_REPORT.json"
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
