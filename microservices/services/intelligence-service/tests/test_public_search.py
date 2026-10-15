import asyncio
from unittest.mock import AsyncMock, patch
from urllib.parse import quote

import pytest
from app.clients.public_search import parse_results, search_public_many
from app.routes.linkedin_leads import LinkedInLeadSearchRequest, search_linkedin_leads


class _Page:
    def __init__(self, status, body):
        self.status_code = status
        self.content = body


def _profile_page(with_next=False):
    target = quote('https://www.linkedin.com/in/ravi', safe='')
    html = (
        f'<a class="result__a" href="//duckduckgo.com/l/?uddg={target}&rut=1">Ravi Kumar</a>'
        f'<a class="result__snippet" href="//duckduckgo.com/l/?uddg={target}">Python corporate trainer</a>'
    )
    if with_next:
        html += '<form action="/html/" method="post"><input name="q" value="Python"><input name="vqd" value="1"></form>'
    return _Page(200, html.encode())


def test_feed_deduplicates_and_rejects_lookalike_hosts():
    feed = b'<rss><channel><item><link>https://linkedin.com/in/alice?x=1</link></item><item><link>https://linkedin.com/in/alice</link></item><item><link>https://linkedin.com.evil.test/in/alice</link></item></channel></rss>'
    assert len(parse_results(feed, 10)) == 1


@pytest.mark.parametrize('feed', [b'<html/>', b'blocked', b'<!DOCTYPE rss><rss/>'])
def test_blocked_or_unsafe_feed_is_explicit_error(feed):
    with pytest.raises(ValueError):
        parse_results(feed, 10)


@pytest.mark.parametrize('mode,collection,url,content', [
    ('trainer', 'trainer_profile_leads', 'https://linkedin.com/in/alice', 'Python corporate trainer'),
    ('client', 'client_leads', 'https://linkedin.com/posts/acme', 'Python corporate trainer required for training requirement'),
])
def test_public_fetch_saves_separately_without_paid_search_or_email(mode, collection, url, content):
    db = {name: AsyncMock() for name in ('trainer_profile_leads', 'client_leads')}
    for table in db.values():
        table.find_one.return_value = None
    row = [{'url': url, 'title': content, 'content': content}]
    with patch('app.clients.public_discovery.search_public', AsyncMock(return_value=row)), patch('app.clients.public_search.search_public_many', AsyncMock(return_value=(row, 1))), patch('app.routes.linkedin_leads._plain_tavily_search', AsyncMock()) as paid, patch('app.routes.linkedin_leads._auto_send_client_mail', AsyncMock()) as mail:
        result = asyncio.run(search_linkedin_leads(LinkedInLeadSearchRequest(domain='Python', mode=mode), db))
    assert result['saved_count'] == 1
    if mode == 'client':
        db[collection].update_one.assert_awaited_once()
        assert db[collection].update_one.await_args.kwargs['upsert'] is True
    else:
        db[collection].insert_one.assert_awaited_once()
    db['client_leads' if mode == 'trainer' else 'trainer_profile_leads'].insert_one.assert_not_awaited()
    paid.assert_not_awaited()
    mail.assert_not_awaited()


def test_a_connect_timeout_then_a_results_page_keeps_the_profile():
    sequence = [(None, True), (_profile_page(), False)]

    async def fetch(method, url, **kwargs):
        return sequence.pop(0)

    with patch('app.clients.public_search._fetch', side_effect=fetch):
        found, attempts = asyncio.run(search_public_many(['Python corporate trainer'], 1))
    assert attempts == 1
    assert [row['url'] for row in found] == ['https://www.linkedin.com/in/ravi']


def test_a_timeout_on_the_next_page_keeps_profiles_already_read():
    sequence = [(_Page(200, b'ok'), False), (_profile_page(with_next=True), False), (None, True), (_Page(202, b'anomaly-modal'), False)]

    async def fetch(method, url, **kwargs):
        return sequence.pop(0)

    with patch('app.clients.public_search._fetch', side_effect=fetch):
        found, attempts = asyncio.run(search_public_many(['Python corporate trainer', 'Python freelance trainer'], 50))
    assert attempts == 2
    assert [row['url'] for row in found] == ['https://www.linkedin.com/in/ravi']


def test_repeated_timeouts_stop_without_raising():
    calls = {'n': 0}

    async def fetch(method, url, **kwargs):
        calls['n'] += 1
        return None, True

    with patch('app.clients.public_search._fetch', side_effect=fetch):
        found, attempts = asyncio.run(search_public_many(['q1', 'q2', 'q3', 'q4'], 50))
    assert found == []
    assert attempts == 2
    assert calls['n'] == 4
