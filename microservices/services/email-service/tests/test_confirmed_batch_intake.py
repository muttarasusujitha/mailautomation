from app.routes.inbox import (
    _confirmed_intake_ready_for_trainer_mail,
    _with_missing_dated_slots,
)


def _complete_extracted():
    return {
        "is_training_request": True,
        "is_non_client_email": False,
        "direct_request_language": True,
        "technology_needed": "DevOps",
        "training_dates": "10 September 2026 to 7 October 2026",
        "duration_days": 20,
        "mode": "Online",
        "participant_count": 20,
        "budget_total": 130000,
    }


def _toc_email():
    return {
        "attachments": [{
            "filename": "DevOps TOC.xlsx",
            "analysis": {"attachment_type": "toc"},
        }],
    }


def test_complete_confirmed_first_mail_can_start_trainer_mail():
    ready = _confirmed_intake_ready_for_trainer_mail(
        _complete_extracted(),
        _toc_email(),
        "Confirmed DevOps training for 20 participants.",
    )
    assert ready is True


def test_confirmed_mail_without_an_attached_toc_waits():
    ready = _confirmed_intake_ready_for_trainer_mail(
        _complete_extracted(),
        {"attachments": []},
        "Confirmed DevOps training for 20 participants.",
    )
    assert ready is False


def test_incomplete_confirmed_mail_waits_for_a_later_reply():
    extracted = _complete_extracted()
    extracted["participant_count"] = None
    ready = _confirmed_intake_ready_for_trainer_mail(
        extracted,
        _toc_email(),
        "Confirmed DevOps training.",
    )
    assert ready is False


def test_tentative_first_mail_is_not_treated_as_ready_confirmed_intake():
    ready = _confirmed_intake_ready_for_trainer_mail(
        _complete_extracted(),
        _toc_email(),
        "We are exploring a possible DevOps requirement and the dates are tentative.",
    )
    assert ready is False


def test_interested_reply_without_three_dated_slots_is_one_followup_item():
    missing = _with_missing_dated_slots(
        [],
        "I am interested and can deliver this training. Please find my profile.",
    )
    assert missing == ["Exactly three dated interview/discussion slots (date, time, and time zone)"]
    assert _with_missing_dated_slots(missing, "Still interested.") == missing


def test_three_dated_slots_are_not_added_to_the_followup():
    reply = "\n".join([
        "01 November 2026, 10:00 AM IST",
        "03 November 2026, 2:00 PM IST",
        "05 November 2026, 4:00 PM IST",
    ])
    assert _with_missing_dated_slots([], reply) == []
