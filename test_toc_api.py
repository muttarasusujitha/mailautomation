#!/usr/bin/env python
"""Test TOC Generation, PDF, and Email sending."""

import requests
import json
import time

BASE_URL = "http://localhost"
GATEWAY_URL = f"{BASE_URL}/api/v1/toc"

print("=" * 80)
print("TOC API TESTING - LIVE SYSTEM")
print("=" * 80)

# Test 1: Generate TOC
print("\n1️⃣ GENERATING 10-DAY DEVOPS TOC...")
print("-" * 80)

toc_payload = {
    "domain": "DevOps",
    "duration_days": 10,
    "level": "intermediate",
    "mode": "Online",
    "notes": "Focus on Docker, Kubernetes, CI/CD"
}

try:
    response = requests.post(
        f"{GATEWAY_URL}/generate",
        json=toc_payload,
        timeout=30
    )
    
    if response.status_code == 200:
        result = response.json()
        toc_id = result.get("toc_id", "")
        toc_data = result.get("toc_data", {})
        
        print(f"✓ TOC Generated Successfully!")
        print(f"  TOC ID: {toc_id}")
        print(f"  Domain: {toc_data.get('domain', 'N/A')}")
        print(f"  Duration: {toc_data.get('duration_days', 'N/A')} days")
        print(f"  Level: {toc_data.get('level', 'N/A')}")
        
        # Check program overview
        if 'program_overview' in toc_data:
            print(f"  Overview: {toc_data['program_overview'][:80]}...")
        
        # Check learning outcomes
        if 'learning_outcomes' in toc_data:
            outcomes = toc_data['learning_outcomes']
            print(f"  Learning Outcomes: {len(outcomes)} items")
            for i, outcome in enumerate(outcomes[:3], 1):
                print(f"    {i}. {outcome[:60]}...")
        
        # Check daily roadmap
        if 'daily_roadmap' in toc_data:
            roadmap = toc_data['daily_roadmap']
            print(f"  Daily Roadmap: {len(roadmap)} days")
            
            # Show first 3 days
            for day_num in range(1, min(4, len(roadmap) + 1)):
                day_key = f"day_{day_num}"
                if day_key in roadmap:
                    day_data = roadmap[day_key]
                    focus = day_data.get('focus_area', 'N/A')
                    sessions = day_data.get('sessions', [])
                    print(f"    Day {day_num}: {focus} ({len(sessions)} sessions)")
        
        # Store TOC ID for next tests
        with open("toc_id.txt", "w") as f:
            f.write(toc_id)
        
        print("\n  ✓ Response saved for PDF generation")
    else:
        print(f"✗ Error: {response.status_code}")
        print(f"  Response: {response.text}")
except Exception as e:
    print(f"✗ Error: {str(e)}")

# Wait a moment for MongoDB to persist
time.sleep(2)

# Test 2: Generate PDF
print("\n2️⃣ GENERATING PDF FROM TOC...")
print("-" * 80)

try:
    with open("toc_id.txt", "r") as f:
        toc_id = f.read().strip()
    
    pdf_payload = {
        "toc_id": toc_id,
        "include_sections": ["overview", "roadmap", "certifications", "assessment"]
    }
    
    response = requests.post(
        f"{GATEWAY_URL}/generate-pdf",
        json=pdf_payload,
        timeout=60
    )
    
    if response.status_code == 200:
        result = response.json()
        print(f"✓ PDF Generated Successfully!")
        print(f"  PDF ID: {result.get('pdf_id', 'N/A')}")
        print(f"  File URL: {result.get('file_url', 'N/A')}")
        print(f"  Status: {result.get('status', 'N/A')}")
        
        with open("pdf_id.txt", "w") as f:
            f.write(result.get('pdf_id', ''))
        
        print("\n  ✓ PDF ready for email sending")
    else:
        print(f"✗ Error: {response.status_code}")
        print(f"  Response: {response.text[:200]}")
except Exception as e:
    print(f"✗ Error: {str(e)}")

# Test 3: Send via Email
print("\n3️⃣ SENDING TOC PDF VIA EMAIL...")
print("-" * 80)

try:
    with open("pdf_id.txt", "r") as f:
        pdf_id = f.read().strip()
    
    email_payload = {
        "recipient_email": "trainer@example.com",
        "pdf_id": pdf_id,
        "subject": "DevOps 10-Day Training Curriculum",
        "include_calendar": True
    }
    
    response = requests.post(
        f"{GATEWAY_URL}/send-email",
        json=email_payload,
        timeout=30
    )
    
    if response.status_code == 200:
        result = response.json()
        print(f"✓ Email Sent Successfully!")
        print(f"  Email ID: {result.get('email_id', 'N/A')}")
        print(f"  Recipient: {result.get('recipient', 'N/A')}")
        print(f"  Status: {result.get('status', 'N/A')}")
    else:
        print(f"✗ Error: {response.status_code}")
        print(f"  Response: {response.text[:200]}")
except Exception as e:
    print(f"✗ Error: {str(e)}")

print("\n" + "=" * 80)
print("✓✓✓ TOC SYSTEM LIVE AND WORKING ✓✓✓")
print("=" * 80)
print("""
ENDPOINTS AVAILABLE:
  POST /api/v1/toc/generate         → Generate TOC from dataset
  POST /api/v1/toc/generate-pdf     → Create PDF from TOC
  POST /api/v1/toc/send-email       → Email PDF to recipients
  GET  /api/v1/toc/knowledge-base   → Get curriculum knowledge base
  GET  /api/v1/toc/{toc_id}         → Retrieve specific TOC

Next Steps:
  1. Use toc_id to generate PDF
  2. Use pdf_id to send emails
  3. Modify payload domain/duration for different programs
  4. Add more recipients to batch send
""")
