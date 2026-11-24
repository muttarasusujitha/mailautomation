#!/usr/bin/env python
"""Generate custom TOC PDFs for any domain, duration, and recipient."""

import requests
import sys

BASE_URL = "http://localhost"

def generate_and_email_toc(domain, duration_days, recipient_email, trainer_name="Trainer"):
    """Generate TOC and send rich PDF to recipient."""
    
    print(f"\n{'='*80}")
    print(f"📧 CUSTOM TOC GENERATION")
    print(f"{'='*80}")
    print(f"Domain: {domain}")
    print(f"Duration: {duration_days} days")
    print(f"Recipient: {recipient_email}")
    
    # Generate TOC
    print(f"\n1️⃣ Generating {duration_days}-day {domain} TOC...", end=" ")
    toc_response = requests.post(
        f"{BASE_URL}/api/v1/toc/generate",
        json={
            "domain": domain,
            "duration_days": duration_days,
            "level": "intermediate",
            "mode": "Online",
            "notes": f"Custom {duration_days}-day program"
        },
        timeout=60
    )
    
    if toc_response.status_code != 200:
        print(f"✗ Failed")
        print(toc_response.text)
        return False
    
    toc_data = toc_response.json()
    toc_id = toc_data.get("toc_id")
    toc_obj = toc_data.get("toc_data", {})
    
    print(f"✓ {toc_id}")
    print(f"   Title: {toc_obj.get('title')}")
    print(f"   Days: {len(toc_obj.get('days', []))}")
    
    # Send email
    print(f"2️⃣ Sending rich PDF to {recipient_email}...", end=" ")
    email_response = requests.post(
        f"{BASE_URL}/api/v1/toc/send-email",
        json={
            "toc_id": toc_id,
            "to_email": recipient_email,
            "trainer_name": trainer_name,
            "subject": f"{domain} - {duration_days}-Day Training Curriculum",
        },
        timeout=120
    )
    
    if email_response.status_code == 200:
        print(f"✓ Sent")
        return True
    else:
        print(f"✗ Failed: {email_response.status_code}")
        return False


if __name__ == "__main__":
    # CUSTOMIZE THESE VALUES:
    DOMAIN = "Python"  # Change to any domain
    DURATION = 10      # 5, 10, 20, 30, 50, or 100
    RECIPIENT = "sujithamuttarasu@gmail.com"
    TRAINER = "Python Trainer"
    
    print(f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    CUSTOM TOC PDF GENERATOR                                  ║
╚══════════════════════════════════════════════════════════════════════════════╝

Available Domains:
  • DevOps, Python, React, Full Stack, Data Engineering, Machine Learning
  • Testing & QA, Cybersecurity, Power BI, Salesforce, Java
  • Project Management, Agentic AI, Azure AI Datasets, AWS AI Datasets
  • Prompt Engineering

Available Durations: 5, 10, 20, 30, 50, 100 days

CUSTOMIZE IN THIS FILE:
  Line 44: DOMAIN = "Python"          → Change to any domain above
  Line 45: DURATION = 10               → Change to 5, 10, 20, 30, 50, or 100
  Line 46: RECIPIENT = "email@..."    → Change to recipient email
  Line 47: TRAINER = "..."            → Change trainer name
""")
    
    success = generate_and_email_toc(DOMAIN, DURATION, RECIPIENT, TRAINER)
    
    if success:
        print(f"\n{'='*80}")
        print(f"✅ SUCCESS! Rich PDF sent to {RECIPIENT}")
        print(f"{'='*80}\n")
    else:
        print(f"\n❌ FAILED\n")
        sys.exit(1)
