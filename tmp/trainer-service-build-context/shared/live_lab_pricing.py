"""Fresh public retail prices. Never accept caller-supplied numeric rates as verified."""
import csv
import io
import json
import math
import os
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

RESOURCES = {
    'VM': 'hour', 'VM Light': 'hour', 'VM Heavy': 'hour',
    'Kubernetes control plane': 'hour', 'Kubernetes worker': 'hour',
    'Disk': 'month', 'Storage': 'month', 'Egress': 'gb',
    'Object storage PUT requests': 'request', 'Object storage GET requests': 'request',
    'Build runner': 'minute', 'Managed database': 'hour',
    'Managed database storage': 'month', 'Monitoring': 'gb',
}
UNITS = {'hour': {'Hrs', '1 Hour', 'Hours', '1/Day'}, 'month': {'GB-Mo', 'GB-month', '1 GB/Month'},
         'gb': {'GB', '1 GB', 'GBytes'}, 'minute': {'minutes', '1 Minute'},
         'request': {'Requests', '1 Request'}}

class PricingUnavailable(ValueError):
    pass


def automatic_pricing_selections(toc=None, assumptions=None):
    """Return a deterministic starter architecture when no catalog is configured.

    The paid compute profile is intentionally conservative (EC2 t3.medium for
    light work and t3.xlarge for heavy workers). Optional managed services are
    marked ``auto_zero`` until the TOC explicitly enables them; this prevents
    silently inventing database, storage, or egress consumption.
    """
    assumptions = assumptions or {}
    provider = str(assumptions.get('cloud_provider') or 'aws').lower()
    mappings = assumptions.get('lab_day_mapping') or []
    mappings = mappings.values() if isinstance(mappings, dict) else mappings
    mappings = list(mappings)
    uses_eks = provider == 'aws' and any(
        int(float(day.get('k8s_control_plane') or 0)) > 0 for day in mappings
    )
    uses_storage = any(float(day.get('object_storage_gb') or 0) > 0 for day in mappings)
    uses_database = any(float(day.get('managed_db') or 0) > 0 for day in mappings)
    from shared.lab_curriculum import cloud_lab_text
    topics = ' '.join(cloud_lab_text(day) for day in (toc or {}).get('days', [])).lower()
    if provider == 'aws':
        light = {'service': 'AmazonEC2', 'attributes': {
            'Instance Type': 't3.medium', 'Operating System': 'Linux',
            'Tenancy': 'Shared', 'MarketOption': 'OnDemand',
            'CapacityStatus': 'Used', 'Pre Installed S/W': 'NA',
            'License Model': 'No License required'}}
        heavy = {'service': 'AmazonEC2', 'attributes': {
            'Instance Type': 't3.xlarge', 'Operating System': 'Linux',
            'Tenancy': 'Shared', 'MarketOption': 'OnDemand',
            'CapacityStatus': 'Used', 'Pre Installed S/W': 'NA',
            'License Model': 'No License required'}}
        zero = {
            'auto_zero': True,
            'service': 'AmazonEC2',
            'not_enabled_reason': 'Not enabled by the automatic baseline architecture',
        }
    elif provider == 'azure':
        light = {'meter_id': '734de0e1-404b-4c78-a340-a5f6498aca77'}
        heavy = {'meter_id': '2382d92d-4ce9-5330-9bb4-8ec9120e6a64'}
        zero = {
            'auto_zero': True,
            'not_enabled_reason': 'Not enabled by the automatic baseline architecture',
        }
    else:
        return {}
    selections = {
        'VM': light, 'VM Light': light, 'VM Heavy': heavy,
        'Kubernetes control plane': zero, 'Kubernetes worker': heavy,
        'Disk': zero, 'Storage': zero,
        'Object storage PUT requests': zero.copy(),
        'Object storage GET requests': zero.copy(), 'Egress': zero,
        'Build runner': zero, 'Managed database': zero,
        'Managed database storage': zero.copy(), 'Monitoring': zero,
    }
    if provider == 'azure':
        selections['Kubernetes control plane']['not_enabled_reason'] = (
            'AKS Free management tier selected for a short-lived training cluster; '
            'worker VMs, disks, load balancing, and data transfer are billed separately'
        )
    if provider == 'aws':
        # gp3 base-capacity pricing is distinct from optional extra IOPS and
        # throughput. Resolve the exact current dimension from the catalog.
        selections['Disk'] = {'service': 'AmazonEC2', 'attributes': {
            'usageType': 'APS3-EBS:VolumeUsage.gp3'}}
        if uses_eks:
            selections['Kubernetes control plane'] = {
                'service': 'AmazonEKS', 'attributes': {
                    'usageType': 'APS3-AmazonEKS-Hours:perCluster'}}
        if uses_storage:
            selections['Storage'] = {'service': 'AmazonS3', 'attributes': {
                'usageType': 'APS3-TimedStorage-ByteHrs'}, 'first_tier_only': True}
            selections['Object storage PUT requests'] = {
                'service': 'AmazonS3', 'attributes': {'usageType': 'APS3-Requests-Tier1'}}
            selections['Object storage GET requests'] = {
                'service': 'AmazonS3', 'attributes': {'usageType': 'APS3-Requests-Tier2'}}
        if uses_database:
            engine = ('PostgreSQL' if 'postgres' in topics and 'mysql' not in topics else 'MySQL')
            if ('sql server' in topics or 'aurora' in topics or
                    ('postgres' in topics and 'mysql' in topics)):
                engine = None
            if engine:
                allocated_storage = _amount(assumptions.get('database_storage_gb', 20))
                if allocated_storage < 20:
                    raise PricingUnavailable('Amazon RDS gp3 requires at least 20 GB in this estimate')
                common_db = {'Deployment Option': 'Single-AZ', 'Database Engine': engine}
                selections['Managed database'] = {'service': 'AmazonRDS', 'attributes': {
                    **common_db, 'Instance Type': 'db.t3.micro',
                    'License Model': 'No license required'}}
                selections['Managed database storage'] = {'service': 'AmazonRDS', 'attributes': {
                    **common_db, 'Product Family': 'Database Storage',
                    'usageType': 'APS3-RDS:GP3-Storage'}}
            else:
                reason = 'Automatic RDS selector supports one MySQL or PostgreSQL Single-AZ engine; SQL Server, Aurora, or mixed-engine topics need a specific approved SKU.'
                selections['Managed database'] = {'auto_zero': True, 'not_enabled_reason': reason}
                selections['Managed database storage'] = {'auto_zero': True, 'not_enabled_reason': reason}
    else:
        # P4 is a fixed 32-GiB Premium SSD LRS disk in Central India. It is
        # divided into a per-GB rate for the workbook and requires this size.
        selections['Disk'] = {'meter_id': 'ed9e91d2-0f0c-4d55-b3dd-7f69d4708b22'}
        if any(float(day.get('vm_qty') or 0) > 0 or
               float(day.get('k8s_worker_nodes') or 0) > 0 for day in mappings):
            assumptions['disk_gb_per_node'] = 32
        if uses_storage:
            selections['Storage'] = {
                'meter_id': '5c7a80d0-80f2-45f7-9135-4b4ac42adf49',
                'product_name': 'General Block Blob v2',
                'meter_name': 'Hot LRS Data Stored',
                'first_tier_only': True,
            }
            selections['Object storage PUT requests'] = {
                'meter_id': 'b8cc594c-522d-4b13-bfe9-0bdade2e94d2',
                'product_name': 'General Block Blob v2',
                'meter_name': 'Hot LRS Write Operations',
                'sku_id': 'DZH318Z0BPH7/00FM', 'normalize_per_unit': 10000,
            }
            selections['Object storage GET requests'] = {
                'meter_id': '2cf4341c-5363-4026-8ed4-d1ddaa0a8276',
                'product_name': 'General Block Blob v2',
                'meter_name': 'Hot Read Operations',
                'sku_id': 'DZH318Z0BPH7/00FH', 'normalize_per_unit': 10000,
            }
        if uses_database and 'azure sql' in topics and not any(
                marker in topics for marker in ('serverless', 'hyperscale', 'azure database for postgresql',
                                                'azure database for mysql')):
            selections['Managed database'] = {
                'meter_id': 'ad4d0278-4c8f-4298-a99b-1952ec4440b9',
                'max_storage_gb': 250,
            }
    return selections

def _amount(value):
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise PricingUnavailable('Provider returned an invalid price')
    return value


def _storage_first_tier(row, selection, resource, values):
    """Allow an explicitly selected S3 first tier only within its usage bound."""
    if not (resource == 'Storage' and selection.get('service') == 'AmazonS3'
            and selection.get('first_tier_only') is True
            and row.get('StartingRange') in ('0', '0.0000000000')):
        return False
    limit = _amount(row['EndingRange'])
    mapping = values.get('lab_day_mapping') or []
    rows = mapping.values() if isinstance(mapping, dict) else mapping
    # Sum all allocations, even if they do not overlap: a conservative bound.
    usage = sum(_amount(day.get('object_storage_gb', 0)) for day in rows)
    usage = max(usage, _amount(values.get('storage_gb', 10)))
    if usage >= limit or limit <= 0:
        raise PricingUnavailable('S3 storage exceeds the selected first-tier capacity; use a tier-aware estimate')
    return True


def _selected_first_tier(row, selection, resource, values):
    """Allow a bounded first price tier only while supplied usage fits it."""
    if resource == 'Storage' and selection.get('service') == 'AmazonS3':
        return _storage_first_tier(row, selection, resource, values)
    if not selection.get('first_tier_only'):
        return False
    if row.get('StartingRange') not in ('0', '0.0000000000'):
        return False
    end_value = str(row.get('EndingRange') or '').strip()
    if end_value.lower() in ('inf', 'infinity', ''):
        return False
    try:
        ceiling = _amount(end_value)
    except (TypeError, ValueError):
        return False
    usage = _amount((values.get('additional_resource_usage') or {}).get(resource, 0))
    if usage >= ceiling:
        raise PricingUnavailable(
            f'{resource} usage {usage:g} exceeds the selected first-tier ceiling {ceiling:g}; '
            'configure a tiered estimate'
        )
    return True

def _choose(rows, resource, unit_key):
    if len(rows) != 1:
        raise PricingUnavailable(f'{resource}: expected one exact rate, found {len(rows)}; confirm SKU and billing dimension')
    row = rows[0]
    allowed = UNITS.get(unit_key)
    compatible = row['unit'] in allowed if allowed else row['unit'] == unit_key
    if not compatible:
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


def discover_price_selectors(provider, region, search, *, service_code=None, service_name=None,
                             service_id=None, unit=None, limit=25):
    """Find current public catalog candidates without selecting a meter for the caller.

    Results are discovery hints only. Saving a selector still performs an exact
    live-price validation, and quote quantities must be supplied separately.
    """
    provider = str(provider or '').strip().lower()
    search = str(search or '').strip()
    if len(search) < 2:
        raise PricingUnavailable('search must contain at least two characters')
    if not 1 <= int(limit) <= 100:
        raise PricingUnavailable('limit must be between 1 and 100')
    needle = search.casefold()
    candidates = []
    if provider == 'aws':
        if not service_code or not re.fullmatch(r'[A-Za-z0-9]+', str(service_code)):
            raise PricingUnavailable('AWS discovery requires an exact service_code such as AWSLambda')
        for row, source in _aws_catalog(str(service_code), region):
            if row.get('TermType') != 'OnDemand' or row.get('Currency') != 'USD':
                continue
            if row.get('StartingRange') not in ('0', '0.0000000000'):
                continue
            if unit and str(row.get('Unit') or '').casefold() != str(unit).casefold():
                continue
            searchable = ' '.join(str(value) for value in row.values() if value is not None).casefold()
            if needle not in searchable:
                continue
            try:
                candidate_rate = _amount(row.get('PricePerUnit'))
            except (TypeError, ValueError):
                continue
            attributes = {key: value for key, value in row.items()
                          if key not in {'SKU', 'RateCode', 'PricePerUnit', 'Currency', 'EffectiveDate',
                                         'TermType', 'StartingRange', 'EndingRange', 'Unit'}
                          and value not in (None, '')}
            candidates.append({
                'provider': provider, 'service_code': str(service_code),
                'sku': row.get('SKU'), 'rate_code': row.get('RateCode'),
                'unit': row.get('Unit'), 'rate': candidate_rate,
                'currency': 'USD', 'effective_date': row.get('EffectiveDate'),
                'description': row.get('Description') or '', 'attributes': attributes,
                'source': source,
            })
            if len(candidates) >= int(limit):
                break
    elif provider == 'azure':
        if not service_name:
            raise PricingUnavailable('Azure discovery requires an exact service_name, for example Virtual Machines')
        url = 'https://prices.azure.com/api/retail/prices?' + urlencode({
            '$filter': f"serviceName eq '{str(service_name).replace(chr(39), chr(39) * 2)}' and armRegionName eq '{region}' and priceType eq 'Consumption'",
            'currencyCode': 'USD',
        })
        pages = 0
        now = datetime.now(timezone.utc)
        while url and pages < 10 and len(candidates) < int(limit):
            with urlopen(url, timeout=30) as response:
                data = json.load(response)
            for row in data.get('Items', []):
                searchable = ' '.join(str(row.get(key) or '') for key in
                                      ('productName', 'skuName', 'meterName', 'armSkuName')).casefold()
                if needle not in searchable or row.get('type') != 'Consumption' or row.get('currencyCode') != 'USD':
                    continue
                if row.get('armRegionName') != region or float(row.get('tierMinimumUnits') or 0) != 0:
                    continue
                if unit and str(row.get('unitOfMeasure') or '').casefold() != str(unit).casefold():
                    continue
                try:
                    effective = datetime.fromisoformat(str(row.get('effectiveStartDate')).replace('Z', '+00:00'))
                except (TypeError, ValueError):
                    continue
                if effective > now:
                    continue
                candidates.append({
                    'provider': provider, 'meter_id': row.get('meterId'),
                    'product_name': row.get('productName'), 'sku_name': row.get('skuName'),
                    'meter_name': row.get('meterName'), 'unit': row.get('unitOfMeasure'),
                    'rate': _amount(row.get('retailPrice')), 'currency': 'USD',
                    'effective_date': row.get('effectiveStartDate'),
                    'source': 'https://prices.azure.com/api/retail/prices',
                })
                if len(candidates) >= int(limit):
                    break
            url = data.get('NextPageLink')
            pages += 1
    elif provider == 'gcp':
        if not service_id:
            raise PricingUnavailable('GCP discovery requires an exact service_id')
        for sku, source in _gcp_catalog(str(service_id), region):
            description = str(sku.get('description') or '')
            if needle not in description.casefold():
                continue
            pricing_info = sku.get('pricingInfo') or [{}]
            expression = pricing_info[0].get('pricingExpression') or {}
            candidates.append({
                'provider': provider, 'service_id': str(service_id),
                'sku_id': sku.get('skuId'), 'description': description,
                'category': sku.get('category') or {},
                'unit': expression.get('usageUnitDescription'),
                'source': source,
            })
            if len(candidates) >= int(limit):
                break
    else:
        raise PricingUnavailable('provider must be aws, azure, or gcp')
    return {'provider': provider, 'region': region, 'search': search,
            'candidates': candidates, 'count': len(candidates),
            'is_discovery_only': True}


def _gcp_catalog(service_id, region):
    """Yield public GCP SKUs for a configured exact service ID.

    Google requires a Cloud Billing Catalog API key even for public retail
    catalog data. The key is read only from the service environment and is
    never included in returned source URLs or error messages.
    """
    api_key = os.environ.get('GCP_BILLING_CATALOG_API_KEY', '').strip()
    if not api_key:
        raise PricingUnavailable('GCP live pricing requires GCP_BILLING_CATALOG_API_KEY in the document-service environment')
    if not re.fullmatch(r'[A-Za-z0-9-]{8,64}', str(service_id)):
        raise PricingUnavailable('GCP selection requires a valid exact service_id')
    page_token = None
    source = f'https://cloudbilling.googleapis.com/v1/services/{service_id}/skus'
    while True:
        params = {'currencyCode': 'USD', 'pageSize': 5000}
        if page_token:
            params['pageToken'] = page_token
        url = source + '?' + urlencode(params)
        request = Request(url, headers={'X-goog-api-key': api_key})
        with urlopen(request, timeout=35) as response:
            data = json.load(response)
        for sku in data.get('skus', []):
            if region in (sku.get('serviceRegions') or []) or 'global' in (sku.get('serviceRegions') or []):
                yield sku, source
        page_token = data.get('nextPageToken')
        if not page_token:
            break


def _gcp_rate(sku, selection, unit_key, source):
    """Convert one exact, single-tier GCP public SKU into a workbook rate."""
    infos = sku.get('pricingInfo') or []
    now = datetime.now(timezone.utc)
    current = []
    for info in infos:
        try:
            effective = datetime.fromisoformat(info['effectiveTime'].replace('Z', '+00:00'))
        except (KeyError, TypeError, ValueError):
            continue
        if effective <= now:
            current.append((effective, info))
    if not current:
        raise PricingUnavailable('GCP SKU has no current public price')
    effective, info = max(current, key=lambda item: item[0])
    expression = info.get('pricingExpression') or {}
    tiers = expression.get('tieredRates') or []
    if len(tiers) != 1 or float(tiers[0].get('startUsageAmount') or 0) != 0:
        raise PricingUnavailable('Tiered GCP SKUs require a tier-aware estimate')
    if float(expression.get('baseUnitConversionFactor') or 1) != 1:
        raise PricingUnavailable('GCP SKU uses a billing-unit conversion that is not configured')
    actual_unit = str(expression.get('usageUnitDescription') or expression.get('usageUnit') or '').strip().lower()
    aggregation = expression.get('aggregationInfo') or {}
    aggregation_level = str(aggregation.get('level') or aggregation.get('aggregationLevel') or '').upper()
    if aggregation_level not in ('', 'ACCOUNT', 'PROJECT', 'AGGREGATION_LEVEL_UNSPECIFIED'):
        raise PricingUnavailable('GCP SKU has unsupported or ambiguous aggregation scope')
    aliases = {
        'hour': {'hour', 'hours', '1 hour', 'h'},
        'month': {'gb-month', 'gibibyte month', 'gibibyte-month', 'gibibyte months', '1 gibibyte month'},
        'gb': {'gb', 'gibibyte', 'gibibytes', '1 gibibyte'},
        'minute': {'minute', 'minutes', '1 minute'},
        'request': {'request', 'requests', '1 request', '1000 requests', '1,000 requests',
                    '1000000 requests', '1,000,000 requests'},
    }
    compatible_units = aliases.get(unit_key)
    if compatible_units is None:
        compatible_units = {str(unit_key).strip().lower()}
    if actual_unit not in compatible_units:
        raise PricingUnavailable(f'GCP SKU billing unit {actual_unit!r} does not match {unit_key}')
    price = tiers[0].get('unitPrice') or {}
    if price.get('currencyCode') != 'USD':
        raise PricingUnavailable('GCP public SKU did not return a USD price')
    amount = _amount(price.get('units', 0)) + _amount(price.get('nanos', 0)) / 1_000_000_000
    divisor = selection.get('normalize_per_unit')
    if divisor is None and unit_key == 'request':
        match = re.fullmatch(r'([\d,]+)\s+requests?', actual_unit)
        if match:
            divisor = float(match.group(1).replace(',', ''))
    if divisor is not None:
        divisor = _amount(divisor)
        if divisor <= 0:
            raise PricingUnavailable('GCP SKU normalization divisor must be positive')
        amount /= divisor
    canonical = {'hour': 'Hrs', 'month': 'GB-Mo', 'gb': 'GB',
                 'minute': 'minutes', 'request': 'Requests'}.get(unit_key, str(unit_key))
    return {'rate': amount, 'unit': canonical, 'sku': sku.get('skuId'),
            'dimension': sku.get('category', {}).get('usageType', 'GCP public SKU'),
            'source': source, 'effective_date': effective.isoformat(),
            'specifications': {'product': sku.get('description', '')},
            'note': f"GCP public SKU {sku.get('skuId')}; {actual_unit}; effective {effective.isoformat()}; single-tier retail rate"}

def _azure(selection, region, values=None):
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
    items = []
    for item in data.get('Items', []):
        if (item.get('currencyCode') != 'USD' or item.get('armRegionName') != region
                or item.get('type') != 'Consumption' or item.get('meterId') != meter):
            continue
        if selection.get('product_name') and item.get('productName') != selection['product_name']:
            continue
        if selection.get('meter_name') and item.get('meterName') != selection['meter_name']:
            continue
        if selection.get('sku_id') and item.get('skuId') != selection['sku_id']:
            continue
        if datetime.fromisoformat(item['effectiveStartDate'].replace('Z', '+00:00')) > now:
            continue
        items.append(item)
    if selection.get('first_tier_only'):
        first_tiers = [item for item in items if item.get('tierMinimumUnits') == 0]
        if len(first_tiers) != 1:
            raise PricingUnavailable('Azure first-tier meter is missing or ambiguous')
        next_tier = min((float(item['tierMinimumUnits']) for item in items
                         if float(item.get('tierMinimumUnits') or 0) > 0), default=None)
        # The usage ceiling is the next tier boundary from the live catalog.
        usage_rows = (values or {}).get('lab_day_mapping') or []
        usage_rows = usage_rows.values() if isinstance(usage_rows, dict) else usage_rows
        usage = sum(_amount(day.get('object_storage_gb', 0)) for day in usage_rows)
        usage = max(usage, _amount((values or {}).get('storage_gb', 10)))
        if next_tier is not None and usage >= next_tier:
            raise PricingUnavailable('Azure Blob storage exceeds the selected first-tier capacity; use a tier-aware estimate')
        items = first_tiers
    elif any(item.get('tierMinimumUnits') != 0 for item in items):
        raise PricingUnavailable('Tiered Azure meters require a different billing formula')
    rows = []
    for item in items:
        rows.append({'rate': item['retailPrice'], 'unit': item['unitOfMeasure'],
                     'sku': item['skuId'], 'dimension': meter, 'source': url,
                     'effective_date': item['effectiveStartDate'],
                     **({'note': f"Azure Blob Hot LRS first-tier estimate, below {next_tier:g} GB; transactions are priced separately and data transfer is excluded. Regenerate if storage quantities change."}
                        if selection.get('first_tier_only') and next_tier is not None else {}),
                     'specifications': {key: item[field] for key, field in (
                         ('instance_type', 'armSkuName'), ('product', 'productName'),
                         ('meter', 'meterName')) if item.get(field)}})
    divisor = selection.get('normalize_per_unit')
    if divisor is not None:
        divisor = _amount(divisor)
        if divisor <= 0:
            raise PricingUnavailable('Azure meter normalization divisor must be positive')
        for row in rows:
            row['provider_rate'] = row['rate']
            row['provider_unit'] = row['unit']
            row['rate'] = _amount(row['rate']) / divisor
            row['unit'] = 'Requests'
            row['note'] = f"Provider rate normalized from {row['provider_unit']} to one request."
    return rows

def refresh_rates(values):
    """Selections are architecture inputs; fresh rates are fetched on every invocation.

    Require the entire editable rate card so subsequent workbook edits cannot
    activate an unverified template rate. Tiered/conditional prices are rejected.
    """
    result = dict(values)
    provider = result['cloud_provider']
    regions = {'aws': 'ap-south-1', 'azure': 'centralindia', 'gcp': 'asia-south1'}
    if provider not in regions:
        raise PricingUnavailable('Live lookup currently supports AWS, Azure, and configured GCP public SKU selections')
    selections = result.get('pricing_selections') or {}
    if not isinstance(selections, dict):
        raise PricingUnavailable('pricing_selections must be an object')
    resource_units = dict(RESOURCES)
    for name, selection in selections.items():
        if name not in RESOURCES:
            if not isinstance(selection, dict):
                raise PricingUnavailable(f'{name}: additional meter selection must be an object')
            unit_key = selection.get('unit_key')
            if not isinstance(unit_key, str) or not unit_key or len(unit_key) > 48:
                raise PricingUnavailable(f'{name}: additional meter selections require a unit_key')
            if provider == 'gcp' and unit_key not in UNITS:
                raise PricingUnavailable(f'{name}: GCP additional meters require a supported unit category')
            resource_units[name] = selection['unit_key']
    # Service coverage is exact-name based. Validate that each explicitly
    # named billable product has its full, priced billing model before a quote
    # can pass architecture validation.
    from shared.lab_architecture import architecture_summary
    from shared.lab_cost_inputs import SERVICE_METER_REQUIREMENTS
    architecture = result.get('service_architecture')
    if not isinstance(architecture, dict):
        toc = result.get('toc') if isinstance(result.get('toc'), dict) else {}
        architecture = architecture_summary(toc, provider, result.get('kubernetes_tier') or 'free')
    unpriced_services = set(architecture.get('unpriced_services') or [])
    additional_usage = result.get('additional_resource_usage') or {}
    if not isinstance(additional_usage, dict):
        raise PricingUnavailable('additional_resource_usage must be an object keyed by additional meter name')
    catalog_validation_only = bool(result.get('catalog_validation_only'))
    from shared.lab_architecture import SERVICE_CATALOG
    from shared.lab_curriculum import cloud_lab_text
    from shared.lab_cost_inputs import SERVICE_METER_REQUIREMENTS as requirements
    mapped = result.get('lab_day_mapping') or []
    mapped = list(mapped.values()) if isinstance(mapped, dict) else list(mapped)
    toc = result.get('toc') if isinstance(result.get('toc'), dict) else {}
    configured_services = set()
    architecture = result.get('service_architecture') or {}
    for day_index, day_architecture in enumerate(architecture.get('days') or []):
        if day_index < len(mapped) and not any(float(mapped[day_index].get(key) or 0) > 0 for key in (
                'vm_qty', 'k8s_control_plane', 'k8s_worker_nodes', 'managed_db', 'object_storage_gb')):
            continue
        configured_services.update(set(day_architecture.get('unpriced_services') or []) & set(requirements))
    if not configured_services:
        for day_index, day in enumerate(toc.get('days') or []):
            if day_index < len(mapped) and not any(float(mapped[day_index].get(key) or 0) > 0 for key in (
                    'vm_qty', 'k8s_control_plane', 'k8s_worker_nodes', 'managed_db', 'object_storage_gb')):
                continue
            day_text = cloud_lab_text(day)
            catalog_rows = SERVICE_CATALOG.get(provider, ())
            for service_name, patterns, _family, _modelled in catalog_rows:
                if service_name in requirements and any(
                        re.search(pattern, day_text, re.IGNORECASE) for pattern in patterns):
                    configured_services.add(service_name)
    for service_name in configured_services:
        meter_names = requirements[service_name]
        missing_meters = sorted(set(meter_names) - set(selections))
        if missing_meters:
            raise PricingUnavailable(service_name + ': configure pricing selectors for ' + ', '.join(missing_meters))
        incomplete = [] if catalog_validation_only else [name for name in meter_names if name not in additional_usage]
        if incomplete:
            raise PricingUnavailable(service_name + ': supply quantities for ' + ', '.join(incomplete)
                                     + ' in additional_resource_usage')
        for name in meter_names:
            if selections[name].get('auto_zero'):
                raise PricingUnavailable(service_name + ': a used service meter cannot be marked not billed (' + name + ')')
    unpriced = [name for name, selection in selections.items()
                if isinstance(selection, dict) and selection.get('auto_zero')
                and not str(selection.get('not_enabled_reason') or '').strip()]
    if unpriced:
        raise PricingUnavailable('Pricing evidence is missing for: ' + ', '.join(unpriced)
                                 + '; these resources cannot be assumed free')
    missing = sorted(set(RESOURCES) - set(selections))
    if missing:
        raise PricingUnavailable('Configure exact pricing selections for: ' + ', '.join(missing))
    if any(not isinstance(selections[name], dict) for name in RESOURCES):
        raise PricingUnavailable('Each pricing selection must be an object')
    additional_usage = result.get('additional_resource_usage') or {}
    if not isinstance(additional_usage, dict):
        raise PricingUnavailable('additional_resource_usage must be an object keyed by additional meter name')
    for name in set(resource_units) - set(RESOURCES):
        if catalog_validation_only:
            additional_usage.setdefault(name, 0)
        elif name not in additional_usage:
            covers = selections[name].get('covers_services') or []
            if isinstance(covers, str):
                covers = [covers]
            if set(covers) & configured_services:
                raise PricingUnavailable(f'{name}: supply its estimated billed quantity in additional_resource_usage')
            if covers:
                # A configured selector is reusable across quotes. An unused
                # service meter contributes zero unless this TOC names it.
                additional_usage[name] = 0
            else:
                raise PricingUnavailable(f'{name}: supply its estimated billed quantity in additional_resource_usage')
        additional_usage[name] = _amount(additional_usage[name])
        if selections[name].get('auto_zero') and additional_usage[name] > 0:
            raise PricingUnavailable(f'{name}: a used additional meter cannot be marked not billed')
    for service_name in (() if catalog_validation_only else configured_services):
        meter_names = requirements[service_name]
        zero_meters = [name for name in meter_names if additional_usage.get(name, 0) <= 0]
        if zero_meters:
            raise PricingUnavailable(service_name + ': provide positive billed usage for ' + ', '.join(zero_meters))
    result['additional_resource_usage'] = additional_usage
    rates = {}
    if provider == 'aws':
        services = {}
        for name in resource_units:
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
        matches = {name: [] for name in resource_units}
        for name, selection in selections.items():
            if selection.get('auto_zero'):
                matches[name] = [{'rate': 0, 'unit': next(iter(UNITS.get(resource_units[name], {resource_units[name]}))),
                                  'sku': 'NOT_BILLED', 'dimension': 'not-enabled',
                                  'source': 'https://aws.amazon.com/pricing/',
                                  'effective_date': '',
                                  'note': selection.get('not_enabled_reason')}]
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
                    if row.get('Unit') not in UNITS.get(resource_units[name], {resource_units[name]}):
                        continue
                    # Attribute searches describe a product, which can also
                    # have hourly reserved terms. Only on-demand terms belong
                    # in this quote; exact rate-code requests remain strict.
                    if s.get('attributes') and row.get('TermType') != 'OnDemand':
                        continue
                    if row.get('TermType') != 'OnDemand' or row.get('Currency') != 'USD':
                        raise PricingUnavailable(f'{name}: tiered or non-on-demand rates require a different billing formula')
                    if row.get('StartingRange') not in ('0', '0.0000000000'):
                        if s.get('first_tier_only'):
                            continue
                        raise PricingUnavailable(f'{name}: tiered or non-on-demand rates require a different billing formula')
                    if row.get('EndingRange') not in ('Inf', 'Infinity'):
                        if s.get('first_tier_only'):
                            if not _selected_first_tier(row, s, name, result):
                                continue
                        elif not _storage_first_tier(row, s, name, result):
                            raise PricingUnavailable(f'{name}: tiered or non-on-demand rates require a different billing formula')
                    tier_note = None
                    if s.get('first_tier_only') and name != 'Storage' and row.get('EndingRange') not in ('Inf', 'Infinity'):
                        tier_note = (
                            f"First-tier rate only, below {row['EndingRange']} {row['Unit']}; "
                            "the quote blocks usage at or above this ceiling."
                        )
                    matches[name].append({'rate': row['PricePerUnit'], 'unit': row['Unit'],
                        'sku': row['SKU'], 'dimension': row['RateCode'], 'source': url,
                        'effective_date': row.get('EffectiveDate', ''),
                        'specifications': {key: row[field] for key, field in (
                            ('instance_type', 'Instance Type'), ('vcpu', 'vCPU'),
                            ('memory', 'Memory'), ('os', 'Operating System')) if row.get(field)},
                        **({'note': (f"S3 Standard first-tier estimate, at most {row['EndingRange']} GB; request charges are separately priced from mapped counts and account-level volume discounts are excluded. Regenerate if storage quantities change." if name == 'Storage' else tier_note)}
                           if s.get('first_tier_only') else {})})
        rates = {name: _choose(matches[name], name, unit) for name, unit in resource_units.items()}
    elif provider == 'azure':
        rates = {}
        for name, unit in resource_units.items():
            selection = selections[name]
            if selection.get('auto_zero'):
                rates[name] = _choose([{'rate': 0, 'unit': next(iter(UNITS.get(unit, {unit}))),
                                        'sku': 'NOT_BILLED', 'dimension': 'not-enabled',
                                        'source': 'https://azure.microsoft.com/en-us/pricing/',
                                        'effective_date': '',
                                        'note': selection.get('not_enabled_reason')}], name, unit)
            else:
                azure_rows = _azure(selection, regions[provider], result)
                if name == 'Managed database' and selection.get('max_storage_gb') is not None:
                    allocated = _amount(result.get('database_storage_gb', 20))
                    if allocated > _amount(selection['max_storage_gb']):
                        raise PricingUnavailable('Azure SQL S0 includes storage only up to 250 GB; choose a larger priced tier')
                    for row in azure_rows:
                        if row['unit'] != '1/Day':
                            raise PricingUnavailable('Azure SQL S0 meter must bill per database-day')
                        row['note'] = 'Azure SQL Database S0 Standard, billed per active database-day; up to 250 GB included. Extra backup, networking, and higher-tier usage are not included.'
                if name == 'Disk' and selection.get('meter_id') == 'ed9e91d2-0f0c-4d55-b3dd-7f69d4708b22':
                    # Central India Premium SSD P4 LRS is a fixed 32-GiB disk.
                    # Normalize only this known meter, with the same allocation
                    # enforced in the workbook so fractional disks cannot result.
                    size = result.get('disk_gb_per_node', 32)
                    if isinstance(size, bool) or float(size) != 32:
                        raise PricingUnavailable('Azure P4 disk selection requires exactly 32 GiB per node')
                    result['disk_gb_per_node'] = 32
                    for row in azure_rows:
                        if row['unit'] != '1/Month':
                            raise PricingUnavailable('Azure P4 disk billing unit changed')
                        row['provider_rate'] = _amount(row['rate'])
                        row['provider_unit'] = row['unit']
                        row['rate'] = row['provider_rate'] / 32
                        row['unit'] = '1 GB/Month'
                        row['note'] = 'Premium SSD P4 LRS: one 32-GiB disk per node; monthly disk price divided by 32 for workbook arithmetic. Keep disk size at 32 GiB; regenerate to change SKU. Retention uses the workbook 30-day month estimate.'
                rates[name] = _choose(azure_rows, name, unit)
    else:
        grouped = {}
        for name, unit in resource_units.items():
            selection = selections[name]
            if selection.get('auto_zero'):
                rates[name] = _choose([{'rate': 0, 'unit': next(iter(UNITS.get(unit, {unit}))),
                                        'sku': 'NOT_BILLED', 'dimension': 'not-enabled',
                                        'source': 'https://cloud.google.com/pricing',
                                        'effective_date': '',
                                        'note': selection.get('not_enabled_reason')}], name, unit)
                continue
            service_id = selection.get('service_id')
            sku_id = selection.get('sku_id')
            if not service_id or not sku_id:
                raise PricingUnavailable(f'{name}: GCP requires configured exact service_id and sku_id')
            grouped.setdefault(str(service_id), []).append((name, unit, selection, str(sku_id)))
        matches = {name: [] for name in resource_units if name not in rates}
        for service_id, requested in grouped.items():
            wanted = {item[3] for item in requested}
            for sku, source in _gcp_catalog(service_id, regions[provider]):
                if sku.get('skuId') not in wanted:
                    continue
                for name, unit, selection, sku_id in requested:
                    if sku.get('skuId') == sku_id:
                        matches[name].append(_gcp_rate(sku, selection, unit, source))
        for name, unit in resource_units.items():
            if name not in rates:
                rates[name] = _choose(matches[name], name, unit)
    checked = datetime.now(timezone.utc)
    validity = int(result.get('quote_validity_days') or 7)
    if not 1 <= validity <= 365:
        raise PricingUnavailable('Quote validity must be 1 to 365 days')
    for row in rates.values():
        row['verified_date'] = checked.isoformat()
        row['note'] = row.get('note') or f"SKU {row['sku']}; dimension {row['dimension']}; effective {row['effective_date']}; USD public retail price"
    if provider == 'aws' and any(float(day.get('managed_db') or 0) > 0 for day in (result.get('lab_day_mapping') or [])):
        rates['Managed database']['note'] += ' Assumed RDS MySQL/PostgreSQL Single-AZ db.t3.micro; '
        rates['Managed database storage']['note'] += f"Assumed {result.get('database_storage_gb', 20)} GB gp3 per database. Automated backup allocation up to provisioned storage is included; extra retained backups/snapshots are not modeled."
    result.update(rate_card_overrides=rates,
        vm_profile_rates={p: rates['VM ' + p]['rate'] for p in ('Light', 'Heavy')},
        vm_profile_sources={p: rates['VM ' + p]['source'] for p in ('Light', 'Heavy')},
        rate_snapshot_id='LCQ-' + uuid4().hex.upper(), rate_checked_at=checked.isoformat(),
        rate_card_verified_date=checked.isoformat(), rate_snapshot_source=rates['VM']['source'],
        quote_valid_until=(checked + timedelta(days=validity)).isoformat(),
        pricing_status='provider_api_verified_public_retail')
    return result


def refresh_exchange_rate(values):
    """Fetch a fresh published observation; never fall back to a saved number."""
    sources = ('https://api.frankfurter.dev/v1/latest?from=USD&to=INR',
               'https://open.er-api.com/v6/latest/USD')
    last_error = None
    for url in sources:
        try:
            with urlopen(url, timeout=20) as response:
                data = json.load(response)
            checked = datetime.now(timezone.utc)
            if 'base_code' in data:
                if data.get('result') != 'success':
                    raise PricingUnavailable('FX provider reported failure')
                base = data['base_code']
                observed = datetime.fromtimestamp(data['time_last_update_unix'], timezone.utc)
                attribution = 'https://www.exchangerate-api.com'
            else:
                base = data.get('base')
                observed = datetime.fromisoformat(data['date']).replace(tzinfo=timezone.utc)
                attribution = 'https://frankfurter.dev'
            raw_rate = data.get('rates', {}).get('INR', 0)
            if isinstance(raw_rate, bool):
                raise PricingUnavailable('Invalid exchange rate')
            rate = _amount(raw_rate)
            if base != 'USD' or rate <= 0 or not 0 <= (checked - observed).total_seconds() <= 7 * 86400:
                raise PricingUnavailable('FX provider returned invalid or stale USD/INR pricing')
            return dict(values, fx_rate=rate, fx_rate_source=url,
                        fx_rate_date=observed.isoformat(), fx_rate_fetched_at=checked.isoformat(),
                        fx_rate_attribution=attribution)
        except Exception as exc:
            last_error = exc
    raise PricingUnavailable('Current USD/INR pricing unavailable from all sources') from last_error
