import io

import openpyxl

from app.routes.excel import _toc_to_excel

SAMPLE = {
    "title": "DevOps Mastery", "domain": "DevOps", "level": "intermediate", "mode": "Offline",
    "hours_per_day": 7, "tools_software": ["Docker", "Kubernetes"],
    "days": [
        {"day": 1, "date": "2026-11-23", "focus_area": "DevOps Orientation", "minutes": 420,
         "subtopics": ["DevOps lifecycle", "CI/CD"], "lab_task": "Delivery Workflow: map a feature to a release decision.",
         "scenario": "A team has no shared definition of done.", "deliverable": "Workflow board and checklist",
         "learning_objectives": ["Distinguish deployment from release-readiness"],
         "acceptance_checks": [{"input_or_condition": "Delete one pod", "expected_result": "A replacement pod is created"}]},
        {"day": 2, "date": "2026-11-24", "focus_area": "Linux Fundamentals", "minutes": 420,
         "subtopics": ["Filesystems", "Permissions"], "lab_task": "Inspect a Linux environment and plan a safe log archive.",
         "deliverable": "Archive plan", "learning_objectives": ["Navigate a Linux host safely"]},
        {"day": 3, "date": "2026-11-25", "focus_area": "Capstone Project", "minutes": 420,
         "subtopics": ["Design", "Build", "Demo"], "lab_task": "Capstone: ship a change from commit to production.",
         "deliverable": "Live demo and evidence"},
    ],
}


def _workbook(toc):
    return openpyxl.load_workbook(io.BytesIO(_toc_to_excel({**toc, "excel_layout": "course_workbook"})))


def test_workbook_has_the_six_specified_sheets_in_order():
    wb = _workbook(SAMPLE)
    assert wb.sheetnames == ["Contents", "Course Overview", "Course Outline",
                             "Labs & Deliverables", "Day-wise Schedule", "Assessment"]


def test_single_day_course_omits_the_day_wise_schedule():
    one = {**SAMPLE, "days": SAMPLE["days"][:1]}
    assert "Day-wise Schedule" not in _workbook(one).sheetnames


def test_course_outline_headers_rows_and_total_formula():
    ws = _workbook(SAMPLE)["Course Outline"]
    header = next(r for r in range(1, 8) if ws.cell(r, 1).value == "Module No.")
    assert [ws.cell(header, c).value for c in range(1, 8)] == \
        ["Module No.", "Module Name", "Day", "Duration (hrs)", "Topics Covered", "Lab Reference", "Participant Output"]
    assert ws.cell(header + 1, 2).value == "DevOps Orientation"
    assert ws.cell(header + 1, 4).value == 7
    assert ws.cell(header + 1, 6).value == "Lab 1"
    total = ws.cell(header + len(SAMPLE["days"]) + 1, 4).value
    assert isinstance(total, str) and total.startswith("=SUM(")


def test_course_overview_reads_the_total_from_course_outline():
    ws = _workbook(SAMPLE)["Course Overview"]
    label = next(r for r in range(1, 12) if ws.cell(r, 1).value == "Duration (hours)")
    value = ws.cell(label, 2).value
    assert isinstance(value, str) and value.startswith("=") and "'Course Outline'!" in value


def test_labs_sheet_uses_module_no_as_the_shared_key_and_never_writes_formulas():
    ws = _workbook(SAMPLE)["Labs & Deliverables"]
    header = next(r for r in range(1, 8) if ws.cell(r, 1).value == "Lab No.")
    assert [ws.cell(header, c).value for c in range(1, 8)] == \
        ["Lab No.", "Lab Name", "Module No.", "Scenario", "Tasks Participants Do", "Deliverable", "Success Measure"]
    assert ws.cell(header + 1, 3).value == 1  # Module No. shared key

    injected = _workbook({**SAMPLE, "days": [{**SAMPLE["days"][0], "deliverable": "=HYPERLINK(\"http://x\")"}]})
    outline = injected["Course Outline"]
    row = next(r for r in range(1, 10) if outline.cell(r, 1).value == 1)
    assert outline.cell(row, 7).data_type == "s"


def test_assessment_weights_sum_to_one_hundred():
    ws = _workbook(SAMPLE)["Assessment"]
    header = next(r for r in range(1, 8) if ws.cell(r, 1).value == "Assessment Item")
    weights = []
    r = header + 1
    while isinstance(ws.cell(r, 2).value, (int, float)):
        weights.append(ws.cell(r, 2).value)
        r += 1
    assert sum(weights) == 100
