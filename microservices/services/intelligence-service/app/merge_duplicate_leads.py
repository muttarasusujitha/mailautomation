"""Merge trainer leads that were saved more than once for the same profile. Writes a backup first.

Run inside the intelligence-service container, from the service folder:

    python -m app.merge_duplicate_leads                      # dry run: lists what would change
    python -m app.merge_duplicate_leads --apply --backup-dir /backups

Leads are the same profile when their URLs give the same profile key (lead_identity.lead_key):
www/in./no-www hosts, http/https, a trailing slash, query strings and /in/<slug>/details pages
all count as one profile. For each profile saved more than once:

- the oldest lead is kept, with its lead_id;
- its empty fields are filled from the copies, oldest copy first;
- it takes the latest status that a person set on any copy (anything other than new/found),
  so a contacted or rejected copy is not reset to new;
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
_INITIAL_STATUSES = ('', 'new', 'found')
_NOT_FILLED = ('_id', 'lead_id', 'created_at', 'updated_at', 'status', 'profile_key', 'last_emailed_at')


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
        for doc in duplicates:
            for field, value in doc.items():
                if field in _NOT_FILLED or _empty(value) or not _empty(keep.get(field)) or field in updates:
                    continue
                updates[field] = value
        decided = [doc for doc in group if str(doc.get('status') or '') not in _INITIAL_STATUSES]
        if decided:
            latest = max(decided, key=lambda doc: (_when(doc, 'updated_at'), _age(doc)))
            if latest.get('status') != keep.get('status'):
                updates['status'] = latest['status']
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
    """Archive the copies, update the kept leads, and set profile keys. Safe to run again."""
    from pymongo.errors import DuplicateKeyError

    now = now or datetime.utcnow()
    table, archive = db[COLLECTION], db[ARCHIVE]
    archived = 0
    for merge in merges:
        keep_id = merge['keep'].get('lead_id')
        for doc in merge['duplicates']:
            copy = {**doc, 'merged_into': keep_id, 'merged_at': now}
            await archive.replace_one({'_id': doc['_id']}, copy, upsert=True)
            await table.delete_one({'_id': doc['_id']})
            archived += 1
        try:
            await table.update_one({'_id': merge['keep']['_id']}, {'$set': merge['updates']})
        except DuplicateKeyError:
            # A search saved this profile again while the script ran; run the script again to merge it.
            updates = {name: value for name, value in merge['updates'].items() if name != 'profile_key'}
            await table.update_one({'_id': merge['keep']['_id']}, {'$set': updates})
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
    parser.add_argument('--backup-dir', default='.', help='folder for the JSON backup of every lead that changes')
    args = parser.parse_args(argv)

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
