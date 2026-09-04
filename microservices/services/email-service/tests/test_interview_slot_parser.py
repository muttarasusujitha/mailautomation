from app.routes.inbox import _has_proper_interview_slots, _slot_options_from_text


def _start_times(text):
    return [option["start"].strftime("%Y-%m-%d %H:%M") for option in _slot_options_from_text(text)]


def test_shared_month_first_date_parses_three_inline_times():
    reply = "All times are IST: Sep 6, 2026 - 10 AM, 2:15 PM and 4.30 PM."

    assert _has_proper_interview_slots(reply)
    assert _start_times(reply) == [
        "2026-09-06 10:00",
        "2026-09-06 14:15",
        "2026-09-06 16:30",
    ]


def test_iso_date_and_24_hour_time_ranges_parse_without_line_breaks():
    reply = "2026-09-07: 09:00-09:30 | 13:30 to 14:00 | 17:00 - 17:30 IST"
    options = _slot_options_from_text(reply)

    assert _has_proper_interview_slots(reply)
    assert _start_times(reply) == [
        "2026-09-07 09:00",
        "2026-09-07 13:30",
        "2026-09-07 17:00",
    ]
    assert [option["end"].strftime("%H:%M") for option in options] == ["09:30", "14:00", "17:30"]


def test_mixed_date_structures_keep_three_distinct_slots():
    reply = (
        "Slot 1 - 08/09/2026 at 10 AM IST\n"
        "Slot 2: 09/09/2026, 14:00 IST\n"
        "3. 10 September 2026, 4 PM IST"
    )
    options = _slot_options_from_text(reply)

    assert _has_proper_interview_slots(reply)
    assert [option["number"] for option in options] == [1, 2, 3]
    assert _start_times(reply) == [
        "2026-09-08 10:00",
        "2026-09-09 14:00",
        "2026-09-10 16:00",
    ]


def test_duplicate_slot_timestamp_is_not_counted_as_three_slots():
    reply = "6 September 2026: 10 AM IST, 10:00 AM IST, 2 PM IST"

    assert not _has_proper_interview_slots(reply)
    assert _start_times(reply) == ["2026-09-06 10:00", "2026-09-06 14:00"]
