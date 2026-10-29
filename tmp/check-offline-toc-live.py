import asyncio
import json
from pathlib import Path
from app.routes.toc import TocRequest, generate_toc


class Collection:
    async def find_one(self, *args, **kwargs):
        return None
    async def insert_one(self, document):
        pass


class Database:
    def __getitem__(self, key):
        return Collection()
    def __getattr__(self, key):
        return Collection()


async def main():
    output = Path('/tmp/offline-toc-live')
    output.mkdir(exist_ok=True)
    for domain, days, hours in [('Engineering Security Product', 2, 6), ('AWS Security', 10, 4),
                                ('Quality Engineering', 18, 4), ('Codex', 3, 8), ('Python', 2, 4)]:
        request = TocRequest(domain=domain, duration_days=days, hours_per_day=hours,
            generation_mode='template', training_dates='2026-11-02', audience_level='Working practitioners')
        result = await generate_toc(request, Database())
        toc = result['toc_data']
        path = output / (domain.replace(' ', '_') + '.json')
        path.write_text(json.dumps(toc, indent=2))
        print(json.dumps({'domain': domain, 'days': len(toc['days']),
            'modules': sum(len(day.get('modules', [])) for day in toc['days']),
            'minutes': sum(day.get('minutes') or 0 for day in toc['days']),
            'status': toc['quality']['status'], 'errors': toc['quality'].get('validation_errors', [])}), flush=True)


asyncio.run(main())
