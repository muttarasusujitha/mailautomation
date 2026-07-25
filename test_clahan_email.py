import sys
sys.path.insert(0, 'backend')

from agents.client_intelligence_agent import get_gmail_service

try:
    service = get_gmail_service()
    
    # Search for Clahan emails
    results = service.users().messages().list(
        userId="me",
        q="from:clahan.com OR from:noreply@clahan.com",
        maxResults=10
    ).execute()
    
    messages = results.get('messages', [])
    print(f'📧 Found {len(messages)} emails from Clahan')
    
    if messages:
        for msg in messages:
            msg_full = service.users().messages().get(userId="me", id=msg['id'], format='full').execute()
            headers = {h['name']: h['value'] for h in msg_full['payload'].get('headers', [])}
            print(f"\n  From: {headers.get('From')}")
            print(f"  Subject: {headers.get('Subject')}")
            print(f"  Date: {headers.get('Date')}")
    else:
        print("\n❌ No emails from Clahan found in Gmail")
        print("\nChecking account email address...")
        profile = service.users().getProfile(userId='me').execute()
        print(f"Account email: {profile.get('emailAddress', 'N/A')}")
        
except Exception as e:
    print(f'❌ Error: {str(e)}')
    import traceback
    traceback.print_exc()
