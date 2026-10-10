import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch
from app.clients.lead_discovery import discover, public_queries
from app.routes.linkedin_leads import LinkedInLeadSearchRequest, _normalize_result, search_linkedin_leads
from app.clients.linkedin_session import LinkedInAuthenticationRequired, RECONNECT_MESSAGE


def test_trainer_public_queries_ask_for_linkedin_profiles():
    queries = public_queries('Python', 'trainer', 'Hyderabad')
    assert queries[0] == 'Python corporate trainer Hyderabad'
    assert queries[1] == 'Python freelance trainer Hyderabad'
    assert len(queries) >= 12
    assert 'Python corporate trainer Bangalore' in queries
    assert all('site:' not in query for query in queries)
    client = public_queries('Python', 'client')
    assert client[0] == 'Python trainer required'
    assert all('site:' not in query for query in client)


def test_public_trainer_search_drops_stale_off_skill_and_non_profiles():
    year = datetime.utcnow().year
    rows = [
        {'url': 'https://www.linkedin.com/in/ravi', 'title': 'Ravi', 'content': f'Python corporate trainer {year}'},
        {'url': 'https://www.linkedin.com/in/old', 'title': 'Old', 'content': 'Python corporate trainer 2019'},
        {'url': 'https://www.linkedin.com/in/java', 'title': 'Java', 'content': f'Java corporate trainer {year}'},
        {'url': 'https://www.linkedin.com/posts/resume', 'title': 'Resume', 'content': f'Python trainer resume {year}'},
        {'url': 'https://www.naukri.com/python-trainer-hyderabad', 'title': 'Naukri', 'content': f'Python corporate trainer {year}'},
    ]
    with patch('app.clients.public_search.search_public_many', AsyncMock(return_value=(rows, 2))) as public, patch(
        'app.clients.linkedin_browser.search_linkedin_account', AsyncMock(side_effect=ValueError('Verification required'))
    ):
        results, outcome = asyncio.run(discover('Python', 'trainer', 20))
    assert [row['url'] for row in results] == [
        'https://www.linkedin.com/in/ravi',
        'https://www.naukri.com/python-trainer-hyderabad',
    ]
    assert outcome['warnings'][0]['source'] == 'linkedin_account'
    assert public.await_args.args[0][0] == 'Python corporate trainer'
    assert public.await_args.args[1] >= 50


def test_later_browser_failure_preserves_collected_matches():
    from app.clients.linkedin_browser import PartialSearchError
    rows = [{'url': 'https://www.linkedin.com/in/alice', 'title': 'Python corporate trainer'}]
    with patch('app.clients.public_search.search_public_many', AsyncMock(return_value=([], 1))), patch('app.clients.linkedin_browser.search_linkedin_account', AsyncMock(side_effect=PartialSearchError('Later page timed out', rows))):
        results, outcome = asyncio.run(discover('Python', 'trainer', 20))
    assert len(results) == 1
    assert outcome['status'] == 'partial'
    assert outcome['warnings'][0]['error'] == 'Later page timed out'


def test_public_matches_survive_blocked_account_and_deduplicate():
    rows = [{'url': 'https://in.linkedin.com/in/alice?trk=x', 'title': 'Python corporate trainer'},
            {'url': 'https://www.linkedin.com/in/alice', 'title': 'Python corporate trainer'},
            {'url': 'https://www.linkedin.com/in/bob', 'title': 'Java corporate trainer'}]
    with patch('app.clients.public_search.search_public_many', AsyncMock(return_value=(rows, 1))), patch('app.clients.linkedin_browser.search_linkedin_account', AsyncMock(side_effect=ValueError('Verification required'))):
        results, outcome = asyncio.run(discover('Python', 'trainer', 20))
    assert len(results) == 1
    assert outcome['matched'] == 1
    assert not outcome['target_met']
    assert outcome['warnings'][0]['source'] == 'linkedin_account'


def test_auto_target_is_per_domain_and_saves_separate_collections():
    async def fake(domain, mode, target, location):
        rows = [{'url': f'https://www.linkedin.com/in/{domain}-{i}', 'title': f'{domain} trainer'} for i in range(20)]
        return rows, {'domain': domain, 'target': target, 'matched': 20, 'target_met': True, 'status': 'target_met'}
    db = {'trainer_profile_leads': AsyncMock(), 'client_leads': AsyncMock()}
    db['trainer_profile_leads'].find_one.return_value = None
    with patch('app.clients.lead_discovery.discover', side_effect=fake):
        result = asyncio.run(search_linkedin_leads(LinkedInLeadSearchRequest(domains=['Python','Java'], search_provider='auto', max_results=20), db))
    assert result['saved_count'] == 40
    assert len(result['domain_outcomes']) == 2
    db['client_leads'].insert_one.assert_not_awaited()


def test_public_timeouts_and_paused_login_report_same_primary_error():
    with patch('app.clients.public_search.search_public_many', AsyncMock(side_effect=TimeoutError())), \
            patch('app.clients.linkedin_browser.search_linkedin_account', AsyncMock(side_effect=LinkedInAuthenticationRequired(RECONNECT_MESSAGE))):
        result = asyncio.run(search_linkedin_leads(LinkedInLeadSearchRequest(
            domains=['sap trainer'], search_provider='auto', max_results=50), {}))
    outcome = result['domain_outcomes'][0]
    assert result['search_error'] == outcome['primary_error'] == outcome['warnings'][0]['error'] == RECONNECT_MESSAGE
    assert outcome['warnings'][1]['error'].startswith('Public web search timed out.')
    assert len(outcome['warnings']) == 2
    assert outcome['matched'] == 0
    assert result['saved_count'] == 0


def test_keyword_qualified_trainer_is_saved_when_the_headline_omits_the_skill():
    db = {'trainer_profile_leads': AsyncMock(), 'client_leads': AsyncMock()}
    db['trainer_profile_leads'].find_one.return_value = None
    row = {
        'url': 'https://www.linkedin.com/in/asha',
        'title': 'Asha',
        'content': 'Asha\nCorporate trainer\nHyderabad',
        'keyword_qualified': True,
    }
    with patch('app.clients.public_search.search_public_many', AsyncMock(return_value=([], 1))), \
            patch('app.clients.linkedin_browser.search_linkedin_account', AsyncMock(return_value=[row])):
        result = asyncio.run(search_linkedin_leads(LinkedInLeadSearchRequest(
            domain='soft skills', search_provider='auto', max_results=20), db))
    assert result['found'] == 1
    assert result['saved_count'] == 1
    saved = db['trainer_profile_leads'].insert_one.await_args.args[0]
    assert saved['domain'] == 'soft skills'
    assert saved['source_url'] == 'https://www.linkedin.com/in/asha'
    assert _normalize_result({**row, 'keyword_qualified': False}, 'soft skills', 'trainer') is None


def test_cancelled_account_search_keeps_profiles_already_collected():
    async def boom(domain, mode, target, location, collected=None):
        collected.append({'url': 'https://www.linkedin.com/in/ada', 'title': 'Ada', 'content': 'Soft skills corporate trainer'})
        raise TimeoutError()

    with patch('app.clients.public_search.search_public_many', AsyncMock(return_value=([], 1))), \
            patch('app.clients.linkedin_browser.search_linkedin_account', side_effect=boom):
        results, outcome = asyncio.run(discover('soft skills', 'trainer', 20))
    assert [row['url'] for row in results] == ['https://www.linkedin.com/in/ada']
    assert outcome['status'] == 'partial'
    assert outcome['primary_error'].startswith('LinkedIn account search timed out.')


def test_timeout_keeps_public_matches_and_uses_readable_error():
    rows = [{'url': 'https://www.linkedin.com/in/alice', 'title': 'SAP corporate trainer'}]
    with patch('app.clients.public_search.search_public_many', AsyncMock(return_value=(rows, 1))), \
            patch('app.clients.linkedin_browser.search_linkedin_account', AsyncMock(side_effect=TimeoutError())):
        found, outcome = asyncio.run(discover('SAP', 'trainer', 50))
    assert len(found) == 1
    assert outcome['status'] == 'partial'
    assert outcome['primary_error'].startswith('LinkedIn account search timed out.')
