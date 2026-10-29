"""Auditable AI pricing resolver for live, RAG evidence, and manual fallback."""
import math
from datetime import datetime, timezone


def _number(value, name):
    number = float(value or 0)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f'{name} must be a finite non-negative number')
    return number


def validate_ai_usage(value):
    if not value:
        return None
    if not isinstance(value, dict):
        raise ValueError('ai_usage must be an object')
    provider = str(value.get('provider') or '').strip().lower()
    model = str(value.get('model') or '').strip()
    if not provider or not model:
        raise ValueError('ai_usage requires provider and model')
    return {'provider': provider, 'model': model,
            'input_tokens': _number(value.get('input_tokens'), 'input_tokens'),
            'output_tokens': _number(value.get('output_tokens'), 'output_tokens'),
            'gpu_hours': _number(value.get('gpu_hours'), 'gpu_hours')}


def rank_manual_evidence(rows, usage):
    """Small deterministic RAG retriever: exact provider/model evidence wins.

    Evidence is admin-approved and carries its original source URL/excerpt;
    values from an LLM are never accepted as prices.
    """
    provider, model = usage['provider'], usage['model'].lower()
    candidates = []
    for row in rows:
        if not row.get('approved'):
            continue
        score = 0
        if str(row.get('provider', '')).lower() == provider:
            score += 4
        if str(row.get('model', '')).lower() == model:
            score += 8
        elif str(row.get('model', '')).lower() in {'*', 'default'}:
            score += 1
        if score >= 12:
            candidates.append((score, str(row.get('effective_date') or ''), row))
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (item[0], item[1]), reverse=True)[0][2]


def resolve_ai_cost(usage, evidence):
    usage = validate_ai_usage(usage)
    if not usage:
        return None
    row = rank_manual_evidence(evidence, usage)
    if not row:
        return {'status': 'ai_pricing_missing', 'usage': usage, 'total_usd': None,
                'message': 'No approved RAG/manual pricing evidence matches this provider and model.'}
    input_rate = _number(row.get('input_per_million'), 'input_per_million')
    output_rate = _number(row.get('output_per_million'), 'output_per_million')
    gpu_rate = _number(row.get('gpu_per_hour'), 'gpu_per_hour')
    total = usage['input_tokens'] / 1_000_000 * input_rate + usage['output_tokens'] / 1_000_000 * output_rate + usage['gpu_hours'] * gpu_rate
    return {'status': 'rag_manual_approved', 'usage': usage, 'total_usd': round(total, 8),
            'input_per_million': input_rate, 'output_per_million': output_rate,
            'gpu_per_hour': gpu_rate, 'source_url': row.get('source_url', ''),
            'source_title': row.get('title', ''), 'evidence_excerpt': row.get('excerpt', ''),
            'effective_date': row.get('effective_date', ''), 'retrieved_at': datetime.now(timezone.utc).isoformat()}
