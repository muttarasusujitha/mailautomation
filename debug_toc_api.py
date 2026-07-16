#!/usr/bin/env python
"""Debug TOC API response structure."""

import requests
import json

BASE_URL = "http://localhost"

# Generate TOC
print("Generating TOC...")
toc_payload = {
    "domain": "DevOps",
    "duration_days": 10,
    "level": "intermediate",
    "mode": "Online",
    "notes": "Focus on Kubernetes"
}

response = requests.post(
    f"{BASE_URL}/api/v1/toc/generate",
    json=toc_payload,
    timeout=30
)

print(f"Status: {response.status_code}")
print(f"\nFull Response:")
print(json.dumps(response.json(), indent=2)[:2000])

# Get TOC ID if available
if response.status_code == 200:
    data = response.json()
    toc_id = data.get("toc_id")
    print(f"\n✓ TOC ID: {toc_id}")
    
    # Try to retrieve the TOC
    if toc_id:
        print(f"\nRetrieving TOC {toc_id}...")
        get_response = requests.get(
            f"{BASE_URL}/api/v1/toc/{toc_id}",
            timeout=30
        )
        print(f"Retrieve Status: {get_response.status_code}")
        if get_response.status_code == 200:
            print(json.dumps(get_response.json(), indent=2)[:2000])
