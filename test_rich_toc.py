#!/usr/bin/env python
"""Test complete TOC generation with all curriculum data."""

import requests
import json
import time

BASE_URL = "http://localhost"

print("=" * 100)
print("TOC GENERATION - COMPLETE CURRICULUM TEST")
print("=" * 100)

# Generate TOC
print("\n📋 Generating 10-Day DevOps TOC with Full Curriculum...")
print("-" * 100)

toc_payload = {
    "domain": "DevOps",
    "duration_days": 10,
    "level": "intermediate",
    "mode": "Online",
    "notes": "Focus on Docker, Kubernetes, CI/CD, Linux"
}

response = requests.post(
    f"{BASE_URL}/api/v1/toc/generate",
    json=toc_payload,
    timeout=30
)

if response.status_code == 200:
    result = response.json()
    toc_data = result.get("toc_data", {})
    toc_id = result.get("toc_id")
    
    print(f"✓ TOC Generated: {toc_id}\n")
    
    # Program Overview
    print(f"📌 PROGRAM OVERVIEW:")
    print(f"  Title: {toc_data.get('title')}")
    print(f"  Subtitle: {toc_data.get('subtitle')}")
    print(f"  Mode: {toc_payload['mode']}")
    overview = toc_data.get('overview', '')
    if overview:
        print(f"  Description: {overview[:120]}...\n")
    
    # Learning Outcomes
    print(f"📚 LEARNING OUTCOMES:")
    outcomes = toc_data.get('learning_outcomes', [])
    for i, outcome in enumerate(outcomes, 1):
        print(f"  {i}. {outcome}")
    print()
    
    # Daily Roadmap
    print(f"📅 10-DAY DAILY ROADMAP:")
    print("-" * 100)
    days = toc_data.get('days', [])
    
    for day_data in days:
        day_num = day_data.get('day', '?')
        title = day_data.get('title', 'N/A')
        focus = day_data.get('focus_area', 'N/A')
        tools = day_data.get('tools', 'N/A')
        
        print(f"\n  Day {day_num}: {title}")
        print(f"    Focus: {focus}")
        print(f"    Tools: {tools}")
        
        # Morning session
        morning = day_data.get('morning_session', {})
        if morning:
            print(f"    Morning ({morning.get('time')}): {morning.get('title')}")
            topics = morning.get('topics', [])
            if topics:
                for topic in topics[:2]:
                    print(f"      • {topic}")
        
        # Afternoon session
        afternoon = day_data.get('afternoon_session', {})
        if afternoon:
            print(f"    Afternoon ({afternoon.get('time')}): {afternoon.get('title')}")
            topics = afternoon.get('topics', [])
            if topics:
                for topic in topics[:2]:
                    print(f"      • {topic}")
        
        # Learning objectives
        objectives = day_data.get('learning_objectives', [])
        if objectives:
            print(f"    Objectives: {objectives[0]}")
        
        # JIRA practice
        jira = day_data.get('jira_practice', [])
        if jira:
            print(f"    JIRA: {', '.join(jira[:2])}")
    
    print("\n" + "-" * 100)
    
    # Certifications
    print(f"\n🏆 CERTIFICATION ROADMAP:")
    certs = toc_data.get('certification_roadmap', [])
    for cert in certs:
        print(f"  • {cert}")
    print()
    
    # Tools & Software
    print(f"🛠️  TOOLS & SOFTWARE:")
    tools = toc_data.get('tools_software', [])
    for i, tool in enumerate(tools[:10], 1):
        print(f"  {i}. {tool}")
    print()
    
    # Hiring Preparation
    print(f"🎯 HIRING PREPARATION:")
    hiring = toc_data.get('hiring_preparation', [])
    for item in hiring[:3]:
        print(f"  • {item[:70]}...")
    print()
    
    # Assessment Plan
    print(f"✅ ASSESSMENT PLAN:")
    assessment = toc_data.get('assessment_plan', [])
    for item in assessment:
        print(f"  • {item}")
    
    print("\n" + "=" * 100)
    print(f"✓✓✓ COMPLETE TOC READY FOR PDF EXPORT: {toc_id} ✓✓✓")
    print("=" * 100)
    
    # Save for PDF generation
    with open("latest_toc_id.txt", "w") as f:
        f.write(toc_id)

else:
    print(f"✗ Error: {response.status_code}")
    print(f"  Response: {response.text}")
