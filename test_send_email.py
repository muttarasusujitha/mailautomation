import sys
sys.path.insert(0, 'backend')

from agents.client_intelligence_agent import send_gmail_reply, get_gmail_service

try:
    print("✅ Gmail service initialized")
    service = get_gmail_service()
    
    # Test send
    print("\n📧 Attempting to send test email...")
    result = send_gmail_reply(
        gmail_service=service,
        to_email="sujithaofficial585@gmail.com",
        subject="Test Auto-Reply from TrainerSync",
        body="This is a test email from the auto-reply system.",
        thread_id="",
        in_reply_to=""
    )
    print(f"✅ Send result: {result}")
    
except Exception as e:
    print(f"❌ Error: {str(e)}")
    import traceback
    traceback.print_exc()
