"""Persistent public and connected-account collection with an execution lease."""
import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from shared.database.service import get_db
from app.routes.linkedin_leads import LinkedInLeadSearchRequest, search_linkedin_leads
from app.clients.course_domains import it_course_domains
from app.clients.client_post_scan import scan_client_posts

router = APIRouter()
logger = logging.getLogger(__name__)


class BotSettings(BaseModel):
    enabled: bool = False
    domain_source: Literal['manual', 'it_catalog', 'all'] = 'manual'
    domains: list[str] = Field(default_factory=lambda: ['Python', 'AWS'], max_length=4)
    interval_minutes: int = Field(default=60, ge=10, le=1440)


@router.get('/{mode}')
async def status(mode: Literal['trainer', 'client'], db=Depends(get_db)):
    config = await db['lead_bots'].find_one({'_id': mode}, {'_id': 0}) or BotSettings(
        interval_minutes=60 if mode == 'trainer' else 10,
        domain_source='manual' if mode == 'trainer' else 'all').model_dump()
    if mode == 'client':
        config.update(interval_minutes=10, scan_strategy='posts_all_domains')
    if config.get('domain_source') in ('it_catalog', 'all'):
        try:
            catalog = it_course_domains(include_nontechnical=True) if config['domain_source'] == 'all' else it_course_domains()
            config['catalog_count'] = len(catalog)
            config['next_domains'] = list(catalog)
        except ValueError as exc:
            config['catalog_error'] = str(exc)
    return config


@router.put('/{mode}')
async def configure(mode: Literal['trainer', 'client'], payload: BotSettings, db=Depends(get_db)):
    from fastapi import HTTPException
    domains = list(dict.fromkeys(d.strip()[:120] for d in payload.domains if d.strip()))
    if payload.domain_source in ('it_catalog', 'all'):
        if mode != 'client':
            raise HTTPException(422, 'Catalog collection is available for client requirements.')
        if payload.enabled and payload.domain_source == 'it_catalog':
            try:
                it_course_domains()
            except ValueError as exc:
                raise HTTPException(503, str(exc)) from exc
    elif not domains:
        raise HTTPException(422, 'Enter at least one domain')
    await db['lead_bots'].update_one({'_id': mode}, {'$set': {
        **payload.model_dump(), 'domains': domains, 'next_run': datetime.utcnow(),
        'interval_minutes': 10 if mode == 'client' else payload.interval_minutes,
    }}, upsert=True)
    return await status(mode, db)


async def collect_due(db, mode):
    now, token = datetime.utcnow(), uuid.uuid4().hex
    config = await db['lead_bots'].find_one_and_update({
        '_id': mode, 'enabled': True,
        '$and': [
            {'$or': [{'next_run': {'$lte': now}}, {'next_run': {'$exists': False}}]},
            {'$or': [{'lease_until': {'$lte': now}}, {'lease_until': {'$exists': False}}]},
        ],
    }, {'$set': {'lease_until': now + timedelta(minutes=20), 'lease_token': token,
                 'status': 'running', 'last_started': now}})
    if not config:
        return
    coverage = {}
    try:
        domains = config['domains']
        if config.get('domain_source') in ('it_catalog', 'all'):
            try:
                catalog = it_course_domains(include_nontechnical=True) if config['domain_source'] == 'all' else it_course_domains()
            except ValueError:
                if config['domain_source'] != 'all':
                    raise
                catalog = ()  # Classification must never gate all-domain collection.
            domains = list(catalog)
            coverage = {'catalog_count': len(catalog)}
        await db['lead_bots'].update_one({'_id': mode, 'lease_token': token}, {
            '$set': {'active_domains': domains},
        })
        if mode == 'client':
            if config.get('domain_source') == 'all':
                scan = scan_client_posts(domains, db, include_unmatched=True)
            else:
                scan = scan_client_posts(domains, db)
            result = await asyncio.wait_for(scan, timeout=240)
        else:
            result = await asyncio.wait_for(search_linkedin_leads(LinkedInLeadSearchRequest(
                mode=mode, domains=domains, search_provider='auto',
                save=True, max_results=60, max_queries=2), db), timeout=800)
        error = result.get('error') or result.get('search_error') or ''
        outcome = {'status': 'error' if error else 'completed' if result.get('found') else 'no_results',
                   'last_error': str(error)[:500], 'found': result.get('found', 0),
                   'saved': result.get('saved_count', 0), 'domain_outcomes': result.get('domain_outcomes', []),
                   'scanned_posts': result.get('scanned_posts', 0), 'scan_warnings': result.get('scan_warnings', []),
                   **coverage}
    except Exception as exc:
        outcome = {'status': 'error', 'last_error': str(exc)[:500] or type(exc).__name__, 'found': 0, 'saved': 0,
                   'domain_outcomes': [], 'scan_warnings': [], 'scanned_posts': 0}
    await db['lead_bots'].update_one({'_id': mode, 'lease_token': token}, {
        '$set': {**outcome, 'last_finished': datetime.utcnow(),
                 'next_run': max(datetime.utcnow(), now + timedelta(minutes=10)) if mode == 'client'
                             else datetime.utcnow() + timedelta(minutes=config.get('interval_minutes', 60))},
        '$unset': {'lease_until': '', 'lease_token': ''},
    })


async def _run_mode(mode):
    while True:
        try:
            db = await get_db()
            if mode == 'client':
                # Upgrade persisted hourly settings without enabling paused bots.
                await db['lead_bots'].update_one(
                    {'_id': mode, 'interval_minutes': {'$ne': 10}},
                    {'$set': {'interval_minutes': 10, 'next_run': datetime.utcnow()}})
                await db['lead_bots'].update_one(
                    {'_id': mode, 'domain_source': 'it_catalog'},
                    {'$set': {'domain_source': 'all', 'next_run': datetime.utcnow()}})
            await collect_due(db, mode)
        except Exception:
            logger.exception('Lead collection cycle failed')
        await asyncio.sleep(30)


async def run_loop():
    # Keep independent schedules when trainer discovery takes over ten minutes.
    async with asyncio.TaskGroup() as group:
        for mode in ('trainer', 'client'):
            group.create_task(_run_mode(mode))
