import sys
sys.path.insert(0, 'backend')

from pymongo import MongoClient
from config import get_settings

settings = get_settings()
client = MongoClient(settings.mongodb_uri)
db = client[settings.mongodb_db]

print("=== ALL EMAILS IN DATABASE ===\n")

emails = list(db['client_emails'].find().limit(100))

if not emails:
    print("No emails found")
else:
    print(f"Total emails: {len(emails)}\n")
    
    # Group by status
    by_status = {}
    for email in emails:
        status = email.get('status', 'unknown')
        if status not in by_status:
            by_status[status] = []
        by_status[status].append(email)
    
    for status, email_list in sorted(by_status.items()):
        print(f"\n📧 {status.upper()}: {len(email_list)} emails")
        for email in email_list[:2]:  # Show first 2
            print(f"  From: {email.get('from_email')[:50]}")
            print(f"  Subject: {email.get('subject', '')[:60]}")
            if email.get('auto_send_error'):
                print(f"  ❌ Error: {email.get('auto_send_error')[:80]}")
            print()

client.close()
