#!/usr/bin/env python
"""Send a single rich TOC PDF for verification."""

import requests

BASE_URL = "http://localhost"
RECIPIENT = "sujithamuttarasu@gmail.com"

print("=" * 100)
print("📧 SENDING 1 DOMAIN FOR VERIFICATION")
print("=" * 100)

# Generate Full Stack TOC
print("\n1️⃣ Generating 10-day Full Stack TOC...")
toc_response = requests.post(
    f"{BASE_URL}/api/v1/toc/generate",
    json={
        "domain": "Full Stack",
        "duration_days": 10,
        "level": "intermediate",
        "mode": "Online",
        "notes": "Single domain verification test"
    },
    timeout=60
)

if toc_response.status_code != 200:
    print(f"✗ Failed: {toc_response.status_code}")
    print(toc_response.text)
    exit(1)

toc_data = toc_response.json()
toc_id = toc_data.get("toc_id")
toc_obj = toc_data.get("toc_data", {})

print(f"✓ TOC Generated: {toc_id}")
print(f"  Title: {toc_obj.get('title')}")
print(f"  Days: {len(toc_obj.get('days', []))}")
print(f"  Tools: {len(toc_obj.get('tools_software', []))}")
print(f"  Certifications: {len(toc_obj.get('certification_roadmap', []))}")

# Send email with rich PDF
print(f"\n2️⃣ Sending Rich PDF to {RECIPIENT}...")
email_response = requests.post(
    f"{BASE_URL}/api/v1/toc/send-email",
    json={
        "toc_id": toc_id,
        "to_email": RECIPIENT,
        "trainer_name": "Full Stack Trainer",
        "subject": "✅ VERIFICATION: Full Stack 10-Day Training (Rich PDF Test)",
    },
    timeout=120
)

if email_response.status_code == 200:
    print(f"✓✓✓ Email Sent Successfully!")
    result = email_response.json()
    print(f"\n📊 Details:")
    print(f"   TOC ID: {result.get('toc_id')}")
    print(f"   Recipient: {result.get('to_email')}")
    print(f"\n📋 PDF Should Contain:")
    print(f"   ✅ Company Header: Clahan Technologies | TrainerSync")
    print(f"   ✅ Title: Full Stack Mastery")
    print(f"   ✅ Subtitle: 10-Day Intensive Training Program")
    print(f"   ✅ Full Program Overview")
    print(f"   ✅ Complete Program Roadmap Table (10 days)")
    print(f"   ✅ Prerequisites")
    print(f"   ✅ Learning Outcomes (5 items)")
    print(f"   ✅ Detailed Daily Breakdown:")
    print(f"      - Day 1: Linux Basics")
    print(f"      - Day 2: React Fundamentals")
    print(f"      - Day 3: Backend API Development")
    print(f"      - Day 4: Database Design")
    print(f"      - Day 5: DevOps and CI/CD")
    print(f"      - Day 6: Cloud Deployment")
    print(f"      - Day 7: State Management")
    print(f"      - Day 8: Full Stack Integration")
    print(f"      - Day 9: Performance and Security")
    print(f"      - Day 10: Capstone Project")
    print(f"   ✅ Morning & Afternoon Sessions (all with time slots)")
    print(f"   ✅ Learning Objectives per day")
    print(f"   ✅ Jira Practice items per day")
    print(f"   ✅ Tools & Software List ({len(toc_obj.get('tools_software', []))} tools)")
    print(f"   ✅ Assessment Plan")
    print(f"   ✅ Hiring & Test Preparation")
    print(f"   ✅ Certification Roadmap ({len(toc_obj.get('certification_roadmap', []))} certifications)")
    print(f"\n✅ Check your email: {RECIPIENT}")
    print(f"✅ Look for subject: ✅ VERIFICATION: Full Stack 10-Day Training (Rich PDF Test)")
    print(f"✅ The PDF should be attached and professionally formatted")
else:
    print(f"✗ Failed: {email_response.status_code}")
    print(email_response.text)

print("\n" + "=" * 100)
