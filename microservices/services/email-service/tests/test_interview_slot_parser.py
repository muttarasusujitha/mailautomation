from datetime import datetime, timedelta

from app.routes.inbox import LOCAL_TZ, _has_proper_interview_slots, _slot_options_from_text


def _start_times(text):
    return [option["start"].strftime("%Y-%m-%d %H:%M") for option in _slot_options_from_text(text)]


def test_shared_month_first_date_parses_three_inline_times():
    reply = "All times are IST: Sep 6, 2027 - 10 AM, 2:15 PM and 4.30 PM."

    assert _has_proper_interview_slots(reply)
    assert _start_times(reply) == [
        "2027-09-06 10:00",
        "2027-09-06 14:15",
        "2027-09-06 16:30",
    ]


def test_iso_date_and_24_hour_time_ranges_parse_without_line_breaks():
    reply = "2027-09-07: 09:00-09:30 | 13:30 to 14:00 | 17:00 - 17:30 IST"
    options = _slot_options_from_text(reply)

    assert _has_proper_interview_slots(reply)
    assert _start_times(reply) == [
        "2027-09-07 09:00",
        "2027-09-07 13:30",
        "2027-09-07 17:00",
    ]
    assert [option["end"].strftime("%H:%M") for option in options] == ["09:30", "14:00", "17:30"]


def test_dotted_24_hour_time_ranges_parse():
    reply = "2027-09-07: 14.30-15.00 | 16.00 to 16.30 | 18.00-18.30 IST"
    options = _slot_options_from_text(reply)

    assert _start_times(reply) == [
        "2027-09-07 14:30",
        "2027-09-07 16:00",
        "2027-09-07 18:00",
    ]
    assert [option["end"].strftime("%H:%M") for option in options] == ["15:00", "16:30", "18:30"]


def test_mixed_date_structures_keep_three_distinct_slots():
    reply = (
        "Slot 1 - 08/09/2027 at 10 AM IST\n"
        "Slot 2: 09/09/2027, 14:00 IST\n"
        "3. 10 September 2027, 4 PM IST"
    )
    options = _slot_options_from_text(reply)

    assert _has_proper_interview_slots(reply)
    assert [option["number"] for option in options] == [1, 2, 3]
    assert _start_times(reply) == [
        "2027-09-08 10:00",
        "2027-09-09 14:00",
        "2027-09-10 16:00",
    ]


def test_duplicate_slot_timestamp_is_not_counted_as_three_slots():
    reply = "6 September 2027: 10 AM IST, 10:00 AM IST, 2 PM IST"

    assert not _has_proper_interview_slots(reply)
    assert _start_times(reply) == ["2027-09-06 10:00", "2027-09-06 14:00"]


def test_yearless_month_date_and_abbreviated_ranges_parse():
    slot_date = datetime.now(LOCAL_TZ).date() + timedelta(days=10)
    reply = (
        f"Available {slot_date.strftime('%b %d')}: "
        "10 AM to 10:30 AM, 2 PM to 2:30 PM and 4 PM to 4:30 PM IST"
    )

    assert _start_times(reply) == [
        f"{slot_date:%Y-%m-%d} 10:00",
        f"{slot_date:%Y-%m-%d} 14:00",
        f"{slot_date:%Y-%m-%d} 16:00",
    ]


def test_today_tomorrow_and_weekday_dates_are_understood():
    today = datetime.now(LOCAL_TZ).date()
    today_reply = (
        f"Today ({today.strftime('%a, %b %d')}): "
        "10:00-10:30 AM, 2:00-2:30 PM and 4:00-4:30 PM IST"
    )
    assert _start_times(today_reply) == [
        f"{today:%Y-%m-%d} 10:00",
        f"{today:%Y-%m-%d} 14:00",
        f"{today:%Y-%m-%d} 16:00",
    ]

    tomorrow_reply = "Tomorrow: 10 AM, 2 PM and 4 PM IST"
    tomorrow = today + timedelta(days=1)
    assert _start_times(tomorrow_reply) == [
        f"{tomorrow:%Y-%m-%d} 10:00",
        f"{tomorrow:%Y-%m-%d} 14:00",
        f"{tomorrow:%Y-%m-%d} 16:00",
    ]

    day_after_tomorrow = today + timedelta(days=2)
    relative_reply = "Day after tomorrow: 10 AM, 2 PM and 4 PM IST"
    assert _start_times(relative_reply) == [
        f"{day_after_tomorrow:%Y-%m-%d} 10:00",
        f"{day_after_tomorrow:%Y-%m-%d} 14:00",
        f"{day_after_tomorrow:%Y-%m-%d} 16:00",
    ]

    next_weekday = today + timedelta(days=7)
    weekday_reply = f"Next {next_weekday.strftime('%A')}: 10 AM, 2 PM and 4 PM IST"
    assert _start_times(weekday_reply) == [
        f"{next_weekday:%Y-%m-%d} 10:00",
        f"{next_weekday:%Y-%m-%d} 14:00",
        f"{next_weekday:%Y-%m-%d} 16:00",
    ]


def test_shared_timezone_heading_applies_to_separate_slot_lines():
    reply = (
        "All times are UTC\n"
        "8 September 2027\n"
        "9 AM\n"
        "10 AM\n"
        "11 AM"
    )

    assert _start_times(reply) == [
        "2027-09-08 14:30",
        "2027-09-08 15:30",
        "2027-09-08 16:30",
    ]


def test_us_numeric_date_is_recognized_when_day_exceeds_twelve():
    reply = "07/28/2027: 10 AM, 2 PM and 4 PM IST"

    assert _start_times(reply) == [
        "2027-07-28 10:00",
        "2027-07-28 14:00",
        "2027-07-28 16:00",
    ]


def test_explicit_timezones_are_converted_to_ist_per_slot():
    reply = (
        "Slot 1: 8 September 2027, 9 AM PST\n"
        "Slot 2: 8 September 2027, 10 AM UTC+00:00\n"
        "Slot 3: 8 September 2027, 11 AM IST"
    )

    assert _start_times(reply) == [
        "2027-09-08 22:30",
        "2027-09-08 15:30",
        "2027-09-08 11:00",
    ]
