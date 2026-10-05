"""Read-only live benchmark: generate drafts without saving to DB or sending mail.

Run from any directory with trainer-service dependencies installed:
    python microservices/tools/benchmark_ollama_planning.py --output benchmark.json
Fixtures are authored regression cases, not trainer-approved curricula or quotes.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'services' / 'trainer-service'), str(ROOT)]

from app.ollama_client import OllamaClient
from app.ollama_curriculum import generate_client_curriculum
from app.routes.toc import TocRequest
from shared.lab_planning import plan_resources


SCENARIOS = [
    dict(name='invoice_csv', domain='Python', custom_topics='CSV; duplicate invoices',
         client_notes='Finance analysts know Python lists and dictionaries. Validate invoice CSV rows; '
                      'write accepted.csv and rejected.csv with reasons. Use local machines only.',
         setup='local'),
    dict(name='containers', domain='Docker', custom_topics='Dockerfile; healthcheck',
         client_notes='Developers know Linux. Build a small HTTP service image, add a healthcheck and '
                      'diagnose a failed container. Each learner uses their own AWS EC2 VM.',
         setup='individual'),
    dict(name='managed_kubernetes', domain='AWS EKS', custom_topics='EKS; deployment; rollback',
         client_notes='Engineers know containers and Kubernetes basics. Use a shared Amazon EKS '
                      'cluster to deploy an HTTP service, detect a bad image rollout and roll back.',
         setup='shared'),
]


async def benchmark(args):
    settings = SimpleNamespace(OLLAMA_URL=args.url, OLLAMA_MODEL=args.model,
                               OLLAMA_TOC_TIMEOUT_SECONDS=args.timeout)
    results = []
    saved = {}
    if args.reuse_tocs:
        saved = {row['scenario']['name']: row['toc'] for row in
                 json.loads(Path(args.reuse_tocs).read_text(encoding='utf-8'))['results'] if row.get('toc')}
    for scenario in SCENARIOS:
        if args.scenario and args.scenario != scenario['name']:
            continue
        started = time.monotonic()
        result = {'scenario': scenario, 'trainer_review_status': 'pending'}
        print('Running ' + scenario['name'], flush=True)
        try:
            request = TocRequest(**{key: scenario[key] for key in ('domain', 'custom_topics', 'client_notes')},
                                 duration_days=1, hours_per_day=6, participant_count=12)
            toc = saved.get(scenario['name'])
            if toc is None:
                toc = await generate_client_curriculum(request, settings)
            else:
                result['toc_reused_from'] = args.reuse_tocs
            result['toc'] = toc
            result['toc_gate_passed'] = not toc['quality']['validation_errors']
            print('TOC complete; checking resources for ' + scenario['name'], flush=True)
            assumptions = dict(participant_count=12, hours_per_day=6, cloud_provider='aws',
                               lab_setup=scenario['setup'])
            try:
                result['resources'] = await plan_resources('ai', toc, assumptions,
                    OllamaClient(args.url, timeout=args.timeout), args.model, native_schema=True)
                result['resource_gate_passed'] = True
            except Exception as exc:
                result['resource_gate_passed'] = False
                result['resource_error'] = type(exc).__name__ + ': ' + str(exc)
                result['template_fallback_resources'] = await plan_resources('template', toc, assumptions)
        except Exception as exc:
            result['error'] = type(exc).__name__ + ': ' + str(exc)
        result['elapsed_seconds'] = round(time.monotonic() - started, 2)
        results.append(result)
        print(json.dumps({key: value for key, value in result.items()
                          if key not in ('toc', 'resources', 'scenario')}), flush=True)
    report = {'model': args.model, 'created_at': datetime.now(timezone.utc).isoformat(),
              'technical_accuracy_verified': False, 'pricing_verified': False,
              'limitations': ['Passing validates content and resource constraints, not trainer approval.',
                              'No cloud resources were provisioned and no prices were fetched.'],
              'results': results}
    Path(args.output).write_text(json.dumps(report, indent=2), encoding='utf-8')
    return all(row.get('toc_gate_passed') and row.get('resource_gate_passed') for row in results)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://localhost:11434/api/generate')
    parser.add_argument('--model', default='qwen3:8b')
    parser.add_argument('--timeout', type=int, default=300)
    parser.add_argument('--scenario', choices=[case['name'] for case in SCENARIOS])
    parser.add_argument('--output', required=True)
    parser.add_argument('--reuse-tocs', help='Reuse TOCs in a previous report to benchmark only resource planning')
    sys.exit(0 if asyncio.run(benchmark(parser.parse_args())) else 1)
