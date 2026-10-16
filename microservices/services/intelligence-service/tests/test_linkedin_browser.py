import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.clients.linkedin_browser import canonical_url, search_url, require_session, search_linkedin_account
from app.routes.linkedin_leads import _normalize_result, LinkedInLeadSearchRequest, search_linkedin_leads


def test_trainer_post_uses_author_headline_not_hiring_body():
    from app.clients.linkedin_browser import read_post_cards
    card = MagicMock()
    card.evaluate_all = AsyncMock(return_value=[{'links': [{'url': 'https://www.linkedin.com/in/alice', 'title': 'Alice\n3rd+'}],
        'content': 'Feed post\n\nAlice\n\nRecruiter\n\nFollow\n\nPython trainer required'}])
    cards = MagicMock()
    cards.first.wait_for = AsyncMock()
    cards.count = AsyncMock(return_value=1)
    cards.nth.return_value = card
    page = MagicMock()
    page.locator.return_value = cards
    page.mouse.wheel = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    rows = asyncio.run(read_post_cards(page, AsyncMock(), 'trainer', 5))
    assert len(rows) == 1
    assert rows[0]['title'] == 'Alice'
    assert 'trainer required' not in rows[0]['content']
    assert _normalize_result(rows[0], 'Python', 'trainer') is None


def test_company_post_does_not_invent_contact_from_slug():
    lead = _normalize_result({'url': 'https://www.linkedin.com/posts/python-trainer-required-123',
                              'title': 'Acme', 'content': 'Python trainer required', 'contact_name': ''}, 'Python', 'client')
    assert lead['contact_name'] == ''


def test_connect_action_separates_author_from_hiring_post():
    from app.clients.linkedin_browser import author_headline
    content = 'Alice\nRecruiter\n\nConnect\n\nPython corporate trainer required'
    assert 'trainer required' not in author_headline(content)
    assert author_headline('Alice\nPython trainer required') == ''


def test_trainer_fallback_loads_matches_after_scrolling_result_panel():
    from app.clients.linkedin_browser import collect_trainer_profiles
    page = MagicMock()
    page.goto = AsyncMock(return_value=MagicMock(status=200))
    page.wait_for_timeout = AsyncMock()
    page.mouse.wheel = AsyncMock()
    people = MagicMock()
    people.evaluate_all = AsyncMock(return_value=[])
    cards = MagicMock()
    cards.first.wait_for = AsyncMock()
    cards.last.scroll_into_view_if_needed = AsyncMock()
    cards.last.hover = AsyncMock()
    recruiter = {'links': [{'url': 'https://www.linkedin.com/in/recruiter', 'title': 'Recruiter'}], 'content': 'Recruiter\nHR\nFollow\nPython trainer required'}
    trainer = {'links': [{'url': 'https://www.linkedin.com/in/trainer', 'title': 'Trainer'}], 'content': 'Trainer\nPython corporate trainer\nFollow\nMy latest course'}
    cards.evaluate_all = AsyncMock(side_effect=[[recruiter], [recruiter, trainer]])
    page.locator.side_effect = lambda selector: cards if 'listitem' in selector else people
    with patch('app.clients.linkedin_browser.require_session', AsyncMock()):
        rows = asyncio.run(collect_trainer_profiles(page, 'Python', '', 1))
    assert [row['url'] for row in rows] == ['https://www.linkedin.com/in/trainer']
    cards.last.scroll_into_view_if_needed.assert_awaited_once()
    cards.last.hover.assert_awaited_once()


def test_search_counts_only_unique_matching_profiles_toward_twenty():
    from app.clients.linkedin_browser import collect_trainer_profiles
    def card(i, headline):
        return {'links': [{'url': f'https://www.linkedin.com/in/person-{i}', 'title': f'Person {i}'}],
                'content': f'Feed post\nPerson {i}\n{headline}\nFollow\nPython trainer required'}
    batch = [card(0, 'Recruiter')] + [card(i, 'Python corporate trainer') for i in range(1, 24)]
    batch.insert(3, batch[1])
    page = MagicMock()
    page.goto = AsyncMock(return_value=MagicMock(status=200))
    page.wait_for_timeout = AsyncMock()
    page.locator.return_value.first.wait_for = AsyncMock()
    page.locator.return_value.evaluate_all = AsyncMock(return_value=batch)
    with patch('app.clients.linkedin_browser.require_session', AsyncMock()):
        results = asyncio.run(collect_trainer_profiles(page, 'Python', '', 20))
    assert len(results) == 20
    assert len({item['url'] for item in results}) == 20
    assert all(item['title'] != 'Person 0' for item in results)


def test_urls_only_accept_linkedin_results():
    assert canonical_url('https://in.linkedin.com/in/alice/?trk=search') == 'https://www.linkedin.com/in/alice'
    assert not canonical_url('https://linkedin.com.evil.test/in/alice')
    assert not canonical_url('https://www.linkedin.com/jobs/123')
    assert '/people/' in search_url('Python', 'trainer')
    assert 'Python+trainer' in search_url('Python', 'trainer')
    assert 'OR' not in search_url('Python', 'trainer')
    assert 'Devops+trainer' in search_url('Devops trainer', 'trainer')
    assert '/content/' in search_url('Python', 'client')


def test_client_domain_and_trainer_intent_are_required():
    item = {'url': 'https://www.linkedin.com/posts/alice-123', 'content': 'Looking for Java trainer. Email alice@example.com'}
    assert _normalize_result(item, 'Python', 'client') is None
    assert _normalize_result(item, 'Java', 'client') is not None
    assert _normalize_result(item, 'Java', 'trainer') is None
    assert _normalize_result({**item, 'content': 'Need JavaScript trainer'}, 'Java', 'client') is None
    assert _normalize_result({**item, 'content': 'Looking out for Java trainers'}, 'Java', 'client') is not None
    assert _normalize_result({**item, 'content': 'Need data entry trainer'}, 'Data Science', 'client') is None
    lead = _normalize_result({**item, 'contact_name': 'Alice', 'contact_linkedin_url': 'https://www.linkedin.com/in/alice'}, 'Java', 'client')
    assert lead['contact_name'] == 'Alice'
    assert lead['contact_linkedin_url'] == 'https://www.linkedin.com/in/alice'


def test_signin_checkpoint_stops_fetch():
    page = AsyncMock()
    page.url = 'https://www.linkedin.com/checkpoint/challenge'
    with pytest.raises(ValueError, match='verification required'):
        asyncio.run(require_session(page))


@pytest.mark.parametrize('destination', ['search', 'checkpoint', 'timeout'])
def test_remember_me_redirect_can_finish_but_verification_is_not_bypassed(destination):
    page = MagicMock()
    page.url = 'https://www.linkedin.com/ssr-login/remember-me-auto-login'
    page.locator.return_value.count = AsyncMock(return_value=0)

    async def redirect(*args, **kwargs):
        if destination == 'timeout':
            raise TimeoutError()
        page.url = ('https://www.linkedin.com/search/results/people/' if destination == 'search'
                    else 'https://www.linkedin.com/checkpoint/challenge')

    page.wait_for_url = AsyncMock(side_effect=redirect)
    if destination == 'search':
        asyncio.run(require_session(page))
    else:
        with pytest.raises(ValueError, match='verification required'):
            asyncio.run(require_session(page))
    page.wait_for_url.assert_awaited_once()


def test_disabled_bot_does_not_launch_browser():
    with patch.dict('os.environ', {'LINKEDIN_BOT_ENABLED': 'false'}):
        with pytest.raises(ValueError, match='not enabled'):
            asyncio.run(search_linkedin_account('Python', 'trainer'))


def test_people_pages_collect_multiword_trainer_profiles():
    from app.clients.linkedin_browser import collect_trainer_profiles
    page = MagicMock()
    page.goto = AsyncMock(return_value=MagicMock(status=200))
    page.wait_for_timeout = AsyncMock()
    page.mouse.wheel = AsyncMock()
    pages = [
        [
            {'url': 'https://www.linkedin.com/in/recruiter', 'text': 'Recruiter\nHR manager\nHyderabad'},
            {'url': 'https://www.linkedin.com/in/ada', 'text': 'Ada\nSoft Skills Trainer\nHyderabad'},
        ],
        [{'url': 'https://www.linkedin.com/in/ben', 'text': 'Ben\nCorporate facilitator for soft skills'}],
    ]
    people = MagicMock()
    people.first.wait_for = AsyncMock()
    people.evaluate_all = AsyncMock(side_effect=pages)

    def locate(selector):
        if 'listitem' in selector:
            raise AssertionError('content fallback started before people pages filled the target')
        return people

    page.locator.side_effect = locate
    with patch('app.clients.linkedin_browser.require_session', AsyncMock()):
        rows = asyncio.run(collect_trainer_profiles(page, 'soft skills', '', 2))
    assert [row['url'] for row in rows] == [
        'https://www.linkedin.com/in/ada',
        'https://www.linkedin.com/in/ben',
    ]
    assert page.goto.await_count == 2
    assert all('/search/results/people/' in call.args[0] and 'soft+skills+trainer' in call.args[0]
               for call in page.goto.await_args_list)


def test_people_search_keeps_paging_until_the_fifty_profile_target():
    from app.clients.linkedin_browser import collect_trainer_profiles
    page = MagicMock()
    page.goto = AsyncMock(return_value=MagicMock(status=200))
    page.wait_for_timeout = AsyncMock()
    page.mouse.wheel = AsyncMock()
    pages = [
        [{'url': f'https://www.linkedin.com/in/trainer-{index}', 'text': f'Trainer {index}\nSAP trainer\nHyderabad'}]
        for index in range(6)
    ]
    calls = {'count': 0}

    async def evaluate(_script):
        calls['count'] += 1
        if calls['count'] <= len(pages):
            return pages[calls['count'] - 1]
        return []

    people = MagicMock()
    people.first.wait_for = AsyncMock()
    people.evaluate_all = AsyncMock(side_effect=evaluate)

    def locate(selector):
        if 'listitem' in selector:
            raise AssertionError('content fallback started before people pages were exhausted')
        return people

    page.locator.side_effect = locate
    with patch('app.clients.linkedin_browser.require_session', AsyncMock()):
        rows = asyncio.run(collect_trainer_profiles(page, 'SAP trainer', '', 50))
    assert len(rows) == 6
    assert page.goto.await_count > 6
    assert sum('page=' in call.args[0] for call in page.goto.await_args_list) >= 6
    assert any('/content/' in call.args[0] for call in page.goto.await_args_list)


def test_scanning_people_stops_at_sixty_trainer_profiles():
    from app.clients.linkedin_browser import collect_trainer_profiles
    page = MagicMock()
    page.goto = AsyncMock(return_value=MagicMock(status=200))
    page.wait_for_timeout = AsyncMock()
    page.mouse.wheel = AsyncMock()
    page.get_by_role.return_value.count = AsyncMock(return_value=1)
    page.get_by_role.return_value.click = AsyncMock()
    pages = []
    for page_index in range(12):
        cards = []
        for slot in range(10):
            number = page_index * 10 + slot
            if slot % 2 == 0:
                cards.append({'url': f'https://www.linkedin.com/in/trainer-{number}', 'text': f'Trainer {number}\nSAP trainer'})
            else:
                cards.append({'url': f'https://www.linkedin.com/in/other-{number}', 'text': f'Person {number}\nSAP consultant'})
        pages.append(cards)
    people = MagicMock()
    people.first.wait_for = AsyncMock()
    people.evaluate_all = AsyncMock(side_effect=pages)
    page.locator.return_value = people
    with patch('app.clients.linkedin_browser.require_session', AsyncMock()):
        rows = asyncio.run(collect_trainer_profiles(page, 'SAP', '', 60))
    assert len(rows) == 60
    assert len({row['url'] for row in rows}) == 60
    assert all('trainer-' in row['url'] for row in rows)
    assert page.goto.await_count == 12
    assert len({call.args[0].split('&page=')[0] for call in page.goto.await_args_list}) >= 3
    assert all('page=13' not in call.args[0] for call in page.goto.await_args_list)
    page.get_by_role.return_value.click.assert_not_awaited()


def test_blank_people_page_is_reread_before_the_search_stops():
    from app.clients.linkedin_browser import collect_trainer_profiles
    page = MagicMock()
    page.goto = AsyncMock(return_value=MagicMock(status=200))
    page.wait_for_timeout = AsyncMock()
    page.mouse.wheel = AsyncMock()
    page.get_by_role.side_effect = AssertionError('next page is not needed')
    snapshots = [
        [],
        [{'url': 'https://www.linkedin.com/in/ada', 'text': 'Ada\nSAP trainer\nHyderabad'}],
    ]
    people = MagicMock()
    people.first.wait_for = AsyncMock()
    people.evaluate_all = AsyncMock(side_effect=snapshots + [[]])
    page.locator.return_value = people
    with patch('app.clients.linkedin_browser.require_session', AsyncMock()):
        rows = asyncio.run(collect_trainer_profiles(page, 'SAP', '', 50))
    assert [row['url'] for row in rows] == ['https://www.linkedin.com/in/ada']


def test_joined_domain_words_still_match_trainer_profiles():
    item = {'url': 'https://www.linkedin.com/in/ada', 'title': 'Ada', 'content': 'SoftSkills corporate trainer'}
    lead = _normalize_result(item, 'soft skills', 'trainer')
    assert lead['source_url'] == 'https://www.linkedin.com/in/ada'
    assert _normalize_result({**item, 'url': 'https://www.linkedin.com/in/js', 'content': 'JavaScript trainer'}, 'Java', 'trainer') is None


def test_people_checkpoint_does_not_start_post_search():
    from app.clients.linkedin_browser import collect_trainer_profiles
    page = MagicMock()
    page.goto = AsyncMock(return_value=MagicMock(status=200))
    page.wait_for_timeout = AsyncMock()
    with patch('app.clients.linkedin_browser.require_session', AsyncMock(side_effect=ValueError('verification required'))):
        with pytest.raises(ValueError, match='verification required'):
            asyncio.run(collect_trainer_profiles(page, 'Python', '', 20))
    page.goto.assert_awaited_once()


def test_account_time_limit_without_profiles_stays_an_error():
    from app.clients.linkedin_browser import PartialSearchError
    with patch('app.clients.linkedin_browser.search_linkedin_account', AsyncMock(side_effect=PartialSearchError('Trainer search reached its time limit.', []))):
        result = asyncio.run(search_linkedin_leads(LinkedInLeadSearchRequest(domain='Python', search_provider='linkedin_account'), {}))
    assert result['success'] is False
    assert result['found'] == 0
    assert result['search_error'] == 'Trainer search reached its time limit.'


def test_direct_account_search_saves_matches_before_later_timeout():
    from app.clients.linkedin_browser import PartialSearchError
    db = {'trainer_profile_leads': AsyncMock()}
    db['trainer_profile_leads'].find_one.return_value = None
    rows = [{'url': 'https://www.linkedin.com/in/alice', 'content': 'Python corporate trainer'}]
    with patch('app.clients.linkedin_browser.search_linkedin_account', AsyncMock(side_effect=PartialSearchError('Search time limit', rows))):
        result = asyncio.run(search_linkedin_leads(LinkedInLeadSearchRequest(domain='Python', search_provider='linkedin_account'), db))
    assert result['saved_count'] == 1
    assert result['found'] == 1
    assert result['success'] is True
    assert result['search_error'] is None


@pytest.mark.parametrize('mode,table,url,text', [
    ('trainer', 'trainer_profile_leads', 'https://www.linkedin.com/in/alice', 'Python corporate trainer'),
    ('client', 'client_leads', 'https://www.linkedin.com/posts/alice-123', 'Seeking Python trainer for our team'),
])
def test_account_results_saved_without_search_api_or_mail(mode, table, url, text):
    db = {name: AsyncMock() for name in ('client_leads', 'trainer_profile_leads')}
    for collection in db.values():
        collection.find_one.return_value = None
    with patch('app.clients.linkedin_browser.search_linkedin_account', AsyncMock(return_value=[{'url': url, 'content': text}])) as browser, patch('app.clients.public_search.search_public', AsyncMock()) as public, patch('app.routes.linkedin_leads._plain_tavily_search', AsyncMock()) as paid, patch('app.routes.linkedin_leads._auto_send_client_mail', AsyncMock()) as mail:
        result = asyncio.run(search_linkedin_leads(LinkedInLeadSearchRequest(domain='Python', mode=mode, search_provider='linkedin_account'), db))
    assert result['saved_count'] == 1
    assert result['results'][0]['verification_status'] == 'unverified_linkedin_account'
    if mode == 'client':
        db[table].update_one.assert_awaited_once()
    else:
        db[table].insert_one.assert_awaited_once()
    browser.assert_awaited_once()
    public.assert_not_awaited()
    paid.assert_not_awaited()
    mail.assert_not_awaited()


def test_account_failure_is_explicit_and_stops_other_domains():
    with patch('app.clients.linkedin_browser.search_linkedin_account', AsyncMock(side_effect=ValueError('Sign in required'))) as browser:
        result = asyncio.run(search_linkedin_leads(LinkedInLeadSearchRequest(domains=['Python', 'Java'], search_provider='linkedin_account'), {}))
    assert result['success'] is False
    assert result['search_error'] == 'Sign in required'
    assert result['saved_count'] == 0
    browser.assert_awaited_once()
