from app.routes.shortlists import (
    _trainer_missing_followup_details, _requested_trainer_details_for_client,
)


def test_linkedin_request_is_not_replaced_with_cv_request():
    requirement = {'requested_details': ['LinkedIn profile']}
    assert _trainer_missing_followup_details({}, requirement) == ['LinkedIn profile']


def test_linkedin_alias_satisfies_request():
    requirement = {'requested_details': ['LinkedIn profile']}
    trainer = {'linkedin_profile': 'https://www.linkedin.com/in/trainer-name'}
    assert _trainer_missing_followup_details(trainer, requirement) == []


def test_company_link_is_not_forwarded_as_trainer_profile():
    requirement = {'requested_details': ['LinkedIn profile']}
    trainer = {'linkedin': 'https://www.linkedin.com/company/example'}
    assert 'https://' not in _requested_trainer_details_for_client(requirement, trainer)
    assert _trainer_missing_followup_details(trainer, requirement) == ['LinkedIn profile']


def test_interested_reply_without_three_slots_is_one_followup_item():
    requirement = {'requested_details': ['LinkedIn profile']}
    trainer = {
        'linkedin_profile': 'https://www.linkedin.com/in/trainer-name',
        'reply_sentiment': 'positive',
        'pipeline_status': 'mail1_replied',
        'mail1_reply_text': 'I am interested and can deliver this training.',
    }
    assert _trainer_missing_followup_details(trainer, requirement) == [
        'Exactly three dated interview/discussion slots (date, time, and time zone)'
    ]


def test_interested_reply_with_three_dated_slots_needs_no_slot_followup():
    requirement = {'requested_details': ['LinkedIn profile']}
    trainer = {
        'linkedin_profile': 'https://www.linkedin.com/in/trainer-name',
        'reply_sentiment': 'positive',
        'pipeline_status': 'mail1_replied',
        'mail1_reply_text': '\n'.join([
            'I am interested.',
            '01 November 2026, 10:00 AM IST',
            '03 November 2026, 2:00 PM IST',
            '05 November 2026, 4:00 PM IST',
        ]),
    }
    assert _trainer_missing_followup_details(trainer, requirement) == []
