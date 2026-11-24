import asyncio
from database import connect_db, get_db

async def check_client_emails():
    await connect_db()
    db = get_db()
    
    # Check client emails collection
    client_emails = await db['client_emails'].find({}).sort('created_at', -1).to_list(5)
    
    print(f'Total client emails: {len(client_emails)}\n')
    print('=== LAST 5 CLIENT EMAILS ===\n')
    
    for email in client_emails:
        print(f'Client: {email.get("client_name")}')
        print(f'Email To: {email.get("to_email")}')
        print(f'Subject: {email.get("subject")}')
        print(f'Status: {email.get("status")}')
        print(f'Reply Sent:\n{email.get("reply_sent", "(none)")}')
        print(f'\nTrainer Details: {email.get("trainer_details", {})}')
        print('\n' + '='*60 + '\n')

asyncio.run(check_client_emails())
