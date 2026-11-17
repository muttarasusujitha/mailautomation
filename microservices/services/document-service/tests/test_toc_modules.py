from app.toc_modules import to_modules


def _teaching_day(number, minutes=420):
    return {"day": number, "minutes": minutes, "focus_area": "Kubernetes Networking",
            "subtopics": ["CNI", "Services", "kube-proxy", "DNS"],
            "learning_objectives": ["Trace a request", "Debug DNS", "Fix a policy"],
            "lab": "Trace one request from a pod to a Service", "deliverable": "Request trace",
            "assessment": "Trace matches the expected path",
            "acceptance_checks": [{"input_or_condition": "Curl the Service", "expected_result": "HTTP 200", "evidence": "curl output"}],
            "scenarios": [{"situation": "Curl the Service", "activity": "Apply", "outcome": "HTTP 200", "evidence": "curl output"}],
            "prerequisites": ["Pods and Services"]}


def test_whole_day_becomes_four_coded_modules_with_the_same_total():
    rows = to_modules([_teaching_day(1), _teaching_day(2)])
    assert [row["focus_area"].split(" - ")[0] for row in rows] == [f"M{i}" for i in range(1, 9)]
    assert sum(row["minutes"] for row in rows if row["day"] == 1) == 420
    lab = rows[2]
    assert lab["lab"] == "Trace one request from a pod to a Service"
    assert lab["deliverable"] == "Request trace"
    assert lab["assessment"] == "Trace matches the expected path"
    assert lab["scenarios"][0]["outcome"] == "HTTP 200"
    assert rows[3]["acceptance_checks"][0]["expected_result"] == "HTTP 200"
    assert rows[3]["assessment"] == "HTTP 200"
    # Day-level readiness items appear once, not on every module.
    assert [bool(row.get("prerequisites")) for row in rows[:4]] == [True, False, False, False]


def test_capstone_day_becomes_build_and_review_modules():
    day = {"day": 5, "minutes": 420, "focus_area": "Capstone: Platform", "lab": "Build the platform",
           "learning_objectives": ["Build it", "Defend it"], "assessment": "Checklist passes"}
    build, review = to_modules([day])
    assert (build["minutes"], review["minutes"]) == (300, 120)
    assert build["lab"] == "Build the platform"
    assert review["assessment"] == "Checklist passes"


def test_minutes_scale_to_a_longer_client_day():
    rows = to_modules([_teaching_day(1, minutes=480)])
    assert sum(row["minutes"] for row in rows) == 480
    assert all(row["minutes"] % 15 == 0 for row in rows)


def test_existing_modules_short_days_and_unknown_hours_are_left_alone():
    modules = [{"title": "Requirements", "minutes": 90}, {"title": "Build", "minutes": 120}]
    assert [row["focus_area"] for row in to_modules([{"day": 1, "modules": modules}])] == ["Requirements", "Build"]
    assert to_modules([{"day": 1, "minutes": 180, "focus_area": "CSV"}])[0]["focus_area"] == "CSV"
    assert to_modules([{"focus_area": "No hours"}])[0].get("minutes") is None
