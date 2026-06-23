import pymongo
import asyncio
from datetime import datetime

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['trainer_platform']

# Check inbox settings
inbox_settings = db['admin_settings'].find_one({'_id': 'default'})
print('=== CURRENT INBOX SETTINGS ===')
print(f'inboxProvider: {inbox_settings.get("inboxProvider", "not set")}')
print(f'gmailUser: {inbox_settings.get("gmailUser", "not set")}')
print(f'imapUser: {inbox_settings.get("imapUser", "not set")}')
print(f'imapHost: {inbox_settings.get("imapHost", "not set")}')
print(f'imapPort: {inbox_settings.get("imapPort", "not set")}')

# Check if IMAP credentials are configured
imap_user = inbox_settings.get('imapUser', '').strip()
imap_pass = inbox_settings.get('imapPass', '').strip()

print(f'\nIMAP configured: {bool(imap_user and imap_pass)}')

if not imap_user or not imap_pass:
    print('\n⚠️  IMAP credentials are NOT configured!')
    print('Need to set imapUser and imapPass in admin_settings')
