#!/usr/bin/env python
"""
Generate 10-day TOC for ALL 16 domains and email to sujithamuttarasu@gmail.com
Testing end-to-end: Generate → Store → Email
"""

import requests
import json
import time
from datetime import datetime

BASE_URL = "http://localhost"
RECIPIENT = "sujithamuttarasu@gmail.com"

# All 16 domains
DOMAINS = [
    "DevOps",
    "Python",
    "React",
    "Full Stack",
    "Data Engineering",
    "Machine Learning",
    "Testing & QA",
    "Cybersecurity",
    "Power BI",
    "Salesforce",
    "Java",
    "Project Management",
    "Agentic AI",
    "Azure AI Datasets",
    "AWS AI Datasets",
    "Prompt Engineering",
]

results = {
    "total": len(DOMAINS),
    "generated": 0,
    "emailed": 0,
    "failed": [],
    "generated_tocs": []
}

print("=" * 100)
print("🚀 COMPREHENSIVE TOC GENERATION & EMAIL TEST")
print("=" * 100)
print(f"\n📧 Target Email: {RECIPIENT}")
print(f"📊 Domains to Test: {len(DOMAINS)}")
print(f"⏱️  Duration per domain: 10 days")
print(f"🎯 Mode: Online, Level: Intermediate")
print("\n" + "-" * 100)

for i, domain in enumerate(DOMAINS, 1):
    print(f"\n[{i:2d}/{len(DOMAINS)}] Processing: {domain}")
    print("-" * 100)
    
    # Step 1: Generate TOC
    print(f"  ① Generating 10-day TOC...", end=" ")
    
    try:
        toc_response = requests.post(
            f"{BASE_URL}/api/v1/toc/generate",
            json={
                "domain": domain,
                "duration_days": 10,
                "level": "intermediate",
                "mode": "Online",
                "notes": f"Auto-generated test for {domain} training program"
            },
            timeout=60
        )
        
        if toc_response.status_code != 200:
            print(f"✗ Failed ({toc_response.status_code})")
            results["failed"].append(f"{domain}: TOC generation failed ({toc_response.status_code})")
            continue
        
        toc_data = toc_response.json()
        toc_id = toc_data.get("toc_id")
        toc_obj = toc_data.get("toc_data", {})
        
        print(f"✓ {toc_id}")
        results["generated"] += 1
        results["generated_tocs"].append({
            "domain": domain,
            "toc_id": toc_id,
            "title": toc_obj.get("title"),
            "days": len(toc_obj.get("days", []))
        })
        
        # Step 2: Send Email with TOC
        print(f"  ② Sending email to {RECIPIENT}...", end=" ")
        
        email_response = requests.post(
            f"{BASE_URL}/api/v1/toc/send-email",
            json={
                "toc_id": toc_id,
                "to_email": RECIPIENT,
                "trainer_name": f"{domain} Trainer",
                "subject": f"[TEST {i:02d}/{len(DOMAINS)}] {domain} - 10-Day Training Curriculum",
                "body": f"""Dear Training Team,

This is an automated test of the TOC generation system.

Domain: {domain}
Program: 10-Day Intensive Training
Level: Intermediate
Mode: Online
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Please find the Table of Contents attached.

Test ID: {toc_id}

Best regards,
TOC Automation System"""
            },
            timeout=30
        )
        
        if email_response.status_code == 200:
            print(f"✓ Sent")
            results["emailed"] += 1
        else:
            print(f"✗ Failed ({email_response.status_code})")
            results["failed"].append(f"{domain}: Email send failed ({email_response.status_code})")
        
        # Show summary
        if toc_obj:
            outcomes = toc_obj.get("learning_outcomes", [])
            tools = toc_obj.get("tools_software", [])
            certs = toc_obj.get("certification_roadmap", [])
            
            print(f"     📌 Title: {toc_obj.get('title')}")
            print(f"     📅 Days: {len(toc_obj.get('days', []))}")
            print(f"     📚 Learning Outcomes: {len(outcomes)}")
            print(f"     🛠️  Tools: {len(tools)}")
            print(f"     🏆 Certifications: {len(certs)}")
        
        time.sleep(0.5)  # Rate limiting
        
    except Exception as e:
        print(f"✗ Error: {str(e)[:50]}")
        results["failed"].append(f"{domain}: {str(e)[:100]}")

print("\n" + "=" * 100)
print("📊 TEST RESULTS SUMMARY")
print("=" * 100)

print(f"\n✓ TOCs Generated: {results['generated']}/{results['total']}")
print(f"✓ Emails Sent:    {results['emailed']}/{results['total']}")

if results["failed"]:
    print(f"\n⚠️  Failed Items ({len(results['failed'])}):")
    for item in results["failed"]:
        print(f"   • {item}")
else:
    print(f"\n✓✓✓ ALL TESTS PASSED - NO FAILURES ✓✓✓")

print(f"\n📧 Check email inbox at: {RECIPIENT}")
print(f"📧 You should receive {results['emailed']} emails")

print("\n" + "-" * 100)
print("Generated TOCs:")
print("-" * 100)

for toc in results["generated_tocs"]:
    print(f"  {toc['domain']:20} | {toc['toc_id']:20} | {toc['title']:30} | {toc['days']} days")

print("\n" + "=" * 100)
print("✓ TEST COMPLETE")
print("=" * 100)

# Save results to file
with open("toc_test_results.json", "w") as f:
    json.dump(results, f, indent=2)
print(f"\n💾 Results saved to: toc_test_results.json")
