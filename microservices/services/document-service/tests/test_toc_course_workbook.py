import io

import openpyxl

from app.routes.excel import _toc_to_excel

DESIGN = {
    "outcomes": [
        {"outcome": "Build a multi-stage image", "assessed_by": "Lab check: image sizes"},
        {"outcome": "Run a container with a volume", "assessed_by": "Lab checks: file listing"},
        {"outcome": "Fix a failing container", "assessed_by": "Seeded-failure troubleshooting"},
    ],
    "topics": [
        {"topic": "Images and layers", "subtopics": ["Layers", "Build cache"], "minutes": 90, "mode": "discussion",
         "failure_scenario": "Dependencies reinstall on every build", "best_practice": "Copy the lock file first"},
        {"topic": "Demo: multi-stage build", "subtopics": ["Builder stage"], "minutes": 60, "mode": "demo",
         "failure_scenario": "", "best_practice": "No build tools at runtime"},
        {"topic": "Lab: Containerise a Web Application", "subtopics": ["Write a Dockerfile"], "minutes": 150, "mode": "lab",
         "failure_scenario": "", "best_practice": ""},
        {"topic": "Troubleshooting the seeded failure", "subtopics": ["Check docker logs"], "minutes": 60, "mode": "lab",
         "failure_scenario": "App listens on 127.0.0.1", "best_practice": "Bind to 0.0.0.0"},
        {"topic": "Knowledge check and recap", "subtopics": ["Quiz"], "minutes": 60, "mode": "discussion",
         "failure_scenario": "", "best_practice": ""},
    ],
    "seeded_failure": {"symptom": "The published port does not respond.", "cause": "Binds to 127.0.0.1", "fix": "Bind to 0.0.0.0"},
    "quiz": ["What is a layer?", "CMD or ENTRYPOINT?", "What does exit code 137 mean?", "Volume or bind mount?", "Why non-root?"],
    "lab_rubric": [["Image build", "Excellent", "Good", "Partial", "Missing"]],
    "lab_environment": [{"tool": "Docker Engine", "version": "24.0 or later", "access": "Linux VM",
                         "setup_owner": "Trainer", "cost": "No licence cost"}],
}

SAMPLE = {
    "title": "DevOps Mastery", "domain": "DevOps", "level": "intermediate", "mode": "Offline",
    "hours_per_day": 7, "participant_count": 12, "tools_software": ["Docker", "Kubernetes", "All DevOps Tools"],
    "certification_roadmap": ["Certified Kubernetes Administrator (CKA)"],
    "days": [
        {"day": 1, "date": "2026-11-23", "focus_area": "DevOps Orientation", "minutes": 420,
         "subtopics": ["DevOps lifecycle", "CI/CD"], "lab_task": "Delivery Workflow: map a feature to a release decision.",
         "scenario": "A team has no shared definition of done.", "deliverable": "Workflow board and checklist",
         "learning_objectives": ["Distinguish deployment from release-readiness"],
         "acceptance_checks": [{"input_or_condition": "Delete one pod", "expected_result": "A replacement pod is created"}]},
        {"day": 2, "date": "2026-11-24", "focus_area": "Docker Fundamentals", "minutes": 420,
         "subtopics": ["Images", "Dockerfiles"], "lab_task": "Containerise a Web Application: write a Dockerfile.",
         "deliverable": "Dockerfile", "learning_objectives": ["Write Dockerfiles"],
         "outline": {"lab": {"title": "Containerise a Web Application", "tasks": ["Write a Dockerfile", "Push the image"]},
                     "design": DESIGN}},
        {"day": 3, "date": "2026-11-25", "focus_area": "Capstone Project", "minutes": 420,
         "subtopics": ["Design", "Build", "Demo"], "lab_task": "Capstone: ship a change from commit to production.",
         "deliverable": "Live demo and evidence"},
    ],
}

SHEETS = ["Contents", "Course Overview", "Course Outline", "Module Outcomes", "Topic Breakdown",
          "Labs & Deliverables", "Day-wise Schedule", "Assessment", "Lab Environment", "Trainer & Support"]


def _workbook(toc):
    return openpyxl.load_workbook(io.BytesIO(_toc_to_excel({**toc, "excel_layout": "course_workbook"})))


def _header_row(ws, first_header):
    return next(r for r in range(1, 10) if ws.cell(r, 1).value == first_header)


def _rows(ws, header, ncols):
    rows, r = [], header + 1
    while ws.cell(r, 1).value is not None:
        rows.append([ws.cell(r, c).value for c in range(1, ncols + 1)])
        r += 1
    return rows


def _all_text(ws):
    return [ws.cell(r, c).value for r in range(1, 120) for c in range(1, 8) if ws.cell(r, c).value is not None]


def test_workbook_has_the_ten_sheets_in_order():
    assert _workbook(SAMPLE).sheetnames == SHEETS


def test_single_day_course_omits_the_day_wise_schedule():
    one = {**SAMPLE, "days": SAMPLE["days"][:1]}
    assert _workbook(one).sheetnames == [name for name in SHEETS if name != "Day-wise Schedule"]


def test_course_outline_headers_rows_and_total_formula():
    ws = _workbook(SAMPLE)["Course Outline"]
    header = _header_row(ws, "Module No.")
    assert [ws.cell(header, c).value for c in range(1, 8)] == \
        ["Module No.", "Module Name", "Day", "Duration (hrs)", "Topics Covered", "Lab Reference", "Participant Output"]
    assert ws.cell(header + 1, 2).value == "DevOps Orientation"
    assert ws.cell(header + 1, 4).value == 7
    assert ws.cell(header + 1, 6).value == "Lab 1"
    total = ws.cell(header + len(SAMPLE["days"]) + 1, 4).value
    assert isinstance(total, str) and total.startswith("=SUM(")


def test_course_overview_reads_the_total_and_lists_level_and_certifications():
    ws = _workbook(SAMPLE)["Course Overview"]
    labels = {ws.cell(r, 1).value: ws.cell(r, 2).value for r in range(4, 16)}
    assert str(labels["Duration (hours)"]).startswith("='Course Outline'!")
    assert labels["Level"] == "Intermediate"
    assert labels["Target Certifications"] == "Certified Kubernetes Administrator (CKA)"


def test_module_outcomes_use_the_design_and_fall_back_to_objectives():
    ws = _workbook(SAMPLE)["Module Outcomes"]
    header = _header_row(ws, "Module No.")
    assert [ws.cell(header, c).value for c in range(1, 4)] == ["Module No.", "Outcome", "Assessed By"]
    rows = _rows(ws, header, 3)
    assert [1, "Distinguish deployment from release-readiness", "Lab 1 checks"] in rows
    # Authored "Lab check" references are numbered for the module's position.
    assert [2, "Build a multi-stage image", "Lab 2 check: image sizes"] in rows
    assert len([row for row in rows if row[0] == 2]) == 3


def test_topic_breakdown_uses_the_design_and_the_standard_split():
    ws = _workbook(SAMPLE)["Topic Breakdown"]
    header = _header_row(ws, "Module No.")
    assert [ws.cell(header, c).value for c in range(1, 8)] == \
        ["Module No.", "Topic", "Sub-topics", "Minutes", "Mode", "Failure Scenario", "Best Practice"]
    rows = _rows(ws, header, 7)
    docker = [row for row in rows if row[0] == 2]
    assert docker[0][1:] == ["Images and layers", "Layers\nBuild cache", 90, "discussion",
                             "Dependencies reinstall on every build", "Copy the lock file first"]
    assert docker[2][1] == "Lab 2: Containerise a Web Application"
    assert sum(row[3] for row in docker) == 420
    standard = [row for row in rows if row[0] == 1]
    assert [row[1] for row in standard][-2:] == ["Troubleshooting a seeded failure", "Knowledge check and recap"]
    assert [row[3] for row in standard] == [90, 60, 150, 60, 60]
    assert sum(row[3] for row in rows if row[0] == 3) == 420  # capstone split


def test_labs_sheet_shows_the_seeded_failure_symptom_but_not_the_answer():
    ws = _workbook(SAMPLE)["Labs & Deliverables"]
    header = _header_row(ws, "Lab No.")
    assert [ws.cell(header, c).value for c in range(1, 8)] == \
        ["Lab No.", "Lab Name", "Module No.", "Scenario", "Tasks Participants Do", "Deliverable", "Success Measure"]
    tasks = ws.cell(header + 2, 5).value
    assert "Troubleshoot the seeded failure: The published port does not respond." in tasks
    assert "0.0.0.0" not in tasks and "127.0.0.1" not in tasks

    injected = _workbook({**SAMPLE, "days": [{**SAMPLE["days"][0], "deliverable": "=HYPERLINK(\"http://x\")"}]})
    outline = injected["Course Outline"]
    row = next(r for r in range(1, 10) if outline.cell(r, 1).value == 1)
    assert outline.cell(row, 7).data_type == "s"


def test_day_wise_schedule_follows_the_theory_lab_assessment_split():
    ws = _workbook(SAMPLE)["Day-wise Schedule"]
    header = _header_row(ws, "Day")
    rows = _rows(ws, header, 6)
    # Lab time matches the 4 priced lab-access hours of a 7-hour day (shared.lab_cost_inputs).
    assert [row[1:3] + row[5:] for row in rows if row[0] == 1] == \
        [["09:00", "11:00", "Theory"], ["12:00", "16:00", "Lab"], ["16:00", "17:00", "Assessment"]]


def test_assessment_has_weights_pass_rule_rubrics_and_questions():
    ws = _workbook(SAMPLE)["Assessment"]
    header = _header_row(ws, "Assessment Item")
    weights, r = [], header + 1
    while isinstance(ws.cell(r, 2).value, (int, float)):
        weights.append(ws.cell(r, 2).value)
        r += 1
    assert sum(weights) == 100
    text = _all_text(ws)
    assert any(str(value).startswith("Pass rule:") for value in text)
    assert "Lab 2 Rubric: Containerise a Web Application" in text
    assert "Standard Lab Rubric (all other labs)" in text
    assert "What does exit code 137 mean?" in text


def test_lab_environment_lists_authored_tools_then_other_tools_without_filler():
    ws = _workbook(SAMPLE)["Lab Environment"]
    header = _header_row(ws, "Tool")
    assert [ws.cell(header, c).value for c in range(1, 6)] == \
        ["Tool", "Version", "Account or Access", "Setup Owner", "Cost per Participant"]
    rows = _rows(ws, header, 5)
    assert rows[0] == ["Docker Engine", "24.0 or later", "Linux VM", "Trainer", "No licence cost"]
    tools = [row[0] for row in rows]
    assert "Kubernetes" in tools and "Docker" not in tools and "All DevOps Tools" not in tools


def test_model_drafted_day_design_is_used_and_an_authored_outline_design_wins():
    drafted = {**DESIGN, "outcomes": [{"outcome": "Drafted outcome", "assessed_by": "Knowledge check"}] * 3}
    days = [{**SAMPLE["days"][0], "design": drafted},
            {**SAMPLE["days"][1], "design": drafted}]  # day 2 also has an authored outline design
    ws = _workbook({**SAMPLE, "days": days})["Module Outcomes"]
    rows = _rows(ws, _header_row(ws, "Module No."), 3)
    assert [row[1] for row in rows if row[0] == 1] == ["Drafted outcome"] * 3
    assert "Build a multi-stage image" in [row[1] for row in rows if row[0] == 2]


def test_trainer_and_support_never_names_the_trainer():
    ws = _workbook({**SAMPLE, "trainer_name": "Jane Trainer"})["Trainer & Support"]
    header = _header_row(ws, "Trainer Profile")
    assert [ws.cell(header, c).value for c in range(1, 4)] == ["Trainer Profile", "Batch Size", "Post-training Support"]
    assert ws.cell(header + 1, 2).value == "12 participants"
    assert "Jane Trainer" not in _all_text(ws)


DATASET_DAY = {
    "day": 1, "focus_area": "Cluster Upgrades and etcd Backup", "minutes": 420,
    "subtopics": ["Version skew policy", "kubeadm upgrade plan", "etcd snapshots"],
    "lab_task": "Upgrade a cluster and restore etcd.", "deliverable": "Upgrade log",
    "learning_objectives": ["Upgrade clusters safely", "Back up and restore etcd", "Kubernetes architecture overview"],
    "acceptance_checks": [
        {"input_or_condition": "Check versions after the upgrade",
         "expected_result": "Control plane and kubelets on the new version", "evidence": "kubectl version and node list"},
        {"input_or_condition": "Restore the snapshot after deleting the namespace",
         "expected_result": "Namespace and its resources are back", "evidence": "Resource list"},
        {"input_or_condition": "Upgrade a kubelet two versions ahead of the API server",
         "expected_result": "The upgrade is rejected with a version skew error", "evidence": "Error output"},
    ],
}


def test_a_module_without_a_design_is_filled_from_its_own_dataset_checks():
    wb = _workbook({**SAMPLE, "days": [DATASET_DAY]})

    outcomes = _rows(wb["Module Outcomes"], _header_row(wb["Module Outcomes"], "Module No."), 3)
    assert outcomes == [
        # One shared word ("upgrade") with two checks is not a clear link, so none is claimed.
        [1, "Upgrade clusters safely", "Lab 1 checks"],
        [1, "Back up and restore etcd", "Lab 1 check: Restore the snapshot after deleting the namespace"],
        [1, "Kubernetes architecture overview", "Lab 1 checks"],  # no shared words: no invented link
    ]

    topics = _rows(wb["Topic Breakdown"], _header_row(wb["Topic Breakdown"], "Module No."), 7)
    troubleshooting = next(row for row in topics if row[1] == "Troubleshooting a seeded failure")
    assert troubleshooting[5] == ("Upgrade a kubelet two versions ahead of the API server: "
                                  "The upgrade is rejected with a version skew error")

    text = _all_text(wb["Assessment"])
    assert any(str(value).startswith("Lab 1 Rubric:") for value in text)
    assert "Namespace and its resources are back; done without help, evidence: Resource list" in text
    assert "Check versions after the upgrade: what result should you see, and how do you show it?" in text
    assert "How would you back up and restore etcd?" in text
    assert not any("kubernetes architecture overview?" in str(value).lower() for value in text)  # not a task


def test_checks_without_an_expected_result_add_no_rubric_or_questions():
    day = {**DATASET_DAY, "acceptance_checks": ["The report names the oversized file"], "learning_objectives": []}
    wb = _workbook({**SAMPLE, "days": [day]})
    text = _all_text(wb["Assessment"])
    assert not any(str(value).startswith("Lab 1 Rubric:") for value in text)
    assert not any("what result should you see" in str(value) for value in text)
    assert "Knowledge Check Questions" not in text  # no generic questions without the module's own
    labs = wb["Labs & Deliverables"]
    assert labs.cell(_header_row(labs, "Lab No.") + 1, 7).value == "The report names the oversized file"


FULL_DESIGN = {
    **DESIGN,
    "seeded_faults": [
        {"symptom": "The published port does not respond.", "cause": "Binds to 127.0.0.1", "fix": "Bind to 0.0.0.0"},
        {"symptom": "The container keeps restarting.", "cause": "Volume owned by root", "fix": "chown before USER"},
    ],
    "quiz": [{"question": question, "answer": f"Answer {index}", "outcome": 1 + index % 3}
             for index, question in enumerate(DESIGN["quiz"])],
}


def test_fuller_designs_show_every_fault_symptom_and_the_outcome_each_question_tests():
    day = {**SAMPLE["days"][1], "outline": {**SAMPLE["days"][1]["outline"], "design": FULL_DESIGN}}
    wb = _workbook({**SAMPLE, "days": [SAMPLE["days"][0], day]})

    labs = wb["Labs & Deliverables"]
    tasks = labs.cell(_header_row(labs, "Lab No.") + 2, 5).value
    assert "Troubleshoot seeded fault 1: The published port does not respond." in tasks
    assert "Troubleshoot seeded fault 2: The container keeps restarting." in tasks
    assert "chown" not in tasks and "127.0.0.1" not in tasks  # causes and fixes stay with the trainer

    outcomes = wb["Module Outcomes"]
    header = _header_row(outcomes, "Module No.")
    assert outcomes.cell(header, 4).value == "Outcome No."
    assert [row[3] for row in _rows(outcomes, header, 4) if row[0] == 2] == ["2.1", "2.2", "2.3"]

    text = _all_text(wb["Assessment"])
    assert "Tests Outcome" in text and "2.1" in text and "2.2" in text
    assert not any(str(value).startswith("Answer ") for value in text)  # answers are not in the client workbook


def test_tables_have_filters_a_mode_dropdown_and_check_cells():
    wb = _workbook(SAMPLE)
    outline = wb["Course Outline"]
    header = _header_row(outline, "Module No.")
    assert [outline.cell(header, c).value for c in (8, 9)] == ["Topic Minutes", "Check"]
    assert outline.cell(header + 1, 8).value == f"=SUMIF('Topic Breakdown'!$A:$A,A{header + 1},'Topic Breakdown'!$D:$D)"
    assert outline.cell(header + 1, 9).value == f'=IF(H{header + 1}=D{header + 1}*60,"OK","Check minutes")'
    assert outline.auto_filter.ref == f"A{header}:I{header + len(SAMPLE['days'])}"

    topics = wb["Topic Breakdown"]
    assert topics.auto_filter.ref.startswith(f"A{_header_row(topics, 'Module No.')}:G")
    modes = topics.data_validations.dataValidation
    assert len(modes) == 1 and modes[0].formula1 == '"demo,lab,discussion"' and str(modes[0].sqref).startswith("E")

    for name in ("Module Outcomes", "Labs & Deliverables", "Day-wise Schedule", "Lab Environment"):
        assert wb[name].auto_filter.ref, name
    assessment = wb["Assessment"]
    total = next(r for r in range(1, 30) if assessment.cell(r, 1).value == "Total")
    assert assessment.cell(total, 3).value == f'=IF(B{total}=100,"OK","Weights must total 100")'


def test_course_overview_lists_official_references_only_when_the_toc_has_them():
    ws = _workbook(SAMPLE)["Course Overview"]
    assert "Official References" not in [ws.cell(r, 1).value for r in range(4, 20)]
    toc = {**SAMPLE, "references": [{"title": "Kubernetes documentation", "url": "https://kubernetes.io/docs/home/"}]}
    ws = _workbook(toc)["Course Overview"]
    labels = {ws.cell(r, 1).value: ws.cell(r, 2).value for r in range(4, 20)}
    assert labels["Official References"] == "Kubernetes documentation: https://kubernetes.io/docs/home/"
