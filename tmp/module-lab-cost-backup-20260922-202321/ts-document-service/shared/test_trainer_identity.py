import pytest

from shared.trainer_identity import linkedin_profile_url


@pytest.mark.parametrize('value', [
    'LinkedIn pending', 'https://linkedin.com/company/training',
    'https://linkedin.com.evil.test/in/trainer',
    'https://evil.test/linkedin.com/in/trainer',
    'https://linkedin.com/search/results/people',
    'https://user@linkedin.com/in/trainer',
])
def test_invalid_profile_is_missing(value):
    assert linkedin_profile_url(value) == ''


def test_supplied_personal_url_is_preserved():
    assert linkedin_profile_url('My profile: https://www.linkedin.com/in/trainer-name.') == 'https://www.linkedin.com/in/trainer-name'
