import asyncio, json
from motor.motor_asyncio import AsyncIOMotorClient
from app.config import get_settings
from app.routes.shortlists import _build_toc
from shared.lab_planning import default_cloud_mapping
from shared.live_lab_pricing import automatic_pricing_selections, refresh_rates

async def main():
    s = get_settings()
    c = AsyncIOMotorClient(s.MONGODB_URL)
    db = c[s.MONGODB_DB_NAME]
    req = await db.requirements.find_one({'requirement_id': 'REQ-4C953BAF'}, {'_id': 0})
    shortlist = await db.shortlists.find_one({'requirement_id': req['requirement_id']}, {'_id': 0})
    trainer = next(t for t in shortlist['top_trainers'] if t['trainer_id'] == 'TR-63F6F0DB')
    toc = await _build_toc(req, trainer, db)
    assumptions = dict(cloud_provider='aws', cloud_region='ap-south-1', participant_count=req['participant_count'], hours_per_day=req['lab_hours_per_day'], fx_rate=req['fx_rate'])
    mapping = default_cloud_mapping(toc, assumptions)
    print(json.dumps({'days': len(toc.get('days', [])), 'mapping': mapping}), flush=True)
    selections = automatic_pricing_selections(toc, assumptions)
    try:
        snapshot = await asyncio.to_thread(refresh_rates, {**assumptions, 'pricing_selections': selections})
        print(json.dumps({'rates': snapshot['rate_card_overrides']}), flush=True)
    except Exception as exc:
        print(type(exc).__name__, str(exc), flush=True)
    c.close()

asyncio.run(main())
