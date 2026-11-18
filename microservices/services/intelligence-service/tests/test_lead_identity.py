import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.clients import lead_identity
from app.clients.lead_identity import lead_key, save_trainer_lead, trainer_lead_key
from fake_mongo import FakeDB

NOW = datetime(2026, 11, 16, 9, 0)


@pytest.mark.parametrize('url', [
    'https://www.linkedin.com/in/ravi-kumar',
    'https://linkedin.com/in/ravi-kumar/',
    'http://in.linkedin.com/in/Ravi-Kumar?trk=public_profile',
    'https://www.linkedin.com/in/ravi-kumar/details/experience/',
])
def test_profile_url_variants_have_one_key(url):
    assert trainer_lead_key(url) == 'https://www.linkedin.com/in/ravi-kumar'


def test_post_naukri_and_unknown_urls():
    post = 'https://www.linkedin.com/posts/ravi_python-trainer-activity-7123456789012345678-AbCd?utm=1'
    feed = 'https://www.linkedin.com/feed/update/urn:li:activity:7123456789012345678/'
    assert trainer_lead_key(post) == trainer_lead_key(feed) == 'linkedin:activity:7123456789012345678'
    assert trainer_lead_key('http://naukri.com/resume/Java-Dev/?src=x') == 'https://www.naukri.com/resume/java-dev'
    assert trainer_lead_key('https://www.linkedin.com/in/ravi') != trainer_lead_key('https://www.linkedin.com/in/ravi-k')
    assert trainer_lead_key('') == trainer_lead_key('mailto:a@b.c') == trainer_lead_key('https://x.test:bad/') == ''


def test_lead_key_falls_back_to_linkedin_url_then_slug():
    assert lead_key({'source_url': '', 'linkedin_url': 'https://linkedin.com/in/asha'}) == 'https://www.linkedin.com/in/asha'
    assert lead_key({'linkedin_slug': 'Asha'}) == 'https://www.linkedin.com/in/asha'
    assert lead_key({'name': 'No URL'}) == ''


def lead(url, **fields):
    return {'lead_id': fields.pop('lead_id', 'TPL-NEW'), 'source_url': url, 'linkedin_url': url, 'name': 'Ravi Kumar',
            'status': 'new', 'domain': 'Python', 'email': '', 'contact_email': '', **fields}


def test_second_save_of_the_same_profile_updates_and_returns_the_saved_lead():
    db = FakeDB()
    first = asyncio.run(save_trainer_lead(db, lead('https://www.linkedin.com/in/ravi', lead_id='TPL-1'), NOW))
    asyncio.run(db['trainer_profile_leads'].update_one({'lead_id': 'TPL-1'}, {'$set': {'status': 'contacted'}}))
    again = asyncio.run(save_trainer_lead(db, lead('http://linkedin.com/in/ravi/', lead_id='TPL-2', name='Other title',
                                                   email='ravi@example.com', contact_email='ravi@example.com',
                                                   verification_tier='contact_in_post', confidence=0.9), NOW))
    assert first == {'lead_id': 'TPL-1', 'created': True, 'status': 'new'}
    assert again == {'lead_id': 'TPL-1', 'created': False, 'status': 'contacted'}
    rows = db['trainer_profile_leads'].docs
    assert len(rows) == 1
    saved = rows[0]
    # Empty contact fields are filled; saved values and status are kept.
    assert saved['email'] == 'ravi@example.com' and saved['name'] == 'Ravi Kumar' and saved['status'] == 'contacted'
    assert saved['verification_tier'] == 'contact_in_post'
    assert saved['profile_key'] == 'https://www.linkedin.com/in/ravi'


def test_verified_tier_is_not_downgraded_by_a_later_search():
    db = FakeDB()
    asyncio.run(db['trainer_profile_leads'].insert_one(lead('https://www.linkedin.com/in/ravi', lead_id='TPL-1',
                                                            verification_tier='internal_verified')))
    asyncio.run(save_trainer_lead(db, lead('https://www.linkedin.com/in/ravi', email='r@example.com',
                                           verification_tier='contact_in_post'), NOW))
    saved = db['trainer_profile_leads'].docs[0]
    assert saved['email'] == 'r@example.com' and saved['verification_tier'] == 'internal_verified'


@pytest.mark.parametrize('legacy', [
    {'source_url': 'https://linkedin.com/in/Ravi', 'linkedin_url': 'https://linkedin.com/in/Ravi'},
    {'source_url': 'https://in.linkedin.com/in/ravi/?trk=x', 'linkedin_url': ''},
    {'source_url': '', 'linkedin_url': '', 'linkedin_slug': 'RAVI'},
])
def test_leads_saved_before_keys_existed_are_found_and_given_the_key(legacy):
    db = FakeDB()
    asyncio.run(db['trainer_profile_leads'].insert_one({'lead_id': 'TPL-OLD', 'name': 'Ravi', 'status': 'reviewed',
                                                        'created_at': NOW, **legacy}))
    saved = asyncio.run(save_trainer_lead(db, lead('https://www.linkedin.com/in/ravi'), NOW))
    assert saved == {'lead_id': 'TPL-OLD', 'created': False, 'status': 'reviewed'}
    assert [row['profile_key'] for row in db['trainer_profile_leads'].docs] == ['https://www.linkedin.com/in/ravi']


def test_a_keyed_lead_is_not_matched_by_another_profiles_slug():
    db = FakeDB()
    asyncio.run(save_trainer_lead(db, lead('https://www.naukri.com/resume/ravi', lead_id='TPL-N', linkedin_slug='ravi'), NOW))
    created = asyncio.run(save_trainer_lead(db, lead('https://www.linkedin.com/in/ravi', lead_id='TPL-L'), NOW))
    assert created['created'] and len(db['trainer_profile_leads'].docs) == 2


def test_two_searches_saving_one_new_profile_keep_one_lead():
    db = FakeDB()
    table = db['trainer_profile_leads']
    asyncio.run(table.create_index('profile_key', unique=True, partialFilterExpression={'profile_key': {'$type': 'string'}}))
    asyncio.run(save_trainer_lead(db, lead('https://www.linkedin.com/in/ravi', lead_id='TPL-1'), NOW))
    # The second search looked before the first one saved.
    with patch.object(lead_identity, 'find_saved_trainer_lead', AsyncMock(return_value=None)):
        result = asyncio.run(save_trainer_lead(db, lead('https://linkedin.com/in/ravi', lead_id='TPL-2',
                                                        email='ravi@example.com'), NOW))
    assert result == {'lead_id': 'TPL-1', 'created': False, 'status': 'new'}
    assert len(table.docs) == 1 and table.docs[0]['email'] == 'ravi@example.com'


def test_a_legacy_copy_does_not_take_a_key_another_lead_holds():
    db = FakeDB()
    table = db['trainer_profile_leads']
    asyncio.run(table.create_index('profile_key', unique=True, partialFilterExpression={'profile_key': {'$type': 'string'}}))
    asyncio.run(table.insert_one({'lead_id': 'TPL-KEYED', 'source_url': 'https://www.linkedin.com/in/ravi',
                                  'profile_key': 'https://www.linkedin.com/in/ravi'}))
    asyncio.run(table.insert_one({'lead_id': 'TPL-COPY', 'source_url': 'https://linkedin.com/in/ravi'}))
    copy = table.docs[1]
    asyncio.run(lead_identity._refresh(table, copy, lead('https://linkedin.com/in/ravi', email='r@example.com'),
                                       'https://www.linkedin.com/in/ravi', NOW))
    assert 'profile_key' not in table.docs[1] and table.docs[1]['email'] == 'r@example.com'
