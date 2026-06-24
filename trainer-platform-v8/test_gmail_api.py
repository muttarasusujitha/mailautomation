import sys
sys.path.insert(0, 'backend')

try:
    from agents.client_intelligence_agent import get_gmail_service
    
    print('✅ Gmail OAuth configured')
    service = get_gmail_service()
    
    # Try to fetch inbox
    results = service.users().messages().list(userId="me", maxResults=5).execute()
    messages = results.get('messages', [])
    
    print(f'\n📧 Found {len(messages)} emails in Gmail inbox')
    
    for msg in messages:
        msg_full = service.users().messages().get(userId="me", id=msg['id'], format='full').execute()
        headers = {h['name']: h['value'] for h in msg_full['payload'].get('headers', [])}
        print(f"  - From: {headers.get('From')}")
        print(f"    Subject: {headers.get('Subject')[:60]}")
        print()
        
except Exception as e:
    print(f'❌ Error: {str(e)}')
