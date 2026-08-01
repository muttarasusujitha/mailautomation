import pymongo

client = pymongo.MongoClient('mongodb://127.0.0.1:27017/')
db = client['trainer_platform']

# Search for DevOps email
devops_emails = list(db['client_emails'].find({'subject': {'$regex': 'DevOps', '$options': 'i'}}).limit(5))

if devops_emails:
    print(f'✓ Found {len(devops_emails)} DevOps-related email(s):')
    for email in devops_emails:
        print(f'\n  From: {email.get("from_email")}')
        print(f'  Subject: {email.get("subject")}')
        print(f'  Status: {email.get("status")}')
        print(f'  Confidence: {email.get("confidence", "N/A")}')
else:
    print('✗ No DevOps emails found in database')
    
# Check all email statuses
print('\n=== ALL EMAIL STATUSES ===')
all_emails = db['client_emails'].find()
statuses = {}
for email in all_emails:
    status = email.get('status', 'unknown')
    statuses[status] = statuses.get(status, 0) + 1

for status, count in sorted(statuses.items()):
    print(f'{status}: {count}')
