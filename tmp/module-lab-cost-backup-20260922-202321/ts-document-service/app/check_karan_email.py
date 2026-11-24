import asyncio
from database import connect_db, get_db

async def check_karan_email():
    await connect_db()
    db = get_db()
    
    # Search for emails from Karan Verma
    email = await db['inbox'].find_one({
        '$or': [
            {'from': {'$regex': 'Karan', '$options': 'i'}},
            {'from': {'$regex': 'karan', '$options': 'i'}},
            {'subject': {'$regex': 'DevOps', '$options': 'i'}}
        ]
    })
    
    if email:
        print('=== FOUND EMAIL ===\n')
        print(f'From: {email.get("from")}')
        print(f'Subject: {email.get("subject")}')
        print(f'Status: {email.get("status")}')
        print(f'Confidence Score: {email.get("confidence_score")}')
        print(f'Generated Reply: {email.get("generated_reply", "(none)")}')
        print(f'\nBody: {email.get("body", "")[:200]}...')
    else:
        # Check all recent emails
        all_emails = await db['inbox'].find().sort('received_at', -1).to_list(10)
        print(f'Total emails in inbox: {await db["inbox"].count_documents({})}')
        print('\n=== RECENT EMAILS ===')
        for e in all_emails:
            print(f'From: {e.get("from")} | Status: {e.get("status")} | Subject: {e.get("subject")[:50]}...')

asyncio.run(check_karan_email())
