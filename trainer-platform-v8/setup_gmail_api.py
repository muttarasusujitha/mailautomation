import pymongo

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['trainer_platform']

# Configure to use Gmail API for inbox polling
result = db['admin_settings'].update_one(
    {'_id': 'default'},
    {'$set': {
        'inboxProvider': 'gmail_api',  # Use Gmail API instead of IMAP
        'autoSendEnabled': True,
        'autoSendThreshold': 50,
        'clientDomainsWhitelist': 'clahan.com,gmail.com,outlook.com',
    }},
    upsert=True
)

print('✅ System configured for Gmail API inbox polling')
print('✅ Auto-send is ENABLED')
print('✅ Ready to receive and reply to client emails')
print('\nTo start receiving emails:')
print('1. Click Admin Dashboard → Tools → "Sync Recent Inbox"')
print('2. Or emails will be processed automatically when they arrive')
