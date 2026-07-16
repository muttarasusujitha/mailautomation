#!/usr/bin/env python
"""Test rich PDF generation and email with updated TOC routes."""

import requests
import json

BASE_URL = "http://localhost"
RECIPIENT = "sujithamuttarasu@gmail.com"

print("=" * 100)
print("🎨 TESTING RICH PDF GENERATION & EMAIL")
print("=" * 100)

# Generate a DevOps TOC
print("\n1️⃣ Generating 10-day DevOps TOC...")
toc_response = requests.post(
    f"{BASE_URL}/api/v1/toc/generate",
    json={
        "domain": "DevOps",
        "duration_days": 10,
        "level": "intermediate",
        "mode": "Online",
        "notes": "Testing rich PDF generation"
    },
    timeout=60
)

if toc_response.status_code != 200:
    print(f"✗ Failed: {toc_response.status_code}")
    print(toc_response.text)
    exit(1)

toc_data = toc_response.json()
toc_id = toc_data.get("toc_id")
print(f"✓ Generated: {toc_id}")

# Send email with rich PDF
print(f"\n2️⃣ Sending rich PDF to {RECIPIENT}...")
email_response = requests.post(
    f"{BASE_URL}/api/v1/toc/send-email",
    json={
        "toc_id": toc_id,
        "to_email": RECIPIENT,
        "trainer_name": "DevOps Trainer",
        "subject": "🚀 DevOps 10-Day Training Curriculum (Rich PDF)",
    },
    timeout=120
)

if email_response.status_code == 200:
    print(f"✓ Email sent successfully!")
    result = email_response.json()
    print(f"  TOC ID: {result.get('toc_id')}")
    print(f"  Recipient: {result.get('to_email')}")
    print("\n✓✓✓ Rich PDF should now contain:")
    print("  ✓ Company header (Clahan Technologies | TrainerSync)")
    print("  ✓ Full program overview")
    print("  ✓ Complete program roadmap table")
    print("  ✓ Prerequisites & Learning Outcomes")
    print("  ✓ Detailed daily breakdowns (all 10 days)")
    print("  ✓  Morning & afternoon sessions with time slots")
    print("  ✓ Learning objectives per day")
    print("  ✓ Jira practice items")
    print("  ✓ Tools & software list")
    print("  ✓ Assessment plan")
    print("  ✓ Hiring & test preparation")
    print("  ✓ Certification roadmap")
    print("  ✓ Professional styling & formatting")
else:
    print(f"✗ Failed: {email_response.status_code}")
    print(email_response.text[:500])

print("\n" + "=" * 100)
print("📧 Check inbox: " + RECIPIENT)
print("=" * 100)
