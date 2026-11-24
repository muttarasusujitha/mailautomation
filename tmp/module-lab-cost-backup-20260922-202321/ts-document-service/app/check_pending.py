import asyncio
from database import connect_db, get_db

async def check_pending():
    await connect_db()
    db = get_db()
    
    # Check for pending replies
    pending = await db['inbox'].find({
        'status': {'$in': ['pending_approval', 'pending_autosend']}
    }).to_list(None)
    
    print(f'Pending replies: {len(pending)}\n')
    
    for email in pending[:5]:
        print(f'From: {email.get("from")}')
        print(f'Subject: {email.get("subject")}')
        print(f'Status: {email.get("status")}')
        print(f'Confidence: {email.get("confidence_score")}')
        print()

asyncio.run(check_pending())
