import asyncio
from database import get_db, connect_db, close_db
from utils.time_utils import utc_now

async def set_autosend_threshold(threshold: int = 30):
    """Set the auto-send confidence threshold to the specified percentage."""
    try:
        await connect_db()
        db = get_db()
    
        # Update the threshold
        result = await db['admin_settings'].update_one(
            {'settings_id': 'default'},
            {
                '$set': {
                    'clientInboxCfg.autoSendThreshold': threshold,
                    'updated_at': utc_now()
                }
            },
            upsert=True
        )
        print(f'Updated: {result.modified_count} documents')
        
        # Verify the update
        settings = await db['admin_settings'].find_one({'settings_id': 'default'})
        current_threshold = settings.get('clientInboxCfg', {}).get('autoSendThreshold', 'NOT SET')
        print(f'Auto-send confidence threshold is now: {current_threshold}%')
    finally:
        await close_db()

if __name__ == '__main__':
    asyncio.run(set_autosend_threshold(30))
