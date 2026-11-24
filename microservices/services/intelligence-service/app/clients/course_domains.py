"""Domains sourced from the application's IT curriculum dataset."""
import json
import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def it_course_domains(include_nontechnical=False):
    packaged = Path('/app/it-course-datasets')
    repository = Path(__file__).resolve().parents[3] / 'trainer-service/app/datasets_compact'
    root = Path(os.environ.get('IT_COURSE_DATASET_PATH') or (packaged if packaged.exists() else repository))
    domains = {}
    for path in sorted(root.glob('*.json')):
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        name = ' '.join(str(data.get('domain') or '').split())
        # This is the sole nontechnical programme in the bundled catalog.
        if name and (include_nontechnical or name.casefold() != 'project management'):
            domains.setdefault(name.casefold(), name)
    if not domains:
        raise ValueError('IT course dataset unavailable. Restore the dataset before enabling catalog collection.')
    priority = ['devops', 'python', 'java', 'cloud']
    ordered = [domains.pop(key) for key in priority if key in domains]
    return tuple(ordered + sorted(domains.values(), key=str.casefold))


def domain_batch(domains, cursor=0, size=4):
    start = max(0, int(cursor)) % len(domains)
    batch = list(domains[start:start + size])
    return batch, (start + len(batch)) % len(domains)
