import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from app.clients.public_search import parse_results
from app.routes.linkedin_leads import LinkedInLeadSearchRequest, search_linkedin_leads


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
    with patch('app.clients.public_discovery.search_public', AsyncMock(return_value=[{'url': url, 'title': content, 'content': content}])), patch('app.routes.linkedin_leads._plain_tavily_search', AsyncMock()) as paid, patch('app.routes.linkedin_leads._auto_send_client_mail', AsyncMock()) as mail:
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
