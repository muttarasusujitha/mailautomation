import asyncio
from database import connect_db, get_db
from agents.email_agent import sync_gmail_inbox

async def manual_sync():
    await connect_db()
    db = get_db()
    
    print('🔄 Starting manual Gmail sync...\n')
    
    try:
        result = await sync_gmail_inbox()
        
        print('✅ Sync completed!')
        print(f'Result: {result}')
        
        # Check how many emails are now in inbox
        count = await db['inbox'].count_documents({})
        print(f'\n📧 Total emails in inbox now: {count}')
        
        # Show recent emails
        recent = await db['inbox'].find().sort('received_at', -1).to_list(5)
        print('\n=== RECENT EMAILS ===')
        for email in recent:
            print(f'From: {email.get("from")}')
            print(f'Subject: {email.get("subject")}')
            print(f'Status: {email.get("status")}')
            print()
            
    except Exception as e:
        print(f'❌ Error: {e}')

asyncio.run(manual_sync())
