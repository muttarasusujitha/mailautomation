import sys
sys.path.insert(0, 'backend')

from pymongo import MongoClient
from config import get_settings
import json

settings = get_settings()
client = MongoClient(settings.mongodb_uri)
db = client[settings.mongodb_db]

print("=== PENDING APPROVAL EMAIL - DETAILS ===\n")

email = db['client_emails'].find_one({"status": "pending_approval"})

if email:
    print(f"From: {email.get('from_email')}")
    print(f"Subject: {email.get('subject')}")
    print(f"Status: {email.get('status')}")
    print(f"Auto-send confidence: {email.get('auto_send_confidence', 'N/A')}")
    print(f"Generated reply: {bool(email.get('generated_reply'))}")
    
    if email.get('generated_reply'):
        reply = email.get('generated_reply')
        print(f"\n📧 GENERATED REPLY:")
        print(f"  Subject: {reply.get('subject', '')[:80]}")
        print(f"  Body preview: {reply.get('body', '')[:200]}")
    
    print(f"\n📋 Why not auto-sent?")
    if email.get('auto_send_confidence', 0) < 50:
        print(f"  ❌ Confidence {email.get('auto_send_confidence', 0)}% < 50% threshold")
    if not email.get('generated_reply'):
        print(f"  ❌ No reply generated yet")
    if email.get('auto_send_error'):
        print(f"  ❌ Error: {email.get('auto_send_error')}")
        
else:
    print("No pending_approval emails found")

client.close()
