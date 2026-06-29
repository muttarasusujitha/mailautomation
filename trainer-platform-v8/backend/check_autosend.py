import asyncio
from database import connect_db, get_db

async def check_autosend_settings():
    await connect_db()
    db = get_db()
    
    # Check current auto-send threshold
    settings = await db['admin_settings'].find_one({'settings_id': 'default'})
    
    print('=== AUTO-SEND SETTINGS ===\n')
    if settings:
        threshold = settings.get('clientInboxCfg', {}).get('autoSendThreshold', 70)
        print(f'Current Auto-Send Threshold: {threshold}%')
        print(f'Settings: {settings.get("clientInboxCfg", {})}')
    else:
        print('No settings found')
    
    # Check if there are any pending replies that should have been sent
    inbox = await db['inbox'].find({
        'status': {'$in': ['pending_approval', 'pending_autosend']},
        'generated_reply': {'$exists': True}
    }).to_list(None)
    
    print(f'\n=== PENDING REPLIES ===')
    print(f'Total pending replies: {len(inbox)}')
    
    for item in inbox[:3]:  # Show first 3
        print(f"\n--- Email from {item.get('from', 'Unknown')} ---")
        print(f"Status: {item.get('status')}")
        print(f"Confidence: {item.get('confidence_score', 'N/A')}")
        print(f"Generated Reply: {item.get('generated_reply', '')[:100]}...")

asyncio.run(check_autosend_settings())
