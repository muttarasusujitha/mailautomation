"""Validated assumptions shared by lab-cost API and document generation."""
import math
import re
from datetime import datetime
from urllib.parse import urlparse


SERVICE_METER_REQUIREMENTS = {
    'Amazon DynamoDB': ('DynamoDB read request units', 'DynamoDB write request units', 'DynamoDB storage GB-month'),
    'AWS Lambda': ('Lambda invocations', 'Lambda GB-seconds'),
    'Amazon API Gateway': ('API Gateway requests',),
    'AWS Step Functions': ('Step Functions state transitions',),
    'Amazon EventBridge': ('EventBridge events',),
    'AWS Secrets Manager': ('Secrets Manager secret-months', 'Secrets Manager API requests'),
    'AWS Key Management Service (KMS)': ('KMS key-months', 'KMS API requests'),
    'Elastic Load Balancing (ALB/NLB)': ('Load balancer hours', 'Load balancer capacity unit-hours'),
    'Amazon Route 53': ('Route 53 hosted-zone months', 'Route 53 DNS queries'),
    'Amazon ECR': ('ECR image storage GB-month',),
    'Amazon CloudWatch': ('CloudWatch log ingestion GB', 'CloudWatch custom metric-months', 'CloudWatch alarm-months'),
    'AWS CloudTrail': ('CloudTrail data events', 'CloudTrail log storage GB-month'),
    'AWS NAT Gateway': ('NAT gateway hours', 'NAT processed GB'),
    'Amazon CloudFront': ('CloudFront requests', 'CloudFront data transfer GB'),
    'Amazon ECS/Fargate': ('Fargate vCPU-hours', 'Fargate GB-hours'),
    'Amazon Aurora': ('Aurora instance-hours', 'Aurora storage GB-month'),
    'Amazon EFS': ('EFS storage GB-month',),
    'Amazon Kinesis': ('Kinesis shard-hours',),
    'Amazon S3 Glacier': ('Glacier storage GB-month',),
    'AWS Systems Manager': ('Systems Manager managed-node hours',),
    'Amazon SageMaker': ('SageMaker instance-hours',),
    'Amazon Bedrock': ('Bedrock input tokens', 'Bedrock output tokens'),
    'Amazon Redshift': ('Redshift node-hours',),
    'AWS Glue': ('Glue DPU-hours',),
    'Azure Database for PostgreSQL/MySQL': ('Azure database vCore-hours', 'Azure database storage GB-month'),
    'Azure Files': ('Azure Files storage GB-month', 'Azure Files transactions'),
    'Azure Load Balancer': ('Azure load balancer hours',),
    'Azure DNS': ('Azure DNS hosted-zone months', 'Azure DNS queries'),
    'Azure Front Door': ('Azure Front Door requests',),
    'Azure Application Gateway': ('Azure Application Gateway hours',),
    'Azure NAT Gateway': ('Azure NAT gateway hours', 'Azure NAT processed GB'),
    'Azure Functions': ('Azure Functions executions', 'Azure Functions GB-seconds'),
    'Azure API Management': ('Azure API Management unit-hours',),
    'Azure Cosmos DB': ('Cosmos DB request units', 'Cosmos DB storage GB-month'),
    'Azure Container Registry': ('Azure registry storage GB-month',),
    'Azure Container Apps': ('Azure Container Apps vCPU-seconds',),
    'Azure App Service': ('Azure App Service plan hours',),
    'Azure Key Vault': ('Azure Key Vault operations',),
    'Azure Event Hubs': ('Azure Event Hubs throughput unit-hours',),
    'Azure Service Bus': ('Azure Service Bus operations',),
    'Azure Event Grid': ('Azure Event Grid operations',),
    'Azure Logic Apps': ('Azure Logic Apps action executions',),
    'Azure Monitor': ('Azure Monitor log ingestion GB',),
    'Azure Data Factory': ('Azure Data Factory activity runs',),
    'Azure Databricks': ('Azure Databricks DBU-hours',),
    'Azure Machine Learning': ('Azure ML compute instance-hours',),
    'Azure OpenAI Service': ('Azure OpenAI input tokens', 'Azure OpenAI output tokens'),
    'Google Cloud Load Balancing': ('GCP load balancer forwarding-rule hours',),
    'Google Cloud NAT': ('GCP NAT gateway hours', 'GCP NAT processed GB'),
    'Google Cloud Functions': ('GCP Functions invocations', 'GCP Functions GB-seconds'),
    'Google Cloud Run': ('GCP Cloud Run vCPU-seconds',),
    'Google BigQuery': ('BigQuery query bytes',),
    'Google Cloud KMS': ('GCP KMS key-months', 'GCP KMS operations'),
    'Google Cloud Logging': ('GCP log ingestion GB',),
    'Google Cloud DNS': ('GCP DNS managed-zone months', 'GCP DNS queries'),
    'Google Pub/Sub': ('GCP Pub/Sub message volume GB',),
    'Google Artifact Registry': ('GCP artifact storage GB-month',),
    'Google Cloud Build': ('GCP Cloud Build build-minutes',),
    'AWS CodeBuild/CodePipeline': ('AWS CodeBuild build-minutes', 'AWS CodePipeline active pipeline-months'),
    'Azure DevOps Pipelines': ('Azure DevOps parallel-job minutes',),
    'Amazon SQS/SNS': ('AWS SQS requests', 'AWS SNS publish requests'),
}

# Units and plain-language quantity prompts shown by the topic input planner.
# These prompts describe billable measurements; they do not set default usage.
SERVICE_METER_INPUTS = {
    'Amazon DynamoDB': {
        'DynamoDB read request units': ('read request units', 'Total read request units for the experiment (include strongly consistent reads and item sizes).'),
        'DynamoDB write request units': ('write request units', 'Total write request units for the experiment (include item sizes).'),
        'DynamoDB storage GB-month': ('GB-month', 'Average table and index storage in GB multiplied by the billed fraction of a month.'),
    },
    'AWS Lambda': {
        'Lambda invocations': ('requests', 'Total function invocations.'),
        'Lambda GB-seconds': ('GB-seconds', 'Sum of configured memory in GB multiplied by billed execution seconds across all invocations.'),
    },
    'Amazon API Gateway': {
        'API Gateway requests': ('requests', 'Total API requests. First choose REST API or HTTP API; their prices differ.'),
    },
    'AWS Step Functions': {
        'Step Functions state transitions': ('state transitions', 'Total billed state transitions across all workflow executions.'),
    },
    'Amazon EventBridge': {
        'EventBridge events': ('billed 64-KB payload units', 'Estimate billable payload units from event count and payload size; one event can consume multiple 64-KB units.'),
    },
    'AWS Secrets Manager': {
        'Secrets Manager secret-months': ('secret-months', 'Number of stored secrets multiplied by the billed fraction of a month.'),
        'Secrets Manager API requests': ('API requests', 'Total billable Secrets Manager API calls.'),
    },
    'AWS Key Management Service (KMS)': {
        'KMS key-months': ('key-months', 'Number of billable customer-managed keys multiplied by the billed fraction of a month.'),
        'KMS API requests': ('API requests', 'Total billable KMS API requests by operation.'),
    },
    'Elastic Load Balancing (ALB/NLB)': {
        'Load balancer hours': ('hours', 'Total hours each load balancer is provisioned.'),
        'Load balancer capacity unit-hours': ('LCU/NLCU-hours', 'Capacity-unit hours from expected traffic, connections, processed bytes, and rule evaluations.'),
    },
    'Amazon Route 53': {
        'Route 53 hosted-zone months': ('hosted-zone-months', 'Number of hosted zones multiplied by the billed fraction of a month.'),
        'Route 53 DNS queries': ('queries', 'Total billable DNS queries by routing policy and query type.'),
    },
    'Amazon CloudWatch': {
        'CloudWatch log ingestion GB': ('GB', 'Uncompressed log data ingested during the experiment.'),
        'CloudWatch custom metric-months': ('metric-months', 'Number of billable custom metrics multiplied by the billed fraction of a month.'),
        'CloudWatch alarm-months': ('alarm-months', 'Number of billable alarms multiplied by the billed fraction of a month.'),
    },
    'AWS CloudTrail': {
        'CloudTrail data events': ('events', 'Total billable data events recorded; management events and data events have different billing.'),
        'CloudTrail log storage GB-month': ('GB-month', 'Average retained log storage in GB multiplied by the billed fraction of a month.'),
    },
    'Azure Functions': {
        'Azure Functions executions': ('executions', 'Total function executions.'),
        'Azure Functions GB-seconds': ('GB-seconds', 'Sum of allocated memory in GB multiplied by execution seconds.'),
    },
    'Azure Cosmos DB': {
        'Cosmos DB request units': ('RU', 'Total request units consumed, based on operation type, item size, consistency, and indexing.'),
        'Cosmos DB storage GB-month': ('GB-month', 'Average data and index storage in GB multiplied by the billed fraction of a month.'),
    },
    'Azure OpenAI Service': {
        'Azure OpenAI input tokens': ('tokens', 'Input tokens processed by model.'),
        'Azure OpenAI output tokens': ('tokens', 'Output tokens generated by model.'),
    },
}

SERVICE_PRICING_CHOICES = {
    'Amazon API Gateway': [{'key': 'api_type', 'prompt': 'Which API type will the lab deploy?', 'options': ['REST API', 'HTTP API']}],
    'Elastic Load Balancing (ALB/NLB)': [{'key': 'load_balancer_type', 'prompt': 'Which load balancer will the lab use?', 'options': ['Application Load Balancer (ALB)', 'Network Load Balancer (NLB)']}],
    'Amazon DynamoDB': [{'key': 'capacity_mode', 'prompt': 'Which DynamoDB capacity mode will the lab use?', 'options': ['On-demand', 'Provisioned']}],
    'Amazon Aurora': [{'key': 'engine', 'prompt': 'Which Aurora-compatible database engine and deployment mode?', 'options': ['Aurora MySQL provisioned', 'Aurora PostgreSQL provisioned', 'Aurora Serverless']}],
}

SERVICE_USAGE_MODEL_BLOCKERS = {
    'Amazon EventBridge': 'AWS bills event payload in 64-KB chunks and pricing can vary by event source/destination; a raw event count alone is insufficient.',
    'Amazon DynamoDB': 'The current workbook needs a tier-aware storage formula and capacity-mode-specific request pricing before a complete quote can be issued.',
    'Amazon API Gateway': 'Choose REST API or HTTP API before selecting a live rate.',
    'Amazon Aurora': 'Choose engine, provisioned or Serverless mode, instance size or capacity range, storage, and backup retention.',
}


def topic_quote_inputs(toc, provider):
    """Return service-level quote questions for the named cloud services in a TOC."""
    from shared.lab_architecture import architecture_summary

    architecture = architecture_summary(toc if isinstance(toc, dict) else {}, provider)
    services = []
    seen = set()
    for day in architecture.get('days') or []:
        for name in day.get('services') or []:
            if name not in SERVICE_METER_REQUIREMENTS or name in seen:
                continue
            seen.add(name)
            inputs = SERVICE_METER_INPUTS.get(name, {})
            services.append({
                'service': name,
                'topic_days': [item['day'] for item in architecture['days'] if name in item.get('services', [])],
                'pricing_choices': SERVICE_PRICING_CHOICES.get(name, []),
                'usage_inputs': [
                    {'name': meter, 'unit': inputs.get(meter, ('provider units', 'Supply the expected billed quantity for this experiment.'))[0],
                     'prompt': inputs.get(meter, ('provider units', 'Supply the expected billed quantity for this experiment.'))[1],
                     'value': None, 'required': True}
                    for meter in SERVICE_METER_REQUIREMENTS[name]
                ],
                'pricing_model_blocker': SERVICE_USAGE_MODEL_BLOCKERS.get(name),
            })
    return {
        'provider': str(provider or '').strip().lower(),
        'services': services,
        'unmatched_services': architecture.get('unpriced_services') or [],
        'complete_estimate_possible': not bool(architecture.get('unpriced_services')) and all(
            item['pricing_model_blocker'] is None for item in services
        ),
    }


def _valid_http_url(value):
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _valid_timestamp(value):
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return True
    except (TypeError, ValueError):
        return False


def validate_lab_cost_inputs(values, *, require_fx=True):
    result = dict(values or {})
    selections = result.get('pricing_selections')
    if selections is not None and not isinstance(selections, dict):
        raise ValueError('pricing_selections must be an object keyed by resource name')
    if isinstance(selections, dict) and any(not isinstance(item, dict) for item in selections.values()):
        raise ValueError('Each pricing selection must be an object')
    result.setdefault('database_storage_gb', 20)
    result.setdefault('storage_put_requests_per_participant_day', 1)
    result.setdefault('storage_get_requests_per_participant_day', 10)
    for key in ('local_costs_status', 'license_costs_status'):
        if result.get(key) is not None and result[key] not in ('covered', 'not_required', 'unverified'):
            raise ValueError(key + ' must be covered, not_required, or unverified')
    unpriced = result.get('required_unpriced_costs')
    if unpriced is not None and (not isinstance(unpriced, list) or
            any(not isinstance(item, str) or not item.strip() for item in unpriced)):
        raise ValueError('required_unpriced_costs must be a list of non-empty cost descriptions')
    setups = result.get('lab_day_setups')
    if setups is not None and not isinstance(setups, (list, dict)):
        raise ValueError('lab_day_setups must be a list or day-number keyed object')
    setup_values = list(setups.values()) if isinstance(setups, dict) else list(setups or [])
    if result.get('lab_setup') is not None:
        setup_values.append(result['lab_setup'])
    if any(value not in ('individual', 'shared', 'local', 'mixed') for value in setup_values):
        raise ValueError('Lab setup must be individual, shared, local, or mixed')
    required = ("cloud_provider", "cloud_region", "hours_per_day", "participant_count") + (("fx_rate",) if require_fx else ())
    missing = [key for key in required if result.get(key) in (None, "")]
    if missing:
        raise ValueError("Confirm lab-cost inputs: " + ", ".join(missing))
    provider = str(result["cloud_provider"]).strip().lower()
    regions = {
        "aws": {"india-mumbai", "mumbai", "ap-south-1"},
        "azure": {"central-india", "centralindia", "central india"},
        "gcp": {"mumbai", "gcp mumbai", "asia-south1"},
    }
    region = str(result["cloud_region"]).strip().lower()
    if provider not in regions or region not in regions[provider]:
        raise ValueError("Unsupported provider/region pair; a matching rate card is required")
    for key in ("hours_per_day", "participant_count") + (("fx_rate",) if require_fx else ()):
        if isinstance(result[key], bool):
            raise ValueError(key + " must be a number, not a boolean")
        number = float(result[key])
        if not math.isfinite(number) or number <= 0:
            raise ValueError(key + " must be a finite positive number")
        if key == "hours_per_day" and number > 24:
            raise ValueError("Lab hours per day cannot exceed 24")
        if key == "participant_count" and not number.is_integer():
            raise ValueError("participant_count must be a whole number")
        result[key] = int(number) if key == "participant_count" else number
    support = result.get("lab_support_per_participant")
    if support is not None:
        support = float(support)
        if not math.isfinite(support) or support < 0:
            raise ValueError("lab_support_per_participant must be finite and non-negative")
        result["lab_support_per_participant"] = support
    for key in ("lab_support_per_participant_day", "disk_gb_per_node"):
        if result.get(key) is None:
            continue
        number = float(result[key])
        if not math.isfinite(number) or number < 0:
            raise ValueError(key + " must be finite and non-negative")
        result[key] = number
    mapping = result.get("lab_day_mapping")
    if mapping is not None and not isinstance(mapping, (list, dict)):
        raise ValueError("lab_day_mapping must be a list or a day-number keyed object")
    mapping_items = mapping.values() if isinstance(mapping, dict) else (mapping or [])
    numeric_mapping_keys = ("vm_qty", "k8s_control_plane", "k8s_worker_nodes", "managed_db",
                            "object_storage_gb", "storage_put_requests", "storage_get_requests", "active_days")
    for item in mapping_items:
        if not isinstance(item, dict):
            raise ValueError("each lab_day_mapping entry must be an object")
        profile = item.get("vm_profile")
        if profile is not None and str(profile).strip().lower() not in {"light", "heavy", "none"}:
            raise ValueError("vm_profile must be Light, Heavy, or None")
        for key in numeric_mapping_keys:
            value = item.get(key)
            if value is None:
                continue
            if isinstance(value, bool):
                raise ValueError(key + " must be a number, not a boolean")
            number = float(value)
            if not math.isfinite(number) or number < 0:
                raise ValueError(key + " must be finite and non-negative")
            if key != "object_storage_gb" and not number.is_integer():
                raise ValueError(key + " must be a whole number; fractional quantities cannot be silently rounded")
            if key == "active_days" and number < 1:
                raise ValueError("active_days must be at least one")
    additional_usage = result.get('additional_resource_usage')
    if additional_usage is not None:
        if not isinstance(additional_usage, dict):
            raise ValueError('additional_resource_usage must be an object keyed by meter name')
        for name, value in additional_usage.items():
            if not isinstance(name, str) or not name.strip() or isinstance(value, bool):
                raise ValueError('additional_resource_usage keys must be names and values must be numbers')
            number = float(value)
            if not math.isfinite(number) or number < 0:
                raise ValueError(f'additional_resource_usage[{name}] must be finite and non-negative')
            additional_usage[name] = number
    for key in ("contingency_percent", "tax_percent", "clahan_margin_percent", "client_lab_markup_percent"):
        if result.get(key) is not None:
            if isinstance(result[key], bool):
                raise ValueError(key + " must be a number, not a boolean")
            number = float(result[key])
            if not math.isfinite(number) or not 0 <= number <= 100:
                raise ValueError(key + " must be between 0 and 100")
            result[key] = number
    # The trainer request owns the canonical setting. Keep the former document
    # setting as an alias for existing direct callers, including an explicit 0%.
    markup = result.get('clahan_margin_percent')
    if markup is None:
        markup = result.get('client_lab_markup_percent')
    if markup is None:
        markup = 30.0
    result['clahan_margin_percent'] = markup
    result['client_lab_markup_percent'] = markup
    for key in ("storage_gb", "egress_gb", "build_minutes", "monitoring_gb", "k8s_worker_nodes",
                "database_storage_gb", "storage_put_requests_per_participant_day",
                "storage_get_requests_per_participant_day"):
        if result.get(key) is not None:
            number = float(result[key])
            if not math.isfinite(number) or number < 0:
                raise ValueError(key + " must be finite and non-negative")
            result[key] = number
    profile_rates = result.get("vm_profile_rates")
    if profile_rates is not None and not isinstance(profile_rates, dict):
        raise ValueError("vm_profile_rates must be an object with Light and Heavy rates")
    if isinstance(profile_rates, dict):
        for profile in ("light", "heavy"):
            value = profile_rates.get(profile) if profile in profile_rates else profile_rates.get(profile.title())
            if value is None:
                continue
            number = float(value)
            if not math.isfinite(number) or number < 0:
                raise ValueError("VM profile rates must be finite and non-negative")
    profile_sources = result.get("vm_profile_sources")
    if profile_sources is not None and not isinstance(profile_sources, dict):
        raise ValueError("vm_profile_sources must be an object with Light and Heavy source URLs")
    if isinstance(profile_sources, dict):
        for profile, source in profile_sources.items():
            if source and not _valid_http_url(source):
                raise ValueError(f"VM profile source for {profile} must be an http(s) URL")
    overrides = result.get("rate_card_overrides")
    if overrides is not None and not isinstance(overrides, dict):
        raise ValueError("rate_card_overrides must be an object keyed by resource")
    if isinstance(overrides, dict):
        for resource, override in overrides.items():
            if not isinstance(override, dict):
                raise ValueError(f"rate-card override for {resource} must be an object")
            spec = override.get('specifications')
            if spec is not None and (not isinstance(spec, dict) or
                    any(not isinstance(value, (str, int, float)) for value in spec.values())):
                raise ValueError(f"specifications for {resource} must be an object of text or numeric values")
            if override.get("rate") is not None:
                rate = float(override["rate"])
                if not math.isfinite(rate) or rate < 0:
                    raise ValueError(f"rate-card override for {resource} must be finite and non-negative")
            if override.get("source") and not _valid_http_url(override["source"]):
                raise ValueError(f"rate-card source for {resource} must be an http(s) URL")
            if override.get("verified_date") and not _valid_timestamp(override["verified_date"]):
                raise ValueError(f"rate-card verified_date for {resource} must be ISO-8601")
    for key in ("rate_snapshot_id", "rate_snapshot_source", "rate_checked_at", "quote_valid_until"):
        if result.get(key) is not None and not str(result[key]).strip():
            raise ValueError(f"{key} cannot be empty")
    if result.get("rate_snapshot_source") and not _valid_http_url(result["rate_snapshot_source"]):
        raise ValueError("rate_snapshot_source must be an http(s) URL")
    for key in ("rate_checked_at", "quote_valid_until"):
        if result.get(key) and not _valid_timestamp(result[key]):
            raise ValueError(f"{key} must be ISO-8601")
    if result.get("price_change_review_threshold_percent") is not None:
        threshold = float(result["price_change_review_threshold_percent"])
        if not math.isfinite(threshold) or threshold < 0 or threshold > 100:
            raise ValueError("price_change_review_threshold_percent must be between 0 and 100")
        result["price_change_review_threshold_percent"] = threshold
    result["cloud_provider"] = provider
    result["cloud_region"] = {"aws": "Mumbai", "azure": "Central India", "gcp": "GCP Mumbai"}[provider]
    return result


def lab_resources(text):
    """Local labs do not imply paid managed services or cloud VMs."""
    text = str(text).lower()
    cloud = any(word in text for word in ("ec2", "azure vm", "compute engine", "cloud vm", "cloud lab"))
    def service(*names):
        return any(re.search(r'\b' + re.escape(name) + r'\b', text) for name in names)

    k8s = service("eks", "aks", "gke", "managed kubernetes")
    database = service("rds", "aurora", "azure sql", "azure database for postgresql",
                       "azure database for mysql", "cloud sql")
    storage = service("s3", "blob", "object storage", "cloud storage", "gcs")
    local_hint = any(word in text for word in ("local lab", "local machine", "localhost", "minikube", "kind cluster", "docker desktop"))
    # A direct managed-service name is stronger evidence than a local tool
    # appearing elsewhere in the same topic description.
    local = local_hint and not (cloud or k8s or database or storage)
    heavy = any(word in text for word in ("docker", "terraform", "ansible", "jenkins", "ci/cd", "pipeline", "agentic ai", "llm"))
    return {
        "vm": cloud and not local,
        "heavy": heavy,
        "k8s": k8s and not local,
        "database": not local and database,
        "storage": not local and storage,
    }


def validate_lab_pricing_coverage(toc, assumptions):
    """Reject an incomplete architecture before fetching or reusing prices."""
    from shared.lab_curriculum import cloud_lab_text
    import re
    from shared.lab_architecture import architecture_summary, services_for_day
    selections = assumptions.get('pricing_selections') or {}
    required = set()
    unresolved = []
    mappings = assumptions.get('lab_day_mapping') or {}
    provider = str(assumptions.get('cloud_provider') or '').lower()
    for index, day in enumerate(toc.get('days') or [], 1):
        text = cloud_lab_text(day)
        resources = lab_resources(text)
        mapping = (mappings[index - 1] if index <= len(mappings) else {}) if isinstance(mappings, list) else (mappings.get(str(index)) or mappings.get(index) or {})
        explicit_services = services_for_day(text, assumptions.get('cloud_provider'))
        local = not text
        practical = any(word in text for word in ('linux', 'shell scripting', 'jenkins', 'docker', 'kubernetes', 'helm', 'terraform', 'ansible'))
        if mapping and not local and (practical or any(resources[key] for key in ('vm', 'k8s', 'database', 'storage'))):
            quantities = ('vm_qty', 'k8s_control_plane', 'k8s_worker_nodes', 'managed_db', 'object_storage_gb')
            if not any(float(mapping.get(key) or 0) > 0 for key in quantities):
                unresolved.append(str(index))
        # A mapped VM must not mask an explicitly named managed service whose
        # own quantity is zero or absent from the plan.
        for service_item in explicit_services:
            family = service_item['resource_family']
            needed = {
                'vm': ('vm_qty',),
                'k8s': ('k8s_control_plane', 'k8s_worker_nodes'),
                'database': ('managed_db',),
                'storage': ('object_storage_gb',),
                'disk': ('vm_qty', 'k8s_worker_nodes'),
            }.get(family, ())
            allocated = [float(mapping.get(key) or 0) > 0 for key in needed]
            included = all(allocated) if family == 'k8s' else any(allocated)
            if needed and not included:
                unresolved.append(str(index))
        if practical and not local and not resources['vm'] and not resources['k8s'] and not mapping:
            unresolved.append(str(index))
        def used(key, inferred):
            value = mapping.get(key, inferred)
            if isinstance(value, str) and value.startswith('='):
                return True
            return float(value or 0) > 0
        if used('vm_qty', resources['vm']):
            profile = str(mapping.get('vm_profile') or ('Heavy' if resources['heavy'] else 'Light')).title()
            if profile not in ('Light', 'Heavy'):
                raise ValueError('A nonzero VM quantity requires a Light or Heavy VM profile')
            required.update(('VM ' + profile, 'Disk'))
        if used('k8s_control_plane', resources['k8s']):
            required.add('Kubernetes control plane')
        if used('k8s_worker_nodes', resources['k8s']):
            required.update(('Kubernetes worker', 'Disk'))
        if used('managed_db', resources['database']):
            required.add('Managed database')
            if provider == 'aws':
                required.add('Managed database storage')
        if used('object_storage_gb', resources['storage']):
            required.update(('Storage', 'Object storage PUT requests', 'Object storage GET requests'))
            if not all(key in mapping for key in ('storage_put_requests', 'storage_get_requests')):
                unresolved.append(str(index))
    for key, resource in (('egress_gb', 'Egress'), ('build_minutes', 'Build runner'), ('monitoring_gb', 'Monitoring')):
        if float(assumptions.get(key, 0) or 0) > 0:
            required.add(resource)
    additional_usage = assumptions.get('additional_resource_usage') or {}
    additional_names = set(selections) - {
        'VM', 'VM Light', 'VM Heavy', 'Kubernetes control plane', 'Kubernetes worker',
        'Disk', 'Storage', 'Egress', 'Object storage PUT requests',
        'Object storage GET requests', 'Build runner', 'Managed database',
        'Managed database storage', 'Monitoring',
    }
    configured_service_meters = {}
    for meter_name in additional_names:
        selector = selections.get(meter_name) or {}
        services = selector.get('covers_services') or []
        if isinstance(services, str):
            services = [services]
        for service_name in services:
            configured_service_meters.setdefault(service_name, set()).add(meter_name)
    architecture = architecture_summary(
        toc, provider, assumptions.get('kubernetes_tier') or 'free')
    mapped_rows = list(mappings.values()) if isinstance(mappings, dict) else list(mappings)
    for index, day_architecture in enumerate(architecture.get('days') or []):
        mapping = mapped_rows[index] if index < len(mapped_rows) and isinstance(mapped_rows[index], dict) else {}
        allocated = any(float(mapping.get(key) or 0) > 0 for key in (
            'vm_qty', 'k8s_control_plane', 'k8s_worker_nodes', 'managed_db', 'object_storage_gb'))
        if not allocated:
            day_architecture['unpriced_services'] = []
            continue
        text = cloud_lab_text((toc.get('days') or [])[day_architecture['day'] - 1])
        selected_services = services_for_day(text, provider)
        service_names = {item['name'] for item in selected_services}
        day_architecture['unpriced_services'] = sorted(set(day_architecture.get('unpriced_services') or []) |
                                                        (service_names & set(SERVICE_METER_REQUIREMENTS)))
    covered_services = set()
    incomplete_service_meters = []
    selected_meter_services = set()
    for meter_name in additional_names:
        selector = selections.get(meter_name) or {}
        services = selector.get('covers_services') or []
        if isinstance(services, str):
            services = [services]
        selected_meter_services.update(services)
    for service_name, meter_names in SERVICE_METER_REQUIREMENTS.items():
        # A saved selector says how a named service can be priced; it does
        # not mean every quote uses that service. Require its meters only
        # when the current TOC architecture actually names it.
        if service_name not in architecture['unpriced_services']:
            continue
        configured = configured_service_meters.get(service_name, set())
        if set(meter_names).issubset(configured) and all(
                name in additional_usage and not selections[name].get('auto_zero')
                for name in meter_names):
            covered_services.add(service_name)
        else:
            incomplete_service_meters.append(service_name + ' (' + ', '.join(meter_names) + ')')
    unrelated_meter_coverage = sorted(selected_meter_services - set(SERVICE_METER_REQUIREMENTS))
    if unrelated_meter_coverage:
        incomplete_service_meters.extend(service + ' (no supported meter policy)' for service in unrelated_meter_coverage)
    remaining_unpriced = [name for name in architecture['unpriced_services']
                          if name not in covered_services]
    architecture['unpriced_services'] = remaining_unpriced
    for day in architecture.get('days', []):
        day['unpriced_services'] = [name for name in day.get('unpriced_services', [])
                                    if name not in covered_services]
        if not day['unpriced_services']:
            day['plan'] = day['plan'].replace('; pricing model required for ', '; metered rates configured for ')
    if incomplete_service_meters:
        errors_for_meter_configuration = 'Configure live price selectors and usage quantities for: ' + '; '.join(incomplete_service_meters)
    else:
        errors_for_meter_configuration = ''
    # AKS Free is Microsoft's documented learning/test tier: the control
    # plane has no charge, while its VM agent nodes and disks remain billable.
    # Standard/Premium AKS must use a priced control-plane selection.
    free_aks_control_plane = provider == 'azure' and str(
        assumptions.get('kubernetes_tier') or 'free').lower() == 'free'
    missing = sorted(name for name in required if (
        not selections.get(name) or
        (selections[name].get('auto_zero') and not (
            name == 'Kubernetes control plane' and free_aks_control_plane
        ))
    ))
    errors = []
    if unresolved:
        errors.append('Specify local/shared/cloud lab infrastructure or include every explicitly named cloud service in lab_day_mapping for days: ' + ', '.join(sorted(set(unresolved))))
    if missing:
        errors.append('Used resources require exact pricing selections and cannot be marked not billed: ' + ', '.join(missing))
    assumptions['service_architecture'] = architecture
    if architecture['unpriced_services']:
        errors.append('These explicitly named services need a supported metered cost model before a complete estimate can be issued: ' + ', '.join(architecture['unpriced_services']))
    if errors_for_meter_configuration:
        errors.append(errors_for_meter_configuration)
    if errors:
        raise ValueError('Incomplete lab estimate. ' + '; '.join(errors))
