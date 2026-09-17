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
