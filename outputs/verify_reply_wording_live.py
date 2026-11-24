"""Read configuration and generate synthetic drafts; no emails or DB writes."""
import asyncio
import json

import httpx
from motor.motor_asyncio import AsyncIOMotorClient
from app.config import get_settings
from app.agents.reply_wording import WORDING_BANKS, vary_template, ai_wording_examples
from app.routes.inbox_actions import _ai_draft_reply


async def main():
    health = httpx.get('http://127.0.0.1:8002/health', timeout=15)
    health.raise_for_status()
    print('HEALTH', health.json(), flush=True)
    settings = get_settings()
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    try:
        mode = await client[settings.MONGODB_DB_NAME].automation_settings.find_one(
            {'key': 'generation_mode'}, {'_id': 0, 'value': 1})
        print('MODE', mode, flush=True)
    finally:
        client.close()
    reference = 'Thank you for sharing your availability. We will check this against the client schedule and update you on the next step.'
    history = []
    for _ in range(10):
        draft = vary_template(reference, history, seed='synthetic-preview')
        assert draft not in history
        history.insert(0, draft)
    print('TEMPLATE_CHECK', json.dumps({'situations': len(WORDING_BANKS), 'options_each': 10,
                                      'unique_previews': len(set(history)), 'samples': history[:3]}), flush=True)
    context = {
        'classification': {'scenario': 'trainer_partial_availability', 'person_type': 'trainer'},
        'extracted_request': {'sender_name': 'Mira'},
        'verified_facts': {'trainer_available': 'Tuesday, 13 October 2026, 3 PM IST',
                           'client_availability': 'not yet confirmed'},
        'recent_replies_to_this_sender': history[:3],
    }
    print('AI_EXAMPLES', json.dumps(ai_wording_examples(reference, history[:3])), flush=True)
    draft = await _ai_draft_reply(
        subject='Re: Interview availability',
        body='I am available on Tuesday, 13 October 2026 at 3 PM IST.',
        workflow_context=context, reference_reply={'body': reference}, require_openai=True,
    )
    print('AI_DRAFT', json.dumps({'body': draft, 'analysis': context.get('reply_analysis')}), flush=True)
    assert draft, 'No usable non-repetitive draft produced'


asyncio.run(main())
