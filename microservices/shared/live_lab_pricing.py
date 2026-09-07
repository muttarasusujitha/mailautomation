"""Fresh public retail prices. Never accept caller-supplied numeric rates as verified."""
import csv
import io
import json
import math
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode
from urllib.request import urlopen
from uuid import uuid4

RESOURCES = {
    'VM': 'hour', 'VM Light': 'hour', 'VM Heavy': 'hour',
    'Kubernetes control plane': 'hour', 'Kubernetes worker': 'hour',
    'Disk': 'month', 'Storage': 'month', 'Egress': 'gb',
    'Build runner': 'minute', 'Managed database': 'hour', 'Monitoring': 'gb',
}
UNITS = {'hour': {'Hrs', '1 Hour', 'Hours'}, 'month': {'GB-Mo', 'GB-month', '1 GB/Month'},
         'gb': {'GB', '1 GB', 'GBytes'}, 'minute': {'minutes', '1 Minute'}}

class PricingUnavailable(ValueError):
    pass


def automatic_pricing_selections(toc=None, assumptions=None):
    """Return a deterministic starter architecture when no catalog is configured.

    The paid compute profile is intentionally conservative (EC2 t3.medium for
    light work and t3.xlarge for heavy workers). Optional managed services are
    marked ``auto_zero`` until the TOC explicitly enables them; this prevents
    silently inventing database, storage, or egress consumption.
    """
    provider = str((assumptions or {}).get('cloud_provider') or 'aws').lower()
    if provider == 'aws':
        light = {'service': 'AmazonEC2', 'attributes': {
            'Instance Type': 't3.medium', 'Operating System': 'Linux',
            'Tenancy': 'Shared', 'MarketOption': 'OnDemand'}}
        heavy = {'service': 'AmazonEC2', 'attributes': {
            'Instance Type': 't3.xlarge', 'Operating System': 'Linux',
            'Tenancy': 'Shared', 'MarketOption': 'OnDemand'}}
        zero = {'auto_zero': True, 'service': 'AmazonEC2'}
    elif provider == 'azure':
        # Central India's standard B2s meter is a stable baseline; callers can
        # still override it with a catalog entry for a different VM size.
        light = {'meter_id': '734de0e1-404b-4c78-a340-a5f6498aca77'}
        heavy = light.copy()
        zero = {'auto_zero': True}
    else:
        return {}
    return {
        'VM': light, 'VM Light': light, 'VM Heavy': heavy,
        'Kubernetes control plane': zero, 'Kubernetes worker': heavy,
        'Disk': zero, 'Storage': zero, 'Egress': zero,
        'Build runner': zero, 'Managed database': zero, 'Monitoring': zero,
    }

def _amount(value):
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise PricingUnavailable('Provider returned an invalid price')
    return value

def _choose(rows, resource, unit_key):
    if len(rows) != 1:
        raise PricingUnavailable(f'{resource}: expected one exact rate, found {len(rows)}; confirm SKU and billing dimension')
    row = rows[0]
    if row['unit'] not in UNITS[unit_key]:
        raise PricingUnavailable(f'{resource}: provider unit {row["unit"]} is incompatible with the workbook')
    row['rate'] = _amount(row['rate'])
    return row


def _aws_selector_matches(row, selection):
    """A selector is stable architecture intent; the catalog supplies the SKU.

    Example: {"attributes": {"Instance Type": "t3.medium",
    "Operating System": "Linux", "Tenancy": "Shared"}}.
    The match must still yield exactly one current on-demand rate.
    """
    attributes = selection.get('attributes') or {}
    if not isinstance(attributes, dict) or not attributes:
        return False
    for key, value in attributes.items():
        actual = str(row.get(key) or '')
        if isinstance(value, dict) and 'contains' in value:
            if str(value['contains']).lower() not in actual.lower():
                return False
        elif actual != str(value):
            return False
    return True

def _aws_catalog(service, region):
    if not re.fullmatch(r'[A-Za-z0-9]+', service):
        raise PricingUnavailable('Invalid AWS service code')
    url = f'https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/{service}/current/{region}/index.csv'
    # Stream regional CSV rather than loading the large EC2 JSON catalogue.
    with urlopen(url, timeout=45) as response:
        stream = io.TextIOWrapper(response, encoding='utf-8-sig')
        for line in stream:
            if line.startswith('"SKU",'):
                reader = csv.DictReader(stream, fieldnames=next(csv.reader([line])))
                yield from ((row, url) for row in reader)
                return
    raise PricingUnavailable('AWS catalogue header missing')

def _azure(selection, region):
    meter = str(selection.get('meter_id') or '')
    if not re.fullmatch(r'[a-fA-F0-9-]{36}', meter):
        raise PricingUnavailable('Azure requires an exact meter_id')
    url = 'https://prices.azure.com/api/retail/prices?' + urlencode({
        '$filter': f"meterId eq '{meter}' and armRegionName eq '{region}' and priceType eq 'Consumption'",
        'currencyCode': 'USD',
    })
    with urlopen(url, timeout=30) as response:
        data = json.load(response)
    if data.get('NextPageLink'):
        raise PricingUnavailable('Azure meter lookup is ambiguous; narrow the meter selection')
    now = datetime.now(timezone.utc)
    rows = []
    for item in data.get('Items', []):
        if (item.get('currencyCode') != 'USD' or item.get('armRegionName') != region
                or item.get('type') != 'Consumption' or item.get('meterId') != meter):
            continue
        if datetime.fromisoformat(item['effectiveStartDate'].replace('Z', '+00:00')) > now:
            continue
        if item.get('tierMinimumUnits') != 0:
            raise PricingUnavailable('Tiered Azure meters require a different billing formula')
        rows.append({'rate': item['retailPrice'], 'unit': item['unitOfMeasure'],
                     'sku': item['skuId'], 'dimension': meter, 'source': url,
                     'effective_date': item['effectiveStartDate']})
    return rows

def refresh_rates(values):
    """Selections are architecture inputs; fresh rates are fetched on every invocation.

    Require the entire editable rate card so subsequent workbook edits cannot
    activate an unverified template rate. Tiered/conditional prices are rejected.
    """
    result = dict(values)
    provider = result['cloud_provider']
    regions = {'aws': 'ap-south-1', 'azure': 'centralindia'}
    if provider not in regions:
        raise PricingUnavailable('Live lookup currently supports AWS and Azure; GCP quotes are blocked pending a catalog connector')
    selections = result.get('pricing_selections') or {}
    unpriced = [name for name, selection in selections.items()
                if isinstance(selection, dict) and selection.get('auto_zero')]
    if unpriced:
        raise PricingUnavailable('Pricing evidence is missing for: ' + ', '.join(unpriced)
                                 + '; these resources cannot be assumed free')
    missing = sorted(set(RESOURCES) - set(selections))
    if missing:
        raise PricingUnavailable('Configure exact pricing selections for: ' + ', '.join(missing))
    if any(not isinstance(selections[name], dict) for name in RESOURCES):
        raise PricingUnavailable('Each pricing selection must be an object')
    rates = {}
    if provider == 'aws':
        services = {}
        for name in RESOURCES:
            s = selections[name]
            if s.get('auto_zero'):
                continue
            if not s.get('service'):
                raise PricingUnavailable(f'{name}: specify an AWS service')
            uses_id = bool(s.get('sku') and s.get('rate_code'))
            uses_attributes = bool(s.get('attributes'))
            if uses_id == uses_attributes:
                raise PricingUnavailable(f'{name}: supply either sku/rate_code or non-empty attributes')
            services.setdefault(s['service'], []).append(name)
        matches = {name: [] for name in RESOURCES}
        for name, selection in selections.items():
            if selection.get('auto_zero'):
                matches[name] = [{'rate': 0, 'unit': next(iter(UNITS[RESOURCES[name]])),
                                  'sku': 'NOT_BILLED', 'dimension': 'not-enabled',
                                  'source': 'https://aws.amazon.com/pricing/',
                                  'effective_date': ''}]
        for service, names in services.items():
            for row, url in _aws_catalog(service, regions[provider]):
                for name in names:
                    s = selections[name]
                    if s.get('attributes'):
                        selected = _aws_selector_matches(row, s)
                    else:
                        selected = row.get('SKU') == s['sku'] and row.get('RateCode') == s['rate_code']
                    if not selected:
                        continue
                    # A SKU can include separate non-hourly dimensions (for
                    # example, reservations). They are not candidates for an
                    # hourly lab-VM formula.
                    if row.get('Unit') not in UNITS[RESOURCES[name]]:
                        continue
                    # Attribute searches describe a product, which can also
                    # have hourly reserved terms. Only on-demand terms belong
                    # in this quote; exact rate-code requests remain strict.
                    if s.get('attributes') and row.get('TermType') != 'OnDemand':
                        continue
                    if (row.get('TermType') != 'OnDemand' or row.get('Currency') != 'USD'
                            or row.get('StartingRange') not in ('0', '0.0000000000')
                            or row.get('EndingRange') not in ('Inf', 'Infinity')):
                        raise PricingUnavailable(f'{name}: tiered or non-on-demand rates require a different billing formula')
                    matches[name].append({'rate': row['PricePerUnit'], 'unit': row['Unit'],
                        'sku': row['SKU'], 'dimension': row['RateCode'], 'source': url,
                        'effective_date': row.get('EffectiveDate', '')})
        rates = {name: _choose(matches[name], name, unit) for name, unit in RESOURCES.items()}
    else:
        rates = {}
        for name, unit in RESOURCES.items():
            selection = selections[name]
            if selection.get('auto_zero'):
                rates[name] = _choose([{'rate': 0, 'unit': next(iter(UNITS[unit])),
                                        'sku': 'NOT_BILLED', 'dimension': 'not-enabled',
                                        'source': 'https://azure.microsoft.com/en-us/pricing/',
                                        'effective_date': ''}], name, unit)
            else:
                rates[name] = _choose(_azure(selection, regions[provider]), name, unit)
    checked = datetime.now(timezone.utc)
    validity = int(result.get('quote_validity_days') or 7)
    if not 1 <= validity <= 365:
        raise PricingUnavailable('Quote validity must be 1 to 365 days')
    for row in rates.values():
        row['verified_date'] = checked.isoformat()
        row['note'] = f"SKU {row['sku']}; dimension {row['dimension']}; effective {row['effective_date']}; USD public retail price"
    result.update(rate_card_overrides=rates,
        vm_profile_rates={p: rates['VM ' + p]['rate'] for p in ('Light', 'Heavy')},
        vm_profile_sources={p: rates['VM ' + p]['source'] for p in ('Light', 'Heavy')},
        rate_snapshot_id='LCQ-' + uuid4().hex.upper(), rate_checked_at=checked.isoformat(),
        rate_card_verified_date=checked.isoformat(), rate_snapshot_source=rates['VM']['source'],
        quote_valid_until=(checked + timedelta(days=validity)).isoformat(),
        pricing_status='provider_api_verified_public_retail')
    return result
