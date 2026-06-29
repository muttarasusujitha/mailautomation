import asyncio
from database import connect_db, get_db

async def check_sent_emails():
    await connect_db()
    db = get_db()
    
    # Find emails that were auto-sent with status
    auto_sent = await db['inbox'].find({
        'status': 'auto_sent'
    }).sort('sent_at', -1).to_list(5)
    
    print('=== LAST 5 AUTO-SENT EMAILS ===\n')
    
    for email in auto_sent:
        print(f'From: {email.get("from")}')
        print(f'Subject: {email.get("subject")}')
        print(f'Status: {email.get("status")}')
        print(f'Generated Reply:\n{email.get("generated_reply", "(none)")}')
        print(f'\nExtracted Data: {email.get("extracted", {})}')
        print('\n' + '='*60 + '\n')

asyncio.run(check_sent_emails())
