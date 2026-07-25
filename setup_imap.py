import pymongo

client = pymongo.MongoClient('mongodb://127.0.0.1:27017/')
db = client['trainer_platform']

# Configure IMAP for email polling
db['admin_settings'].update_one(
    {'_id': 'default'},
    {'$set': {
        'inboxProvider': 'imap',  # Enable IMAP polling
        'imapHost': 'imap.gmail.com',
        'imapPort': 993,
        'imapUser': 'trainermatching@gmail.com',  # Gmail account
        'imapPass': 'app_password_here',  # Will prompt user
    }},
    upsert=True
)

print('✓ IMAP provider configured')
print('✓ Next: Set imapPass in admin settings (use Gmail App Password)')
print('\nTo get Gmail App Password:')
print('1. Go to Google Account Security: https://myaccount.google.com/security')
print('2. Enable 2-Step Verification (if not already)')
print('3. Create App Password for "Mail" and "Windows Computer"')
print('4. Copy the 16-character password to admin settings')
