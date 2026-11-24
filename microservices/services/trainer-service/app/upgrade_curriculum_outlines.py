"""Clean curriculum datasets and attach course outlines to reference modules.

    python -m app.upgrade_curriculum_outlines            # report only
    python -m app.upgrade_curriculum_outlines --write    # update the files

For every compact dataset day that is not manually authored:
  * remove legacy filler subtopics ("<Domain> terminology and feature mapping
    for this topic", generator padding such as "Terminology and scope");
  * remove items copied onto most days of the course (for example the same
    tool list on every day), keeping them on the first day that uses them.

For every reference module with imported PDF text, store a parsed
``outline`` (topic groups, sub-topics, principle, lab, deliverables).

Lab, deliverable, assessment and delivery steps are left in place because
delivery gates require them; the PDF leaves template wording out instead.
The script is idempotent and never changes review status.
"""

import argparse
import json
from pathlib import Path

from app.course_outline import OUTLINE_VERSION, clean_subtopics, outline_from_reference, repeated_items

ROOT = Path(__file__).parent


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, document) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clean_document(document) -> dict:
    """Clean one compact dataset in place and return what changed."""
    days = [day for day in document.get("days") or [] if isinstance(day, dict)]
    repeated = repeated_items(days)
    stats = {"days": len(days), "days_changed": 0, "subtopics_removed": 0}
    for index, day in enumerate(days):
        if day.get("content_quality_stage"):
            continue  # manually authored or pilot content stays exactly as written
        before = list(day.get("subtopics") or [])
        drop = [item for item, first_day in repeated.items() if first_day != index]
        after = clean_subtopics(before, drop)
        if len(after) < 3:
            after = clean_subtopics(before)
        if after != before:
            day["subtopics"] = after
            stats["days_changed"] += 1
            stats["subtopics_removed"] += len(before) - len(after)
    if stats["days_changed"]:
        document["content_cleanup_version"] = OUTLINE_VERSION
    return stats


def outline_document(document) -> int:
    """Attach parsed outlines to reference modules in place; return the count."""
    count = 0
    for module in document.get("modules") or []:
        if not isinstance(module, dict) or not module.get("reference_text"):
            continue
        outline = outline_from_reference(module["reference_text"])
        outline["version"] = OUTLINE_VERSION
        if module.get("outline") != outline:
            module["outline"] = outline
            count += 1
    return count


def run(root: Path = ROOT, write: bool = False) -> dict:
    report = {"compact_files": 0, "compact_files_changed": 0, "days": 0, "days_changed": 0,
              "subtopics_removed": 0, "reference_outlines": 0}
    for path in sorted((root / "datasets_compact").glob("*.json")):
        document = _read(path)
        stats = clean_document(document)
        report["compact_files"] += 1
        for key in ("days", "days_changed", "subtopics_removed"):
            report[key] += stats[key]
        if stats["days_changed"]:
            report["compact_files_changed"] += 1
            if write:
                _write(path, document)
    for path in sorted((root / "reference_curricula").glob("*.json")):
        document = _read(path)
        changed = outline_document(document)
        report["reference_outlines"] += changed
        if changed and write:
            _write(path, document)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true", help="update the dataset files")
    args = parser.parse_args()
    print(json.dumps(run(write=args.write), indent=2))


if __name__ == "__main__":
    main()
