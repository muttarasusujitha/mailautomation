#!/usr/bin/env python
"""Check if domain dataset is accessible from microservice."""

import sys
sys.path.insert(0, r"c:\Users\sujit\Desktop\mail\mailautomation\trainer-platform-v8\microservices\services\trainer-service")

from app.toc_domain_dataset import get_domain, DOMAINS

print("Available domains:")
for domain_name in list(DOMAINS.keys())[:5]:
    print(f'  - {domain_name}')
print(f'Total domains: {len(DOMAINS)}')

print("\nTesting DevOps domain:")
devops = get_domain('DevOps')
if devops:
    print(f'✓ Found: {devops.get("name")}')
    print(f'  Icon: {devops.get("icon")}')
    print(f'  Has level_map: {bool(devops.get("level_map"))}')
    if devops.get("level_map"):
        levels = list(devops["level_map"].keys())
        print(f'  Levels: {levels}')
        if "foundation" in devops["level_map"]:
            foundation = devops["level_map"]["foundation"]
            print(f'  Foundation topics: {len(foundation)}')
            for topic in foundation[:2]:
                print(f'    - {topic.get("topic")}')
else:
    print('✗ DevOps domain not found!')

print("\nTesting generation function:")
from app.toc_generation_agent import generate_toc_from_dataset

try:
    toc = generate_toc_from_dataset(
        domain_name="DevOps",
        duration_days=10,
        level="intermediate",
        mode="Online",
        notes="Test"
    )
    print(f'✓ TOC Generated')
    print(f'  Title: {toc.get("title")}')
    print(f'  Days: {len(toc.get("days", []))}')
    if toc.get("days"):
        day1 = toc["days"][0]
        print(f'  Day 1: {day1.get("title")}')
        print(f'    Focus: {day1.get("focus_area")}')
        if day1.get("sessions"):
            print(f'    Sessions: {len(day1["sessions"])}')
except Exception as e:
    print(f'✗ Error generating TOC: {e}')
    import traceback
    traceback.print_exc()
