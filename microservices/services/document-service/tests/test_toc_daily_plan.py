import io

import openpyxl

from app.routes.excel import _toc_to_excel


def _workbook(toc):
    return openpyxl.load_workbook(io.BytesIO(_toc_to_excel({**toc, "excel_layout": "daily_plan"})))


def test_daily_plan_is_one_clean_sheet_with_header_and_day_rows():
    wb = _workbook({
        "title": "DevOps Mastery", "domain": "DevOps", "level": "intermediate",
        "mode": "Offline", "hours_per_day": 7,
        "days": [
            {"day": 1, "date": "2026-11-23", "focus_area": "DevOps Orientation",
             "subtopics": ["DevOps lifecycle", "CI/CD"], "lab_task": "Map a feature to a release decision."},
            {"day": 2, "date": "2026-11-24", "focus_area": "Linux Fundamentals",
             "subtopics": ["Filesystems", "Permissions"], "lab_task": "Plan a safe log archive."},
        ],
    })
    assert len(wb.worksheets) == 1
    ws = wb.active
    assert ws.title == "Daily Plan"
    assert "DevOps" in str(ws["A1"].value) and "Training TOC" in str(ws["A1"].value)
    summary = str(ws["A2"].value)
    for part in ("2 days", "14 planned hours", "Intermediate", "Offline"):
        assert part in summary

    header_row = next(r for r in range(1, 12) if ws.cell(r, 1).value == "Day")
    assert [ws.cell(header_row, col).value for col in range(1, 6)] == \
        ["Day", "Date", "Topic", "Topics Covered", "Hands-on Lab"]

    assert ws.cell(header_row + 1, 1).value == 1
    assert ws.cell(header_row + 1, 2).value == "23 Nov 2026"
    assert ws.cell(header_row + 1, 3).value == "DevOps Orientation"
    assert ws.cell(header_row + 1, 4).value == "DevOps lifecycle, CI/CD"
    assert ws.cell(header_row + 1, 5).value == "Map a feature to a release decision."
    assert ws.cell(header_row + 2, 3).value == "Linux Fundamentals"


def test_daily_plan_notes_a_proposed_breakdown_and_never_writes_formulas():
    wb = _workbook({
        "title": "DevOps", "hours_per_day": 7,
        "days": [{"day": 1, "date": "2026-11-23", "focus_area": "=HYPERLINK(\"http://x\")",
                  "subtopics": ["A"], "lab_task": "Do X", "proposed_fields": ["delivery_steps"]}],
    })
    ws = wb.active
    note = " ".join(str(cell.value) for row in ws.iter_rows() for cell in row if cell.value)
    assert "proposed and should be reviewed by a trainer" in note
    topic_row = next(r for r in range(1, 12) if ws.cell(r, 1).value == 1)
    assert ws.cell(topic_row, 3).data_type == "s"
