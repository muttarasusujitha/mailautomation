"""Dependency-light Linux smoke test; no API, database or email connections."""
import json
import platform
from app.scoped_curriculum import select_requested_curriculum
from app.toc_generation_agent import generate_toc_from_dataset
from app.toc_evaluation import evaluate_toc


def main():
    results = []
    for domain in ("Python", "Java", "DevOps", "Power BI", "Agentic AI"):
        for level, count in (("beginner", 2), ("intermediate", 5), ("advanced", 10)):
            toc = generate_toc_from_dataset(domain, count, level=level)
            assert len(toc["days"]) == count, (domain, level)
            evaluation = evaluate_toc(toc, requested_days=count, hours_per_day=4)
            assert evaluation["technical_accuracy_verified"] is False
            results.append({"domain": domain, "level": level, "days": count, "status": evaluation["status"]})
    selected = []
    for objective in ("Pandas", "FastAPI"):
        source = select_requested_curriculum("Python", objective)
        assert source
        toc = generate_toc_from_dataset("Python", 1, domain_override=source)
        assert objective.lower() in str(toc["days"][0]).lower()
        selected.append(toc["days"][0]["focus_area"])
    assert selected[0] != selected[1]
    print(json.dumps({"platform": platform.system(), "generation_cases": results,
                      "objective_selection": selected, "smoke_checks": "passed",
                      "note": "Execution and scope checks only; content review remains required"}, indent=2))


if __name__ == "__main__":
    main()
