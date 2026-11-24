import asyncio
from database import connect_db, get_db
from agents.client_intelligence_agent import poll_gmail_api_client_inbox

async def sync_gmail_inbox():
    await connect_db()
    db = get_db()
    
    print('Starting Gmail API client inbox sync...\n')
    
    try:
        # Poll Gmail for new emails
        result = await poll_gmail_api_client_inbox(db)
        
        print('Gmail sync completed!')
        print(f'Result: {result}\n')
        
        # Check how many emails are now in inbox
        count = await db['inbox'].count_documents({})
        print(f'Total emails in database: {count}')
        
        # Show recent emails
        recent = await db['inbox'].find().sort('received_at', -1).to_list(5)
        print('\n=== RECENT EMAILS ===')
        for email in recent:
            print(f'From: {email.get("from")}')
            print(f'Subject: {email.get("subject")}')
            print(f'Status: {email.get("status")}')
            print(f'Confidence: {email.get("confidence_score", "N/A")}')
            print()
            
    except Exception as e:
        print(f'Error: {e}')
        import traceback
        traceback.print_exc()

asyncio.run(sync_gmail_inbox())
