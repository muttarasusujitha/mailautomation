import asyncio
import json
from openai import AsyncOpenAI
from app.config import get_settings
from shared.lab_planning import plan_resources

async def main():
    settings = get_settings()
    async with AsyncOpenAI(api_key=settings.OPENAI_API_KEY, timeout=60, max_retries=0) as client:
        try:
            mapping = await plan_resources('ai', {'days': [
                {'day': 1, 'lab': 'Linux shell practice on an individual AWS VM for each participant'},
            ]}, {'participant_count': 2, 'cloud_provider': 'aws', 'hours_per_day': 3},
                client, settings.OPENAI_MODEL)
            print(json.dumps({'ai_planning': 'passed', 'mapping': mapping}))
        except Exception as exc:
            print(json.dumps({'ai_planning': 'failed', 'error_type': type(exc).__name__,
                'status_code': getattr(exc, 'status_code', None), 'code': getattr(exc, 'code', None)}))
            raise SystemExit(1)

asyncio.run(main())
