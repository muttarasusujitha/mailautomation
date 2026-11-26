from app.toc_generation_agent import _standard_step_minutes, generate_toc_from_dataset


def _steps(*methods, minutes=None):
    return [{"method": method, "minutes": minutes, "activity": f"{method} activity", "evidence": f"{method} evidence"}
            for method in methods]


FOUR = ("Explanation and demonstration", "Guided practice", "Independent application", "Assessment and feedback")


def test_missing_step_minutes_get_the_standard_seven_hour_split():
    assert [step["minutes"] for step in _standard_step_minutes(_steps(*FOUR), "Azure Advanced")] == [150, 150, 60, 60]
    assert [step["minutes"] for step in _standard_step_minutes(_steps(*FOUR), "Capstone Project")] == [30, 240, 60, 90]
    assert _standard_step_minutes(_steps(*FOUR, minutes=30), "Azure") is None  # authored minutes are kept
    assert _standard_step_minutes(_steps(*FOUR[:3]), "Azure") is None  # other shapes keep the old handling
    assert _standard_step_minutes(_steps("Lecture", *FOUR[1:]), "Azure") is None


def test_a_toc_keeps_the_course_files_step_activities_instead_of_generic_ones():
    toc = generate_toc_from_dataset("Cloud", 60)
    compact_days = [day for day in toc["days"] if (day.get("design_ref") or {}).get("file") in ("cloud_30", "cloud_60")]
    assert compact_days
    for day in compact_days:
        activities = " ".join(str(step.get("activity")) for step in day["delivery_steps"])
        assert "Explain and demonstrate the core" not in activities  # the generic fallback text
        assert sum(step["minutes"] for step in day["delivery_steps"]) == day["minutes"] == 420
