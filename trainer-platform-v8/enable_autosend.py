import pymongo

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['trainer_platform']

# Create admin settings with auto-send enabled
result = db['admin_settings'].update_one(
    {'_id': 'default'},
    {'$set': {
        'autoSendEnabled': True,
        'autoSendThreshold': 50,  # Lower threshold to catch more emails
        'clientDomainsWhitelist': 'clahan.com,gmail.com,outlook.com',
        'gmailUser': 'trainermatching@gmail.com',
        'replySignature': 'TrainerSync Team'
    }},
    upsert=True
)

print('✓ Auto-send settings created')
print('✓ autoSendEnabled: True')
print('✓ autoSendThreshold: 50%')
print('✓ Whitelisted domains: clahan.com, gmail.com, outlook.com')

# Check for pending emails
pending = db['client_emails'].count_documents({'status': 'pending_approval'})
print(f'\n✓ Pending emails waiting to auto-send: {pending}')

# Show samples
if pending > 0:
    print('\nPending emails:')
    for email in db['client_emails'].find({'status': 'pending_approval'}).limit(3):
        print(f'  - {email.get("from_email")}: {email.get("subject", "")[0:60]}')
