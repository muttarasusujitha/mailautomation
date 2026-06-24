import pymongo
import asyncio
from datetime import datetime

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['trainer_platform']

# Check for received emails
emails = list(db['client_emails'].find().sort('received_at', -1).limit(10))

print('=== RECEIVED EMAILS ===')
if emails:
    for email in emails:
        print(f"\nEmail ID: {email.get('email_id')}")
        print(f"From: {email.get('from_email')}")
        print(f"Subject: {email.get('subject')}")
        print(f"Status: {email.get('status')}")
        print(f"Auto-send eligible: {email.get('auto_send_eligible')}")
        print(f"Received: {email.get('received_at')}")
else:
    print("No emails in database yet")

# Check settings
settings = db['admin_settings'].find_one({'_id': 'default'})
print(f'\n=== SYSTEM SETTINGS ===')
print(f'Auto-send Enabled: {settings.get("autoSendEnabled")}')
print(f'Inbox Provider: {settings.get("inboxProvider")}')
