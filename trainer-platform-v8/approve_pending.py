import sys
import requests
import json
sys.path.insert(0, 'backend')

from pymongo import MongoClient
from config import get_settings

settings = get_settings()
client = MongoClient(settings.mongodb_uri)
db = client[settings.mongodb_db]

BASE_URL = "http://localhost:8000"

print("=== APPROVING PENDING EMAILS ===\n")

# Get all pending emails with confidence >= 0.50
pending_emails = db['client_emails'].find(
    {
        "status": "pending_approval",
        "confidence": {"$gte": 0.50},
        "generated_reply.body": {"$exists": True, "$ne": ""}
    },
    {"_id": 1, "email_id": 1, "from_email": 1}
)

emails_to_approve = list(pending_emails)
print(f"Found {len(emails_to_approve)} emails to approve\n")

approved_count = 0
failed_count = 0

for email in emails_to_approve[:10]:  # Approve first 10
    email_id = email.get('email_id')
    from_email = email.get('from_email', '')
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/inbox/{email_id}/approve",
            json={},
            timeout=10
        )
        
        if response.status_code == 200:
            print(f"✅ Approved {from_email[:40]}")
            approved_count += 1
        else:
            print(f"❌ Failed {from_email[:40]} - Status {response.status_code}")
            print(f"   Response: {response.text[:100]}")
            failed_count += 1
    except Exception as e:
        print(f"❌ Error approving {from_email[:40]}: {str(e)[:50]}")
        failed_count += 1

print(f"\n📊 Results:")
print(f"  ✅ Approved: {approved_count}")
print(f"  ❌ Failed: {failed_count}")
print(f"  ⏳ Total pending: {len(emails_to_approve)}")

client.close()
