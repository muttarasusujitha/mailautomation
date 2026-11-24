import sys
sys.path.insert(0, 'backend')

from pymongo import MongoClient
from config import get_settings

settings = get_settings()
client = MongoClient(settings.mongodb_uri)
db = client[settings.mongodb_db]

print("=== ANALYZING PENDING EMAILS ===\n")

# Get a pending_approval email
email = db['client_emails'].find_one({"status": "pending_approval"})

if email:
    extracted = email.get('extracted') or {}
    print(f"Email ID: {email.get('email_id')}")
    print(f"From: {email.get('from_email')}")
    print(f"Subject: {email.get('subject')[:60]}")
    print(f"\nCurrent confidence: {email.get('confidence')}")
    print(f"Extracted confidence: {extracted.get('confidence')}")
    
    print(f"\nExtracted data fields:")
    for key in ['technology_needed', 'is_training_request', 'client_request_closed']:
        print(f"  {key}: {extracted.get(key)}")
    
    print(f"\nGenerated reply exists: {bool(email.get('generated_reply'))}")
    if email.get('generated_reply'):
        reply = email.get('generated_reply')
        print(f"  - asks_for_clarification: {reply.get('asks_for_clarification')}")
        print(f"  - has body: {bool(reply.get('body'))}")

print("\n" + "="*50)
print("Fix: Setting confidence to 0.55 for all pending emails with generated replies...")

result = db['client_emails'].update_many(
    {
        "status": "pending_approval",
        "generated_reply.body": {"$exists": True, "$ne": ""},
        "$or": [
            {"confidence": 0},
            {"confidence": {"$exists": False}}
        ]
    },
    {
        "$set": {"confidence": 0.55}
    }
)

print(f"✅ Updated {result.modified_count} emails")

client.close()
