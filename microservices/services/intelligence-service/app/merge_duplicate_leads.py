"""Merge trainer leads that were saved more than once for the same profile. Writes a backup first.

Run inside the intelligence-service container. Back up the database first (mongodump), and
pause the lead bot and searches while --apply runs, because the plan is made from one read:

    docker exec ts-intelligence-service python -m app.merge_duplicate_leads      # dry run
    docker exec ts-intelligence-service python -m app.merge_duplicate_leads --apply --backup-dir /tmp/merge
    docker cp ts-intelligence-service:/tmp/merge ./trainer-lead-merge-backup     # keep the backup

Leads are the same profile when their URLs give the same profile key (lead_identity.lead_key):
www/in./no-www hosts, http/https, a trailing slash, query strings and /in/<slug>/details pages
all count as one profile. For each profile saved more than once:

- the oldest lead is kept, with its lead_id;
- its empty fields are filled from the copies, oldest copy first; a contact taken from a copy
  brings that copy's verification tier when the kept lead's tier is weak;
- it takes the furthest status of any copy (new/found < failed send < reviewed < contacted <
  later stages and decisions such as converted or rejected), so progress is never reset;
- the copies are moved to trainer_profile_leads_merged, each with merged_into = the kept lead_id.

Every remaining lead then gets its profile_key, and the unique profile_key index is created.
Client leads are not touched: they already have a unique post_key.
"""
import argparse
import asyncio
import json
import logging
import os
from datetime import datetime

from app.clients.lead_identity import lead_key

logger = logging.getLogger(__name__)

COLLECTION = 'trainer_profile_leads'
ARCHIVE = 'trainer_profile_leads_merged'
_NOT_FILLED = ('_id', 'lead_id', 'created_at', 'updated_at', 'status', 'profile_key', 'last_emailed_at',
               'verification_tier', 'confidence')
_CONTACT_FIELDS = ('email', 'phone', 'contact_email', 'contact_phone')
_WEAK_TIERS = ('', 'unverified', 'linkedin_signal')
# How far a lead has moved on. Any status not listed is a later pipeline stage or a decision
# (converted, rejected, interview_scheduled, ...), which a copy that is only new or found never undoes.
_STATUS_RANK = {'': 0, 'new': 0, 'found': 0, 'outreach_failed': 1, 'reviewed': 2, 'contacted': 3, 'outreach_sent': 3}


def _status_rank(doc):
    return _STATUS_RANK.get(str(doc.get('status') or ''), 4)


def _empty(value):
    return value is None or value == '' or value == [] or value == {}


def _when(doc, field):
    value = doc.get(field)
    return value if isinstance(value, datetime) else datetime.min


def _age(doc):
    return (_when(doc, 'created_at'), str(doc.get('_id', '')))


def plan_merges(docs, now=None):
    """Group leads by profile key. Returns (merges, keys).

    merges: [{'key', 'keep', 'duplicates', 'updates'}] for profiles saved more than once.
    keys: [(_id, key)] for single leads that do not have their profile_key yet.
    """
    now = now or datetime.utcnow()
    groups = {}
    for doc in docs:
        key = lead_key(doc)
        if key:
            groups.setdefault(key, []).append(doc)
    merges, keys = [], []
    for key, group in groups.items():
        if len(group) == 1:
            if group[0].get('profile_key') != key:
                keys.append((group[0]['_id'], key))
            continue
        group = sorted(group, key=_age)
        keep, duplicates = group[0], group[1:]
        updates = {}
        contact_from = None
        for doc in duplicates:
            for field, value in doc.items():
                if field in _NOT_FILLED or _empty(value) or not _empty(keep.get(field)) or field in updates:
                    continue
                updates[field] = value
                if field in _CONTACT_FIELDS and contact_from is None:
                    contact_from = doc
        # A contact taken from a copy brings that copy's verification, unless the kept lead's is stronger.
        if contact_from is not None and (keep.get('verification_tier') or '') in _WEAK_TIERS:
            for field in ('verification_tier', 'confidence'):
                if not _empty(contact_from.get(field)):
                    updates[field] = contact_from[field]
        # The furthest status wins; between equal stages, the most recently updated copy.
        furthest = max(group, key=lambda doc: (_status_rank(doc), _when(doc, 'updated_at'), _age(doc)))
        if _status_rank(furthest) > 0 and furthest.get('status') != keep.get('status'):
            updates['status'] = furthest['status']
        emailed = [doc['last_emailed_at'] for doc in group if isinstance(doc.get('last_emailed_at'), datetime)]
        if emailed and max(emailed) != keep.get('last_emailed_at'):
            updates['last_emailed_at'] = max(emailed)
        updates['profile_key'] = key
        updates['updated_at'] = now
        merges.append({'key': key, 'keep': keep, 'duplicates': duplicates, 'updates': updates})
    return merges, keys


def _backup(merges, folder, now):
    from bson import json_util

    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f'trainer-lead-merge-backup-{now.strftime("%Y%m%dT%H%M%S")}.json')
    docs = [doc for merge in merges for doc in (merge['keep'], *merge['duplicates'])]
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(json_util.dumps(docs, indent=1))
    return path


async def apply_merges(db, merges, keys, now=None):
    """Update the kept leads, archive the copies, and set profile keys. Safe to run again.

    The kept lead is updated before its copies are removed, so a stop half-way loses nothing:
    running the script again merges whatever copies are left.
    """
    from pymongo.errors import DuplicateKeyError

    now = now or datetime.utcnow()
    table, archive = db[COLLECTION], db[ARCHIVE]
    archived = 0
    for merge in merges:
        keep_filter = {'_id': merge['keep']['_id']}
        keep_id = merge['keep'].get('lead_id')
        updates = {name: value for name, value in merge['updates'].items() if name != 'profile_key'}
        await table.update_one(keep_filter, {'$set': updates})
        for doc in merge['duplicates']:
            # The copy as it is now, in case the service changed it after the plan was made.
            current = await table.find_one({'_id': doc['_id']})
            if current is None:
                continue
            await archive.replace_one({'_id': doc['_id']}, {**current, 'merged_into': keep_id, 'merged_at': now},
                                      upsert=True)
            await table.delete_one({'_id': doc['_id']})
            archived += 1
        try:
            await table.update_one(keep_filter, {'$set': {'profile_key': merge['key']}})
        except DuplicateKeyError:
            # A search saved this profile again while the script ran; run the script again to merge it.
            logger.warning('Profile %s was saved again during the merge; run the script again.', merge['key'])
    keyed = 0
    for doc_id, key in keys:
        try:
            await table.update_one({'_id': doc_id}, {'$set': {'profile_key': key}})
            keyed += 1
        except DuplicateKeyError:
            logger.warning('Profile %s was saved again during the merge; run the script again.', key)
    await table.create_index('profile_key', unique=True, partialFilterExpression={'profile_key': {'$type': 'string'}})
    return {'archived': archived, 'merged_profiles': len(merges), 'keys_set': keyed}


def _describe(merges, keys):
    lines = [f'{len(merges)} profile(s) are saved more than once; '
             f'{sum(len(merge["duplicates"]) for merge in merges)} copy/copies would be merged.',
             f'{len(keys)} other lead(s) would get their profile key.']
    for merge in merges[:50]:
        copies = ', '.join(doc.get('lead_id', '?') for doc in merge['duplicates'])
        changes = ', '.join(sorted(name for name in merge['updates'] if name not in ('profile_key', 'updated_at')))
        lines.append(f'  {merge["key"]}: keep {merge["keep"].get("lead_id")}, merge {copies}'
                     + (f' (fills: {changes})' if changes else ''))
    if len(merges) > 50:
        lines.append(f'  ... and {len(merges) - 50} more')
    return '\n'.join(lines)


async def run(db, apply=False, backup_dir='.', now=None):
    now = now or datetime.utcnow()
    docs = await db[COLLECTION].find({}).to_list(length=None)
    merges, keys = plan_merges(docs, now)
    report = {'leads': len(docs), 'merges': merges, 'keys': keys, 'summary': _describe(merges, keys)}
    if not apply:
        return report
    report['backup'] = _backup(merges, backup_dir, now) if merges else ''
    report.update(await apply_merges(db, merges, keys, now))
    return report


async def _main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--apply', action='store_true', help='make the changes; without it nothing is written')
    parser.add_argument('--backup-dir', default='',
                        help='folder for the JSON backup of every lead that changes (required with --apply)')
    args = parser.parse_args(argv)
    if args.apply and not args.backup_dir:
        parser.error('--apply needs --backup-dir. A folder inside the container is lost on the next deploy, '
                     'so copy the backup file out afterwards (docker cp).')

    from motor.motor_asyncio import AsyncIOMotorClient
    from app.config import get_settings

    settings = get_settings()
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    try:
        report = await run(client[settings.MONGODB_DB_NAME], apply=args.apply, backup_dir=args.backup_dir)
    finally:
        client.close()
    print(report['summary'])
    if args.apply:
        print(json.dumps({name: report[name] for name in ('backup', 'archived', 'merged_profiles', 'keys_set')}))
    else:
        print('Dry run: nothing was changed. Back up the database, then run again with --apply.')


if __name__ == '__main__':
    asyncio.run(_main())
