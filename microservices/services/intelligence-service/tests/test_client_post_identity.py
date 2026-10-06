import asyncio
import re
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from pymongo.errors import DuplicateKeyError
from app.clients.client_post_identity import post_identity, post_lookup, save_client_post


def test_activity_permalink_variants_have_one_identity_and_find_legacy_urls():
    urls = ['https://www.linkedin.com/posts/author-python-activity-1234567890123456789-abcd?trk=search',
            'https://in.linkedin.com/feed/update/urn:li:activity:1234567890123456789/',
            'https://www.linkedin.com/feed/update/urn%3Ali%3Aactivity%3A1234567890123456789/']
    assert len({post_identity(url) for url in urls}) == 1
    pattern = post_lookup(urls[0])['$or'][1]['source_url']['$regex']
    assert all(re.search(pattern, url, re.I) for url in urls)
    assert not re.search(pattern, urls[0].replace('1234567890123456789', '12345678901234567890'))


def test_url_fallback_ignores_tracking_and_does_not_merge_different_posts():
    assert post_identity('https://in.linkedin.com/posts/author-one/?trk=1') == post_identity('https://www.linkedin.com/posts/author-one')
    assert post_identity('https://www.linkedin.com/pulse/first') != post_identity('https://www.linkedin.com/pulse/second')


def test_concurrent_insert_updates_existing_post_without_resetting_status():
    table = AsyncMock()
    table.update_one.side_effect = [DuplicateKeyError('duplicate post key'), SimpleNamespace(upserted_id=None)]
    lead = {'source_url': 'https://www.linkedin.com/posts/author-one', 'lead_id': 'CL-1', 'domain': 'Python', 'status': 'new'}
    saved = asyncio.run(save_client_post(lead, {'client_leads': table}, datetime.utcnow()))
    assert not saved
    assert table.update_one.await_count == 2
    mutation = table.update_one.await_args.args[1]
    assert 'status' not in mutation['$set']
    assert mutation['$addToSet']['matched_domains']['$each'] == ['Python']
