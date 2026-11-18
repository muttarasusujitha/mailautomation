import asyncio
import json
from datetime import datetime, timedelta

import pytest
from pymongo.errors import DuplicateKeyError

from app.merge_duplicate_leads import plan_merges, run
from app.clients.lead_identity import save_trainer_lead
from fake_mongo import FakeDB

T0 = datetime(2026, 1, 1)
NOW = datetime(2026, 11, 16, 12, 0)


def lead(lead_id, url, minutes, **fields):
    return {'lead_id': lead_id, 'source_url': url, 'linkedin_url': url, 'created_at': T0 + timedelta(minutes=minutes),
            'updated_at': T0 + timedelta(minutes=minutes), 'status': 'new', **fields}


def seed():
    db = FakeDB()
    rows = [
        lead('TPL-OLD', 'https://linkedin.com/in/ravi', 0, name='Ravi', email=''),
        lead('TPL-COPY1', 'https://www.linkedin.com/in/ravi/', 5, name='Ravi K', email='ravi@example.com',
             status='contacted', last_emailed_at=T0 + timedelta(days=3), updated_at=T0 + timedelta(days=3)),
        lead('TPL-COPY2', 'http://in.linkedin.com/in/Ravi?trk=1', 9, phone='+919999999999', status='new',
             updated_at=T0 + timedelta(days=9)),
        lead('TPL-ASHA', 'https://www.linkedin.com/in/asha', 1),
        lead('TPL-NAUKRI', 'https://naukri.com/resume/java', 2),
        lead('TPL-NAUKRI2', 'https://www.naukri.com/resume/java/', 3, status='rejected'),
        {'lead_id': 'TPL-NOURL', 'name': 'Manual entry', 'created_at': T0},
    ]
    for row in rows:
        asyncio.run(db['trainer_profile_leads'].insert_one(row))
    return db


def test_plan_keeps_the_oldest_fills_empty_fields_and_keeps_the_latest_decision():
    db = seed()
    merges, keys = plan_merges(db['trainer_profile_leads'].docs, NOW)
    by_key = {merge['key']: merge for merge in merges}
    ravi = by_key['https://www.linkedin.com/in/ravi']
    assert ravi['keep']['lead_id'] == 'TPL-OLD'
    assert [doc['lead_id'] for doc in ravi['duplicates']] == ['TPL-COPY1', 'TPL-COPY2']
    updates = ravi['updates']
    # Name is kept, empty email and phone are filled, and "contacted" is not reset to "new".
    assert 'name' not in updates and updates['email'] == 'ravi@example.com' and updates['phone'] == '+919999999999'
    assert updates['status'] == 'contacted' and updates['last_emailed_at'] == T0 + timedelta(days=3)
    naukri = by_key['https://www.naukri.com/resume/java']
    assert naukri['keep']['lead_id'] == 'TPL-NAUKRI' and naukri['updates']['status'] == 'rejected'
    assert [key for _id, key in keys] == ['https://www.linkedin.com/in/asha']


def test_dry_run_changes_nothing():
    db = seed()
    before = [dict(doc) for doc in db['trainer_profile_leads'].docs]
    report = asyncio.run(run(db, apply=False, now=NOW))
    assert '2 profile(s) are saved more than once; 3 copy/copies would be merged.' in report['summary']
    assert db['trainer_profile_leads'].docs == before and not db['trainer_profile_leads_merged'].docs


def test_apply_backs_up_archives_merges_and_adds_the_unique_index(tmp_path):
    db = seed()
    report = asyncio.run(run(db, apply=True, backup_dir=str(tmp_path), now=NOW))
    assert report['archived'] == 3 and report['merged_profiles'] == 2 and report['keys_set'] == 1
    backup = json.loads((tmp_path / 'trainer-lead-merge-backup-20261116T120000.json').read_text())
    assert sorted(doc['lead_id'] for doc in backup) == ['TPL-COPY1', 'TPL-COPY2', 'TPL-NAUKRI', 'TPL-NAUKRI2', 'TPL-OLD']
    live = {doc['lead_id']: doc for doc in db['trainer_profile_leads'].docs}
    assert sorted(live) == ['TPL-ASHA', 'TPL-NAUKRI', 'TPL-NOURL', 'TPL-OLD']
    assert live['TPL-OLD']['email'] == 'ravi@example.com' and live['TPL-OLD']['status'] == 'contacted'
    assert live['TPL-ASHA']['profile_key'] == 'https://www.linkedin.com/in/asha'
    assert 'profile_key' not in live['TPL-NOURL']
    archived = {doc['lead_id']: doc['merged_into'] for doc in db['trainer_profile_leads_merged'].docs}
    assert archived == {'TPL-COPY1': 'TPL-OLD', 'TPL-COPY2': 'TPL-OLD', 'TPL-NAUKRI2': 'TPL-NAUKRI'}
    # The unique index now stops a second copy, and a save updates the kept lead.
    with pytest.raises(DuplicateKeyError):
        asyncio.run(db['trainer_profile_leads'].insert_one({'lead_id': 'X', 'profile_key': 'https://www.linkedin.com/in/asha'}))
    saved = asyncio.run(save_trainer_lead(db, {'lead_id': 'TPL-NEW', 'source_url': 'https://linkedin.com/in/ravi'}, NOW))
    assert saved['lead_id'] == 'TPL-OLD' and not saved['created']
    # Running it again finds nothing more to merge.
    again = asyncio.run(run(db, apply=True, backup_dir=str(tmp_path), now=NOW))
    assert again['archived'] == 0 and again['merged_profiles'] == 0 and again['backup'] == ''


@pytest.mark.parametrize('kept,copy,expected', [
    # A failed send or a later automatic update never undoes a decision.
    ({'status': 'converted'}, {'status': 'outreach_failed', 'updated_at': T0 + timedelta(days=30)}, None),
    ({'status': 'new'}, {'status': 'contacted'}, 'contacted'),
    ({'status': 'contacted'}, {'status': 'rejected'}, 'rejected'),
    ({'status': 'reviewed'}, {'status': 'found', 'updated_at': T0 + timedelta(days=30)}, None),
])
def test_merge_keeps_the_furthest_status(kept, copy, expected):
    docs = [lead('TPL-OLD', 'https://www.linkedin.com/in/ravi', 0, **kept),
            lead('TPL-COPY', 'https://linkedin.com/in/ravi', 5, **copy)]
    for index, doc in enumerate(docs):
        doc['_id'] = index
    merges, _keys = plan_merges(docs, NOW)
    assert merges[0]['updates'].get('status') == expected


def test_a_contact_taken_from_a_copy_brings_its_verification():
    docs = [lead('TPL-OLD', 'https://www.linkedin.com/in/ravi', 0, verification_tier='linkedin_signal', confidence=0.75),
            lead('TPL-COPY', 'https://linkedin.com/in/ravi', 5, email='ravi@example.com',
                 verification_tier='contact_in_post', confidence=0.9)]
    for index, doc in enumerate(docs):
        doc['_id'] = index
    updates = plan_merges(docs, NOW)[0][0]['updates']
    assert updates['email'] == 'ravi@example.com'
    assert updates['verification_tier'] == 'contact_in_post' and updates['confidence'] == 0.9


def test_apply_merges_the_leads_as_they_are_when_merged(tmp_path):
    from app.merge_duplicate_leads import apply_merges
    db = seed()
    merges, keys = plan_merges(db['trainer_profile_leads'].docs, NOW)
    # The service changes a copy after the plan was made.
    asyncio.run(db['trainer_profile_leads'].update_one(
        {'lead_id': 'TPL-COPY2'}, {'$set': {'notes': 'called today', 'status': 'converted', 'updated_at': NOW}}))
    asyncio.run(apply_merges(db, merges, keys, NOW))
    archived = {doc['lead_id']: doc for doc in db['trainer_profile_leads_merged'].docs}
    kept = next(doc for doc in db['trainer_profile_leads'].docs if doc['lead_id'] == 'TPL-OLD')
    assert archived['TPL-COPY2']['notes'] == 'called today'
    assert kept['status'] == 'converted' and kept['notes'] == 'called today'


@pytest.mark.parametrize('statuses,expected', [
    (('details_requested', 'training_confirmed'), 'training_confirmed'),
    (('training_confirmed', 'details_requested'), 'training_confirmed'),
    (('outreach_sent', 'interview_scheduled'), 'interview_scheduled'),
    (('converted', 'some_new_stage'), 'converted'),
])
def test_later_pipeline_stages_win(statuses, expected):
    docs = [lead(f'TPL-{index}', 'https://www.linkedin.com/in/ravi', index, status=status, _id=index)
            for index, status in enumerate(statuses)]
    merges, _keys = plan_merges(docs, NOW)
    assert merges[0]['updates'].get('status', docs[0]['status']) == expected


def test_the_dry_run_lists_each_status_change():
    db = seed()
    summary = asyncio.run(run(db, apply=False, now=NOW))['summary']
    assert 'https://www.linkedin.com/in/ravi: keep TPL-OLD, merge TPL-COPY1, TPL-COPY2; status new -> contacted' in summary


def test_apply_needs_a_backup_folder(capsys):
    from app.merge_duplicate_leads import _main
    with pytest.raises(SystemExit):
        asyncio.run(_main(['--apply']))
    assert '--apply needs --backup-dir' in capsys.readouterr().err
