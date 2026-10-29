"""Apply explicitly authored Python exercises; no model calls or approval claims."""
import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).parent
STAGE = "manually_authored_pending_lab_validation"


def run():
    authored = json.loads((ROOT / "manual_python_content.json").read_text(encoding="utf-8"))
    mapping = {row[0]: row for row in authored}
    changed, files = 0, []
    for path in sorted((ROOT / "datasets_compact").glob("python*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        count = 0
        for module in document.get("days", []):
            if module.get("topic") not in mapping:
                continue
            title, scenario, lab, output, checks, prerequisites = mapping[module["topic"]]
            if module.get("content_quality_stage") == "authored_pilot_pending_lab_validation":
                continue
            module.setdefault("content_before_manual_rewrite", deepcopy(module))
            module.update(scenario=scenario, lab=lab, lab_task=lab, deliverable=output,
                          learning_objectives=checks[:2], assessment="\n".join(checks),
                          prerequisites=[prerequisites], content_quality_stage=STAGE,
                          review_status="unreviewed", content_enrichment_version="manual-python-v1")
            module["acceptance_checks"] = checks
            module["preparation_requirements"] = [
                "Prepare the application or data fixture specified in this lab: " + lab,
                "Verify these expected results before teaching: " + "; ".join(checks),
                "Confirm installed tool versions and allocate activity times for the participant level",
            ]
            module["delivery_steps"] = [
                {"method": "Trainer demonstration", "minutes": None,
                 "activity": scenario + " Trace the first acceptance case: " + checks[0],
                 "evidence": "Annotated baseline result for: " + checks[0]},
                {"method": "Guided implementation", "minutes": None,
                 "activity": lab, "evidence": output},
                {"method": "Independent validation", "minutes": None,
                 "activity": checks[1], "evidence": "Recorded inputs and observed result for: " + checks[1]},
                {"method": "Assessment and explanation", "minutes": None,
                 "activity": checks[2], "evidence": "Participant demonstration and explanation of: " + checks[2]},
            ]
            module["delivery_basis"] = "Manually authored activities; timings and lab execution remain to be validated"
            module["proposed_fields"] = ["scenario", "lab", "deliverable", "learning_objectives", "assessment",
                "acceptance_checks", "prerequisites", "preparation_requirements", "delivery_steps"]
            module["source_verification"] = "Exercise is manually authored, not a claim of full technical or lab verification"
            # These links were inspected during this batch. Do not attach unrelated
            # docs or mark a whole exercise verified merely because a link exists.
            sources = {
                "Python Basics": "https://docs.python.org/3/tutorial/",
                "Control Flow & Functions": "https://docs.python.org/3/tutorial/",
                "Data Structures": "https://docs.python.org/3/tutorial/",
                "Object-Oriented Programming": "https://docs.python.org/3/tutorial/",
                "Modules & Packages": "https://docs.python.org/3/tutorial/",
                "Testing & TDD": "https://docs.djangoproject.com/en/5.2/topics/testing/",
                "FastAPI Basics": "https://fastapi.tiangolo.com/tutorial/",
                "Machine Learning Basics": "https://scikit-learn.org/stable/modules/cross_validation.html",
            }
            if title in sources:
                module["source_urls"] = list(dict.fromkeys([*module.get("source_urls", []), sources[title]]))
            count += 1
        if count:
            path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            changed += count
            files.append({"file": path.name, "entries": count})
    preview = ["# Manually authored Python TOC content", "",
        "29 distinct modules. Applied only to exact topic matches in Python datasets. Original source subtopics are retained; these exercises do not establish mastery of every subtopic. Lab assets, timings and technical review remain pending.", ""]
    for title, scenario, lab, output, checks, prerequisites in authored:
        preview.extend(["## " + title, "", "**Prerequisites:** " + prerequisites, "", "**Scenario:** " + scenario,
            "", "**Lab:** " + lab, "", "**Participant output:** " + output, "", "**Acceptance checks:**", ""])
        preview.extend("- " + check for check in checks)
        preview.append("")
    (ROOT.parents[4] / "MANUAL_PYTHON_CONTENT_REVIEW.md").write_text("\n".join(preview), encoding="utf-8")
    print(json.dumps({"distinct_authored_modules": len(authored), "updated_entries": changed, "files": files}))


if __name__ == "__main__":
    run()
