import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from app.clients.linkedin_browser import collect_trainer_profiles, PartialSearchError, people_identities_hidden


def test_anonymous_result_detection():
    assert people_identities_hidden('LinkedIn Member\nDevOps Trainer\nLinkedIn Member\nInstructor')
    assert not people_identities_hidden('No results found')


@pytest.mark.parametrize('has_fallback', [True, False])
def test_hidden_people_stop_retries_but_keep_identifiable_fallback(has_fallback):
    page = MagicMock()
    page.goto = AsyncMock(return_value=MagicMock(status=200))
    page.wait_for_timeout = AsyncMock()
    page.mouse.wheel = AsyncMock()
    people = MagicMock()
    people.first.wait_for = AsyncMock()
    people.evaluate_all = AsyncMock(return_value=[])
    body = MagicMock()
    body.inner_text = AsyncMock(return_value='LinkedIn Member\nDevOps Trainer\nLinkedIn Member')
    cards = MagicMock()
    cards.first.wait_for = AsyncMock()
    cards.evaluate_all = AsyncMock(return_value=[{'content': 'Alice\nDevOps trainer\nFollow\nCourse', 'links': [{'url': 'https://www.linkedin.com/in/alice', 'title': 'Alice'}]}] if has_fallback else [])
    page.locator.side_effect = lambda selector: body if selector == 'body' else cards if 'listitem' in selector else people
    with patch('app.clients.linkedin_browser.require_session', AsyncMock()), patch('app.clients.linkedin_browser.scroll_results', AsyncMock()):
        if has_fallback:
            assert len(asyncio.run(collect_trainer_profiles(page, 'DevOps', '', 1))) == 1
        else:
            with pytest.raises(PartialSearchError, match='anonymous'):
                asyncio.run(collect_trainer_profiles(page, 'DevOps', '', 1))
    assert sum('/people/' in call.args[0] for call in page.goto.await_args_list) == 1
