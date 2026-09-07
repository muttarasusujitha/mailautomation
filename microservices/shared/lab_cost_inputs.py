"""Validated assumptions shared by lab-cost API and document generation."""
import math
from datetime import datetime
from urllib.parse import urlparse


def _valid_http_url(value):
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _valid_timestamp(value):
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return True
    except (TypeError, ValueError):
        return False


def validate_lab_cost_inputs(values):
    result = dict(values or {})
    required = ("cloud_provider", "cloud_region", "hours_per_day", "participant_count", "fx_rate")
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
    for key in ("hours_per_day", "participant_count", "fx_rate"):
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
    numeric_mapping_keys = ("vm_qty", "k8s_control_plane", "k8s_worker_nodes", "managed_db", "object_storage_gb", "active_days")
    for item in mapping_items:
        if not isinstance(item, dict):
            raise ValueError("each lab_day_mapping entry must be an object")
        profile = item.get("vm_profile")
        if profile is not None and str(profile).strip().lower() not in {"light", "heavy", "none"}:
            raise ValueError("vm_profile must be Light, Heavy, or None")
        for key in numeric_mapping_keys:
            value = item.get(key)
            if value is None or (isinstance(value, str) and value.startswith("=")):
                continue
            number = float(value)
            if not math.isfinite(number) or number < 0:
                raise ValueError(key + " must be finite and non-negative")
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
    local = any(word in text for word in ("local lab", "local machine", "localhost", "minikube", "kind cluster", "docker desktop"))
    cloud = any(word in text for word in ("ec2", "azure vm", "compute engine", "cloud vm", "cloud lab"))
    k8s = any(word in text for word in ("eks", "aks", "gke", "managed kubernetes"))
    heavy = any(word in text for word in ("docker", "terraform", "ansible", "jenkins", "ci/cd", "pipeline", "agentic ai", "llm"))
    return {
        "vm": cloud and not local,
        "heavy": heavy,
        "k8s": k8s and not local,
        "database": not local and any(word in text for word in ("rds", "azure sql", "cloud sql")),
        "storage": not local and any(word in text for word in ("s3", "blob storage", "object storage", "cloud storage bucket")),
    }
