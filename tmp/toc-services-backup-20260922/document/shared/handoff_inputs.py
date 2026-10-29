"""Stable requirement version for resuming blocked handoff preparation."""
import hashlib
import json


def handoff_input_version(requirement):
    inputs = {key: value for key, value in requirement.items()
              if key not in {"_id", "updated_at", "created_at", "pipeline_summary"}}
    return hashlib.sha256(json.dumps(inputs, sort_keys=True, default=str).encode()).hexdigest()
