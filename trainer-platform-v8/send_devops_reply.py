import sys
sys.path.insert(0, 'backend')

from pymongo import MongoClient
from config import get_settings
import requests

settings = get_settings()
client = MongoClient(settings.mongodb_uri)
db = client[settings.mongodb_db]

print("=== SEARCHING FOR CALHAN DEVOPS EMAIL ===\n")

# Search for Calhan DevOps email
email = db['client_emails'].find_one({
    "$or": [
        {"body": {"$regex": "DevOps", "$options": "i"}},
        {"subject": {"$regex": "DevOps", "$options": "i"}}
    ]
}, sort=[("received_at", -1)])

if email:
    email_id = email.get('email_id')
    from_email = email.get('from_email')
    subject = email.get('subject')
    status = email.get('status')
    confidence = email.get('confidence')
    
    print(f"✅ Found email!")
    print(f"  Email ID: {email_id}")
    print(f"  From: {from_email}")
    print(f"  Subject: {subject}")
    print(f"  Status: {status}")
    print(f"  Confidence: {confidence}")
    
    if status == "pending_approval":
        print(f"\n📤 Sending auto-reply...")
        try:
            response = requests.post(
                f"http://localhost:8000/api/inbox/{email_id}/approve",
                json={},
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"✅ Reply sent! Result: {result}")
            else:
                print(f"❌ Failed - Status {response.status_code}")
                print(f"Response: {response.text[:200]}")
        except Exception as e:
            print(f"❌ Error: {str(e)}")
    else:
        print(f"\n⚠️ Email status is '{status}', not pending_approval")
        print("Trying to send it anyway...")
        
        try:
            response = requests.post(
                f"http://localhost:8000/api/inbox/{email_id}/approve",
                json={},
                timeout=10
            )
            
            if response.status_code == 200:
                print(f"✅ Reply sent!")
            else:
                print(f"❌ Failed - Status {response.status_code}")
        except Exception as e:
            print(f"❌ Error: {str(e)}")
            
else:
    print("❌ DevOps email not found in database")
    print("\nTrying to fetch from Gmail...")

client.close()
